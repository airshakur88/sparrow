                                                                     

from __future__ import annotations

import logging

from helpers import make_post

from sparrow.cache import Cache
from sparrow.observe import configure_logging_from_env, emit, logger
from sparrow.router import Pool


def test_hook_receives_success_event(providers, env, quota):
    events = []
    pool = Pool(providers, quota=quota, env=env, post=make_post({}), on_event=events.append)
    pool.chat([{"role": "user", "content": "hi"}])
    kinds = [e["event"] for e in events]
    assert "attempt" in kinds
    assert "success" in kinds
    success = next(e for e in events if e["event"] == "success")
    assert "target" in success and "latency_ms" in success


def test_hook_sees_error_and_exhausted(providers, env, quota):
    events = []
                                             
    post = make_post({".test": (500, {"error": "down"})})
    pool = Pool(providers, quota=quota, env=env, post=post, on_event=events.append)
    try:
        pool.chat([{"role": "user", "content": "hi"}], providers=["alpha"])
    except Exception:                
        pass
    kinds = [e["event"] for e in events]
    assert "error" in kinds
    assert "exhausted" in kinds


def test_a_broken_hook_does_not_break_routing(providers, env, quota):
    def boom(_event):
        raise RuntimeError("hook is broken")

    pool = Pool(providers, quota=quota, env=env, post=make_post({}), on_event=boom)
    reply = pool.chat([{"role": "user", "content": "hi"}])
    assert reply.text == "ok"                                                  


def test_cache_events_are_emitted(providers, env, quota, tmp_path):
    events = []
    pool = Pool(
        providers,
        quota=quota,
        env=env,
        post=make_post({}),
        cache=Cache(ttl=60, path=tmp_path / "cache.db"),
        on_event=events.append,
    )
    pool.ask("same")
    pool.ask("same")
    kinds = [event["event"] for event in events]
    assert "cache_miss" in kinds
    assert "cache_store" in kinds
    assert "cache_hit" in kinds


def test_emit_without_hook_is_noop():
    emit(None, "attempt", target="x")                  


def test_configure_logging_from_env_attaches_one_handler():
    before = list(logger.handlers)
    try:
        assert configure_logging_from_env({"SPARROW_LOG": "debug"}) is True
        assert logger.level == logging.DEBUG
        n = len([h for h in logger.handlers if getattr(h, "_sparrow", False)])
        assert n == 1
                                                                
        configure_logging_from_env({"SPARROW_LOG": "info"})
        n2 = len([h for h in logger.handlers if getattr(h, "_sparrow", False)])
        assert n2 == 1
        assert configure_logging_from_env({}) is False                 
    finally:
        logger.handlers = before
        logger.setLevel(logging.WARNING)
