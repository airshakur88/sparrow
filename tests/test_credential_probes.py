from __future__ import annotations

from sparrow import benchmark as benchmark_module
from sparrow import client as client_module
from sparrow.conformance import FEATURE_CHAT, run_target_canaries
from sparrow.credentials import (
    CredentialOperation,
    CredentialSelection,
    CredentialUnavailable,
    UnavailableReason,
)
from sparrow.router import Pool


class _Manager:
    def __init__(self, unavailable: bool = False) -> None:
        self.calls: list[tuple[str, str, CredentialOperation]] = []
        self.unavailable = unavailable

    def reserve(self, provider_id, model, operation, **_kwargs):
        self.calls.append((provider_id, model, operation))
        if self.unavailable:
            return CredentialUnavailable(UnavailableReason.COOLDOWN, provider_id, "cooling")
        return CredentialSelection(
            credential_id="probe-key",
            provider_id=provider_id,
            quota_group="shared",
            secret="managed-probe-secret",
            attempt_id="attempt",
            generation="generation",
        )


def test_benchmark_uses_managed_discovery_and_probe_keys(providers, monkeypatch):
    manager = _Manager()
    discovered_keys: list[str | None] = []
    call_keys: list[str | None] = []

    def discover(_base_url, *, api_key=None, timeout):
        del timeout
        discovered_keys.append(api_key)
        return ["alpha-small"]

    def call(*_args, api_key=None, **_kwargs):
        call_keys.append(api_key)
        return client_module.Reply("ok", "alpha", "alpha-small", {})

    monkeypatch.setattr(benchmark_module, "discover_openai_models", discover)
    monkeypatch.setattr(benchmark_module._client, "call", call)
    pool = Pool(providers, env={}, credential_manager=manager)                          

    rows = benchmark_module.benchmark(pool, providers=["alpha"], workers=1)

    assert rows[0].ok
    assert discovered_keys == ["managed-probe-secret"]
    assert call_keys == ["managed-probe-secret"]
    assert [operation for _, _, operation in manager.calls] == [
        CredentialOperation.DISCOVERY,
        CredentialOperation.PROBE,
    ]


def test_conformance_reuses_one_managed_probe_selection(providers):
    manager = _Manager()
    seen_keys: list[str | None] = []

    def call(*_args, api_key=None, **_kwargs):
        seen_keys.append(api_key)
        return client_module.Reply("ok", "alpha", "alpha-small", {})

    result = run_target_canaries(
        providers[0],
        "alpha-small",
        env={},
        features=[FEATURE_CHAT],
        call_fn=call,
        stream_fn=lambda *_args, **_kwargs: (),
        credential_manager=manager,                          
    )

    assert result[FEATURE_CHAT]["classification"] == "verified"
    assert seen_keys == ["managed-probe-secret"]
    assert [operation for _, _, operation in manager.calls] == [CredentialOperation.PROBE]


def test_conformance_reports_exhausted_probe_without_calling_provider(providers):
    manager = _Manager(unavailable=True)
    called = False

    def call(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not be called")

    result = run_target_canaries(
        providers[0],
        "alpha-small",
        env={},
        features=[FEATURE_CHAT],
        call_fn=call,
        stream_fn=lambda *_args, **_kwargs: (),
        credential_manager=manager,                          
    )

    assert result[FEATURE_CHAT]["status"] == "unavailable"
    assert not called
