"""Tests for speaker diarization (post-spec feature).

pyannote is NEVER installed in CI: the pipeline is faked via
``pipeline_factory`` (a test double stands in for the dependency), and the
availability matrix asserts clean unavailability without it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from conftest import requires_ffmpeg
from fastapi.testclient import TestClient
from test_pipeline import FakeEngine, FakeManager

from app.core.config import Settings
from app.core.errors import DiarizationUnavailable
from app.main import app
from app.pipeline import TranscriptionPipeline
from app.services.diarization import (
    DiarizationService,
    DiarizationTurn,
    assign_speakers_to_subtitles,
    read_diarization_payload,
    write_diarization_payload,
)
from app.services.subtitle.models import Subtitle
from app.workers.worker import options_from_settings

# ---------------------------------------------------------------- fakes

@dataclass
class _FakeSegment:
    start: float
    end: float


@dataclass
class _FakeAnnotation:
    tracks: list[tuple[_FakeSegment, str]] = field(default_factory=list)

    def itertracks(self, yield_label: bool = False):  # noqa: ANN201, FBT001
        for segment, speaker in self.tracks:
            yield (segment, None, speaker) if yield_label else (segment, None)


class _FakePipeline:
    """Duck-types pyannote's Pipeline enough for DiarizationService."""

    def __init__(self, annotation: _FakeAnnotation) -> None:
        self._annotation = annotation

    def __call__(self, resource: object) -> _FakeAnnotation:  # noqa: ANN001, ARG002
        return self._annotation


def _service(turns: list[tuple[float, float, str]]) -> DiarizationService:
    annotation = _FakeAnnotation(
        tracks=[(_FakeSegment(start, end), speaker) for start, end, speaker in turns]
    )
    settings = Settings(_env_file=None)
    return DiarizationService(settings, pipeline_factory=lambda _s: _FakePipeline(annotation))


def _test_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


# ------------------------------------------------------- alignment (pure)

def _subs(*spans: tuple[int, int]) -> list[Subtitle]:
    return [
        Subtitle(index=i, start_ms=start, end_ms=end, text=f"row {i}", original_text="")
        for i, (start, end) in enumerate(spans)
    ]


class TestAlignment:
    def test_majority_overlap_wins(self):
        subs = _subs((1000, 3000))
        turns = [
            DiarizationTurn(0, 1200, "SPEAKER_00"),  # overlap 200 ms
            DiarizationTurn(1200, 2900, "SPEAKER_01"),  # overlap 1700 ms
        ]
        assignment = assign_speakers_to_subtitles(subs, turns)
        assert assignment.speakers == ["SPEAKER_01"]

    def test_no_overlap_keeps_none(self):
        subs = _subs((5000, 6000))
        turns = [DiarizationTurn(0, 4000, "SPEAKER_00")]
        assert assign_speakers_to_subtitles(subs, turns).speakers == [None]

    def test_cross_talk_accumulates_across_turns(self):
        subs = _subs((0, 10_000))
        turns = [
            DiarizationTurn(0, 2000, "A"),
            DiarizationTurn(3000, 3500, "A"),  # A total: 2500
            DiarizationTurn(4000, 8000, "B"),  # B total: 4000
        ]
        assert assign_speakers_to_subtitles(subs, turns).speakers == ["B"]

    def test_apply_to_sets_speaker_on_rows(self):
        subs = _subs((0, 1000), (2000, 3000))
        turns = [DiarizationTurn(0, 900, "Host")]
        assignment = assign_speakers_to_subtitles(subs, turns)
        assert assignment.apply_to(subs) == 1
        assert subs[0].speaker == "Host"
        assert subs[1].speaker is None

    def test_empty_turns_label_nothing(self):
        subs = _subs((0, 1000))
        assert assign_speakers_to_subtitles(subs, []).speakers == [None]


# ---------------------------------------------------------- service unit

