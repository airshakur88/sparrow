from __future__ import annotations

import json
import tomllib

import pytest

from sparrow.cli import build_parser
from sparrow.credential_cli import (
    register_credential,
    remove_credential,
    render_status,
    render_usage,
)
from sparrow.credential_store import CredentialStore


def test_register_credential_preserves_existing_tables_and_adds_slot(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[settings]\nrouting = "fast"\n\n[keys]\nOLD = "old-secret"\n', encoding="utf-8")

    register_credential(
        path,
        provider="alpha",
        credential_id="secondary",
        env_var="ALPHA_SECONDARY",
        quota_group="shared",
        secret="new-secret",
    )

    content = path.read_text(encoding="utf-8")
    assert 'routing = "fast"' in content
    assert 'OLD = "old-secret"' in content
    assert 'ALPHA_SECONDARY = "new-secret"' in content
    assert 'id = "secondary"' in content
    parsed = tomllib.loads(content)
    assert parsed["keys"]["ALPHA_SECONDARY"] == "new-secret"
    assert parsed["credentials"][0]["id"] == "secondary"


def test_register_credential_escapes_values_and_preserves_following_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[keys]\nOLD = \"old\"\n\n[settings]\nrouting = \"fast\"\n", encoding="utf-8")

    register_credential(
        path,
        provider='provider"name',
        credential_id="secondary",
        env_var="SECONDARY_KEY",
        quota_group="shared",
        secret='secret\\with\"quotes',
    )

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["keys"]["SECONDARY_KEY"] == 'secret\\with"quotes'
    assert parsed["settings"]["routing"] == "fast"
    assert parsed["credentials"][0]["provider"] == 'provider"name'


def test_register_credential_rejects_conflicting_existing_key(tmp_path):
    path = tmp_path / "config.toml"
    original = '[keys]\nSECONDARY_KEY = "old"\n'
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="different value"):
        register_credential(
            path,
            provider="alpha",
            credential_id="secondary",
            env_var="SECONDARY_KEY",
            quota_group="shared",
            secret="new",
        )

    assert path.read_text(encoding="utf-8") == original


def test_register_malformed_config_is_untouched(tmp_path):
    path = tmp_path / "config.toml"
    original = "[settings\ninvalid"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="malformed"):
        register_credential(
            path,
            provider="alpha",
            credential_id="secondary",
            env_var="ALPHA_SECONDARY",
            quota_group="shared",
            secret="new-secret",
        )

    assert path.read_text(encoding="utf-8") == original


def test_keys_add_has_no_secret_value_option():
    parser = build_parser()
    args = parser.parse_args(["keys", "add", "alpha", "--id", "secondary"])
    assert args.credential_id == "secondary"
    with pytest.raises(SystemExit):
        parser.parse_args(["keys", "add", "alpha", "--value", "secret"])


def test_usage_json_is_stable_and_secret_free(tmp_path):
    store = CredentialStore(tmp_path / "state.db")
    config = tmp_path / "config.toml"
    config.write_text(
        '[keys]\nALPHA_PRIMARY = "secret-value"\n\n'
        '[[credentials]]\nprovider = "alpha"\nid = "primary"\n'
        'env_var = "ALPHA_PRIMARY"\nquota_group = "team-a"\nenabled = true\n',
        encoding="utf-8",
    )
    store.reserve_attempt("attempt", "request", "alpha", "primary", "team-a", "model", "chat", "gen", 10)
    store.mark_dispatched("attempt")
    store.finalize_attempt("attempt", "succeeded", prompt_tokens=2, completion_tokens=3)
    output = render_usage(store, as_json=True, config_path=config)
    rows = json.loads(output)
    assert rows[0]["quota_group"] == "team-a"
    assert rows[0]["succeeded"] == 1
    assert rows[0]["prompt_tokens"] == 2
    assert rows[0]["completion_tokens"] == 3
    assert "secret" not in output.lower()


def test_status_shows_duplicate_alias_without_secret(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[keys]\nALPHA_ONE = "shared-secret"\nALPHA_TWO = "shared-secret"\n\n'
        '[[credentials]]\nprovider = "alpha"\nid = "one"\nenv_var = "ALPHA_ONE"\n'
        'quota_group = "team-a"\nenabled = true\n\n'
        '[[credentials]]\nprovider = "alpha"\nid = "two"\nenv_var = "ALPHA_TWO"\n'
        'quota_group = "team-a"\nenabled = true\n',
        encoding="utf-8",
    )
    status = render_status(config, CredentialStore(tmp_path / "state.db"), env={})
    assert "alpha/one env=ALPHA_ONE group=team-a status=ready" in status
    assert "alpha/two env=ALPHA_TWO group=team-a status=duplicate-alias:one" in status
    assert "shared-secret" not in status


def test_remove_credential_removes_only_target_slot_and_unshared_key(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[keys]\nONE = "one-secret"\nTWO = "two-secret"\n\n'
        '[[credentials]]\nprovider = "alpha"\nid = "one"\n'
        'env_var = "ONE"\nquota_group = "shared"\nenabled = true\n\n'
        '[[credentials]]\nprovider = "alpha"\nid = "two"\n'
        'env_var = "TWO"\nquota_group = "shared"\nenabled = true\n',
        encoding="utf-8",
    )

    assert remove_credential(config, provider="alpha", credential_id="one") == ("alpha", "ONE")
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert parsed["keys"] == {"TWO": "two-secret"}
    assert [row["id"] for row in parsed["credentials"]] == ["two"]


def test_remove_credential_rejects_ambiguous_id(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[[credentials]]\nprovider = "alpha"\nid = "shared"\nenv_var = "A"\n\n'
        '[[credentials]]\nprovider = "beta"\nid = "shared"\nenv_var = "B"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ambiguous"):
        remove_credential(config, provider=None, credential_id="shared")


def test_register_credential_accumulates_distinct_slots(tmp_path):
    config = tmp_path / "config.toml"

    register_credential(
        config,
        provider="alpha",
        credential_id="key-1",
        env_var="ALPHA_API_KEY",
        quota_group="shared",
        secret="first-secret",
    )
    register_credential(
        config,
        provider="alpha",
        credential_id="key-2",
        env_var="ALPHA_API_KEY_2",
        quota_group="shared",
        secret="second-secret",
    )

    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert [row["id"] for row in parsed["credentials"]] == ["key-1", "key-2"]
    assert set(parsed["keys"]) == {"ALPHA_API_KEY", "ALPHA_API_KEY_2"}
