"""Tests for the Ollama LLM subtitle-cleanup pass.

The Ollama server is faked: ``OllamaCleanupClient._request`` (the only
network touchpoint) is monkeypatched, so these tests run offline.
"""

from __future__ import annotations

import io
import urllib.error

import pytest
from fastapi.testclient import TestClient
from translation_fixtures import seed_translation_job

from app.main import app
from app.services.llm.cleanup import (
    MODE_INSTRUCTIONS,
    CleanupServiceError,
    OllamaCleanupClient,
)


def _chat_reply(content: str) -> dict:
    return {"message": {"role": "assistant", "content": content}}


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------- unit tests


def test_cleanup_aligns_batch_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_request(self: OllamaCleanupClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        calls.append(body or {})
        reply_lines = body["messages"][1]["content"].split("\n")[-3:]
        return _chat_reply("\n".join(f"cleaned: {line}" for line in reply_lines if line))

    monkeypatch.setattr(OllamaCleanupClient, "_request", fake_request)
    ollama = OllamaCleanupClient("http://x", "qwen2.5:7b")
    result = ollama.cleanup(
        ["hello world", "", "how are you"], ["punctuation", "casing"]
    )

    assert result.texts == ["cleaned: hello world", "", "cleaned: how are you"]
    assert result.requests == 1
    body = calls[0]
    assert body["model"] == "qwen2.5:7b"
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0}
    system, user = body["messages"]
    assert system["role"] == "system"
    assert user["role"] == "user"


