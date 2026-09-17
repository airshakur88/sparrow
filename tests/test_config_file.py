                                                   

from __future__ import annotations

import sparrow.config as config_module
from sparrow.config import (
    config_diagnostics,
    configured_providers,
    effective_env,
    known_aliases,
    load_catalog,
    load_config_file,
    resolve_alias,
    settings,
)


def _write(tmp_path, body: str) -> dict[str, str]:
    p = tmp_path / "config.toml"
    p.write_text(body)
    return {"SPARROW_CONFIG_FILE": str(p)}


def test_no_config_file_is_empty():
    assert load_config_file({"SPARROW_CONFIG_FILE": "/nonexistent/x.toml"}) == {}


def test_keys_fill_under_env(tmp_path):
    env = _write(tmp_path, '[keys]\nGROQ_API_KEY = "from-file"\nCEREBRAS_API_KEY = "from-file"\n')
    env["CEREBRAS_API_KEY"] = "from-env"                 
    merged = effective_env(env)
    assert merged["GROQ_API_KEY"] == "from-file"
    assert merged["CEREBRAS_API_KEY"] == "from-env"


def test_configured_providers_reads_default_config_file(tmp_path, monkeypatch):
    env = _write(tmp_path, '[keys]\nGROQ_API_KEY = "from-file"\n')
    monkeypatch.setenv("SPARROW_CONFIG_FILE", env["SPARROW_CONFIG_FILE"])
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    ids = {p.id for p in configured_providers(load_catalog())}

    assert "groq" in ids


def test_configured_providers_reads_provider_credential_slots(tmp_path):
    env = _write(
        tmp_path,
        '[providers.nvidia]\n'
        'api_keys = [{ id = "nvidia-1", env = "NVIDIA_API_KEY_1" }]\n',
    )
    env["NVIDIA_API_KEY_1"] = "test-key"

    ids = {p.id for p in configured_providers(load_catalog(), env)}

    assert "nvidia" in ids


def test_configured_providers_reads_numbered_keys(tmp_path):
    env = _write(tmp_path, '[keys]\nNVIDIA_API_KEY_1 = "from-file"\n')

    ids = {p.id for p in configured_providers(load_catalog(), env)}

    assert "nvidia" in ids


def test_configured_providers_ignores_disabled_provider_credential_slot(tmp_path):
    env = _write(
        tmp_path,
        '[providers.nvidia]\n'
        'api_keys = [{ id = "nvidia-1", env = "NVIDIA_API_KEY_1", enabled = false }]\n',
    )
    env["NVIDIA_API_KEY_1"] = "test-key"

    ids = {p.id for p in configured_providers(load_catalog(), env)}

    assert "nvidia" not in ids


def test_config_alias(tmp_path):
    env = _write(tmp_path, '[aliases]\n"gpt-4o-mini" = "groq/llama-3.1-8b-instant"\n')
    assert resolve_alias("gpt-4o-mini", env) == "groq/llama-3.1-8b-instant"


def test_known_aliases_include_config_alias(tmp_path):
    env = _write(tmp_path, '[aliases]\n"my-model" = "groq/llama-3.1-8b-instant"\n')
    assert "my-model" in known_aliases(env)


def test_env_alias_beats_config(tmp_path):
    env = _write(tmp_path, '[aliases]\n"gpt-4o-mini" = "from-config"\n')
    env["SPARROW_ALIAS_GPT_4O_MINI"] = "from-env"
    assert resolve_alias("gpt-4o-mini", env) == "from-env"


def test_settings(tmp_path):
    env = _write(tmp_path, '[settings]\ncooldown_seconds = 30\nproxy_key = "abc"\n')
    s = settings(env)
    assert s["cooldown_seconds"] == 30
    assert s["proxy_key"] == "abc"


def test_virtual_provider_setting_normalizes_nonempty_string_ids():
    assert config_module.parse_virtual_providers(
        {"virtual_providers": [" openai ", "", 42, "openai"]}
    ) == frozenset({"openai"})


