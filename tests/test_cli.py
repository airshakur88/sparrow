from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sparrow.cli import _strip_fences, build_parser, main
from sparrow.models import Model, Provider


def _subparser_choices(parser: argparse.ArgumentParser, destination: str) -> set[str]:
    action = next(action for action in parser._actions if action.dest == destination)
    assert isinstance(action, argparse._SubParsersAction)
    return set(action.choices)


def test_build_parser_registers_exact_public_commands() -> None:
    parser = build_parser()
    command_action = next(action for action in parser._actions if action.dest == "command")
    assert isinstance(command_action, argparse._SubParsersAction)
    providers_parser = command_action.choices["providers"]
    keys_parser = command_action.choices["key"]

    assert set(command_action.choices) == {
        "ask",
        "start",
        "models",
        "providers",
        "key",
        "keys",
        "settings",
        "quota",
        "doctor",
    }
    assert _subparser_choices(providers_parser, "providers_command") == {"health"}
    assert _subparser_choices(keys_parser, "keys_command") == {
        "status",
        "usage",
        "checklist",
        "add",
        "list",
        "rm",
    }
    assert _subparser_choices(command_action.choices["settings"], "settings_command") == {"edit"}


@pytest.mark.parametrize(
    "removed_command",
    [
        "roles",
        "tokenmax",
        "battle",
        "playground",
        "recipe",
        "jobs",
        "report",
        "cost",
        "quota-wise",
        "stats",
        "badge",
        "local",
        "catalog",
        "capability",
        "conformance",
        "capacity",
        "benchmark",
        "tailnet",
        "init",
        "profile",
        "mcp",
        "code",
    ],
)
def test_removed_top_level_commands_are_rejected(removed_command: str) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([removed_command])


def test_start_parser_accepts_tailnet_options_and_rejects_proxy() -> None:
    parser = build_parser()

    args = parser.parse_args(["start", "--tailnet", "--allow-lan", "--api-key", "secret"])

    assert args.command == "start"
    assert args.tailnet is True
    assert args.allow_lan is True
    assert args.logs is False
    assert parser.parse_args(["start", "--logs"]).logs is True
    help_text = parser.format_help()
    assert "start" in help_text
    assert not any(line.lstrip().startswith("proxy ") for line in help_text.splitlines())
    with pytest.raises(SystemExit):
        parser.parse_args(["proxy"])


