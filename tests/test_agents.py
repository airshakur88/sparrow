from __future__ import annotations

from sparrow.agents import AGENTS, list_agents, render


def test_list_agents():
    out = list_agents()
    for a in ("codex", "aider", "cline", "continue", "cursor", "opencode", "hermes"):
        assert a in out


def test_render_hermes_custom_endpoint():
    out = render("hermes")
    assert out is not None
    assert "provider: custom" in out
    assert "default: quality" in out
    assert "http://localhost:8080/v1" in out


def test_render_known():
    out = render("aider")
    assert out is not None
    assert "openai/auto" in out
    assert "sparrow start" in out


def test_render_unknown():
    assert render("bogus") is None


def test_all_agents_render():
    for name in AGENTS:
        assert render(name)


def test_agents_legacy_shape_is_preserved():
    rec = AGENTS["aider"]
    assert "label" in rec
    assert "steps" in rec
    assert "note" in rec
    assert any("sparrow start" in step for step in rec["steps"])


def test_all_agent_keys_appear_in_supported_agent_list():
    out = list_agents()
    for name in AGENTS:
        assert name in out


