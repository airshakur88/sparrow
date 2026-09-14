from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

import pytest

from sparrow.client import HTTPResult
from sparrow.credential_manager import CredentialManager
from sparrow.credential_store import CredentialStore
from sparrow.credentials import CredentialSlot
from sparrow.models import Model, Provider
from sparrow.proxy import serve
from sparrow.router import Pool


def _post_result(body: dict, status: int = 200, headers: dict | None = None) -> HTTPResult:
    return HTTPResult(status, body, json.dumps(body), headers)


def _request_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def _manager(tmp_path: Path, provider: Provider, env: dict[str, str]) -> CredentialManager:
    store = CredentialStore(tmp_path / "credential.db")
    return CredentialManager(
        [
            CredentialSlot("primary", provider.id, provider.key_env or "KEY_ONE", "team"),
            CredentialSlot("secondary", provider.id, "KEY_TWO", "team"),
        ],
        env,
        store,
    )


def test_loopback_proxy_preserves_public_shape_and_hides_secrets(tmp_path, providers):
    provider = providers[0]
    env = {provider.key_env: "INTEGRATION-SECRET-A", "KEY_TWO": "INTEGRATION-SECRET-B"}
    calls: list[dict] = []

    def post(url, headers, body, timeout):
        calls.append({"url": url, "headers": headers, "body": body})
        return _post_result({"choices": [{"message": {"content": "hello"}}]})

    pool = Pool([provider], env=env, post=post, credential_manager=_manager(tmp_path, provider, env))
    httpd = serve(pool, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/v1/chat/completions"
        response = _request_json(url, {"model": "alpha-small", "messages": [{"role": "user", "content": "hi"}]})
        assert response["choices"][0]["message"]["content"] == "hello"
    finally:
        httpd.shutdown()
        httpd.server_close()
    serialized = json.dumps(response)
    assert "INTEGRATION-SECRET-A" not in serialized
    assert "INTEGRATION-SECRET-B" not in serialized
    assert {call["headers"]["Authorization"] for call in calls} == {
        "Bearer INTEGRATION-SECRET-A"
    }


def test_managed_chat_rejects_one_key_then_rotates_without_leaking_error(tmp_path, providers):
    provider = providers[0]
    env = {provider.key_env: "INTEGRATION-SECRET-A", "KEY_TWO": "INTEGRATION-SECRET-B"}
    seen: list[dict] = []

    def post(url, headers, body, timeout):
        del url, body, timeout
        seen.append(headers)
        if headers["Authorization"] == "Bearer INTEGRATION-SECRET-A":
            return _post_result({"error": {"message": "bad credential"}}, 401)
        return _post_result({"choices": [{"message": {"content": "recovered"}}]})

    manager = _manager(tmp_path, provider, env)
    pool = Pool([provider], env=env, post=post, credential_manager=manager)
    reply = pool.chat([{"role": "user", "content": "hello"}], providers=[provider.id])
    assert reply.text == "recovered"
    assert len(seen) == 2
    assert "INTEGRATION-SECRET-A" not in repr(reply)


def test_embedding_and_transcription_use_selected_wire_credentials(tmp_path):
    embedder = Provider("embed", "Embed", "openai", "https://embed.test/v1", (Model("embed-model"),), key_env="EMBED_KEY")
    transcriber = Provider("audio", "Audio", "openai", "https://audio.test/v1", (Model("audio-model"),), key_env="AUDIO_KEY")
    env = {"EMBED_KEY": "EMBED-SECRET", "AUDIO_KEY": "AUDIO-SECRET"}
    seen: list[dict] = []

    def post(url, headers, body, timeout):
        seen.append({"url": url, "headers": headers, "body": body})
        if url.endswith("/embeddings"):
            return _post_result({"data": [{"embedding": [1.0, 2.0]}]})
        raise AssertionError(url)

    def multipart(url, headers, files, data, timeout):
        seen.append({"url": url, "headers": headers, "data": data})
        return _post_result({"text": "transcribed"})

    pool = Pool(
        [], env=env, post=post, transcribe_post=multipart,
        embedders=[embedder], transcribers=[transcriber],
        credential_manager=CredentialManager(
            [CredentialSlot("embed-slot", "embed", "EMBED_KEY", "team"), CredentialSlot("audio-slot", "audio", "AUDIO_KEY", "team")],
            env, CredentialStore(tmp_path / "modalities.db"),
        ),
    )
    assert pool.embed("hello").vectors == [[1.0, 2.0]]
    assert pool.transcribe(b"audio", "sample.wav").text == "transcribed"
    assert [item["headers"]["Authorization"] for item in seen] == ["Bearer EMBED-SECRET", "Bearer AUDIO-SECRET"]


def test_malformed_retry_after_and_exhausted_keys_do_not_expose_secrets(tmp_path, providers):
    provider = providers[0]
    env = {provider.key_env: "INTEGRATION-SECRET-A", "KEY_TWO": "INTEGRATION-SECRET-B"}

    def post(url, headers, body, timeout):
        del url, headers, body, timeout
        return _post_result({"error": {"message": "quota"}}, 429, {"Retry-After": "not-a-duration"})

    pool = Pool([provider], env=env, post=post, credential_manager=_manager(tmp_path, provider, env))
    with pytest.raises(Exception) as failure:
        pool.chat([{"role": "user", "content": "hello"}], providers=[provider.id])
    message = str(failure.value)
    assert "INTEGRATION-SECRET-A" not in message
    assert "INTEGRATION-SECRET-B" not in message
