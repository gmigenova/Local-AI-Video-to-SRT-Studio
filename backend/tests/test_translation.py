"""Tests for the Google Cloud Translation integration.

The Google API itself is faked: ``GoogleTranslateClient._post`` (the only
network touchpoint) is monkeypatched, so these tests run offline.
"""

from __future__ import annotations

import io
import urllib.error

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.database.base import get_session_factory
from app.main import app
from app.models.media_file import MediaFile
from app.models.project import Project
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.services.subtitle.models import Subtitle
from app.services.translation.google_translate import (
    _TRANSLATE_URL,
    GoogleTranslateClient,
    TranslationServiceError,
)

# --------------------------------------------------------------------- unit


def test_translate_preserves_order_and_unescapes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_post(self: GoogleTranslateClient, body: dict, endpoint: str = _TRANSLATE_URL):
        calls.append(body)
        return {
            "data": {
                "translations": [
                    {
                        "translatedText": f"t-{q} &#39;ok&#39;",
                        "detectedSourceLanguage": "en",
                    }
                    for q in body["q"]
                ]
            }
        }

    monkeypatch.setattr(GoogleTranslateClient, "_post", fake_post)
    client = GoogleTranslateClient("key")
    result = client.translate(["one", "", "three"], "th")

    assert result.texts == ["t-one 'ok'", "", "t-three 'ok'"]
    assert result.detected_source_language == "en"
    # empty cue never sent to the API
    assert calls[0]["q"] == ["one", "three"]
    assert calls[0]["target"] == "th"
    assert "source" not in calls[0]


def test_translate_batches_large_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    batch_sizes: list[int] = []

    def fake_post(self: GoogleTranslateClient, body: dict, endpoint: str = _TRANSLATE_URL):
        batch_sizes.append(len(body["q"]))
        return {
            "data": {
                "translations": [{"translatedText": "x"} for _ in body["q"]],
                "detectedSourceLanguage": "en",
            }
        }

    monkeypatch.setattr(GoogleTranslateClient, "_post", fake_post)
    client = GoogleTranslateClient("key")
    result = client.translate([f"line {i}" for i in range(70)], "en")

    assert len(result.texts) == 70
    assert all(text == "x" for text in result.texts)
    assert sum(batch_sizes) == 70  # nothing lost
    assert all(size <= 64 for size in batch_sizes)  # within the request limit


def test_translate_explicit_source_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_post(self: GoogleTranslateClient, body: dict, endpoint: str = _TRANSLATE_URL):
        calls.append(body)
        return {"data": {"translations": [{"translatedText": "สวัสดี"} for _ in body["q"]]}}

    monkeypatch.setattr(GoogleTranslateClient, "_post", fake_post)
    client = GoogleTranslateClient("key")
    result = client.translate(["hello"], "th", source_language="en")

    assert result.texts == ["สวัสดี"]
    assert result.detected_source_language is None  # not reported for explicit source
    assert calls[0]["source"] == "en"


def test_translate_rejects_bad_language_codes() -> None:
    client = GoogleTranslateClient("key")
    with pytest.raises(TranslationServiceError) as exc:
        client.translate(["hi"], "not a code!")
    assert exc.value.status_code == 400