def test_empty_virtual_provider_setting_has_no_opt_in():
    assert config_module.parse_virtual_providers({"virtual_providers": []}) == frozenset()


def test_malformed_config_is_ignored(tmp_path):
    env = _write(tmp_path, "this is not valid toml = = =")
    assert load_config_file(env) == {}


def test_config_file_parse_is_cached_but_return_value_is_isolated(tmp_path, monkeypatch):
    env = _write(tmp_path, '[keys]\nGROQ_API_KEY = "secret"\n')
    original = config_module.tomllib.load
    calls = 0

    def counted(handle):
        nonlocal calls
        calls += 1
        return original(handle)

    monkeypatch.setattr(config_module.tomllib, "load", counted)
    first = load_config_file(env)
    first["keys"]["GROQ_API_KEY"] = "mutated"

    assert load_config_file(env)["keys"]["GROQ_API_KEY"] == "secret"
    assert calls == 1


def test_config_diagnostics_are_strict_and_secret_safe(tmp_path):
    env = _write(tmp_path, '[keys]\nGROQ_API_KEY = "super-secret"\nbroken =\n')
    diagnostics = config_diagnostics(env)

    assert diagnostics[0]["code"] == "toml_syntax"
    assert diagnostics[0]["line"] == 3
    assert diagnostics[0]["column"] is not None
    assert "super-secret" not in repr(diagnostics)


def test_config_diagnostics_report_wrong_table_types_without_values(tmp_path):
    env = _write(
        tmp_path,
        'keys = "super-secret"\nsettings = 42\naliases = ["private-model"]\n',
    )
    diagnostics = config_diagnostics(env)

    assert {item["table"] for item in diagnostics} == {"keys", "settings", "aliases"}
    assert {item["code"] for item in diagnostics} == {"table_type"}
    assert "super-secret" not in repr(diagnostics)
    assert "private-model" not in repr(diagnostics)


def test_config_diagnostics_report_unknown_virtual_provider_ids(tmp_path):
    env = _write(
        tmp_path,
        '[settings]\nvirtual_providers = ["openai", "missing-provider"]\n',
    )

    diagnostics = config_diagnostics(env)

    unknown = [item for item in diagnostics if item["code"] == "unknown_provider"]
    assert len(unknown) == 1
    assert unknown[0]["setting"] == "virtual_providers"
    assert unknown[0]["provider"] == "missing-provider"
    assert "openai" not in repr(unknown)


def test_config_diagnostics_reject_free_virtual_provider_ids(tmp_path):
    env = _write(tmp_path, '[settings]\nvirtual_providers = ["openrouter"]\n')

    diagnostics = config_diagnostics(env)

    assert len(diagnostics) == 1
    assert diagnostics[0]["code"] == "setting_value"
    assert diagnostics[0]["provider"] == "openrouter"
    assert "paid providers" in str(diagnostics[0]["message"])


def test_config_diagnostics_report_free_virtual_provider_as_setting_value(tmp_path):
    env = _write(tmp_path, '[settings]\nvirtual_providers = ["openrouter"]\n')

    diagnostics = config_diagnostics(env)

    assert len(diagnostics) == 1
    assert diagnostics[0]["code"] == "setting_value"
    assert diagnostics[0]["setting"] == "virtual_providers"
    assert diagnostics[0]["provider"] == "openrouter"
    assert "paid providers" in str(diagnostics[0]["message"])
    assert "unknown_provider" not in repr(diagnostics)


def test_config_diagnostics_report_invalid_virtual_provider_setting_type(tmp_path):
    env = _write(tmp_path, '[settings]\nvirtual_providers = "openai"\n')

    diagnostics = config_diagnostics(env)

    assert len(diagnostics) == 1
    assert diagnostics[0]["code"] == "setting_type"
    assert diagnostics[0]["message"] == "[settings].virtual_providers must be a list"
    assert diagnostics[0]["setting"] == "virtual_providers"