def test_system_prompt_contains_only_selected_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def fake_request(self: OllamaCleanupClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        prompts.append(body["messages"][0]["content"])
        return _chat_reply("ok")

    monkeypatch.setattr(OllamaCleanupClient, "_request", fake_request)
    ollama = OllamaCleanupClient("http://x", "m")
    ollama.cleanup(["hi"], ["punctuation", "thai_polish"])

    system = prompts[0]
    assert MODE_INSTRUCTIONS["punctuation"] in system
    assert MODE_INSTRUCTIONS["thai_polish"] in system
    for mode in ("casing", "fillers", "fluency"):
        assert MODE_INSTRUCTIONS[mode] not in system
    assert "never merge or split lines" in system.lower()


def test_batch_prompt_carries_line_count_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def fake_request(self: OllamaCleanupClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        prompts.append(body["messages"][1]["content"])
        return _chat_reply("a\nb")

    monkeypatch.setattr(OllamaCleanupClient, "_request", fake_request)
    ollama = OllamaCleanupClient("http://x", "m")
    ollama.cleanup(["one", "two"], ["punctuation"])

    assert "2 subtitle lines" in prompts[0]
    assert "exactly 2 plain lines" in prompts[0]


def test_unknown_mode_rejected() -> None:
    ollama = OllamaCleanupClient("http://x", "m")
    with pytest.raises(CleanupServiceError) as exc:
        ollama.cleanup(["hi"], ["translate"])  # type: ignore[list-item]
    assert exc.value.status_code == 400
    assert "translate" in exc.value.message


def test_empty_modes_rejected() -> None:
    ollama = OllamaCleanupClient("http://x", "m")
    with pytest.raises(CleanupServiceError) as exc:
        ollama.cleanup(["hi"], [])
    assert exc.value.status_code == 400


def test_numbered_batch_reply_is_cleaned(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(self: OllamaCleanupClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        lines = body["messages"][1]["content"].split("\n")[-2:]
        return _chat_reply("\n".join(f"{i}. fixed {line}" for i, line in enumerate(lines, 1)))

    monkeypatch.setattr(OllamaCleanupClient, "_request", fake_request)
    ollama = OllamaCleanupClient("http://x", "m")
    result = ollama.cleanup(["one", "two"], ["punctuation"])
    assert result.texts == ["fixed one", "fixed two"]


def test_line_mismatch_falls_back_per_cue(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(self: OllamaCleanupClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        prompt = body["messages"][1]["content"]
        if "subtitle lines" in prompt:  # batch request
            return _chat_reply("merged into one line")  # wrong count (2 -> 1)
        cue = prompt.split("\n\n\n")[1]
        return _chat_reply(f"wrapped\noutput ({cue})")

    monkeypatch.setattr(OllamaCleanupClient, "_request", fake_request)
    ollama = OllamaCleanupClient("http://x", "m")
    result = ollama.cleanup(["alpha", "beta"], ["punctuation"])

    assert result.texts == ["wrapped output (alpha)", "wrapped output (beta)"]
    assert result.requests == 3  # 1 batch + 2 per-cue retries


def test_fallback_failure_raises_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(self: OllamaCleanupClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        prompt = body["messages"][1]["content"]
        if "subtitle lines" in prompt:
            return _chat_reply("only one line")  # mismatch (2 -> 1)
        return _chat_reply("   ")  # empty single-cue response -> failure

    monkeypatch.setattr(OllamaCleanupClient, "_request", fake_request)
    ollama = OllamaCleanupClient("http://x", "m")
    with pytest.raises(CleanupServiceError) as exc:
        ollama.cleanup(["alpha", "beta"], ["punctuation"])
    assert exc.value.status_code == 502


def test_unreachable_server_maps_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float | None = None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    ollama = OllamaCleanupClient("http://127.0.0.1:11434", "m")
    with pytest.raises(CleanupServiceError) as exc:
        ollama.cleanup(["hi"], ["punctuation"])
    assert exc.value.status_code == 502
    assert "Ollama" in exc.value.message


def test_missing_model_maps_to_404_with_pull_hint(
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
    ollama = OllamaCleanupClient("http://x", "m")
    with pytest.raises(CleanupServiceError) as exc:
        ollama.cleanup(["hi"], ["punctuation"])
    assert exc.value.status_code == 404
    assert "ollama pull" in exc.value.message


# ---------------------------------------------------------------- API tests


def _fake_ollama_chat(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[dict]:
    calls: list[dict] = []

    def fake_request(self: OllamaCleanupClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        calls.append(body or {})
        return _chat_reply(reply)

    monkeypatch.setattr(OllamaCleanupClient, "_request", fake_request)
    return calls


def test_cleanup_endpoint_happy_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_ollama_chat(monkeypatch, "สวัสดีครับ\nสบายดีไหม")
    job_id = seed_translation_job(["สวัสดี  ครับ", "", "สบายดี ไหม"])

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/cleanup",
        json={"modes": ["punctuation", "thai_polish"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == "qwen2.5:7b"
    assert body["modes"] == ["punctuation", "thai_polish"]
    assert body["total"] == 3
    assert body["cleaned"] == 2  # the blank cue is not counted as cleaned
    assert [item["text"] for item in body["subtitles"]] == ["สวัสดีครับ", "", "สบายดีไหม"]
    # the system message carries the selected mode instructions
    system = calls[0]["messages"][0]["content"]
    assert MODE_INSTRUCTIONS["punctuation"] in system
    assert MODE_INSTRUCTIONS["thai_polish"] in system


def test_cleanup_without_subtitles_is_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, "x")
    job_id = seed_translation_job(["Hello"])
    from translation_fixtures import clear_subtitles

    clear_subtitles(job_id)
    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/cleanup", json={"modes": ["punctuation"]}
    )
    assert response.status_code == 409


def test_cleanup_with_empty_modes_is_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, "x")
    job_id = seed_translation_job(["Hello"])
    response = client.post(f"/api/v1/jobs/{job_id}/subtitles/cleanup", json={"modes": []})
    assert response.status_code == 422  # pydantic min_length=1


def test_cleanup_with_invalid_mode_is_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, "x")
    job_id = seed_translation_job(["Hello"])
    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/cleanup", json={"modes": ["summarise"]}
    )
    assert response.status_code == 422


def test_cleanup_unknown_job_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, "x")
    response = client.post(
        "/api/v1/jobs/nope/subtitles/cleanup", json={"modes": ["punctuation"]}
    )
    assert response.status_code == 404


def test_cleanup_model_override_from_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_ollama_chat(monkeypatch, "ok")
    job_id = seed_translation_job(["Hello"])

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/cleanup",
        json={"modes": ["punctuation"], "model": "llama3.1:8b"},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "llama3.1:8b"
    assert calls[0]["model"] == "llama3.1:8b"


def test_cleanup_never_touches_timestamps_or_persistence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint returns raw texts only - rows on disk are unchanged."""
    _fake_ollama_chat(monkeypatch, "Cleaned line")
    job_id = seed_translation_job(["Original line"])

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/cleanup", json={"modes": ["punctuation"]}
    )
    assert response.status_code == 200

    rows = client.get(f"/api/v1/jobs/{job_id}/subtitles").json()
    assert rows[0]["text"] == "Original line"  # NOT the cleaned text
    assert rows[0]["start_ms"] == 0
    assert rows[0]["end_ms"] == 1500


def test_cleanup_errors_map_cleanly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        OllamaCleanupClient, "_request",
        lambda self, path, body=None, timeout=None: (_ for _ in ()).throw(
            CleanupServiceError(502, "Could not reach Ollama. Check that it is running.")
        ),
    )
    job_id = seed_translation_job(["Hello"])

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/cleanup", json={"modes": ["punctuation"]}
    )
    assert response.status_code == 502
    assert "Ollama" in response.json()["detail"]
