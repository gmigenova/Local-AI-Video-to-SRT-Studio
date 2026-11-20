"""Tests for the Ollama LLM video-summary feature.

The Ollama server is faked: ``OllamaSummaryClient._request`` (the only
network touchpoint) is monkeypatched, so these tests run offline.
"""

from __future__ import annotations

import io
import urllib.error

import pytest
from fastapi.testclient import TestClient
from translation_fixtures import seed_translation_job

from app.core.config import get_settings
from app.main import app
from app.services.llm.summary import (
    OllamaSummaryClient,
    SummaryServiceError,
    parse_summary_reply,
)

_REPLY = (
    "SUMMARY:\n"
    "The video introduces the product and answers questions.\n"
    "\n"
    "KEY POINTS:\n"
    "- [00:00] Welcome and introduction\n"
    "- [00:04] Product overview\n"
    "- [01:02] Q&A session"
)


def _chat_reply(content: str) -> dict:
    return {"message": {"role": "assistant", "content": content}}


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------- unit tests


def test_summary_single_chunk_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_request(self: OllamaSummaryClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        calls.append(body or {})
        return _chat_reply(_REPLY)

    monkeypatch.setattr(OllamaSummaryClient, "_request", fake_request)
    ollama = OllamaSummaryClient("http://x", "qwen2.5:7b")
    result = ollama.summarize(
        [(0, "Hello and welcome"), (4000, "Product overview"), (62000, "Questions")],
        "th",
    )

    assert result.requests == 1
    assert result.summary.startswith("The video introduces")
    assert [p.text for p in result.key_points] == [
        "Welcome and introduction",
        "Product overview",
        "Q&A session",
    ]
    assert result.key_points[0].time_ms == 0
    assert result.key_points[1].time_ms == 4000
    assert result.key_points[2].time_ms == 62000

    body = calls[0]
    assert body["model"] == "qwen2.5:7b"
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0}
    system, user = body["messages"]
    assert "Thai" in system["content"]  # language baked into the prompt
    assert "[00:00] Hello and welcome" in user["content"]
    assert "[01:02] Questions" in user["content"]  # mm:ss from 62000 ms


