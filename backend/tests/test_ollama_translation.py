"""Tests for the Ollama TranslateGemma translation engine.

The Ollama server is faked: ``OllamaTranslateClient._request`` (the only
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
from app.services.translation.ollama_translate import (
    _CHAT_PATH,
    _TAGS_PATH,
    OllamaTranslateClient,
    TranslationServiceError,
)


def _chat_reply(content: str) -> dict:
    return {"message": {"role": "assistant", "content": content}}


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------- unit tests


def test_prompt_uses_official_template(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        calls.append((path, body or {}))
        return _chat_reply("สวัสดี")

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    ollama = OllamaTranslateClient("http://127.0.0.1:11434", "translategemma:12b")
    result = ollama.translate(["Hello"], "th", "en")

    assert result.texts == ["สวัสดี"]
    path, body = calls[0]
    assert path == _CHAT_PATH
    assert body["model"] == "translategemma:12b"
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0}
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    prompt = body["messages"][0]["content"]
    # official template shape: names + codes, closing colon, TWO blank lines
    assert prompt.startswith(
        "You are a professional English (en) to Thai (th) translator."
    )
    assert "Please translate the following English text into Thai:" in prompt
    assert ":\n\n\nHello" in prompt
    # single-cue batches carry no line-count instruction
    assert "subtitle lines" not in prompt


def test_order_preserved_and_empty_cues_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        prompts.append(body["messages"][0]["content"])
        text_lines = body["messages"][0]["content"].split("\n")[-1]
        return _chat_reply("\n".join(f"t-{line}" for line in text_lines.split("\n")))

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    ollama = OllamaTranslateClient("http://x", "m")
    result = ollama.translate(["one", "", "three"], "th", "en")

    assert result.texts == ["t-one", "", "t-three"]
    # the empty cue never appears in any prompt: the text block is exactly
    # the two non-empty cues, one per line, no blank line in between
    text_block = prompts[0].rsplit("\n\n\n", 1)[1]
    assert text_block == "one\nthree"
    assert result.detected_source_language is None


def test_batching_within_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    batch_sizes: list[int] = []

    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        lines = body["messages"][0]["content"].split("\n\n\n")[1].split("\n")
        batch_sizes.append(len(lines))
        return _chat_reply("\n".join(f"t{i}" for i in range(len(lines))))

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    ollama = OllamaTranslateClient("http://x", "m")
    cues = [f"line {i}" for i in range(60)]
    result = ollama.translate(cues, "th", "en")

    assert len(result.texts) == 60
    assert sum(batch_sizes) == 60  # nothing lost or duplicated
    assert all(size <= 25 for size in batch_sizes)  # within the cue cap
    assert result.requests == len(batch_sizes)


def test_numbered_batch_reply_is_cleaned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Models sometimes number the reply lines despite the prompt; the
    enumeration prefixes must be stripped, not pasted into subtitles."""

    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        lines = body["messages"][0]["content"].split("\n\n\n")[1].split("\n")
        reply = "\n".join(f"{i}. แปล-{line}" for i, line in enumerate(lines, start=1))
        return _chat_reply(reply)

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    ollama = OllamaTranslateClient("http://x", "m")
    result = ollama.translate(["one", "two", "three"], "th", "en")

    assert result.texts == ["แปล-one", "แปล-two", "แปล-three"]