def test_strip_fences_handles_plain_and_markdown_json() -> None:
    assert _strip_fences('{"a": 1}') == '{"a": 1}'
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_models_json_is_machine_readable(monkeypatch, capsys) -> None:
    catalog = [
        Provider(
            id="ready",
            label="Ready",
            adapter="openai",
            base_url="https://ready.test/v1",
            auth="none",
            models=(Model("on"),),
        )
    ]
    monkeypatch.setattr("sparrow.cli._runtime_catalog", lambda: catalog)
    monkeypatch.setattr("sparrow.cli.configured_providers", lambda providers: catalog)

    assert main(["models", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["provider"] == "ready"
    assert payload[0]["model"] == "on"
    assert payload[0]["billing"] == "paid"
    assert payload[0]["keyless"] is True


def test_models_json_classifies_each_openai_model_as_paid(monkeypatch, capsys) -> None:
    model_names = (
        "gpt-6-astra",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.5",
    )
    catalog = [
        Provider(
            id="openai",
            label="OpenAI",
            adapter="openai",
            base_url="https://api.openai.com/v1",
            key_env="OPENAI_API_KEY",
            billing="paid",
            models=tuple(Model(name) for name in model_names),
        )
    ]
    monkeypatch.setattr("sparrow.cli._runtime_catalog", lambda: catalog)
    monkeypatch.setattr("sparrow.cli.configured_providers", lambda providers: [])

    assert main(["models", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [row["model"] for row in payload] == list(model_names)
    assert all(row["billing"] == "paid" and row["keyless"] is False for row in payload)


def test_models_and_providers_plain_output_identifies_billing_and_access(
    monkeypatch, capsys
) -> None:
    catalog = [
        Provider(
            id="ready",
            label="Ready",
            adapter="openai",
            base_url="https://ready.test/v1",
            auth="none",
            billing="free",
            models=(Model("on"),),
        ),
        Provider(
            id="paid",
            label="Paid",
            adapter="openai",
            base_url="https://paid.test/v1",
            key_env="PAID_API_KEY",
            billing="paid",
            models=(Model("on"),),
        ),
    ]
    monkeypatch.setattr("sparrow.cli._runtime_catalog", lambda: catalog)
    monkeypatch.setattr("sparrow.cli.configured_providers", lambda providers: [catalog[0]])

    assert main(["providers"]) == 0
    providers_output = capsys.readouterr().out
    assert "free" in providers_output
    assert "keyless" in providers_output
    assert "paid" in providers_output
    assert "key required" in providers_output

    assert main(["models", "--providers", "ready"]) == 0
    models_output = capsys.readouterr().out
    assert "free" in models_output
    assert "keyless" in models_output


def test_main_without_command_shows_welcome(capsys) -> None:
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "SPARROW" in output
    assert "sparrow ask" in output
    assert "sparrow doctor" in output


def test_key_alias_and_new_commands_parse() -> None:
    parser = build_parser()

    assert parser.parse_args(["key", "list"]).command == "key"
    assert parser.parse_args(["keys", "list"]).command == "keys"
    assert parser.parse_args(["key", "rm", "key-1", "--yes"]).credential_id == "key-1"


def test_key_list_never_prints_secret(monkeypatch, tmp_path, capsys) -> None:
    config = tmp_path / "config.toml"
    state = tmp_path / "state.db"
    config.write_text(
        '[keys]\nALPHA_API_KEY = "super-secret"\n\n'
        '[[credentials]]\nprovider = "alpha"\nid = "key-1"\n'
        'env_var = "ALPHA_API_KEY"\nquota_group = "shared"\nenabled = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SPARROW_CONFIG_FILE", str(config))
    monkeypatch.setenv("SPARROW_CREDENTIAL_STATE_FILE", str(state))

    assert main(["key", "list"]) == 0

    output = capsys.readouterr().out
    assert "alpha/key-1" in output
    assert "super-secret" not in output


def test_key_rm_removes_one_slot(monkeypatch, tmp_path, capsys) -> None:
    config = tmp_path / "config.toml"
    state = tmp_path / "state.db"
    config.write_text(
        '[keys]\nONE = "one-secret"\nTWO = "two-secret"\n\n'
        '[[credentials]]\nprovider = "alpha"\nid = "one"\n'
        'env_var = "ONE"\nquota_group = "shared"\nenabled = true\n\n'
        '[[credentials]]\nprovider = "alpha"\nid = "two"\n'
        'env_var = "TWO"\nquota_group = "shared"\nenabled = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SPARROW_CONFIG_FILE", str(config))
    monkeypatch.setenv("SPARROW_KEYS_PATH", str(tmp_path / "keys.toml"))
    monkeypatch.setenv("SPARROW_CREDENTIAL_STATE_FILE", str(state))

    assert main(["key", "rm", "one", "--yes"]) == 0

    content = config.read_text(encoding="utf-8")
    assert 'id = "one"' not in content
    assert 'id = "two"' in content
    assert "ONE =" not in content
    assert "one-secret" not in capsys.readouterr().out


def test_settings_edit_uses_windows_file_association(monkeypatch, tmp_path, capsys) -> None:
    import sparrow.cli as cli_module

    config = tmp_path / "config.toml"
    opened: list[str] = []
    monkeypatch.setenv("SPARROW_CONFIG_FILE", str(config))
    monkeypatch.setattr(cli_module.sys, "platform", "win32")
    monkeypatch.setattr(cli_module.os, "startfile", lambda path: opened.append(path), raising=False)

    assert main(["settings", "edit"]) == 0

    assert opened == [str(config)]
    assert Path(config).exists()
    assert "super-secret" not in capsys.readouterr().out


def test_help_hides_usage_description_version_and_routing_aliases() -> None:
    help_text = build_parser().format_help()

    assert "usage:" not in help_text
    assert "Pool free-tier" not in help_text
    assert "--version" not in help_text
    assert "--routing" not in help_text
    assert "sparrow/quality" not in help_text
