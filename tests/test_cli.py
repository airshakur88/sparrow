from __future__ import annotations

import argparse
import json

import pytest

from sparrow.cli import _strip_fences, build_parser
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
    keys_parser = command_action.choices["keys"]

    assert set(command_action.choices) == {
        "ask",
        "start",
        "models",
        "providers",
        "keys",
        "quota",
        "doctor",
    }
    assert _subparser_choices(providers_parser, "providers_command") == {"health"}
    assert _subparser_choices(keys_parser, "keys_command") == {
        "status",
        "usage",
        "checklist",
        "add",
    }


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
    help_text = parser.format_help()
    assert "start" in help_text
    assert not any(line.lstrip().startswith("proxy ") for line in help_text.splitlines())
    with pytest.raises(SystemExit):
        parser.parse_args(["proxy"])


def test_strip_fences_handles_plain_and_markdown_json() -> None:
    assert _strip_fences('{"a": 1}') == '{"a": 1}'
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_models_json_is_machine_readable(monkeypatch, capsys) -> None:
    from sparrow.cli import main

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