def test_genuine_leading_digits_survive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Digits that genuinely start a subtitle (countdowns, amounts) are
    only enumeration when the number matches the line's position - here
    none do, so every line passes through untouched."""

    reply = "3. 2. 1. ขึ้น\n10 บาทที่เหลือ\nepisode 12 begins"
    monkeypatch.setattr(
        OllamaTranslateClient,
        "_request",
        lambda self, path, body=None, timeout=None: _chat_reply(reply),
    )
    ollama = OllamaTranslateClient("http://x", "m")
    result = ollama.translate(["a", "b", "c"], "th", "en")

    assert result.texts == reply.split("\n")


def test_batch_prompt_forbids_line_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        prompts.append(body["messages"][0]["content"])
        return _chat_reply("one\ntwo")

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    ollama = OllamaTranslateClient("http://x", "m")
    ollama.translate(["one", "two"], "th", "en")

    assert "no line numbers" in prompts[0]
    assert "no bullet points" in prompts[0]


def test_line_mismatch_falls_back_per_cue(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        calls.append(body)
        prompt = body["messages"][0]["content"]
        if "subtitle lines" in prompt:  # batch request
            return _chat_reply("merged into one line")  # wrong count (2 -> 1)
        # single-cue fallback: model wraps long output across lines
        cue = prompt.split("\n\n\n")[1]
        return _chat_reply(f"first half\nsecond half ({cue})")

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    ollama = OllamaTranslateClient("http://x", "m")
    result = ollama.translate(["alpha", "beta"], "th", "en")

    # wrapped single-cue output is joined with a single space
    assert result.texts == [
        "first half second half (alpha)",
        "first half second half (beta)",
    ]
    # 1 batch request + 2 per-cue retries, all counted
    assert result.requests == 3


def test_fallback_failure_raises_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        prompt = body["messages"][0]["content"]
        if "subtitle lines" in prompt:
            return _chat_reply("only one line")  # mismatch (2 -> 1)
        return _chat_reply("   ")  # empty single-cue response -> failure

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    ollama = OllamaTranslateClient("http://x", "m")
    with pytest.raises(TranslationServiceError) as exc:
        ollama.translate(["alpha", "beta"], "th", "en")
    assert exc.value.status_code == 502


def test_chinese_codes_alias_to_script_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        prompts.append(body["messages"][0]["content"])
        return _chat_reply("你好")

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    ollama = OllamaTranslateClient("http://x", "m")
    ollama.translate(["hello"], "zh-CN", "en")

    assert "English (en) to Chinese (Simplified) (zh-Hans) translator." in prompts[0]


def test_source_language_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    ollama = OllamaTranslateClient("http://x", "m")
    with pytest.raises(TranslationServiceError) as exc:
        ollama.translate(["hi"], "th", None)
    assert exc.value.status_code == 400
    assert "source language" in exc.value.message


def test_invalid_codes_rejected() -> None:
    ollama = OllamaTranslateClient("http://x", "m")
    with pytest.raises(TranslationServiceError) as target:
        ollama.translate(["hi"], "not a code!", "en")
    with pytest.raises(TranslationServiceError) as source:
        ollama.translate(["hi"], "th", "bad code!")
    assert target.value.status_code == 400
    assert source.value.status_code == 400


def test_unreachable_server_maps_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float | None = None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    ollama = OllamaTranslateClient("http://127.0.0.1:11434", "m")
    with pytest.raises(TranslationServiceError) as exc:
        ollama.translate(["hi"], "th", "en")
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
    ollama = OllamaTranslateClient("http://x", "m")
    with pytest.raises(TranslationServiceError) as exc:
        ollama.translate(["hi"], "th", "en")
    assert exc.value.status_code == 404
    assert "ollama pull" in exc.value.message


def test_list_models_parses_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, float | None]] = []

    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        calls.append((path, timeout))
        return {"models": [{"name": "zeta:1b"}, {"name": "alpha:7b"}, {"name": ""}]}

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    ollama = OllamaTranslateClient("http://x", "m", timeout_seconds=300.0)
    models = ollama.list_models()

    assert models == ["alpha:7b", "zeta:1b"]
    assert calls[0][0] == _TAGS_PATH
    assert calls[0][1] is not None and calls[0][1] < 5  # short probe timeout


# ---------------------------------------------------------------- API tests


def _fake_ollama_chat(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[dict]:
    calls: list[dict] = []

    def fake_request(self: OllamaTranslateClient, path: str, body: dict | None = None,
                     timeout: float | None = None) -> dict:
        if path == _TAGS_PATH:
            return {"models": [{"name": "translategemma:12b"}, {"name": "llama3:8b"}]}
        calls.append(body or {})
        return _chat_reply(reply)

    monkeypatch.setattr(OllamaTranslateClient, "_request", fake_request)
    return calls


def test_languages_endpoint_includes_engines_block(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "google_translate_api_key", "")
    monkeypatch.setattr(
        OllamaTranslateClient, "_request",
        lambda self, path, body=None, timeout=None: (_ for _ in ()).throw(
            TranslationServiceError(502, "Could not reach Ollama.")
        ),
    )

    response = client.get("/api/v1/translation/languages")

    assert response.status_code == 200
    body = response.json()
    # legacy fields intact
    assert body["configured"] is False
    assert len(body["languages"]) > 0
    assert body["engines"]["google"] == {"configured": False}
    assert body["engines"]["ollama"]["available"] is False
    assert body["engines"]["ollama"]["models"] == []
    assert body["engines"]["ollama"]["model"] == get_settings().ollama_translate_model


def test_languages_endpoint_lists_installed_models(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, "x")
    response = client.get("/api/v1/translation/languages")

    assert response.status_code == 200
    ollama = response.json()["engines"]["ollama"]
    assert ollama["available"] is True
    assert ollama["models"] == ["llama3:8b", "translategemma:12b"]


def test_translate_with_ollama_happy_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_ollama_chat(monkeypatch, "สวัสดี\nสบายดีไหม")
    job_id = seed_translation_job(["Hello world", "", "How are you?"], detected_language="en")

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/translate",
        json={"engine": "ollama", "target_language": "th", "mode": "dual"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "ollama"
    assert body["model"] == "translategemma:12b"
    assert body["usage"] is None  # local + free: not metered
    assert body["detected_source_language"] is None
    assert [item["text"] for item in body["subtitles"]] == ["สวัสดี", "", "สบายดีไหม"]
    # prompt used the job's detected language as source
    prompt = calls[0]["messages"][0]["content"]
    assert prompt.startswith("You are a professional English (en) to Thai (th) translator.")


def test_ollama_translation_does_not_meter_usage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, "ok")
    job_id = seed_translation_job(["Hello"], detected_language="en")
    before = client.get("/api/v1/translation/usage").json()

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/translate",
        json={"engine": "ollama", "target_language": "th"},
    )
    assert response.status_code == 200

    after = client.get("/api/v1/translation/usage").json()
    assert after["characters_sent"] == before["characters_sent"]
    assert after["jobs"] == before["jobs"]


def test_ollama_ignores_google_quota(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, "ok")
    monkeypatch.setattr(get_settings(), "google_translate_monthly_char_limit", 10)
    job_id = seed_translation_job(["Hello world, this is long enough to exceed 10"], "en")

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/translate",
        json={"engine": "ollama", "target_language": "th"},
    )
    assert response.status_code == 200  # quota guard is Google-only


def test_ollama_without_any_source_language_is_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama_chat(monkeypatch, "ok")
    job_id = seed_translation_job(["Hello"])  # no detected_language either

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/translate",
        json={"engine": "ollama", "target_language": "th", "source_language": None},
    )
    assert response.status_code == 400
    assert "auto-detect" in response.json()["detail"]


def test_ollama_model_override_from_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_ollama_chat(monkeypatch, "ok")
    job_id = seed_translation_job(["Hello"], detected_language="en")

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/translate",
        json={"engine": "ollama", "target_language": "th", "model": "translategemma:4b"},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "translategemma:4b"
    assert calls[0]["model"] == "translategemma:4b"


def test_ollama_errors_map_cleanly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        OllamaTranslateClient, "_request",
        lambda self, path, body=None, timeout=None: (_ for _ in ()).throw(
            TranslationServiceError(502, "Could not reach Ollama. Check that it is running.")
        ),
    )
    job_id = seed_translation_job(["Hello"], detected_language="en")

    response = client.post(
        f"/api/v1/jobs/{job_id}/subtitles/translate",
        json={"engine": "ollama", "target_language": "th"},
    )
    assert response.status_code == 502
    assert "Ollama" in response.json()["detail"]