def test_summary_prompts_english_for_other_languages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def fake_request(self: OllamaSummaryClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        prompts.append(body["messages"][0]["content"])
        return _chat_reply(_REPLY)

    monkeypatch.setattr(OllamaSummaryClient, "_request", fake_request)
    ollama = OllamaSummaryClient("http://x", "m")
    ollama.summarize([(0, "Bonjour")], "fr")  # unknown code -> English

    assert "English" in prompts[0]
    assert "Thai" not in prompts[0]


def test_summary_long_transcripts_map_reduce(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_request(self: OllamaSummaryClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        calls.append(body or {})
        system = body["messages"][0]["content"]
        if "PORTION" in system:
            return _chat_reply("- [00:10] partial point")
        return _chat_reply("SUMMARY:\nLong video\n\nKEY POINTS:\n- [00:10] merged point")

    monkeypatch.setattr(OllamaSummaryClient, "_request", fake_request)
    ollama = OllamaSummaryClient("http://x", "m")
    # 12 cues x ~400 chars -> > 3000 chars -> at least 2 map chunks
    cues = [(i * 2000, f"cue {i} " + "word " * 80) for i in range(12)]
    result = ollama.summarize(cues, "en")

    map_calls = [c for c in calls if "PORTION" in c["messages"][0]["content"]]
    reduce_calls = [c for c in calls if "PORTION" not in c["messages"][0]["content"]]
    assert len(map_calls) >= 2
    assert len(reduce_calls) == 1  # everything merged in a single final reduce
    assert result.requests == len(calls)
    assert result.summary == "Long video"
    assert result.key_points[0].text == "merged point"

    # every request stays under the batching char cap (context safety)
    for call in calls:
        assert len(call["messages"][1]["content"]) < 3200


def test_parse_summary_reply_variants() -> None:
    # well-formed
    summary, points = parse_summary_reply(_REPLY)
    assert summary == "The video introduces the product and answers questions."
    assert len(points) == 3

    # markdown-flavoured headings and * bullets
    summary, points = parse_summary_reply(
        "## Summary\nText.\n\n**Key Points:**\n* [00:05] one\n* two"
    )
    assert summary == "Text."
    assert points[0].time_ms == 5000
    assert points[1].time_ms is None  # no stamp -> null, text kept

    # garbage: no headings at all -> everything becomes the summary
    summary, points = parse_summary_reply("Just some model rambling.")
    assert summary == "Just some model rambling."
    assert points == []


def test_summary_empty_cues_rejected() -> None:
    ollama = OllamaSummaryClient("http://x", "m")
    with pytest.raises(SummaryServiceError) as exc:
        ollama.summarize([(0, "   ")], "en")
    assert exc.value.status_code == 400


def test_summary_unreachable_server_maps_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float | None = None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    ollama = OllamaSummaryClient("http://127.0.0.1:11434", "m")
    with pytest.raises(SummaryServiceError) as exc:
        ollama.summarize([(0, "hi")], "en")
    assert exc.value.status_code == 502
    assert "Ollama" in exc.value.message


def test_summary_missing_model_maps_to_404_with_pull_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, timeout: float | None = None):
        raise urllib.error.HTTPError(
            "http://x/api/chat",
            404,
            "Not Found",
            None,
            io.BytesIO(b'{"error": "model \'m\' not found"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    ollama = OllamaSummaryClient("http://x", "m")
    with pytest.raises(SummaryServiceError) as exc:
        ollama.summarize([(0, "hi")], "en")
    assert exc.value.status_code == 404
    assert "ollama pull" in exc.value.message


# ---------------------------------------------------------------- API tests


def _fake_ollama_chat(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[dict]:
    calls: list[dict] = []

    def fake_request(self: OllamaSummaryClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        calls.append(body or {})
        return _chat_reply(reply)

    monkeypatch.setattr(OllamaSummaryClient, "_request", fake_request)
    return calls


def _summary_path(job_id: str):
    return get_settings().storage_subdir("transcripts") / job_id / "summary.json"


def test_summarize_endpoint_persists_and_get_returns_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_ollama_chat(monkeypatch, _REPLY)
    job_id = seed_translation_job(["Hello", "World"])

    assert client.get(f"/api/v1/jobs/{job_id}/summary").status_code == 404  # not yet

    response = client.post(f"/api/v1/jobs/{job_id}/summarize", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == "qwen2.5:7b"  # cleanup-model fallback
    assert body["language"] == "en"  # no detected language on the seeded job
    assert body["cue_count"] == 2
    assert body["summary"].startswith("The video introduces")
    assert [p["time_ms"] for p in body["key_points"]] == [0, 4000, 62000]
    assert _summary_path(job_id).is_file()  # persisted server-side

    stored = client.get(f"/api/v1/jobs/{job_id}/summary")
    assert stored.status_code == 200
    assert stored.json()["summary"] == body["summary"]
    assert calls[0]["model"] == "qwen2.5:7b"


def test_summarize_language_defaults_from_detected_language(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_ollama_chat(monkeypatch, _REPLY)
    job_id = seed_translation_job(["สวัสดี"], detected_language="th")

    response = client.post(f"/api/v1/jobs/{job_id}/summarize", json={})

    assert response.status_code == 200
    assert response.json()["language"] == "th"
    assert "Thai" in calls[0]["messages"][0]["content"]


def test_summarize_model_override_from_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_ollama_chat(monkeypatch, _REPLY)
    job_id = seed_translation_job(["Hello"])

    response = client.post(
        f"/api/v1/jobs/{job_id}/summarize", json={"model": "llama3.1:8b"}
    )

    assert response.status_code == 200
    assert response.json()["model"] == "llama3.1:8b"
    assert calls[0]["model"] == "llama3.1:8b"


def test_summarize_without_subtitles_is_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, _REPLY)
    job_id = seed_translation_job(["Hello"])
    from translation_fixtures import clear_subtitles

    clear_subtitles(job_id)
    response = client.post(f"/api/v1/jobs/{job_id}/summarize", json={})
    assert response.status_code == 409


def test_summarize_unknown_job_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, _REPLY)
    response = client.post("/api/v1/jobs/nope/summarize", json={})
    assert response.status_code == 404
    assert client.get("/api/v1/jobs/nope/summary").status_code == 404


def test_summarize_errors_map_cleanly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        OllamaSummaryClient,
        "_request",
        lambda self, path, body=None, timeout=None: (_ for _ in ()).throw(
            SummaryServiceError(502, "Could not reach Ollama. Check that it is running.")
        ),
    )
    job_id = seed_translation_job(["Hello"])

    response = client.post(f"/api/v1/jobs/{job_id}/summarize", json={})
    assert response.status_code == 502
    assert "Ollama" in response.json()["detail"]
    assert not _summary_path(job_id).exists()  # nothing persisted on failure
