from __future__ import annotations

from sparrow import client as client_module
from sparrow.credentials import CredentialOperation, CredentialSelection
from sparrow.router import Pool


class _Manager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, CredentialOperation]] = []

    def reserve(self, provider_id, model, operation, **_kwargs):
        self.calls.append((provider_id, model, operation))
        return CredentialSelection(
            credential_id="secondary",
            provider_id=provider_id,
            quota_group="shared",
            secret="managed-secret",
            attempt_id="attempt-1",
            generation="generation-1",
        )


def test_chat_passes_the_reserved_secret_to_the_single_transport_attempt(providers):
    manager = _Manager()
    seen: list[dict[str, str]] = []

    def post(url, headers, body, timeout):
        del url, body, timeout
        seen.append(headers)
        return client_module.HTTPResult(
            200,
            {"choices": [{"message": {"content": "ok"}}]},
            "",
        )

    pool = Pool(
        providers,
        env={"ALPHA_KEY": "legacy-secret"},
        post=post,
        credential_manager=manager,                          
    )

    reply = pool.chat([{"role": "user", "content": "hello"}], providers=["alpha"])

    assert reply.text == "ok"
    assert manager.calls[0][0] == "alpha"
    assert manager.calls[0][2] is CredentialOperation.CHAT
    assert seen[0]["Authorization"] == "Bearer managed-secret"
