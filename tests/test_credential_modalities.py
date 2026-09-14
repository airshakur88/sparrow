from __future__ import annotations

from sparrow import client as client_module
from sparrow.credentials import CredentialOperation, CredentialSelection
from sparrow.models import Model, Provider
from sparrow.router import Pool


class _Manager:
    def __init__(self) -> None:
        self.operations: list[CredentialOperation] = []

    def reserve(self, provider_id, model, operation, **_kwargs):
        self.operations.append(operation)
        return CredentialSelection(
            credential_id="secondary",
            provider_id=provider_id,
            quota_group="shared",
            secret="managed-secret",
            attempt_id=f"attempt-{len(self.operations)}",
            generation="generation-1",
        )


def _provider() -> Provider:
    return Provider(
        id="alpha",
        label="Alpha",
        adapter="openai",
        base_url="https://alpha.test/v1",
        key_env="ALPHA_KEY",
        models=(Model("alpha-1", rpd=0),),
    )


def test_embed_uses_managed_secret_without_legacy_env_key():
    seen: list[str | None] = []

    def post(url, headers, body, timeout):
        del url, body, timeout
        seen.append(headers.get("Authorization"))
        return client_module.HTTPResult(200, {"data": [{"embedding": [1.0]}]}, "")

    manager = _Manager()
    reply = Pool(
        [],
        env={},
        post=post,
        embedders=[_provider()],
        credential_manager=manager,  # type: ignore[arg-type]
    ).embed("hello", providers=["alpha"])

    assert reply.vectors == [[1.0]]
    assert seen == ["Bearer managed-secret"]
    assert manager.operations == [CredentialOperation.EMBED]


def test_transcribe_uses_managed_secret_without_legacy_env_key():
    seen: list[str | None] = []

    def multipart(url, headers, files, data, timeout):
        del url, files, data, timeout
        seen.append(headers.get("Authorization"))
        return client_module.HTTPResult(200, {"text": "hello"}, "")

    manager = _Manager()
    reply = Pool(
        [],
        env={},
        transcribe_post=multipart,
        transcribers=[_provider()],
        credential_manager=manager,  # type: ignore[arg-type]
    ).transcribe(b"audio", "sample.wav", providers=["alpha"])

    assert reply.text == "hello"
    assert seen == ["Bearer managed-secret"]
    assert manager.operations == [CredentialOperation.TRANSCRIBE]
