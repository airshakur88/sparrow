                                                                                         

from __future__ import annotations

import os
import stat

import pytest
from helpers import make_post

from sparrow import client as flp_client
from sparrow.cache import Cache
from sparrow.config import load_catalog
from sparrow.errors import ProviderHTTPError
from sparrow.models import Model, Provider
from sparrow.router import _MIN_LEARNABLE_CONTEXT, Pool


def _provider(host="ex.test"):
    return Provider(
        id="p",
        label="p",
        adapter="openai",
        base_url=f"https://{host}/v1",
        auth="none",
        models=(Model("m"),),
    )


                                                     
def _call_with_body(body):
    return flp_client.call(
        _provider(),
        "m",
        [{"role": "user", "content": "hi"}],
        api_key=None,
        env={},
        post=make_post({"ex.test": (200, body)}),
    )


def test_list_content_does_not_crash_and_joins_text():
    body = {
        "choices": [
            {
                "message": {
                    "content": [{"type": "text", "text": "Hel"}, {"type": "text", "text": "lo"}]
                }
            }
        ]
    }
    assert _call_with_body(body).text == "Hello"


def test_null_content_is_empty_not_crash():
    body = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "1"}]}}]}
    assert _call_with_body(body).text == ""


def test_malformed_message_raises_clean_provider_error():
    with pytest.raises(ProviderHTTPError):
        _call_with_body({"choices": ["not-a-dict"]})
    with pytest.raises(ProviderHTTPError):
        _call_with_body({"choices": [{"message": "a-string"}]})


                                          
def test_malformed_user_catalog_does_not_crash(tmp_path, monkeypatch):
    bad = tmp_path / "providers.toml"
    bad.write_text(
        '[[provider]]\nid = "ok"\nbase_url = "https://ok.test/v1"\n'
        'models = [{ name = "good", context = "128k" }, { rpd = 5 }, { name = "z", context = 0 }]\n'
        '[[provider]]\nlabel = "no id or base_url"\n'                                 
    )
    monkeypatch.setenv("SPARROW_CONFIG", str(bad))
    cat = {p.id: p for p in load_catalog()}                  
    ok = cat["ok"]
    names = {m.name: m for m in ok.models}
    assert "good" in names and "z" in names                        
    assert names["good"].context is None                                  
    assert names["z"].context is None                                          


def test_broken_toml_user_catalog_is_ignored(tmp_path, monkeypatch):
    bad = tmp_path / "providers.toml"
    bad.write_text("this is = not valid toml [[[")
    monkeypatch.setenv("SPARROW_CONFIG", str(bad))
    assert any(p.id == "groq" for p in load_catalog())                                


                                              
def test_learned_context_floor_ignores_implausible_limit():
    pool = Pool([_provider()])
    pool._learn_context_limit("p/m", _MIN_LEARNABLE_CONTEXT - 1)
    assert "p/m" not in pool._ctx_limits                                  
    pool._learn_context_limit("p/m", 8192)
    assert pool._ctx_limits["p/m"][0] == 8192


def test_learned_context_limit_expires():
    from sparrow.router import _CTX_LIMIT_TTL, Target

    t = [0.0]
    prov = _provider()
    pool = Pool([prov], clock=lambda: t[0])
    target = Target(prov, "m", 0)
    pool._learn_context_limit(target.name, 4096)
    assert pool._effective_context(target) == 4096
                                                                          
    t[0] += _CTX_LIMIT_TTL - 1
    pool._learn_context_limit(target.name, 9999)
    assert pool._ctx_limits[target.name] == (4096, 0.0)             
    t[0] += 2                              
    assert pool._effective_context(target) is None


                                            
def test_make_key_returns_none_on_non_json():
    assert Cache.make_key([{"role": "user", "content": object()}], "m", None, 16, 0.0, None) is None


def test_cache_none_key_is_noop(tmp_path):
    c = Cache(ttl=60, path=tmp_path / "c.db")
    c.put(None, {"text": "x"})                  
    assert c.get(None) is None


def test_cache_prunes_expired_rows(tmp_path):
    now = [1000.0]
    c = Cache(ttl=10, path=tmp_path / "c.db", clock=lambda: now[0])
    c.put("k1", {"text": "old"})
    now[0] += 100                  
    c.put("k2", {"text": "new"})                           
    import sqlite3

    rows = sqlite3.connect(c.path).execute("SELECT key FROM cache").fetchall()
    assert {r[0] for r in rows} == {"k2"}


                                                
def test_upsert_config_key_is_0600(tmp_path):
    from sparrow.key_inventory import upsert_config_key

    p = upsert_config_key("GROQ_API_KEY", "secret", tmp_path / "config.toml")
    if os.name != "nt":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert 'GROQ_API_KEY = "secret"' in p.read_text()


                                                              
def test_render_table_handles_empty_error():
    from sparrow.benchmark import BenchRow, render_table

    out = render_table([BenchRow("p/m", False, None, None, "")])
    assert "FAIL" in out                                       


                                                             
def test_discovery_opener_blocks_redirects():
    from sparrow.catalog import _NoRedirect

                                                                                    
    assert _NoRedirect().redirect_request(None, None, 302, "Found", {}, "http://evil") is None