class TestDiarizationService:
    def test_turns_converted_to_ms(self, tmp_path: Path):
        service = _service([(1.2, 3.5, "SPEAKER_00")])
        turns = service.diarize(tmp_path / "ignored.wav")
        assert turns == [DiarizationTurn(1200, 3500, "SPEAKER_00")]

    def test_progress_callback_receives_stage(self, tmp_path: Path):
        service = _service([])
        stages: list[str] = []
        turns = service.diarize(
            tmp_path / "x.wav", progress_callback=lambda _f, stage: stages.append(stage)
        )
        assert turns == []
        assert "Identifying speakers" in stages

    def test_unavailable_without_dependency_when_no_factory(self):
        settings = _test_settings(
            diarize_enabled=True, huggingface_token="hf_test"
        )
        service = DiarizationService(settings)  # real import path
        with pytest.raises(DiarizationUnavailable) as exc:
            service.diarize(Path("nowhere.wav"))
        # pyannote is not installed in CI -> the clean install hint
        assert "requirements-diarization" in str(exc.value)

    def test_availability_matrix(self):
        disabled = _test_settings()
        available, reason = DiarizationService.is_available(disabled)
        assert (available, reason is not None) == (False, True)
        assert "DIARIZE_ENABLED" in reason

        no_token = _test_settings(diarize_enabled=True)
        available, reason = DiarizationService.is_available(no_token)
        assert available is False
        assert "HUGGINGFACE_TOKEN" in reason

        with_token = _test_settings(diarize_enabled=True, huggingface_token="hf_x")
        available, reason = DiarizationService.is_available(with_token)
        # pyannote missing in CI -> still unavailable, but for that reason
        assert available is False
        assert "pyannote" in (reason or "")

    def test_payload_round_trip(self, tmp_path: Path):
        path = tmp_path / "diarization.json"
        turns = [DiarizationTurn(0, 1500, "A"), DiarizationTurn(1500, 3000, "B")]
        write_diarization_payload(turns, path)
        assert read_diarization_payload(path) == turns
        assert read_diarization_payload(tmp_path / "missing.json") is None


# ------------------------------------------------------- pipeline wiring

def _fake_diarize_pipeline(turns: list[tuple[float, float, str]]) -> TranscriptionPipeline:
    return TranscriptionPipeline(
        settings=Settings(_env_file=None),
        model_manager=FakeManager(FakeEngine()),  # type: ignore[arg-type]
        diarizer=_service(turns),
    )


class TestPipelineIntegration:
    def test_diarize_option_flows_through_settings(self):
        options, _rules = options_from_settings(
            "tiny", None, {"diarize": True, "beam_size": 1}
        )
        assert options.diarize is True
        assert "diarize" not in options.to_engine_kwargs()  # never a whisper kwarg

    @requires_ffmpeg
    def test_run_labels_subtitles_and_persists_turns(
        self, sample_video: Path, tmp_path: Path
    ):
        pipeline = _fake_diarize_pipeline([(1.0, 3.0, "SPEAKER_00")])
        from app.services.transcription.engine import TranscriptionOptions

        result = pipeline.run(
            video_path=sample_video,
            options=TranscriptionOptions(model="fake-model", diarize=True),
            work_dir=tmp_path / "work",
            output_dir=tmp_path / "out",
        )
        # the FakeEngine's segment (1200-3500 ms) mostly overlaps SPEAKER_00
        assert result.subtitles[0].speaker == "SPEAKER_00"
        assert result.labelled_subtitles == 1
        assert result.diarization_path is not None
        assert read_diarization_payload(result.diarization_path) == [
            DiarizationTurn(1000, 3000, "SPEAKER_00")
        ]

    @requires_ffmpeg
    def test_progress_stays_monotonic_with_diarization(
        self, sample_video: Path, tmp_path: Path
    ):
        pipeline = _fake_diarize_pipeline([(0.5, 2.0, "SPEAKER_00")])
        from app.services.transcription.engine import TranscriptionOptions

        fractions: list[float] = []
        pipeline.run(
            video_path=sample_video,
            options=TranscriptionOptions(model="fake-model", diarize=True),
            work_dir=tmp_path / "work",
            output_dir=tmp_path / "out",
            progress=lambda fraction, _stage: fractions.append(fraction),
        )
        assert fractions == sorted(fractions)
        assert abs(fractions[-1] - 1.0) < 1e-6

    @requires_ffmpeg
    def test_unconfigured_diarizer_skips_without_failing(
        self, sample_video: Path, tmp_path: Path
    ):
        pipeline = TranscriptionPipeline(
            settings=Settings(_env_file=None),
            model_manager=FakeManager(FakeEngine()),  # type: ignore[arg-type]
            diarizer=None,
        )
        from app.services.transcription.engine import TranscriptionOptions

        stages: list[str] = []
        result = pipeline.run(  # diarize=True but no diarizer wired
            video_path=sample_video,
            options=TranscriptionOptions(model="fake-model", diarize=True),
            work_dir=tmp_path / "work",
            output_dir=tmp_path / "out",
            progress=lambda _f, stage: stages.append(stage),
        )
        assert any("Skipped speaker diarization" in stage for stage in stages)
        assert result.subtitles[0].speaker is None
        assert result.diarization_path is None


