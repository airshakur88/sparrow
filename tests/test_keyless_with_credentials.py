from pathlib import Path

import pytest

from sparrow.client import HTTPResult
from sparrow.quota import QuotaStore
from sparrow.router import Pool


@pytest.mark.parametrize("route", ["llm7/default", "ovh/Qwen3.5-397B-A17B",
                                  "kilo/cohere/north-mini-code:free",
                                  "opencode/ling-3.0-flash-fin-free"])
def test_keyless_chat_survives_managed_provider_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str,
) -> None:
    # Given a configured keyed provider alongside the built-in keyless providers.
    config = tmp_path / "config.toml"
    config.write_text(
        '[keys]\nTEST_GROQ_KEY = "test-only"\n'
        '[providers.groq]\napi_keys = [{env = "TEST_GROQ_KEY"}]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SPARROW_CONFIG_FILE", str(config))
    monkeypatch.setenv("SPARROW_CREDENTIAL_STATE_FILE", str(tmp_path / "keys.db"))
    monkeypatch.setenv("SPARROW_STATS_PATH", str(tmp_path / "stats.json"))
    monkeypatch.setenv("SPARROW_HEALTH_FILE", str(tmp_path / "health.json"))

    def post(url, headers, body, timeout):
        assert "Authorization" not in headers
        return HTTPResult(200, {"choices": [{"message": {"content": "OK"}}]}, "")

    pool = Pool.from_default_config(quota=QuotaStore(tmp_path / "quota.json"), post=post)
    # When an explicit keyless route is requested.
    reply = pool.chat([{"role": "user", "content": "hello"}], model=route)
    # Then the request reaches the upstream without requiring a managed key.
    assert reply.text == "OK"
    assert reply.provider_id == route.split("/", 1)[0]
