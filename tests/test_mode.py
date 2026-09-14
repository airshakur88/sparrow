from __future__ import annotations

import pytest

from sparrow.mode import (
    WISE_DEFAULT_MAX_TOKENS,
    WISE_DEFAULT_ROUTING,
    default_routing_for_mode,
)
from sparrow.models import Reply


class _EmptyQuota:
    def snapshot(self):
        return {}


class _FakeAskPool:
    quota = _EmptyQuota()

    def __init__(self, captured, env=None):
        self.captured = captured
        self.env = {"SPARROW_MODE": "wise"} if env is None else env
        self.providers = []

    def rank_targets(self, messages, **kwargs):
        self.captured["rank_messages"] = messages
        self.captured["rank"] = kwargs
        return []

    def ask(self, prompt, **kwargs):
        self.captured["prompt"] = prompt
        self.captured.update(kwargs)
        return Reply(text="ok", provider_id="fake", model="fake-model", raw={})


def test_default_routing_for_mode_preserves_explicit_choices():
    assert default_routing_for_mode({}, {}) == "fair"
    assert default_routing_for_mode({"SPARROW_MODE": "wise"}, {}) == "spread"
    assert default_routing_for_mode({}, {"mode": "wise"}) == "spread"
    assert (
        default_routing_for_mode(
            {"SPARROW_MODE": "wise", "SPARROW_ROUTING": "fast"}, {}
        )
        == "fast"
    )
    assert default_routing_for_mode({"SPARROW_MODE": "wise"}, {"routing": "quality"}) == "quality"


def test_unrelated_mode_environment_name_is_ignored():
    assert default_routing_for_mode({"OTHER_MODE": "wise"}, {}) == "fair"


def test_wise_ask_applies_lower_defaults(monkeypatch, capsys):
    from sparrow.cli import main
    from sparrow.router import Pool

    captured = {}
    monkeypatch.setenv("SPARROW_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: _FakeAskPool(captured)))
    monkeypatch.setattr("sparrow.cli._read_stdin", lambda: "")

    assert main(["ask", "hello"]) == 0

    assert captured["max_tokens"] == WISE_DEFAULT_MAX_TOKENS
    assert captured["routing"] == WISE_DEFAULT_ROUTING
    assert capsys.readouterr().out.strip() == "ok"


def test_per_command_mode_enables_wise_defaults(monkeypatch):
    from sparrow.cli import main
    from sparrow.router import Pool

    captured = {}
    monkeypatch.delenv("SPARROW_MODE", raising=False)
    monkeypatch.setattr(
        Pool,
        "from_default_config",
        classmethod(lambda cls: _FakeAskPool(captured, env={})),
    )
    monkeypatch.setattr("sparrow.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--mode", "wise"]) == 0

    assert captured["max_tokens"] == WISE_DEFAULT_MAX_TOKENS
    assert captured["routing"] == WISE_DEFAULT_ROUTING


def test_config_mode_enables_wise_defaults(monkeypatch):
    from sparrow.cli import main
    from sparrow.router import Pool

    captured = {}
    monkeypatch.delenv("SPARROW_MODE", raising=False)
    monkeypatch.setattr(
        Pool,
        "from_default_config",
        classmethod(lambda cls: _FakeAskPool(captured, env={})),
    )
    monkeypatch.setattr("sparrow.cli.settings", lambda _env: {"mode": "wise"})
    monkeypatch.setattr("sparrow.cli._read_stdin", lambda: "")

    assert main(["ask", "hello"]) == 0

    assert captured["max_tokens"] == WISE_DEFAULT_MAX_TOKENS
    assert captured["routing"] == WISE_DEFAULT_ROUTING


@pytest.mark.parametrize(
    ("argv", "key", "expected"),
    [
        (["ask", "hello", "--max-tokens", "2048"], "max_tokens", 2048),
        (["ask", "hello", "--routing", "fast"], "routing", "fast"),
        (["ask", "hello", "--model", "beta-1"], "model", "beta-1"),
        (["ask", "hello", "--providers", "beta,alpha"], "providers", ["beta", "alpha"]),
    ],
)
def test_wise_ask_explicit_flags_win(monkeypatch, argv, key, expected):
    from sparrow.cli import main
    from sparrow.router import Pool

    captured = {}
    monkeypatch.setenv("SPARROW_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: _FakeAskPool(captured)))
    monkeypatch.setattr("sparrow.cli._read_stdin", lambda: "")

    assert main(argv) == 0

    assert captured[key] == expected


def test_wise_ask_role_defaults_win(monkeypatch):
    from sparrow.cli import main
    from sparrow.router import Pool

    captured = {}
    monkeypatch.setenv("SPARROW_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: _FakeAskPool(captured)))
    monkeypatch.setattr("sparrow.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--role", "coder"]) == 0

    assert captured["max_tokens"] == 2048
    assert captured["routing"] == "quality"


def test_wise_exhausted_declared_quota_fails_before_provider_call(
    providers, env, quota, monkeypatch, capsys
):
    from helpers import make_post

    from sparrow.cli import main
    from sparrow.router import Pool

    quota.record("alpha", "alpha-small", 2)
    post = make_post({})
    pool = Pool(
        providers,
        quota=quota,
        env={**env, "SPARROW_MODE": "wise"},
        post=post,
    )
    monkeypatch.setenv("SPARROW_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("sparrow.cli._read_stdin", lambda: "")

    assert main(["ask", "hello"]) == 4

    assert vars(post)["calls"] == []
    assert "declared local free quota is exhausted" in capsys.readouterr().err


def test_wise_ask_narrows_to_exact_declared_headroom_target(providers, env, quota, monkeypatch):
    from helpers import make_post

    from sparrow.cli import main
    from sparrow.router import Pool

    post = make_post({"alpha.test": (500, {})})
    pool = Pool(
        providers,
        quota=quota,
        env={**env, "SPARROW_MODE": "wise"},
        post=post,
    )
    monkeypatch.setenv("SPARROW_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("sparrow.cli._read_stdin", lambda: "")

    assert main(["ask", "hello"]) == 4

    assert len(vars(post)["calls"]) == 1
    assert vars(post)["calls"][0]["body"]["model"] == "alpha-small"


def test_wise_explicit_provider_can_override_exhausted_declared_quota(
    providers, env, quota, monkeypatch
):
    from helpers import make_post

    from sparrow.cli import main
    from sparrow.router import Pool

    quota.record("alpha", "alpha-small", 2)
    post = make_post({})
    pool = Pool(
        providers,
        quota=quota,
        env={**env, "SPARROW_MODE": "wise"},
        post=post,
    )
    monkeypatch.setenv("SPARROW_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("sparrow.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--providers", "beta"]) == 0

    assert len(vars(post)["calls"]) == 1
    assert "beta.test" in vars(post)["calls"][0]["url"]