def test_http_error_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float | None = None):
        raise urllib.error.HTTPError(
            "https://translation.test",
            403,
            "Forbidden",
            None,
            io.BytesIO(b'{"error":{"message":"API key not valid"}}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = GoogleTranslateClient("bad-key")
    with pytest.raises(TranslationServiceError) as exc:
        client.translate(["hi"], "th")
    assert exc.value.status_code == 401
    assert "API key" in exc.value.message


def test_network_error_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float | None = None):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = GoogleTranslateClient("key")
    with pytest.raises(TranslationServiceError) as exc:
        client.translate(["hi"], "th")
    assert exc.value.status_code == 502


def test_list_supported_languages(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoints: list[str] = []

    def fake_post(self: GoogleTranslateClient, body: dict, endpoint: str = _TRANSLATE_URL):
        endpoints.append(endpoint)
        return {
            "data": {
                "languages": [
                    {"language": "en", "name": "English"},
                    {"language": "th", "name": "Thai"},
                ]
            }
        }

    monkeypatch.setattr(GoogleTranslateClient, "_post", fake_post)
    client = GoogleTranslateClient("key")
    languages = client.list_supported_languages()

    assert endpoints[0].endswith("/languages")
    assert languages == [
        {"code": "en", "name": "English"},  # sorted by name
        {"code": "th", "name": "Thai"},
    ]


# ------------------------------------------------------------------- API


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _seed_job(texts: list[str]) -> str:
    """Create a project + media + job + subtitle rows; returns the job id."""
    db = get_session_factory()()
    try:
        project = Project(name="Translation Test")
        db.add(project)
        db.flush()
        media = MediaFile(
            project_id=project.id,
            original_name="clip.mp4",
            stored_name="clip.mp4",
            file_path="clip.mp4",
        )
        db.add(media)
        db.flush()
        job = JobsRepository(db).create(
            media_id=media.id, model_name="tiny", language=None, settings_json={}
        )
        SubtitlesRepository(db).replace_for_job(
            job.id,
            [
                Subtitle(
                    index=i,
                    start_ms=(i - 1) * 2000,
                    end_ms=(i - 1) * 2000 + 1500,
                    text=text,
                    original_text=text,
                )
                for i, text in enumerate(texts, start=1)
            ],
        )
        db.commit()
        return job.id
    finally:
        db.close()


def _clear_subtitles(job_id: str) -> None:
    db = get_session_factory()()
    try:
        SubtitlesRepository(db).replace_for_job(job_id, [])
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def seeded_job() -> str:
    return _seed_job(["Hello world", "", "How are you?"])


def test_languages_unconfigured_falls_back_to_catalog(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "google_translate_api_key", "")
    response = client.get("/api/v1/translation/languages")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    codes = {lang["code"] for lang in body["languages"]}
    assert {"th", "en", "zh-CN", "ja"} <= codes


def test_languages_configured_uses_live_list(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "google_translate_api_key", "test-key")

    def fake_post(self: GoogleTranslateClient, body: dict, endpoint: str = _TRANSLATE_URL):
        return {
            "data": {
                "languages": [{"language": "th", "name": "Thai"}, {"language": "fr", "name": "French"}]
            }
        }

    monkeypatch.setattr(GoogleTranslateClient, "_post", fake_post)
    response = client.get("/api/v1/translation/languages")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["languages"] == [
        {"code": "fr", "name": "French"},
        {"code": "th", "name": "Thai"},
    ]


def test_translate_without_api_key_is_409(
    client: TestClient, seeded_job: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "google_translate_api_key", "")
    response = client.post(
        f"/api/v1/jobs/{seeded_job}/subtitles/translate",
        json={"target_language": "th"},
    )
    assert response.status_code == 409
    assert "GOOGLE_TRANSLATE_API_KEY" in response.json()["detail"]


def test_translate_unknown_job_is_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs/nope/subtitles/translate",
        json={"target_language": "th"},
    )
    assert response.status_code == 404


def test_translate_without_subtitles_is_409(
    client: TestClient, seeded_job: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "google_translate_api_key", "test-key")
    _clear_subtitles(seeded_job)
    response = client.post(
        f"/api/v1/jobs/{seeded_job}/subtitles/translate",
        json={"target_language": "th"},
    )
    assert response.status_code == 409


def test_translate_returns_aligned_texts(
    client: TestClient, seeded_job: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "google_translate_api_key", "test-key")

    def fake_post(self: GoogleTranslateClient, body: dict, endpoint: str = _TRANSLATE_URL):
        return {
            "data": {
                "translations": [
                    {"translatedText": f"แปล:{q}", "detectedSourceLanguage": "en"}
                    for q in body["q"]
                ]
            }
        }

    monkeypatch.setattr(GoogleTranslateClient, "_post", fake_post)
    response = client.post(
        f"/api/v1/jobs/{seeded_job}/subtitles/translate",
        json={"target_language": "th", "source_language": "en", "mode": "dual"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == seeded_job
    assert body["target_language"] == "th"
    assert body["mode"] == "dual"
    assert body["detected_source_language"] == "en"
    assert body["translated"] == 2  # the empty middle cue is skipped
    assert body["total"] == 3
    assert [item["index"] for item in body["subtitles"]] == [1, 2, 3]
    assert [item["text"] for item in body["subtitles"]] == [
        "แปล:Hello world",
        "",
        "แปล:How are you?",
    ]


def test_translate_api_failure_maps_to_clean_detail(
    client: TestClient, seeded_job: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "google_translate_api_key", "test-key")

    def raise_quota(self: GoogleTranslateClient, body: dict, endpoint: str = _TRANSLATE_URL):
        raise TranslationServiceError(429, "Google Cloud Translation quota exceeded.")

    monkeypatch.setattr(
        GoogleTranslateClient, "_post", raise_quota
    )
    response = client.post(
        f"/api/v1/jobs/{seeded_job}/subtitles/translate",
        json={"target_language": "th"},
    )
    assert response.status_code == 429
    assert response.json()["detail"] == "Google Cloud Translation quota exceeded."
