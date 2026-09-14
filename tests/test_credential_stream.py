from __future__ import annotations

import json

import pytest

from sparrow import client as client_module
from sparrow.credentials import CredentialOperation, CredentialSelection
from sparrow.errors import ProviderHTTPError
from sparrow.router import Pool


class _Manager:
    def __init__(self) -> None:
        self.index = 0
        self.reservations: list[str] = []
        self.failures: list[object] = []

    def reserve(self, provider_id, model, operation, **_kwargs):
        assert operation is CredentialOperation.CHAT
        self.index += 1
        credential_id = f"key-{self.index}"
        self.reservations.append(credential_id)
        return CredentialSelection(
            credential_id=credential_id,
            provider_id=provider_id,
            quota_group="shared",
            secret=f"secret-{self.index}",
            attempt_id=f"attempt-{self.index}",
            generation="generation-1",
        )

    def record_failure(self, selection, failure) -> None:
        self.failures.append((selection, failure))


def _sse(*rows: dict) -> list[str]:
    return [f"data: {json.dumps(row)}" for row in rows] + ["data: [DONE]"]


def test_stream_pre_content_auth_failure_rotates_to_another_managed_key(providers):
    manager = _Manager()
    headers: list[str | None] = []

    def stream_post(url, request_headers, body, timeout):
        del url, body, timeout
        headers.append(request_headers.get("Authorization"))
        if len(headers) == 1:
            return 401, iter(("unauthorized",))
        return 200, iter(_sse({"choices": [{"delta": {"content": "ok"}}]}))

    pool = Pool(
        providers,
        env={"ALPHA_KEY": "legacy-secret"},
        stream_post=stream_post,
        credential_manager=manager,  # type: ignore[arg-type]
    )

    output = list(pool.stream_chat([{"role": "user", "content": "hello"}], providers=["alpha"]))

    assert output[-1] == "ok"
    assert headers == ["Bearer secret-1", "Bearer secret-2"]
    assert len(manager.failures) == 1


def test_stream_error_after_content_does_not_fail_over_or_emit_second_provider(providers):
    calls: list[str] = []

    def stream_post(url, request_headers, body, timeout):
        del url, request_headers, body, timeout
        calls.append("request")
        return 200, iter(
            _sse(
                {"choices": [{"delta": {"content": "partial"}}]},
                {"error": {"message": "upstream failed", "code": 502}},
            )
        )

    pool = Pool(
        providers,
        env={"ALPHA_KEY": "legacy-secret", "BETA_KEY": "beta-secret"},
        stream_post=stream_post,
    )

    stream = pool.stream_chat([{"role": "user", "content": "hello"}], providers=["alpha"])
    meta = next(stream)
    assert isinstance(meta, dict)
    assert meta["provider"] == "alpha"
    assert next(stream) == "partial"
    with pytest.raises(ProviderHTTPError, match="upstream failed"):
        next(stream)
    assert calls == ["request"]


def test_stream_usage_callback_is_internal_and_preserves_text_shape(providers):
    usage: dict[str, int] = {}

    def stream_post(url, headers, body, timeout):
        del url, headers, body, timeout
        return 200, iter(
            _sse(
                {"choices": [{"delta": {"content": "ok"}}]},
                {"usage": {"prompt_tokens": 3, "completion_tokens": 1}},
            )
        )

    result = list(
        client_module.stream_call(
            providers[0],
            "alpha-small",
            [{"role": "user", "content": "hello"}],
            api_key="secret",
            env={},
            stream_post=stream_post,
            usage_callback=usage.update,
        )
    )

    assert result == ["ok"]
    assert usage == {"prompt_tokens": 3, "completion_tokens": 1}
