from __future__ import annotations

from pathlib import Path

import pytest

from sparrow.config import load_config_file
from sparrow.credential_config import ParseError, parse_credentials
from sparrow.credentials import CredentialSelection
from sparrow.models import Model, Provider
from sparrow.quota import QuotaStore
from sparrow.router import Pool


def _provider(provider_id: str = "nvidia") -> Provider:
    return Provider(provider_id, provider_id, "openai", "https://example.invalid", (Model("model"),), "API_KEY")


def test_yaml_config_loads_provider_key_mapping(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "providers:\n  nvidia:\n    enabled: true\n    api_keys:\n      - env: NVIDIA_API_KEY_1\n      - env: NVIDIA_API_KEY_2\n",
        encoding="utf-8",
    )
    data = load_config_file({"SPARROW_CONFIG_FILE": str(path)})
    slots = parse_credentials(data, [_provider()], {"NVIDIA_API_KEY_1": "one", "NVIDIA_API_KEY_2": "two"})
    assert [slot.id for slot in slots] == ["key-1", "key-2"]
    assert [slot.env_var for slot in slots] == ["NVIDIA_API_KEY_1", "NVIDIA_API_KEY_2"]


def test_provider_schema_disabled_and_empty_keys_are_unavailable():
    data = {"providers": {"nvidia": {"enabled": False, "api_keys": [{"env": "KEY"}]}}}
    slots = parse_credentials(data, [_provider()], {"KEY": "secret"})
    assert slots[0].enabled is False


def test_legacy_credentials_override_compact_provider_schema():
    data = {
        "providers": {"nvidia": {"api_keys": [{"env": "NEW_KEY"}]}},
        "credentials": [{
            "provider": "nvidia", "id": "legacy-row", "env_var": "OLD_KEY",
            "quota_group": "shared", "enabled": True,
        }],
    }
    slots = parse_credentials(data, [_provider()], {"OLD_KEY": "old", "NEW_KEY": "new"})
    assert [(slot.id, slot.env_var) for slot in slots] == [("legacy-row", "OLD_KEY")]


def test_provider_schema_rejects_unknown_fields():
    with pytest.raises(ParseError, match="unsupported provider fields"):
        parse_credentials({"providers": {"nvidia": {"region": "us", "api_keys": []}}}, [_provider()], {})


def test_pool_from_default_config_uses_compact_provider_slots(tmp_path, monkeypatch):
    import sparrow.router as router

    config = tmp_path / "config.toml"
    config.write_text(
        '[providers.nvidia]\nenabled = true\n'
        'api_keys = [{ env = "NVIDIA_API_KEY_1" }]\n',
        encoding="utf-8",
    )
    provider = _provider()
    monkeypatch.setattr(router, "load_catalog", lambda: [provider])
    monkeypatch.setenv("SPARROW_CONFIG_FILE", str(config))
    monkeypatch.setenv("NVIDIA_API_KEY_1", "synthetic-key")
    monkeypatch.setenv("SPARROW_CREDENTIAL_STATE_FILE", str(tmp_path / "state.db"))
    pool = Pool.from_default_config(
        env={
            "SPARROW_CONFIG_FILE": str(config),
            "NVIDIA_API_KEY_1": "synthetic-key",
            "SPARROW_CREDENTIAL_STATE_FILE": str(tmp_path / "state.db"),
        },
        quota=QuotaStore(path=tmp_path / "quota.json"),
    )
    assert pool.credential_manager is not None
    selection = pool.credential_manager.reserve("nvidia", "model", "chat")
    assert isinstance(selection, CredentialSelection)
    assert selection.secret == "synthetic-key"