# ------------------------------------------------------------- API level

@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def project_id(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Diarize Test"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture()
def media_id(client: TestClient, project_id: str, sample_video: Path) -> str:
    with open(sample_video, "rb") as handle:
        response = client.post(
            "/api/v1/media/upload",
            files={"file": ("sample.mp4", handle, "video/mp4")},
            data={"project_id": project_id, "audio_stream_index": "0"},
        )
    assert response.status_code == 201, response.text
    return response.json()["media_id"]


def _completed_job(client: TestClient, media_id: str) -> str:
    """A finished transcription job (fake engine) with one subtitle row."""
    from test_api import drain_queue

    from app.core.config import get_settings
    from app.database.base import get_session_factory
    from app.workers.worker import JobWorker

    drain_queue()
    job_id = client.post(
        "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
    ).json()["job_id"]
    worker = JobWorker(
        settings=get_settings(),
        session_factory=get_session_factory(),
        pipeline_factory=lambda: TranscriptionPipeline(
            settings=get_settings(),
            model_manager=FakeManager(FakeEngine()),  # type: ignore[arg-type]
        ),
    )
    assert worker.process_once() == job_id
    return job_id


class TestDiarizationApi:
    def test_system_info_diarization_block(self, client: TestClient):
        response = client.get("/api/v1/system/info")
        assert response.status_code == 200
        block = response.json()["diarization"]
        assert block["available"] is False
        assert isinstance(block["reason"], str)
        assert block["model"] == "pyannote/speaker-diarization-3.1"

    def test_job_settings_allowlist_accepts_diarize(self):
        from app.api.v1.jobs import _ALLOWED_SETTING_KEYS

        assert "diarize" in _ALLOWED_SETTING_KEYS

    @requires_ffmpeg
    def test_sync_round_trip_and_speaker_export(self, client: TestClient, media_id: str):
        job_id = _completed_job(client, media_id)
        rows = client.get(f"/api/v1/jobs/{job_id}/subtitles").json()
        assert rows[0]["speaker"] is None

        # sync carries the speaker through the atomic replace
        saved = client.post(
            f"/api/v1/jobs/{job_id}/subtitles/sync",
            json={
                "subtitles": [
                    {
                        "subtitle_index": 1,
                        "start_ms": rows[0]["start_ms"],
                        "end_ms": rows[0]["end_ms"],
                        "text": rows[0]["text"],
                        "original_text": rows[0]["original_text"],
                        "is_edited": True,
                        "speaker": "Host",
                    }
                ]
            },
        )
        assert saved.status_code == 200, saved.text
        after = client.get(f"/api/v1/jobs/{job_id}/subtitles").json()
        assert after[0]["speaker"] == "Host"

        # exports: plain has no prefix, ?speakers=true prefixes
        plain = client.get(f"/api/v1/jobs/{job_id}/export/srt")
        assert b"[Host]" not in plain.content
        prefixed = client.get(f"/api/v1/jobs/{job_id}/export/srt?speakers=true")
        assert b"[Host] Hello world." in prefixed.content
        prefixed_txt = client.get(f"/api/v1/jobs/{job_id}/export/txt?speakers=true")
        assert b"[Host] Hello world." in prefixed_txt.content

    @requires_ffmpeg
    def test_reprocess_reapplies_speakers_from_payload(self, client: TestClient, media_id: str):
        from app.core.config import get_settings

        job_id = _completed_job(client, media_id)
        transcripts = get_settings().storage_subdir("transcripts") / job_id
        transcripts.mkdir(parents=True, exist_ok=True)
        # the FakeEngine's cue is 1200-3500 ms: mostly SPEAKER_00
        write_diarization_payload(
            [
                DiarizationTurn(0, 3000, "SPEAKER_00"),
                DiarizationTurn(3000, 4000, "SPEAKER_01"),
            ],
            transcripts / "diarization.json",
        )

        response = client.post(f"/api/v1/jobs/{job_id}/subtitles/reprocess")
        assert response.status_code == 200, response.text
        assert response.json()["speakers"] == 1
        rows = client.get(f"/api/v1/jobs/{job_id}/subtitles").json()
        assert rows[0]["speaker"] == "SPEAKER_00"
