                                                          

                                                                            
                                                                          

                               
                                                     
                                                           

                                                                        
                                      

                 
                                                                       
                                                                            
                                                                                  
                                                          
                                                                                        
                                                                           
                                                                                  
                                                               
                                                          
                                                  
                                                        
                                                                           
   

from __future__ import annotations

import base64
import collections
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .anthropic_shim import estimate_tokens, reply_to_message, reply_to_sse, request_to_chat
from .config import known_aliases, resolve_alias
from .errors import (
    AllProvidersExhausted,
    ContextWindowExceeded,
    NoProvidersConfigured,
    SparrowError,
)
from .readiness import ReadinessSnapshot, readiness_snapshot
from .router import Pool
from .routing_modes import routing_override
from .savings import usd_saved
from .task_quality import task_resolution
from .virtual_models import VIRTUAL_MODELS

_MAX_BODY = 16 * 1024 * 1024                               
                                                                                        
                                                                                         
_MAX_AUDIO_BODY = 25 * 1024 * 1024
                                                                                   
                                                                                 
                                                                                  
                                                                 
_AGENT_UPSTREAM_TIMEOUT = 540.0                                             
                                                                                            
                                                                                           
_TRANSCRIPTION_FORMATS = ("json", "text", "verbose_json")
_log = logging.getLogger(__name__)


def _max_tokens_value(req: dict[str, Any], default: int) -> Any:
                                                                           
    for field in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        if field in req and req[field] is not None:
            return req[field]
    return default


def _model_ids(pool: Pool, ready_model_ids: frozenset[str] | None = None) -> list[str]:
                                                                                   
                                           
                                                                                
                                                                                   
    ids: list[str] = []
    if ready_model_ids is None:
        ids.extend(model.name for model in VIRTUAL_MODELS)
    for provider in pool.providers:
        for m in provider.models:
            model_id = f"{provider.id}/{m.name}"
            if m.enabled and (ready_model_ids is None or model_id in ready_model_ids):
                ids.append(model_id)
    return ids


def _openai_models_payload(
    pool: Pool, ready_model_ids: frozenset[str] | None = None
) -> dict:
    target_lookup = {
        f"{provider.id}/{model.name}": (provider, model.name)
        for provider in pool.providers
        for model in provider.models
        if model.enabled
    }
    conformance_snapshot = (
        pool.conformance.snapshot() if pool.conformance is not None else None
    )
    data = []
    for model_id in _model_ids(pool, ready_model_ids):
        row = {"id": model_id, "object": "model", "owned_by": "sparrow"}
        target = target_lookup.get(model_id)
        evidence = (
            pool.conformance.evidence(*target, snapshot=conformance_snapshot)
            if target is not None and pool.conformance is not None
            else {}
        )
        row["capabilities"] = evidence
        row["verified_features"] = sorted(
            feature for feature, result in evidence.items() if result.get("status") == "pass"
        )
        data.append(row)
    return {"object": "list", "data": data}


def _anthropic_models_payload(
    pool: Pool, ready_model_ids: frozenset[str] | None = None
) -> dict:
    ids = _model_ids(pool, ready_model_ids)
    if ready_model_ids is None:
        ids.extend(a for a in known_aliases(pool.env) if a.startswith("claude-") and a not in ids)
    target_lookup = {
        f"{provider.id}/{model.name}": (provider, model.name)
        for provider in pool.providers
        for model in provider.models
        if model.enabled
    }
    conformance_snapshot = (
        pool.conformance.snapshot() if pool.conformance is not None else None
    )
    data = []
    for mid in ids:
        target = target_lookup.get(mid)
        evidence = (
            pool.conformance.evidence(*target, snapshot=conformance_snapshot)
            if target is not None and pool.conformance is not None
            else {}
        )
        data.append(
            {
            "type": "model",
            "id": mid,
            "display_name": mid,
            "created_at": "2024-01-01T00:00:00Z",
                "capabilities": evidence,
                "verified_features": sorted(
                    feature
                    for feature, result in evidence.items()
                    if result.get("status") == "pass"
                ),
            }
        )
    return {
        "data": data,
        "has_more": False,
        "first_id": ids[0] if ids else None,
        "last_id": ids[-1] if ids else None,
    }


def _readiness_snapshot(pool: Pool) -> ReadinessSnapshot:
                                                                       
    now = pool._clock()
    return readiness_snapshot(
        pool.providers,
        env=pool.env,
        quota=pool.quota.snapshot(),
        cooldowns=pool.cooldown_snapshot(now),
        route_cooldowns=pool.route_cooldown_snapshot(),
    )


def _ready_filter(query: str) -> bool | None:
    values = parse_qs(query, keep_blank_values=True).get("ready")
    if values is None:
        return None
    if len(values) != 1:
        raise ValueError("ready must be specified once")
    value = values[0].casefold()
    if value in {"true", "1"}:
        return True
    if value in {"false", "0"}:
        return False
    raise ValueError("ready must be true, false, 1, or 0")


def _provider_leaderboard(pool: Pool, limit: int = 5) -> list[tuple[str, float]]:
                                                                                  
                                          
    snap = pool.quota.snapshot()
    totals: dict[str, int] = {}
    for key, count in snap.items():
        pid = key.split("::", 1)[0]
        totals[pid] = totals.get(pid, 0) + int(count)
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])[:limit]
    top = ranked[0][1] if ranked and ranked[0][1] > 0 else 1
    return [(pid, count / top) for pid, count in ranked if count > 0]


def _status_payload(pool: Pool, recent: Sequence[dict], tokenmax: dict | None = None) -> dict:
                                                                  

                                                                                  
                                                                                      
                                                                                       
                                                
       
    now = pool._clock()
    quota_snap = pool.quota.snapshot()
    metrics_snap = pool.metrics.snapshot()
    health_snap = pool.route_health_snapshot()
    health_store = pool.route_health
    cooldown_snap = pool.cooldown_snapshot(now)                                       
    conformance_snapshot = (
        pool.conformance.snapshot() if pool.conformance is not None else None
    )

    def modality_routes(providers) -> list[dict]:
        rows = []
        for provider in providers:
            for model in provider.models:
                if not model.enabled:
                    continue
                persistent = health_snap.get(f"{provider.id}/{model.name}")
                rows.append(
                    {
                        "provider": provider.id,
                        "name": model.name,
                        "circuit_state": persistent.state if persistent else "closed",
                        "consecutive_failures": (
                            persistent.consecutive_failures if persistent else 0
                        ),
                        "failure_class": (
                            persistent.failure_class if persistent else None
                        ),
                        "ewma_ms": persistent.ewma_ms if persistent else None,
                        "success_rate": (
                            persistent.success_rate
                            if persistent and persistent.total
                            else None
                        ),
                        "sample_age_s": (
                            health_store.sample_age(persistent)
                            if health_store is not None
                            else None
                        ),
                        "reset_remaining_s": (
                            health_store.reset_remaining(persistent)
                            if health_store is not None
                            else 0.0
                        ),
                    }
                )
        return rows

    providers_list = []
    for p in pool.providers:
        cooldown_remaining = cooldown_snap.get(p.id, 0.0)
        provider_health = health_snap.get(f"{p.id}/*")

        models_list = []
        for m in p.models:
            if not m.enabled:
                continue
            key = f"{p.id}::{m.name}"
            used = quota_snap.get(key, 0)
            remaining = (m.rpd - used) if m.rpd > 0 else None
            stat = metrics_snap.get(f"{p.id}/{m.name}")
            persistent = health_snap.get(f"{p.id}/{m.name}")
            capabilities = (
                pool.conformance.evidence(
                    p,
                    m.name,
                    snapshot=conformance_snapshot,
                )
                if pool.conformance is not None
                else {}
            )
            models_list.append(
                {
                    "name": m.name,
                    "rpd": m.rpd,
                    "used_today": used,
                    "remaining": remaining,
                    "ewma_ms": (
                        persistent.ewma_ms
                        if persistent and persistent.ewma_ms is not None
                        else stat.ewma_ms if stat else None
                    ),
                    "success_rate": (
                        persistent.success_rate
                        if persistent and persistent.total
                        else stat.success_rate if stat else None
                    ),
                    "last_error": stat.last_error if stat else None,
                    "circuit_state": persistent.state if persistent else "closed",
                    "consecutive_failures": (
                        persistent.consecutive_failures if persistent else 0
                    ),
                    "failure_class": persistent.failure_class if persistent else None,
                    "sample_age_s": (
                        health_store.sample_age(persistent)
                        if health_store is not None
                        else None
                    ),
                    "reset_remaining_s": (
                        health_store.reset_remaining(persistent)
                        if health_store is not None
                        else 0.0
                    ),
                    "capabilities": capabilities,
                    "verified_features": sorted(
                        feature
                        for feature, result in capabilities.items()
                        if result.get("status") == "pass"
                    ),
                }
            )

        providers_list.append(
            {
                "id": p.id,
                "configured": p.is_configured(pool.env),
                "cooldown_remaining_s": cooldown_remaining,
                "circuit_state": (
                    provider_health.state if provider_health else "closed"
                ),
                "failure_class": (
                    provider_health.failure_class if provider_health else None
                ),
                "sample_age_s": (
                    health_store.sample_age(provider_health)
                    if health_store is not None
                    else None
                ),
                "models": models_list,
            }
        )

    s = pool.stats_snapshot()
    saved = usd_saved(s.get("prompt_tokens", 0), s.get("completion_tokens", 0))
    life = pool.lifetime_stats()

    return {
        "routing": pool.routing,
        "pool": {
            "requests": s.get("requests", 0),
            "prompt_tokens": s.get("prompt_tokens", 0),
            "completion_tokens": s.get("completion_tokens", 0),
            "cache_hits": s.get("cache_hits", 0),
            "usd_saved": saved,
        },
                                                                                 
        "lifetime": {
            "requests": life.get("requests", 0),
            "prompt_tokens": life.get("prompt_tokens", 0),
            "completion_tokens": life.get("completion_tokens", 0),
            "cache_hits": life.get("cache_hits", 0),
            "usd_saved": usd_saved(life.get("prompt_tokens", 0), life.get("completion_tokens", 0)),
            "first_seen": life.get("first_seen"),
        },
        "providers": providers_list,
        "routes": {
            "embeddings": modality_routes(pool.embedders),
            "transcriptions": modality_routes(pool.transcribers),
        },
        "recent": list(recent),
        "tokenmax": tokenmax or {"active": False},
    }


def _routing_and_model(headers, requested: str) -> tuple[str | None, str]:
                                                                  
                                                                          
                                                                                     
                                                                        
    override = routing_override(headers.get("X-Sparrow-Routing"))
    if isinstance(requested, str):
                                                                                
                                                                                      
                                                                                             
        alias = requested.rsplit("/", 1)[-1].lower()
        alias_override = routing_override(alias)
        if alias_override is not None:
            override = override or alias_override
            requested = "auto"
        elif alias == "auto":
            requested = "auto"                                                                 
    return override, requested


def _task_hint(headers, req: dict) -> object:
                                                                               
    header = headers.get("X-Sparrow-Task")
    return header if header is not None else req.get("task")


def make_handler(pool: Pool, api_key: str | None = None, request_logger=None):
                                                                            
                                                                                
                                                                            
    recent = collections.deque(maxlen=25)
    recent_lock = threading.Lock()

    def record_recent(entry: dict) -> None:
        with recent_lock:
            recent.appendleft(entry)
        if request_logger is not None:
            request_logger(entry)

                                                                                      
                                                                                       
                                                                                           
    tokenmax_state: dict = {"active": False}
    tokenmax_lock = threading.Lock()

    def tokenmax_snapshot() -> dict:
        with tokenmax_lock:
            snap = dict(tokenmax_state)
        if snap.get("active") and snap.get("started_at") is not None:
            snap["elapsed_s"] = round(max(0.0, pool._clock() - snap["started_at"]), 1)
        return snap

    class Handler(BaseHTTPRequestHandler):
        server_version = f"sparrow/{__version__}"
        _response_started = False
                                                                                   
                                                                                
        timeout = 75

                                                                      
        def log_message(self, format, *args):              
            return

        def end_headers(self) -> None:
                                                                                 
                                                                                   
                                                                                   
            self._response_started = True
            super().end_headers()

        def _send(self, status: int, payload: dict, headers: dict | None = None) -> None:
            data = json.dumps(payload).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(data)))
                for key, value in (headers or {}).items():
                    self.send_header(key, str(value))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):                    
                pass

        def _error(self, status: int, message: str, code: str = "sparrow_error") -> None:
            if request_logger is not None:
                request_logger(
                    {"kind": "error", "status": status, "code": code, "message": message, "path": self.path}
                )
            self._send(status, {"error": {"message": message, "type": code}})

        def _anthropic_error(self, status: int, message: str, code: str = "invalid_request_error"):
                                                                                   
                                                                       
            if request_logger is not None:
                request_logger(
                    {"kind": "error", "status": status, "code": code, "message": message, "path": self.path}
                )
            self._send(status, {"type": "error", "error": {"type": code, "message": message}})

        def _authorized(self) -> bool:
                                                                            
                                                             
            if not api_key:
                return True
                                                                               
                                                             
            if hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {api_key}"):
                return True
            return hmac.compare_digest(self.headers.get("x-api-key", ""), api_key)

        def _wants_anthropic_models(self) -> bool:
                                                                               
                                                                       
            headers = {k.lower(): v.lower() for k, v in self.headers.items()}
            user_agent = headers.get("user-agent", "")
            return (
                "anthropic-version" in headers
                or "anthropic-beta" in headers
                or user_agent.startswith("claude")
            )

        def _send_browser_shell(self) -> None:
                                                                                  
            html = _browser_shell_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", _browser_shell_csp())
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_GET(self) -> None:              
            self._response_started = False
            try:
                self._do_get()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception as exc:                                       
                _log.exception("unexpected GET handler failure")
                if self._response_started:
                    self.close_connection = True
                else:
                    self._error(500, f"internal error: {type(exc).__name__}", "internal_error")

        def do_POST(self) -> None:              
            self._response_started = False
            try:
                self._do_post()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception as exc:                                       
                _log.exception("unexpected POST handler failure")
                if self._response_started:
                    self.close_connection = True
                else:
                    self._error(500, f"internal error: {type(exc).__name__}", "internal_error")

        def _do_get(self) -> None:
            path = urlsplit(self.path).path.rstrip("/") or "/"
                                                                                 
                                                                                  
                                                                                 
                                                                      
            if path in ("/", "/dashboard", "/playground"):
                self._send_browser_shell()
                return
            if path in ("/healthz", "/livez"):
                self._send(200, {"status": "ok"})
                return
            if path == "/readyz":
                snapshot = _readiness_snapshot(pool)
                self._send(
                    200 if snapshot.ready_providers else 503,
                    snapshot.readiness_payload(),
                )
                return
                                                                                   
                                                                            
                                                                                     
            if path in ("/badge.svg", "/summary.svg"):
                public = os.environ.get("SPARROW_PUBLIC_BADGE", "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                    "on",
                )
                if not public and not self._authorized():
                    self._error(401, "invalid or missing API key", "invalid_api_key")
                    return
                from . import svg as _svg

                life = pool.lifetime_stats()
                if path == "/summary.svg":
                    body = _svg.summary_svg(life, _provider_leaderboard(pool))
                else:
                    metric = parse_qs(urlsplit(self.path).query).get("metric", ["tokens"])[0]
                    body = _svg.badge_svg(life, metric=metric)
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
                self.send_header("Cache-Control", "max-age=300")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
                                                                              
                                                                                  
            if not self._authorized():
                self._error(401, "invalid or missing API key", "invalid_api_key")
                return
            if path.endswith("/v1/models") or path == "/models":
                try:
                    ready = _ready_filter(urlsplit(self.path).query)
                except ValueError as exc:
                    self._error(400, str(exc), "invalid_request_error")
                    return
                ready_ids = None
                if ready:
                    ready_ids = frozenset(_readiness_snapshot(pool).ready_model_ids)
                payload = (
                    _anthropic_models_payload(pool, ready_ids)
                    if self._wants_anthropic_models()
                    else _openai_models_payload(pool, ready_ids)
                )
                self._send(200, payload)
                return
            if path == "/v1/providers":
                self._send(200, _readiness_snapshot(pool).provider_payload())
                return
            if path in ("/status", "/v1/status"):
                with recent_lock:
                    recent_snapshot = list(recent)
                self._send(200, _status_payload(pool, recent_snapshot, tokenmax_snapshot()))
                return
            self._error(404, f"unknown route {self.path}", "not_found")

        def _do_post(self) -> None:
            route = urlsplit(self.path).path.rstrip("/")
            is_chat = route.endswith("/v1/chat/completions") or route == "/chat/completions"
            is_responses = route.endswith("/v1/responses") or route == "/responses"
            is_embeddings = route.endswith("/v1/embeddings") or route == "/embeddings"
            is_count = route.endswith("/v1/messages/count_tokens")
            is_messages = not is_count and (route.endswith("/v1/messages") or route == "/messages")
            is_tokenmax = route.endswith("/tokenmax") or route == "/tokenmax"
            is_battle = route == "/sparrow/battle"
            is_transcription = (
                route.endswith("/v1/audio/transcriptions") or route == "/audio/transcriptions"
            )
            if not (
                is_chat
                or is_responses
                or is_embeddings
                or is_messages
                or is_count
                or is_tokenmax
                or is_battle
                or is_transcription
            ):
                self._error(404, f"unknown route {self.path}", "not_found")
                return
            if not self._authorized():
                self._error(401, "invalid or missing API key", "invalid_api_key")
                return

            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                self._error(400, "invalid Content-Length header", "invalid_request_error")
                return
            if length < 0:
                self._error(400, "invalid Content-Length header", "invalid_request_error")
                return
            max_body = _MAX_AUDIO_BODY if is_transcription else _MAX_BODY
            if length > max_body:
                self._error(413, "request body too large", "invalid_request_error")
                return
            try:
                raw = self.rfile.read(length) if length else b""
                if length and len(raw) < length:                                   
                    self._error(400, "incomplete request body", "invalid_request_error")
                    return
            except (OSError, ValueError):
                self._error(400, "could not read request body", "invalid_request_error")
                return

                                                                                           
            if is_transcription:
                self._handle_transcription(raw, self.headers.get("Content-Type", ""))
                return

            try:
                req = json.loads(raw or b"{}")
            except (json.JSONDecodeError, ValueError):
                self._error(400, "invalid JSON body", "invalid_request_error")
                return
            if not isinstance(req, dict):
                self._error(400, "request body must be a JSON object", "invalid_request_error")
                return

            if is_embeddings:
                self._handle_embeddings(req)
            elif is_responses:
                self._handle_responses(req)
            elif is_count:
                self._send(200, {"input_tokens": estimate_tokens(req)})
            elif is_messages:
                self._handle_messages(req)
            elif is_tokenmax:
                self._handle_tokenmax(req)
            elif is_battle:
                self._handle_battle(req)
            else:
                self._handle_chat(req)

        def _handle_battle(self, req: dict) -> None:
            from .battle import battle_to_dict, run_battle

            prompt = req.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                self._error(400, "'prompt' is required", "invalid_request_error")
                return
            result = run_battle(
                pool,
                prompt.strip(),
                n=req.get("n", req.get("models", 3)),
                max_tokens=_max_tokens_value(req, 512),
                timeout=90.0,
                routing=str(req.get("routing") or "quality"),
                synthesize=bool(req.get("synthesize")),
            )
            if not result.answers:
                self._error(503, "no providers configured", "no_providers")
                return
            self._send(200, battle_to_dict(result))

        def _handle_tokenmax(self, req: dict) -> None:
                                                                                      

                                                                                      
                                                                                        
                                                       
               
            from . import tokenmax as _tm

            prompt = req.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                self._error(400, "'prompt' is required", "invalid_request_error")
                return
            msgs: list[dict[str, str]] = []
            system = req.get("system")
            if isinstance(system, str) and system.strip():
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})
            try:
                max_tokens = max(1, min(8192, int(_max_tokens_value(req, 350))))
            except (TypeError, ValueError):
                max_tokens = 350

            picks, n_providers = _tm.select_targets(pool, msgs, req.get("max_models"))
            if not picks:
                self._error(503, "no providers configured", "no_providers")
                return
            total = len(picks)

            def on_progress(done: int, _total: int, _label: str) -> None:
                with tokenmax_lock:
                    if tokenmax_state.get("active"):                                          
                                                                                             
                                                                                          
                                                           
                        tokenmax_state["done"] = max(int(tokenmax_state.get("done", 0)), done)

                                                                                        
                                                                                            
                                                                                          
            with tokenmax_lock:
                busy = bool(tokenmax_state.get("active"))
                if not busy:
                    tokenmax_state.clear()
                    tokenmax_state.update(
                        {
                            "active": True,
                            "prompt": prompt[:120],
                            "done": 0,
                            "total": total,
                            "n_providers": n_providers,
                            "started_at": pool._clock(),
                        }
                    )
            if busy:
                self._error(409, "a tokenmax swarm is already in flight", "tokenmax_busy")
                return
            try:
                answered, failed = _tm.fan_out(
                    pool, msgs, picks, max_tokens=max_tokens, progress=on_progress
                )
                with tokenmax_lock:                                               
                    tokenmax_state["done"] = total
                    tokenmax_state["answered"] = len(answered)
            finally:
                                                                                        
                                                                                          
                with tokenmax_lock:
                    tokenmax_state["active"] = False
            self._send(
                200,
                {
                    "answers": [{"model": lbl, "text": txt} for lbl, txt in answered],
                    "failed": failed,
                    "answered": len(answered),
                    "total": total,
                    "n_providers": n_providers,
                },
            )

        def _handle_messages(self, req: dict) -> None:
                                                                                           
            if not isinstance(req.get("messages"), list) or not req["messages"]:
                self._anthropic_error(400, "'messages' must be a non-empty array")
                return
            chat = request_to_chat(req)
            if not chat["messages"]:
                self._anthropic_error(400, "no usable message content in request")
                return
            display_model = req.get("model") or "auto"
            stream_deadline: float | None = None
                                                                              
                                                                                
                                                                       
            if req.get("stream") and _anthropic_text_streamable(req, chat):
                stream_deadline = pool._clock() + self._text_stream_timeout(req)
                if self._stream_messages_text(
                    req,
                    chat,
                    str(display_model),
                    deadline=stream_deadline,
                ):
                    return
            routing_override, model_str = _routing_and_model(self.headers, str(chat["model"]))
            resolved = resolve_alias(model_str, pool.env)
            provider_filter, model_filter = _parse_model(resolved, {p.id for p in pool.providers})
            try:
                task = task_resolution(
                    chat["messages"], _task_hint(self.headers, req)
                ).task
                reply = pool.chat(
                    chat["messages"],
                    model=model_filter,
                    providers=provider_filter,
                    max_tokens=chat["max_tokens"],
                    temperature=chat["temperature"],
                    tools=chat["tools"],
                    tool_choice=chat["tool_choice"],
                    timeout=(
                        max(0.0, stream_deadline - pool._clock())
                        if stream_deadline is not None
                        else 90.0
                    ),
                    protocol="anthropic_messages",
                    routing=routing_override,
                    task=task,
                )
            except ValueError as exc:
                self._anthropic_error(400, str(exc))
                return
            except NoProvidersConfigured as exc:
                self._anthropic_error(503, str(exc), "no_providers")
                return
            except ContextWindowExceeded as exc:
                self._anthropic_error(413, str(exc), "context_length_exceeded")
                return
            except AllProvidersExhausted as exc:
                client_status = getattr(exc, "client_status", None)
                if isinstance(client_status, int) and 400 <= client_status < 500:
                    self._anthropic_error(
                        client_status,
                        getattr(exc, "client_message", None) or str(exc),
                        "invalid_request_error",
                    )
                else:
                    self._anthropic_error(502, str(exc), "all_providers_exhausted")
                return
                                  
            record_recent(
                {"provider": reply.provider_id, "model": reply.model, "attempts": reply.attempts}
            )
            if req.get("stream"):
                self._send_sse(reply_to_sse(reply, display_model))
            else:
                self._send(200, reply_to_message(reply, display_model))

        def _stream_messages_text(
            self,
            req: dict,
            chat: dict,
            display_model: str,
            *,
            deadline: float,
        ) -> bool:
                                                      

                                                                              
                                                                              
                                                                                
                                                                                 
               
            try:
                gen, meta = self._open_text_stream(
                    req,
                    chat["messages"],
                    max_tokens=chat["max_tokens"],
                    temperature=chat["temperature"],
                    timeout=max(0.0, deadline - pool._clock()),
                    protocol="anthropic_messages",
                )
            except ContextWindowExceeded as exc:
                self._anthropic_error(413, str(exc), "context_length_exceeded")
                return True
            except ValueError as exc:
                self._anthropic_error(400, str(exc))
                return True
            except (NoProvidersConfigured, AllProvidersExhausted, StopIteration):
                return False
            except Exception:                                                       
                return False

            provider_id = str(meta.get("provider", "auto")) if isinstance(meta, dict) else "auto"
            model_name = str(meta.get("model", "auto")) if isinstance(meta, dict) else "auto"
            attempts = meta.get("attempts", 1) if isinstance(meta, dict) else 1
            attempts = attempts if isinstance(attempts, int) else 1
            msg_id = f"msg-sparrow-{provider_id}"
            text_parts: list[str] = []
            input_tokens = estimate_tokens(req)
            disconnected = False
            succeeded = False
            try:
                try:
                    self._send_event_stream_headers()
                    self._write_named_sse(
                        "message_start",
                        {
                            "type": "message_start",
                            "message": {
                                "id": msg_id,
                                "type": "message",
                                "role": "assistant",
                                "model": display_model,
                                "content": [],
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": {"input_tokens": input_tokens, "output_tokens": 0},
                            },
                        },
                    )
                    self._write_named_sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                except (OSError, ValueError):
                    disconnected = True

                while not disconnected:
                    try:
                        delta = next(gen)
                    except StopIteration:
                        succeeded = True
                        break
                    except Exception:                                               
                        try:
                            self._write_named_sse(
                                "error",
                                {
                                    "type": "error",
                                    "error": {
                                        "type": "api_error",
                                        "message": (
                                            "Upstream stream failed; output is incomplete."
                                        ),
                                    },
                                },
                            )
                        except (OSError, ValueError):
                            disconnected = True
                        break
                    if not isinstance(delta, str) or not delta:
                        continue
                    text_parts.append(delta)
                    try:
                        self._write_named_sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": 0,
                                "delta": {"type": "text_delta", "text": delta},
                            },
                        )
                    except (OSError, ValueError):
                        disconnected = True

                if succeeded and not disconnected:
                    output_tokens = max(0, len("".join(text_parts)) // 4)
                    try:
                        self._write_named_sse(
                            "content_block_stop",
                            {"type": "content_block_stop", "index": 0},
                        )
                        self._write_named_sse(
                            "message_delta",
                            {
                                "type": "message_delta",
                                "delta": {
                                    "stop_reason": "end_turn",
                                    "stop_sequence": None,
                                },
                                "usage": {"output_tokens": output_tokens},
                            },
                        )
                        self._write_named_sse("message_stop", {"type": "message_stop"})
                    except (OSError, ValueError):
                        disconnected = True
            finally:
                self._close_upstream_stream(gen)
                record_recent(
                    {
                        "provider": provider_id,
                        "model": model_name,
                        "attempts": attempts,
                    }
                )
            return True

        def _handle_embeddings(self, req: dict) -> None:
            data = req.get("input")
            if isinstance(data, str):
                inputs = [data]
            elif isinstance(data, list) and all(isinstance(x, str) for x in data):
                inputs = data
            else:
                self._error(
                    400, "'input' must be a string or array of strings", "invalid_request_error"
                )
                return
            if not inputs:
                self._error(400, "'input' is required", "invalid_request_error")
                return
            requested = req.get("model")
                                                                                 
                                                                         
            provider_filter = None
            model = None
            if isinstance(requested, str) and requested not in ("", "auto"):
                provider_filter, model = _parse_model(requested, {p.id for p in pool.embedders})
            try:
                reply = pool.embed(inputs, model=model, providers=provider_filter)
            except NoProvidersConfigured as exc:
                self._error(503, str(exc), "no_providers")
                return
            except AllProvidersExhausted as exc:
                client_status = getattr(exc, "client_status", None)
                if isinstance(client_status, int) and 400 <= client_status < 500:
                    self._error(
                        client_status,
                        getattr(exc, "client_message", None) or str(exc),
                        "invalid_request_error",
                    )
                else:
                    self._error(502, str(exc), "all_providers_exhausted")
                return
            self._send(200, _to_embeddings_response(reply))

        def _handle_transcription(self, raw: bytes, content_type: str) -> None:
                                                                                  
            if "multipart/form-data" not in content_type.lower():
                self._error(
                    400, "audio transcription requires multipart/form-data", "invalid_request_error"
                )
                return
            try:
                form = _parse_multipart_form(content_type, raw)
            except ValueError as exc:
                self._error(400, f"malformed multipart body: {exc}", "invalid_request_error")
                return
            filepart = form.get("file")
            if not isinstance(filepart, tuple):
                self._error(400, "'file' part is required", "invalid_request_error")
                return
            filename, audio = filepart
            if not audio:
                self._error(400, "'file' is empty", "invalid_request_error")
                return
            requested = form.get("model") if isinstance(form.get("model"), str) else None
            language = form.get("language") if isinstance(form.get("language"), str) else None
            response_format = form.get("response_format")
            response_format = response_format if isinstance(response_format, str) else "json"
            if response_format not in _TRANSCRIPTION_FORMATS:
                self._error(
                    400,
                    f"unsupported response_format '{response_format}'; use one of "
                    f"{', '.join(_TRANSCRIPTION_FORMATS)}",
                    "invalid_request_error",
                )
                return
                                                                                               
            provider_filter = None
            model = None
            if requested and requested not in ("", "auto"):
                provider_filter, model = _parse_model(requested, {p.id for p in pool.transcribers})
            try:
                reply = pool.transcribe(
                    audio,
                    filename,
                    model=model,
                    providers=provider_filter,
                    language=language,
                    response_format=response_format,
                )
            except NoProvidersConfigured as exc:
                self._error(503, str(exc), "no_providers")
                return
            except AllProvidersExhausted as exc:
                client_status = getattr(exc, "client_status", None)
                if isinstance(client_status, int) and 400 <= client_status < 500:
                    self._error(
                        client_status,
                        getattr(exc, "client_message", None) or str(exc),
                        "invalid_request_error",
                    )
                else:
                    self._error(502, str(exc), "all_providers_exhausted")
                return
            if response_format == "text":
                payload = reply.text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self._send(200, _to_transcription_response(reply))

        def _resolve(
            self,
            req: dict,
            messages: list[dict],
            *,
            tools=None,
            tool_choice=None,
            response_format=None,
            protocol: str | None = None,
            timeout: float | None = None,
        ):
                                                                                 
                                                        
            requested = req.get("model") or "auto"
            if not isinstance(requested, str):
                self._error(400, "'model' must be a string", "invalid_request_error")
                return None
            routing_override, requested = _routing_and_model(self.headers, requested)
            requested = resolve_alias(requested, pool.env)                             
            provider_filter, model_filter = _parse_model(requested, {p.id for p in pool.providers})
            try:
                max_tokens = int(_max_tokens_value(req, 1024))
                temp_raw = req.get("temperature")
                temperature = 0.0 if temp_raw is None else float(temp_raw)
                task = task_resolution(
                    messages, _task_hint(self.headers, req)
                ).task
            except (TypeError, ValueError):
                self._error(
                    400,
                    "'max_tokens'/'max_completion_tokens'/'max_output_tokens'/"
                    "'temperature' must be numbers and 'task' must be valid",
                    "invalid_request_error",
                )
                return None
            upstream_timeout = (
                timeout
                if timeout is not None
                else (
                    _AGENT_UPSTREAM_TIMEOUT
                    if (routing_override or pool.routing) == "agent"
                    else 90.0
                )
            )
            try:
                return pool.chat(
                    messages,
                    model=model_filter,
                    providers=provider_filter,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=max(0.0, upstream_timeout),
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    protocol=protocol,
                    routing=routing_override,
                    task=task,
                )
            except NoProvidersConfigured as exc:
                self._error(503, str(exc), "no_providers")
            except ContextWindowExceeded as exc:
                self._error(413, str(exc), "context_length_exceeded")
            except AllProvidersExhausted as exc:
                                                                                 
                                                                                    
                                              
                cs = getattr(exc, "client_status", None)
                if isinstance(cs, int) and 400 <= cs < 500:
                    self._error(
                        cs,
                        getattr(exc, "client_message", None) or str(exc),
                        "invalid_request_error",
                    )
                else:
                    self._error(502, str(exc), "all_providers_exhausted")
            except SparrowError as exc:                                
                self._error(500, str(exc), "sparrow_error")
            return None

        def _open_text_stream(
            self,
            req: dict,
            messages: list[dict],
            *,
            max_tokens: int | None = None,
            temperature: float | None = None,
            timeout: float | None = None,
            protocol: str | None = None,
        ):
                                                                           

                                                                                    
                                                                                  
                                                                                  
               
            requested = req.get("model") or "auto"
            if not isinstance(requested, str):
                raise ValueError("'model' must be a string")
            routing_override, requested = _routing_and_model(self.headers, requested)
            requested = resolve_alias(requested, pool.env)
            provider_filter, model_filter = _parse_model(
                requested, {provider.id for provider in pool.providers}
            )
            max_tokens_value = (
                int(_max_tokens_value(req, 1024))
                if max_tokens is None
                else int(max_tokens)
            )
            if temperature is None:
                temp_raw = req.get("temperature")
                temperature_value = 0.0 if temp_raw is None else float(temp_raw)
            else:
                temperature_value = float(temperature)
            task = task_resolution(messages, _task_hint(self.headers, req)).task
            upstream_timeout = (
                timeout
                if timeout is not None
                else (
                    _AGENT_UPSTREAM_TIMEOUT
                    if (routing_override or pool.routing) == "agent"
                    else 90.0
                )
            )
            gen = pool.stream_chat(
                messages,
                model=model_filter,
                providers=provider_filter,
                max_tokens=max_tokens_value,
                temperature=temperature_value,
                timeout=upstream_timeout,
                routing=routing_override,
                protocol=protocol,
                task=task,
            )
            try:
                meta = next(gen)
            except BaseException:
                closer = getattr(gen, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:                                               
                        pass
                raise
            return gen, meta

        def _text_stream_timeout(self, req: dict) -> float:
            requested = req.get("model") or "auto"
            requested = requested if isinstance(requested, str) else "auto"
            routing_override, _requested = _routing_and_model(self.headers, requested)
            return (
                _AGENT_UPSTREAM_TIMEOUT
                if (routing_override or pool.routing) == "agent"
                else 90.0
            )

        def _send_event_stream_headers(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

        def _write_named_sse(self, name: str, payload: dict) -> None:
            block = f"event: {name}\ndata: {json.dumps(payload)}\n\n"
            try:
                self.wfile.write(block.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
                raise

        @staticmethod
        def _close_upstream_stream(gen) -> None:
            closer = getattr(gen, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:                                                    
                    pass

        def _handle_chat(self, req: dict) -> None:
            messages = req.get("messages")
            if not isinstance(messages, list) or not messages:
                self._error(400, "'messages' must be a non-empty array", "invalid_request_error")
                return
            if not all(isinstance(m, dict) for m in messages):
                self._error(400, "each message must be an object", "invalid_request_error")
                return
            norm = _normalize_messages(messages)
            tools = req.get("tools") if isinstance(req.get("tools"), list) else None
            response_format = req.get("response_format")
            if response_format is not None and not isinstance(response_format, dict):
                self._error(
                    400,
                    "'response_format' must be an object",
                    "invalid_request_error",
                )
                return
                                                                                       
            if req.get("stream") and not tools and response_format is None:
                self._stream_chat(req, norm)
                return
            reply = self._resolve(
                req,
                norm,
                tools=tools,
                tool_choice=req.get("tool_choice"),
                response_format=response_format,
            )
            if reply is None:
                return
                                  
            record_recent(
                {"provider": reply.provider_id, "model": reply.model, "attempts": reply.attempts}
            )
            if req.get("stream"):
                self._send_sse(_sse_chunks(reply))
            else:
                self._send(200, _to_openai_response(reply), headers=_obs_headers(reply))

        def _stream_chat(self, req: dict, norm: list[dict]) -> None:
            requested = req.get("model") or "auto"
            if not isinstance(requested, str):
                self._error(400, "'model' must be a string", "invalid_request_error")
                return
            routing_override, requested = _routing_and_model(self.headers, requested)
            provider_filter, model_filter = _parse_model(
                resolve_alias(requested, pool.env), {p.id for p in pool.providers}
            )
            try:
                max_tokens = int(_max_tokens_value(req, 1024))
                temp_raw = req.get("temperature")
                temperature = 0.0 if temp_raw is None else float(temp_raw)
                task = task_resolution(norm, _task_hint(self.headers, req)).task
            except (TypeError, ValueError):
                self._error(
                    400,
                    "'max_tokens'/'max_completion_tokens'/'max_output_tokens'/"
                    "'temperature' must be numbers and 'task' must be valid",
                    "invalid_request_error",
                )
                return
            upstream_timeout = (
                _AGENT_UPSTREAM_TIMEOUT
                if (routing_override or pool.routing) == "agent"
                else 90.0
            )
            deadline = pool._clock() + upstream_timeout
            try:
                gen = pool.stream_chat(
                    norm,
                    model=model_filter,
                    providers=provider_filter,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=upstream_timeout,
                    routing=routing_override,
                    task=task,
                )
                meta = next(gen)                                                     
            except NoProvidersConfigured as exc:
                self._error(503, str(exc), "no_providers")
                return
            except ContextWindowExceeded as exc:
                                                                                        
                self._error(413, str(exc), "context_length_exceeded")
                return
            except (AllProvidersExhausted, StopIteration) as exc:
                if isinstance(exc, AllProvidersExhausted):
                    client_status = getattr(exc, "client_status", None)
                    if isinstance(client_status, int) and 400 <= client_status < 500:
                        self._error(
                            client_status,
                            getattr(exc, "client_message", None) or str(exc),
                            "invalid_request_error",
                        )
                        return
                                                                                   
                reply = self._resolve(
                    req,
                    norm,
                    timeout=max(0.0, deadline - pool._clock()),
                    protocol="anthropic_messages",
                )
                if reply is not None:
                    record_recent(
                        {
                            "provider": reply.provider_id,
                            "model": reply.model,
                            "attempts": reply.attempts,
                        }
                    )
                    self._send_sse(_sse_chunks(reply))
                return

            provider_id = meta["provider"] if isinstance(meta, dict) else "auto"
            model_name = meta["model"] if isinstance(meta, dict) else "auto"
            attempts = meta.get("attempts", 1) if isinstance(meta, dict) else 1
            cid = f"chatcmpl-sparrow-{provider_id}"
            model_id = f"{provider_id}/{model_name}"
            created = int(time.time())
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(
                    _chunk_block(cid, model_id, role="assistant", created=created).encode()
                )
                for delta in gen:
                    self.wfile.write(
                        _chunk_block(cid, model_id, content=delta, created=created).encode()
                    )
                self.wfile.write(
                    _chunk_block(cid, model_id, finish="stop", created=created).encode()
                )
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):                    
                pass                       
            except Exception as exc:                
                                                                                    
                                                                                  
                                                                                   
                                                                                   
                                                                                   
                pool.metrics.record_failure(
                    f"{provider_id}/{model_name}", f"stream truncated: {exc}"
                )
                try:
                    err = json.dumps(
                        {
                            "error": {
                                "message": "upstream stream failed mid-response; output is incomplete",
                                "type": "upstream_error",
                                "code": "stream_truncated",
                            }
                        }
                    )
                    self.wfile.write(f"data: {err}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            finally:
                gen.close()                                                        
                                           
            record_recent(
                {"provider": provider_id, "model": model_name, "attempts": int(attempts)}
            )

        def _handle_responses(self, req: dict) -> None:
                                                                              
                                                
            messages = _responses_input_to_messages(req)
            if not messages:
                self._error(400, "'input' is required", "invalid_request_error")
                return
            try:
                tools, tool_choice = _responses_tools_to_chat(req)
            except ValueError as exc:
                self._error(400, str(exc), "invalid_request_error")
                return
                                                                            
                                                                              
                                                                               
            stream_deadline: float | None = None
            if req.get("stream") and _responses_text_streamable(req, messages, tools):
                stream_deadline = pool._clock() + self._text_stream_timeout(req)
                if self._stream_responses_text(
                    req,
                    messages,
                    deadline=stream_deadline,
                ):
                    return
            reply = self._resolve(
                req,
                messages,
                tools=tools,
                tool_choice=tool_choice,
                protocol="responses",
                timeout=(
                    max(0.0, stream_deadline - pool._clock())
                    if stream_deadline is not None
                    else None
                ),
            )
            if reply is None:
                return
            record_recent(
                {"provider": reply.provider_id, "model": reply.model, "attempts": reply.attempts}
            )
            if req.get("stream"):
                self._send_sse(_responses_sse_events(reply))
            else:
                self._send(200, _to_responses_object(reply))

        def _stream_responses_text(
            self,
            req: dict,
            messages: list[dict],
            *,
            deadline: float,
        ) -> bool:
                                                                               

                                                                                
                                                                              
                                                                   
                                                                               
               
            try:
                gen, meta = self._open_text_stream(
                    req,
                    messages,
                    timeout=max(0.0, deadline - pool._clock()),
                    protocol="responses",
                )
            except ContextWindowExceeded as exc:
                self._error(413, str(exc), "context_length_exceeded")
                return True
            except ValueError as exc:
                self._error(400, str(exc), "invalid_request_error")
                return True
            except (NoProvidersConfigured, AllProvidersExhausted, StopIteration):
                return False
            except Exception:                                                       
                return False

            provider_id = str(meta.get("provider", "auto")) if isinstance(meta, dict) else "auto"
            model_name = str(meta.get("model", "auto")) if isinstance(meta, dict) else "auto"
            attempts = meta.get("attempts", 1) if isinstance(meta, dict) else 1
            attempts = attempts if isinstance(attempts, int) else 1
            created_at = int(time.time())
            item_id = f"msg-{provider_id}"
            sequence_number = 0
            text_parts: list[str] = []
            disconnected = False
            succeeded = False

            def emit(name: str, payload: dict) -> None:
                nonlocal sequence_number
                event_payload = {**payload, "sequence_number": sequence_number}
                sequence_number += 1
                self._write_named_sse(name, event_payload)

            try:
                try:
                    self._send_event_stream_headers()
                    emit(
                        "response.created",
                        {
                            "type": "response.created",
                            "response": _responses_live_text_object(
                                provider_id,
                                model_name,
                                "",
                                created_at=created_at,
                                status="in_progress",
                            ),
                        },
                    )
                    emit(
                        "response.in_progress",
                        {
                            "type": "response.in_progress",
                            "response": _responses_live_text_object(
                                provider_id,
                                model_name,
                                "",
                                created_at=created_at,
                                status="in_progress",
                            ),
                        },
                    )
                    emit(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": 0,
                            "item": _responses_text_item(item_id, "", "in_progress", empty=True),
                        },
                    )
                    emit(
                        "response.content_part.added",
                        {
                            "type": "response.content_part.added",
                            "item_id": item_id,
                            "output_index": 0,
                            "content_index": 0,
                            "part": {
                                "type": "output_text",
                                "text": "",
                                "annotations": [],
                            },
                        },
                    )
                except (OSError, ValueError):
                    disconnected = True

                while not disconnected:
                    try:
                        delta = next(gen)
                    except StopIteration:
                        succeeded = True
                        break
                    except Exception:                                               
                        partial = "".join(text_parts)
                        try:
                            emit(
                                "response.failed",
                                {
                                    "type": "response.failed",
                                    "response": _responses_live_text_object(
                                        provider_id,
                                        model_name,
                                        partial,
                                        created_at=created_at,
                                        status="failed",
                                        error={
                                            "code": "server_error",
                                            "message": (
                                                "Upstream stream failed; output is incomplete."
                                            ),
                                        },
                                    ),
                                },
                            )
                        except (OSError, ValueError):
                            disconnected = True
                        break
                    if not isinstance(delta, str) or not delta:
                        continue
                    text_parts.append(delta)
                    try:
                        emit(
                            "response.output_text.delta",
                            {
                                "type": "response.output_text.delta",
                                "item_id": item_id,
                                "output_index": 0,
                                "content_index": 0,
                                "delta": delta,
                                "logprobs": [],
                            },
                        )
                    except (OSError, ValueError):
                        disconnected = True

                if succeeded and not disconnected:
                    text = "".join(text_parts)
                    part = {"type": "output_text", "text": text, "annotations": []}
                    item = _responses_text_item(item_id, text, "completed")
                    try:
                        emit(
                            "response.output_text.done",
                            {
                                "type": "response.output_text.done",
                                "item_id": item_id,
                                "output_index": 0,
                                "content_index": 0,
                                "text": text,
                                "logprobs": [],
                            },
                        )
                        emit(
                            "response.content_part.done",
                            {
                                "type": "response.content_part.done",
                                "item_id": item_id,
                                "output_index": 0,
                                "content_index": 0,
                                "part": part,
                            },
                        )
                        emit(
                            "response.output_item.done",
                            {
                                "type": "response.output_item.done",
                                "output_index": 0,
                                "item": item,
                            },
                        )
                        emit(
                            "response.completed",
                            {
                                "type": "response.completed",
                                "response": _responses_live_text_object(
                                    provider_id,
                                    model_name,
                                    text,
                                    created_at=created_at,
                                    status="completed",
                                ),
                            },
                        )
                    except (OSError, ValueError):
                        disconnected = True
            finally:
                self._close_upstream_stream(gen)
                record_recent(
                    {
                        "provider": provider_id,
                        "model": model_name,
                        "attempts": attempts,
                    }
                )
            return True

        def _send_sse(self, sse_blocks) -> None:
                                                         

                                                                           
                                                                                
                                                                                
                                                                                 
                                                       
               
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                for block in sse_blocks:
                    self.wfile.write(block.encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):                    
                self.close_connection = True

    return Handler


def _parse_model(requested: object, provider_ids: set[str]):
                                                                      

                                                                     
                                                                    
                                                         
                                                                                          
                                                                                     
                                                                             
       
    if not isinstance(requested, str) or not requested or requested == "auto":
        return None, None
    if "/" in requested:
        provider, _, model = requested.partition("/")
                                                                              
                                                                 
        if provider in provider_ids:
            return [provider], model
    if requested in provider_ids:
        return [requested], None
    return None, requested


def _messages_are_text_only(messages: list[dict]) -> bool:
                                                                     
    for message in messages:
        if message.get("role") == "tool" or message.get("tool_calls"):
            return False
        content = message.get("content")
        if isinstance(content, str):
            continue
        if not isinstance(content, list) or not content:
            return False
        if not all(
            isinstance(part, dict)
            and part.get("type") in {"text", "input_text", "output_text"}
            and isinstance(part.get("text"), str)
            for part in content
        ):
            return False
    return True


def _anthropic_text_streamable(req: dict, chat: dict) -> bool:
                                                                             
    if chat.get("tools") or chat.get("tool_choice") is not None:
        return False
    system = req.get("system")
    if system is not None and not (
        isinstance(system, str)
        or (
            isinstance(system, list)
            and all(
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
                for block in system
            )
        )
    ):
        return False
    for message in req.get("messages", []):
        if not isinstance(message, dict):
            return False
        content = message.get("content")
        if isinstance(content, str):
            continue
        if not isinstance(content, list) or not content:
            return False
        if not all(
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
            for block in content
        ):
            return False
    messages = chat.get("messages")
    return isinstance(messages, list) and bool(messages) and _messages_are_text_only(messages)


def _responses_text_streamable(req: dict, messages: list[dict], tools) -> bool:
                                                                                 
    if tools or any(req.get(field) is not None for field in ("include", "reasoning", "modalities")):
        return False
    text_config = req.get("text")
    if text_config is not None:
        if not isinstance(text_config, dict):
            return False
        text_format = text_config.get("format")
        if text_format is not None and (
            not isinstance(text_format, dict) or text_format.get("type") != "text"
        ):
            return False
    if req.get("response_format") is not None:
        return False
    return _messages_are_text_only(messages)


def _content(message: dict) -> str:
                                                                            
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if content is None:
        return ""                                                           
    return str(content)


def _normalize_messages(messages: list) -> list[dict]:
                                                                               
    out: list[dict] = []
    for m in messages:
        content = m.get("content")
        normalized_content = content if isinstance(content, list) else _content(m)
        nm: dict = {
            "role": str(m.get("role", "user")),
            "content": normalized_content,
        }
        for key in ("tool_calls", "tool_call_id", "name"):
            if m.get(key) is not None:
                nm[key] = m[key]
        out.append(nm)
    return out


def _header_safe(value: object) -> str:
                                                                                  
                                                                              
                                                              
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value))


def _obs_headers(reply) -> dict:
    return {
        "X-Sparrow-Provider": _header_safe(reply.provider_id),
        "X-Sparrow-Model": _header_safe(reply.model),
        "X-Sparrow-Attempts": reply.attempts,
    }


def _to_embeddings_response(reply) -> dict:
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": vec}
            for i, vec in enumerate(reply.vectors)
        ],
        "model": f"{reply.provider_id}/{reply.model}",
        "usage": {
            "prompt_tokens": reply.prompt_tokens or 0,
            "total_tokens": reply.prompt_tokens or 0,
        },
        "x_sparrow": {"provider": reply.provider_id, "model": reply.model},
    }


def _to_transcription_response(reply) -> dict:
    return {
        "text": reply.text,
        "x_sparrow": {"provider": reply.provider_id, "model": reply.model},
    }


def _parse_multipart_form(content_type: str, body: bytes) -> dict:
                                                                                  

                                                                                      
                                                                  
    m = re.search(r'boundary="?([^";]+)"?', content_type, re.IGNORECASE)
    if not m:
        raise ValueError("no boundary in Content-Type")
    boundary = m.group(1).strip().encode("latin-1")
                                                                                           
                                                                                           
                                                                                           
                                                                                  
    segments = (b"\r\n" + body).split(b"\r\n--" + boundary)
                                                                                            
                                                                                                
    if len(segments) < 2 or not segments[-1].startswith(b"--"):
        raise ValueError("missing closing multipart boundary")
    out: dict = {}
    for seg in segments[1:-1]:                                                      
        seg = seg[2:] if seg.startswith(b"\r\n") else seg                                      
        hdr, sep, payload = seg.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = hdr.decode("latin-1", "replace")
                                                                                            
                                                                                             
                                                                               
        name_m = re.search(r'(?<![A-Za-z])name="([^"]*)"', headers, re.IGNORECASE)
        if not name_m:
            continue
        name = name_m.group(1)
        fn_m = re.search(r'filename="([^"]*)"', headers, re.IGNORECASE)
        if fn_m is not None:
            out[name] = (fn_m.group(1), payload)                         
        else:
            out[name] = payload.decode("utf-8", "replace")              
    return out


def _to_openai_response(reply) -> dict:
    message = {"role": "assistant", "content": reply.text or None}
    finish = "stop"
    if reply.message and reply.message.get("tool_calls"):
        message["tool_calls"] = reply.message["tool_calls"]
        finish = "tool_calls"
    return {
        "id": f"chatcmpl-sparrow-{reply.provider_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"{reply.provider_id}/{reply.model}",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": reply.prompt_tokens or 0,
            "completion_tokens": reply.completion_tokens or 0,
            "total_tokens": (reply.prompt_tokens or 0) + (reply.completion_tokens or 0),
        },
        "x_sparrow": {"provider": reply.provider_id, "model": reply.model},
    }


def _dashboard_html(pool) -> str:
                                                                             
    import html as _html

    from . import __version__
    from .capacity import build_capacity_report
    from .key_inventory import load_inventory
    from .savings import usd_saved

    s = pool.stats_snapshot()
    saved = usd_saved(s.get("prompt_tokens"), s.get("completion_tokens"))
    snap = pool.quota.snapshot()
    by_provider: dict[str, int] = {}
    for key, count in snap.items():
        pid = key.split("::", 1)[0]
        by_provider[pid] = by_provider.get(pid, 0) + count

    configured = {p.id for p in pool.providers}
    rows = []
    for p in pool.providers:
        used = by_provider.get(p.id, 0)
        keyless = " · keyless" if p.keyless else ""
        rows.append(
            f"<tr><td>{_html.escape(p.id)}{keyless}</td>"
            f"<td>{len(p.models)}</td><td class=num>{used}</td></tr>"
        )
    other = sorted(pid for pid in by_provider if pid not in configured)
    for pid in other:
        rows.append(
            f"<tr><td>{_html.escape(pid)}</td><td>-</td><td class=num>{by_provider[pid]}</td></tr>"
        )
    provider_rows = "\n".join(rows) or "<tr><td colspan=3>no providers configured</td></tr>"

    capacity = build_capacity_report(env=pool.env, quota=pool.quota, inventory=load_inventory())
    capacity_rows = []
    for item in capacity.providers:
        if item.status == "missing":
            continue
        quota = "?" if item.quota_hint <= 0 else str(item.quota_hint)
        capacity_rows.append(
            f"<tr><td>{_html.escape(item.provider_id)}</td>"
            f"<td>{_html.escape(item.status)}</td>"
            f"<td class=num>{item.used_today}/{quota}</td>"
            f"<td>{_html.escape(item.reason)}</td></tr>"
        )
    capacity_table_rows = "\n".join(capacity_rows) or "<tr><td colspan=4>no capacity data</td></tr>"
    capacity_table = (
        "<h2>capacity</h2>"
        "<table><tr><th>provider</th><th>status</th><th class=num>usage</th><th>reason</th></tr>"
        f"{capacity_table_rows}</table>"
    )

                                                                        
    metrics_snap = pool.metrics.snapshot() if getattr(pool, "metrics", None) else {}
    measured = sorted(
        ((k, v) for k, v in metrics_snap.items() if v.ewma_ms is not None),
        key=lambda kv: kv[1].ewma_ms,
    )[:8]
    if measured:
        mrows = "\n".join(
            f"<tr><td>{_html.escape(k)}</td>"
            f"<td class=num>{v.ewma_ms:,.0f} ms</td>"
            f"<td class=num>{v.success_rate * 100:.0f}%</td></tr>"
            for k, v in measured
        )
        metrics_table = (
            "<h2 style='font-size:14px;color:#8a93a2;margin:24px 0 8px'>measured latency "
            "(fastest first)</h2>"
            "<table><tr><th>provider/model</th><th class=num>latency</th>"
            f"<th class=num>success</th></tr>{mrows}</table>"
        )
    else:
        metrics_table = ""

    cards = [
        ("requests served", str(s.get("requests", 0))),
        ("cache hits", str(s.get("cache_hits", 0))),
        ("healthy providers", f"{capacity.healthy_count}/{capacity.target}"),
        ("estimated not spent (Claude Opus 4.8)", f"${saved:,.2f}"),
    ]
    card_html = "\n".join(
        f"<div class=card><div class=big>{v}</div><div class=lbl>{k}</div></div>" for k, v in cards
    )
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta http-equiv=refresh content=5><title>sparrow</title>
<style>
 body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:0;background:#0b0e14;color:#e6e6e6}}
 .wrap{{max-width:760px;margin:0 auto;padding:32px 20px}}
 h1{{font-size:22px;margin:0 0 2px}} h2{{font-size:14px;color:#8a93a2;margin:24px 0 8px}}
 .sub{{color:#8a93a2;font-size:13px;margin-bottom:24px}}
 .cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:28px}}
 .card{{background:#141925;border:1px solid #232a39;border-radius:10px;padding:16px;text-align:center}}
 .big{{font-size:26px;font-weight:700}} .lbl{{color:#8a93a2;font-size:11px;margin-top:4px}}
 table{{width:100%;border-collapse:collapse;background:#141925;border:1px solid #232a39;border-radius:10px;overflow:hidden}}
 th,td{{padding:9px 14px;text-align:left;border-bottom:1px solid #232a39;font-size:14px}}
 th{{color:#8a93a2;font-weight:600;font-size:12px}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
 a{{color:#6ea8ff}}
</style></head><body><div class=wrap>
<h1>sparrow <span style="color:#8a93a2;font-weight:400;font-size:14px">v{__version__}</span></h1>
<div class=sub>{len(pool.providers)} providers configured · today's usage (UTC) · auto-refreshes every 5s</div>
<div class=cards>{card_html}</div>
<table><tr><th>provider</th><th>models</th><th class=num>requests today</th></tr>
{provider_rows}</table>
{capacity_table}
{metrics_table}
	<p class=sub style="margin-top:20px">OpenAI endpoint: <code>/v1</code> · <a href="https://github.com/airshakur88/sparrow">github.com/airshakur88/sparrow</a></p>
	</div></body></html>"""


_BROWSER_SHELL_STYLE = """
:root{color-scheme:dark;font-family:ui-sans-serif,system-ui,sans-serif;background:#0b0e14;color:#e8eaf0}
*{box-sizing:border-box}body{margin:0}.wrap{max-width:980px;margin:0 auto;padding:28px 18px 48px}
h1{font-size:24px;margin:0}.sub,.meta{color:#9aa4b5;font-size:13px}.top{display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}
nav,.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}button,input,textarea{font:inherit}
button{background:#dce8ff;color:#101522;border:0;border-radius:7px;padding:9px 13px;font-weight:700;cursor:pointer}
button:disabled{opacity:.55;cursor:not-allowed}button.secondary{background:#20283a;color:#dce8ff;border:1px solid #36415a}.panel{margin-top:20px;background:#141925;border:1px solid #273044;border-radius:10px;padding:18px}
.auth{max-width:520px;margin:56px auto}.auth form{display:flex;gap:8px;margin-top:14px}.auth input{flex:1;min-width:130px}
input,textarea{background:#0f1420;color:#f5f7fb;border:1px solid #36415a;border-radius:7px;padding:10px 12px}
textarea{width:100%;min-height:125px;margin:12px 0;resize:vertical}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:16px 0}
.card,.answer{background:#101622;border:1px solid #273044;border-radius:8px;padding:13px}.big{font-size:23px;font-weight:750}.label{color:#9aa4b5;font-size:11px;margin-top:3px}
table{width:100%;border-collapse:collapse}th,td{padding:9px 8px;text-align:left;border-bottom:1px solid #273044;font-size:13px}th{color:#9aa4b5;font-size:11px}.num{text-align:right;font-variant-numeric:tabular-nums}
.table-wrap{overflow-x:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:16px}.answer{white-space:pre-wrap}.fail{color:#ffb4a8}.ok{color:#a8e6b0}.notice{min-height:20px;margin-top:8px}[hidden]{display:none!important}
""".strip()

_BROWSER_SHELL_SCRIPT = """
(() => {
'use strict';
let token = '';
let authEpoch = 0;
let refreshPromise = null;
let refreshEpoch = -1;
let battleInFlight = false;
const byId = id => document.getElementById(id);
const authPanel = byId('auth-panel');
const app = byId('app');
const tokenInput = byId('proxy-token');
const authMessage = byId('auth-message');
const out = byId('out');
const runButton = byId('run');
const countInput = byId('count');

function clearProtectedView() {
  for (const [id, value] of [
    ['requests', '0'], ['tokens', '0'], ['cache-hits', '0'], ['saved', '$0.00'],
    ['healthy', '0/0'], ['models', '0']
  ]) text(id, value);
  byId('provider-rows').replaceChildren();
  byId('metrics-rows').replaceChildren();
  out.replaceChildren();
}
function showAuth(message) {
  token = '';
  authEpoch += 1;
  refreshPromise = null;
  refreshEpoch = -1;
  tokenInput.value = '';
  app.hidden = true;
  authPanel.hidden = false;
  clearProtectedView();
  authMessage.textContent = message || 'Enter the proxy token to continue.';
  tokenInput.focus();
}
function authorizedOptions(options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('Authorization', 'Bearer ' + token);
  return {...options, headers, credentials: 'omit', cache: 'no-store', redirect: 'error'};
}
async function protectedFetch(path, options = {}, expectedEpoch = authEpoch) {
  const response = await fetch(path, authorizedOptions(options));
  if (response.status === 401 || response.status === 403) {
    if (expectedEpoch === authEpoch) showAuth('That proxy token was not accepted.');
    throw new Error('authentication required');
  }
  return response;
}
async function readJson(response) {
  if (!response.ok) throw new Error('request failed (' + response.status + ')');
  return response.json();
}
function text(id, value) { byId(id).textContent = String(value); }
function formatNumber(value) { return Number(value || 0).toLocaleString(); }
function humanStatus(value) { return String(value || 'unknown').replaceAll('_', ' '); }
function appendCells(row, values) {
  for (const value of values) {
    const cell = document.createElement('td');
    cell.textContent = String(value ?? '');
    row.appendChild(cell);
  }
}
function quotaSummary(provider) {
  const providerModels = Array.isArray(provider.models) ? provider.models : [];
  let used = 0;
  let limitedQuota = 0;
  let hasUnmeteredModel = false;
  for (const model of providerModels) {
    used += Number(model.used_today || 0);
    if (model.daily_limit === null || model.daily_limit === undefined) {
      hasUnmeteredModel = true;
    } else {
      limitedQuota += Number(model.daily_limit || 0);
    }
  }
  let quota = formatNumber(limitedQuota);
  if (hasUnmeteredModel) quota = limitedQuota ? quota + ' + unmetered' : 'unmetered';
  return formatNumber(used) + ' / ' + quota;
}
function readinessReason(provider) {
  const ready = Number(provider.ready_models || 0);
  const enabled = Number(provider.enabled_models || 0);
  const cooldown = Math.max(0, Number(provider.cooldown_remaining_s || 0));
  if (provider.status === 'ready') return ready + '/' + enabled + ' enabled models ready';
  if (provider.status === 'unconfigured') return 'credentials not configured';
  if (provider.status === 'no_enabled_models') return 'no enabled models';
  if (provider.status === 'cooldown') {
    return cooldown ? 'cooldown; retry in ' + Math.ceil(cooldown) + 's' : 'provider cooldown';
  }
  if (provider.status === 'quota_exhausted') return 'daily quota exhausted';
  return humanStatus(provider.status);
}
function renderModelList(models) {
  const rows = byId('model-rows');
  rows.replaceChildren();
  const entries = Array.isArray(models.data) ? models.data : [];
  for (const model of entries) {
    const row = document.createElement('tr');
    appendCells(row, [model.id, model.owned_by || 'sparrow']);
    rows.appendChild(row);
  }
  if (!entries.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 2;
    cell.textContent = 'No available models are listed.';
    row.appendChild(cell);
    rows.appendChild(row);
  }
}
function renderMetrics(status) {
  const measured = [];
  for (const provider of Array.isArray(status.providers) ? status.providers : []) {
    for (const model of Array.isArray(provider.models) ? provider.models : []) {
      if (model.ewma_ms === null && model.success_rate === null) continue;
      measured.push({
        id: provider.id + '/' + model.name,
        latency: model.ewma_ms,
        success: model.success_rate,
        circuit: model.circuit_state
      });
    }
  }
  measured.sort((a, b) => {
    const aLatency = a.latency === null ? Number.POSITIVE_INFINITY : Number(a.latency);
    const bLatency = b.latency === null ? Number.POSITIVE_INFINITY : Number(b.latency);
    return aLatency - bLatency;
  });
  const rows = byId('metrics-rows');
  rows.replaceChildren();
  for (const metric of measured.slice(0, 8)) {
    const latency = metric.latency === null ? 'not measured' : formatNumber(Math.round(Number(metric.latency))) + ' ms';
    const success = metric.success === null ? 'not measured' : Math.round(Number(metric.success) * 100) + '%';
    const row = document.createElement('tr');
    appendCells(row, [metric.id, latency, success, humanStatus(metric.circuit)]);
    rows.appendChild(row);
  }
  if (!measured.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 4;
    cell.textContent = 'No measured calls yet.';
    row.appendChild(cell);
    rows.appendChild(row);
  }
}
function renderDashboard(status, inventory, readyModels, availableModels) {
  const usage = status.pool || {};
  text('requests', formatNumber(usage.requests));
  text('tokens', formatNumber(Number(usage.prompt_tokens || 0) + Number(usage.completion_tokens || 0)));
  text('cache-hits', formatNumber(usage.cache_hits));
  text('saved', '$' + Number(usage.usd_saved || 0).toFixed(2));
  const providers = Array.isArray(inventory.data) ? inventory.data : [];
  text('healthy', providers.filter(item => item.ready).length + '/' + providers.length);
  text('models', Array.isArray(readyModels.data) ? readyModels.data.length : 0);
  const rows = byId('provider-rows');
  rows.replaceChildren();
  for (const provider of providers) {
    const row = document.createElement('tr');
    appendCells(row, [
      provider.id,
      humanStatus(provider.status),
      provider.ready_models + '/' + provider.enabled_models,
      quotaSummary(provider),
      readinessReason(provider)
    ]);
    rows.appendChild(row);
  }
  if (!providers.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 5;
    cell.textContent = 'No provider inventory is available.';
    row.appendChild(cell);
    rows.appendChild(row);
  }
  renderModelList(availableModels);
  renderMetrics(status);
}
function refreshDashboard() {
  const epoch = authEpoch;
  if (refreshPromise && refreshEpoch === epoch) return refreshPromise;
  const active = (async () => {
    const responses = await Promise.all([
      protectedFetch('/v1/status', {}, epoch),
      protectedFetch('/v1/providers', {}, epoch),
       protectedFetch('/v1/models?ready=true', {}, epoch),
       protectedFetch('/v1/models', {}, epoch)
    ]);
    const data = await Promise.all(responses.map(readJson));
    if (epoch !== authEpoch) return;
    renderDashboard(data[0], data[1], data[2], data[3]);
    authPanel.hidden = true;
    app.hidden = false;
    authMessage.textContent = '';
  })();
  refreshPromise = active;
  refreshEpoch = epoch;
  return active.finally(() => {
    if (refreshPromise === active) {
      refreshPromise = null;
      refreshEpoch = -1;
    }
  });
}
function card(label, value, failed) {
  const element = document.createElement('div');
  element.className = 'answer';
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = label;
  const body = document.createElement('div');
  if (failed) body.className = 'fail';
  body.textContent = value || '';
  element.append(meta, body);
  return element;
}
async function runBattle() {
  if (battleInFlight) return;
  const prompt = byId('prompt').value.trim();
  if (!prompt) {
    out.replaceChildren(card('prompt required', 'Enter a question first.', true));
    return;
  }
  const epoch = authEpoch;
  const n = selectedBattleCount();
  battleInFlight = true;
  runButton.disabled = true;
  runButton.textContent = 'Running...';
  out.replaceChildren(card('running', 'Comparing ' + n + ' free models...', false));
  try {
    const response = await protectedFetch('/sparrow/battle', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt, n})
    }, epoch);
    const data = await readJson(response);
    if (epoch !== authEpoch) return;
    out.replaceChildren();
    for (const answer of data.answers || []) {
      out.appendChild(card(answer.label || answer.model, answer.error || answer.text, Boolean(answer.error)));
    }
    if (data.synthesis && data.synthesis.text) {
      out.appendChild(card('synthesis', data.synthesis.text, false));
    }
  } catch (_error) {
    if (epoch === authEpoch) {
      out.replaceChildren(card('request failed', 'The battle could not be completed.', true));
    }
  } finally {
    battleInFlight = false;
    runButton.disabled = false;
    runButton.textContent = 'Run battle';
  }
}
function selectedBattleCount() {
  return Math.max(2, Math.min(5, Number(countInput.value) || 3));
}
function updateBattleDisclosure() {
  const count = selectedBattleCount();
  text(
    'battle-disclosure',
    'One run starts ' + count + ' model completions; provider failover may add attempts.'
  );
}
byId('auth-form').addEventListener('submit', async event => {
  event.preventDefault();
  token = tokenInput.value;
  tokenInput.value = '';
  if (!token) {
    showAuth('Enter a proxy token.');
    return;
  }
  const epoch = ++authEpoch;
  authMessage.textContent = 'Checking token...';
  try {
    await refreshDashboard();
  } catch (_error) {
    if (epoch === authEpoch && authMessage.textContent === 'Checking token...') {
      showAuth('The proxy could not be reached. Check it and try again.');
    }
  }
});
runButton.addEventListener('click', runBattle);
countInput.addEventListener('input', updateBattleDisclosure);
byId('forget-token').addEventListener('click', () => {
  showAuth('Token forgotten. Enter it again to reconnect.');
  refreshDashboard().catch(() => {});
});
function selectPanel(name) {
  byId('dashboard-panel').hidden = name !== 'dashboard';
  byId('playground-panel').hidden = name !== 'playground';
}
for (const button of document.querySelectorAll('[data-panel]')) {
  button.addEventListener('click', () => selectPanel(button.dataset.panel));
}
selectPanel(location.pathname.endsWith('/playground') ? 'playground' : 'dashboard');
updateBattleDisclosure();
refreshDashboard().catch(() => showAuth('Enter the proxy token to continue.'));
setInterval(() => { if (!app.hidden) refreshDashboard().catch(() => {}); }, 5000);
})();
""".strip()


def _browser_shell_csp() -> str:
                                                                                    

    def source_hash(source: str) -> str:
        digest = hashlib.sha256(source.encode("utf-8")).digest()
        return base64.b64encode(digest).decode("ascii")

    return "; ".join(
        (
            "default-src 'none'",
            f"style-src 'sha256-{source_hash(_BROWSER_SHELL_STYLE)}'",
            f"script-src 'sha256-{source_hash(_BROWSER_SHELL_SCRIPT)}'",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        )
    )


def _browser_shell_html() -> str:
                                                                              
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sparrow</title><style>{_BROWSER_SHELL_STYLE}</style></head><body>
<main class="wrap">
<div class="top"><div><h1>sparrow</h1><div class="sub">local free-model pool</div></div></div>
<section id="auth-panel" class="panel auth" hidden>
<h2>Connect to this proxy</h2>
<div class="sub">The token stays only in this page's memory and is forgotten on reload.</div>
<form id="auth-form" autocomplete="off">
<input id="proxy-token" type="password" autocomplete="off" autocapitalize="off"
 spellcheck="false" aria-label="Proxy token" placeholder="Proxy token">
<button type="submit">Continue</button></form><div id="auth-message" class="notice fail"></div>
</section>
<section id="app" hidden>
<div class="top"><nav aria-label="Views"><button class="secondary" data-panel="dashboard">Dashboard</button>
<button class="secondary" data-panel="playground">Playground</button>
<button id="forget-token" class="secondary" type="button">Forget token</button></nav>
<div class="sub">Usage and inventory refresh every 5 seconds</div></div>
<section id="dashboard-panel" class="panel"><h2>Dashboard</h2>
<div class="cards"><div class="card"><div id="requests" class="big">0</div><div class="label">requests served</div></div>
<div class="card"><div id="tokens" class="big">0</div><div class="label">tokens served</div></div>
<div class="card"><div id="cache-hits" class="big">0</div><div class="label">cache hits</div></div>
<div class="card"><div id="saved" class="big">$0.00</div><div class="label">estimated not spent</div></div>
<div class="card"><div id="healthy" class="big">0/0</div><div class="label">healthy providers</div></div>
<div class="card"><div id="models" class="big">0</div><div class="label">ready models</div></div></div>
<h3>Provider capacity</h3><div class="table-wrap"><table><thead><tr><th>provider</th><th>status</th><th>ready</th><th>usage / daily quota</th><th>readiness reason</th></tr></thead>
<tbody id="provider-rows"></tbody></table></div>
<h3>All available models</h3><div class="sub">Every model currently exposed by this proxy, including virtual routes.</div>
<div class="table-wrap"><table><thead><tr><th>model</th><th>owner</th></tr></thead>
<tbody id="model-rows"></tbody></table></div>
<h3>Measured latency and success</h3><div class="sub">Observed in this proxy process; fastest measured routes appear first.</div>
<div class="table-wrap"><table><thead><tr><th>provider/model</th><th>latency</th><th>success</th><th>circuit</th></tr></thead>
<tbody id="metrics-rows"></tbody></table></div></section>
<section id="playground-panel" class="panel" hidden><h2>Playground</h2>
<div class="bar"><label>models <input id="count" type="number" min="2" max="5" value="3" aria-describedby="battle-disclosure"></label>
<button id="run" type="button">Run battle</button></div>
<div id="battle-disclosure" class="sub">One run starts 3 model completions; provider failover may add attempts.</div>
<textarea id="prompt" placeholder="Ask a question to compare across free models"></textarea>
<section id="out" class="grid" aria-live="polite"></section></section>
</section></main><script>{_BROWSER_SHELL_SCRIPT}</script></body></html>"""


def _playground_html() -> str:
                                                                              
    return _browser_shell_html()


def _chunk_block(
    cid: str,
    model_id: str,
    *,
    role=None,
    content=None,
    finish=None,
    created: int | None = None,
) -> str:
    delta: dict = {}
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    chunk = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()) if created is None else created,
        "model": model_id,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def _sse_chunks(reply):
                                                                          

                                                                                
                                                                      
       
    cid = f"chatcmpl-sparrow-{reply.provider_id}"
    model = f"{reply.provider_id}/{reply.model}"
    base = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
    }
    tool_calls = reply.message.get("tool_calls") if reply.message else None

    def block(chunk):
        return f"data: {json.dumps(chunk)}\n\n"

    yield block(
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
    )
    if reply.text:
        yield block(
            {
                **base,
                "choices": [{"index": 0, "delta": {"content": reply.text}, "finish_reason": None}],
            }
        )
    if tool_calls:
                                                                               
        indexed = [{**tc, "index": i} for i, tc in enumerate(tool_calls)]
        yield block(
            {
                **base,
                "choices": [{"index": 0, "delta": {"tool_calls": indexed}, "finish_reason": None}],
            }
        )
    finish = "tool_calls" if tool_calls else "stop"
    yield block({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
    yield "data: [DONE]\n\n"


                                                                                


def _responses_input_to_messages(req: dict) -> list[dict]:
                                                                               

                                                                            
                                                                       
       
    messages: list[dict] = []
    instructions = req.get("instructions")
    if isinstance(instructions, str) and instructions:
        messages.append({"role": "system", "content": instructions})

    data = req.get("input")
    if isinstance(data, str):
        messages.append({"role": "user", "content": data})
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "function_call":
                call_id = item.get("call_id")
                name = item.get("name")
                arguments = item.get("arguments")
                if (
                    isinstance(call_id, str)
                    and call_id
                    and isinstance(name, str)
                    and name
                    and isinstance(arguments, str)
                ):
                    messages.append(
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": arguments,
                                    },
                                }
                            ],
                        }
                    )
                continue
            if kind == "function_call_output":
                call_id = item.get("call_id")
                output = item.get("output")
                if isinstance(call_id, str) and call_id and isinstance(output, str):
                    messages.append(
                        {
                            "role": "tool",
                            "content": output,
                            "tool_call_id": call_id,
                        }
                    )
                continue
            role = str(item.get("role", "user"))
            content = item.get("content", "")
            if isinstance(content, list):
                parts = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    kind = part.get("type")
                    text = part.get("text")
                    if kind in {"input_text", "text"} and isinstance(text, str):
                        parts.append({"type": "text", "text": text})
                    elif kind in {"input_image", "image_url"}:
                        image_url = part.get("image_url")
                        if isinstance(image_url, str):
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_url},
                                }
                            )
                        elif isinstance(image_url, dict) and isinstance(
                            image_url.get("url"), str
                        ):
                            parts.append({"type": "image_url", "image_url": image_url})
                normalized_content: object = parts
            else:
                normalized_content = str(content)
            messages.append({"role": role, "content": normalized_content})
    return messages


def _responses_tools_to_chat(req: dict) -> tuple[list[dict] | None, object | None]:
                                                                                   

    raw_tools = req.get("tools")
    raw_choice = req.get("tool_choice")
    if raw_tools is None:
        if raw_choice is not None:
            raise ValueError("'tool_choice' requires a non-empty 'tools' array")
        return None, None
    if not isinstance(raw_tools, list):
        raise ValueError("'tools' must be an array of function tools")
    if not raw_tools:
        if raw_choice is not None:
            raise ValueError("'tool_choice' requires a non-empty 'tools' array")
        return None, None

    tools: list[dict] = []
    for tool in raw_tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ValueError("only Responses function tools are supported")
        source = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = source.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("each function tool requires a non-empty 'name'")
        function: dict[str, object] = {"name": name}
        description = source.get("description")
        if description is not None:
            if not isinstance(description, str):
                raise ValueError("function tool 'description' must be a string")
            function["description"] = description
        parameters = source.get("parameters")
        if parameters is not None:
            if not isinstance(parameters, dict):
                raise ValueError("function tool 'parameters' must be an object")
            function["parameters"] = parameters
        strict = source.get("strict")
        if strict is not None:
            if not isinstance(strict, bool):
                raise ValueError("function tool 'strict' must be a boolean")
            function["strict"] = strict
        tools.append({"type": "function", "function": function})

    if raw_choice is None or isinstance(raw_choice, str):
        if isinstance(raw_choice, str) and raw_choice not in {"auto", "none", "required"}:
            raise ValueError("unsupported Responses 'tool_choice'")
        return tools, raw_choice
    if not isinstance(raw_choice, dict) or raw_choice.get("type") != "function":
        raise ValueError("unsupported Responses 'tool_choice'")
    choice_source = (
        raw_choice.get("function")
        if isinstance(raw_choice.get("function"), dict)
        else raw_choice
    )
    choice_name = choice_source.get("name")
    if not isinstance(choice_name, str) or not choice_name:
        raise ValueError("function 'tool_choice' requires a non-empty 'name'")
    return tools, {"type": "function", "function": {"name": choice_name}}


def _responses_function_call_items(reply) -> list[dict]:
    tool_calls = reply.message.get("tool_calls") if isinstance(reply.message, dict) else None
    if not isinstance(tool_calls, list):
        return []
    items = []
    for index, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function")
        if tool_call.get("type") != "function" or not isinstance(function, dict):
            continue
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not name or not isinstance(arguments, str):
            continue
        raw_call_id = tool_call.get("id")
        call_id = (
            raw_call_id
            if isinstance(raw_call_id, str) and raw_call_id
            else f"call-{reply.provider_id}-{index}"
        )
        items.append(
            {
                "type": "function_call",
                "id": f"fc-{call_id}",
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "status": "completed",
            }
        )
    return items


def _responses_text_item(
    item_id: str,
    text: str,
    status: str,
    *,
    empty: bool = False,
) -> dict:
    content = []
    if not empty:
        content.append({"type": "output_text", "text": text, "annotations": []})
    return {
        "type": "message",
        "id": item_id,
        "status": status,
        "role": "assistant",
        "content": content,
    }


def _responses_live_text_object(
    provider_id: str,
    model_name: str,
    text: str,
    *,
    created_at: int,
    status: str,
    error: dict | None = None,
) -> dict:
                                                                              
    finished = status == "completed"
    output = []
    if status != "in_progress":
        item_status = "completed" if finished else "incomplete"
        output.append(_responses_text_item(f"msg-{provider_id}", text, item_status))
    output_tokens = max(0, len(text) // 4)
    usage = None
    if finished:
        usage = {
            "input_tokens": 0,
            "output_tokens": output_tokens,
            "total_tokens": output_tokens,
        }
    return {
        "id": f"resp-sparrow-{provider_id}",
        "object": "response",
        "created_at": created_at,
        "status": status,
        "completed_at": int(time.time()) if finished else None,
        "error": error,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": f"{provider_id}/{model_name}",
        "output": output,
        "output_text": text,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "store": False,
        "temperature": 0.0,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": usage,
        "user": None,
        "metadata": {},
        "x_sparrow": {"provider": provider_id, "model": model_name},
    }


def _to_responses_object(reply) -> dict:
    rid = f"resp-sparrow-{reply.provider_id}"
    output = []
    if reply.text:
        output.append(
            {
                "type": "message",
                "id": f"msg-{reply.provider_id}",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": reply.text,
                        "annotations": [],
                    }
                ],
            }
        )
    output.extend(_responses_function_call_items(reply))
    if not output:
        output.append(
            {
                "type": "message",
                "id": f"msg-{reply.provider_id}",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "", "annotations": []}],
            }
        )
    return {
        "id": rid,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "completed_at": int(time.time()),
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": f"{reply.provider_id}/{reply.model}",
        "output": output,
        "output_text": reply.text or "",                                                
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "store": False,
        "temperature": 0.0,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": {
            "input_tokens": reply.prompt_tokens or 0,
            "output_tokens": reply.completion_tokens or 0,
            "total_tokens": (reply.prompt_tokens or 0) + (reply.completion_tokens or 0),
        },
        "user": None,
        "metadata": {},
        "x_sparrow": {"provider": reply.provider_id, "model": reply.model},
    }


def _responses_sse_events(reply):
                                                                             
    obj = _to_responses_object(reply)
    sequence_number = 0

    def event(name, payload):
        nonlocal sequence_number
        payload = {**payload, "sequence_number": sequence_number}
        sequence_number += 1
        return f"event: {name}\ndata: {json.dumps(payload)}\n\n"

    created = {
        **obj,
        "status": "in_progress",
        "completed_at": None,
        "output": [],
        "output_text": "",
        "usage": None,
    }
    yield event(
        "response.created",
        {"type": "response.created", "response": created},
    )
    yield event(
        "response.in_progress",
        {"type": "response.in_progress", "response": created},
    )
    for output_index, item in enumerate(obj["output"]):
        if item.get("type") == "message":
            initial_item = {**item, "status": "in_progress", "content": []}
            yield event(
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "output_index": output_index,
                    "item": initial_item,
                },
            )
            content = item.get("content")
            if not isinstance(content, list) or not content:
                yield event(
                    "response.output_item.done",
                    {
                        "type": "response.output_item.done",
                        "output_index": output_index,
                        "item": item,
                    },
                )
                continue
            part = content[0]
            initial_part = {**part, "text": ""}
            yield event(
                "response.content_part.added",
                {
                    "type": "response.content_part.added",
                    "item_id": item["id"],
                    "output_index": output_index,
                    "content_index": 0,
                    "part": initial_part,
                },
            )
            text = part.get("text") or ""
            if text:
                yield event(
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": item["id"],
                        "output_index": output_index,
                        "content_index": 0,
                        "delta": text,
                        "logprobs": [],
                    },
                )
            yield event(
                "response.output_text.done",
                {
                    "type": "response.output_text.done",
                    "item_id": item["id"],
                    "output_index": output_index,
                    "content_index": 0,
                    "text": text,
                    "logprobs": [],
                },
            )
            yield event(
                "response.content_part.done",
                {
                    "type": "response.content_part.done",
                    "item_id": item["id"],
                    "output_index": output_index,
                    "content_index": 0,
                    "part": part,
                },
            )
            yield event(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": output_index,
                    "item": item,
                },
            )
            continue
        if item.get("type") != "function_call":
            continue
        initial_item = {**item, "arguments": "", "status": "in_progress"}
        yield event(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": output_index,
                "item": initial_item,
            },
        )
        yield event(
            "response.function_call_arguments.done",
            {
                "type": "response.function_call_arguments.done",
                "item_id": item["id"],
                "name": item["name"],
                "output_index": output_index,
                "arguments": item["arguments"],
            },
        )
        yield event(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": output_index,
                "item": item,
            },
        )
    yield event("response.completed", {"type": "response.completed", "response": obj})


def serve(
    pool: Pool,
    host: str = "127.0.0.1",
    port: int = 8080,
    api_key: str | None = None,
    request_logger=None,
) -> ThreadingHTTPServer:
                                                                              
                                                                                  
    if api_key is None:
        api_key = os.environ.get("SPARROW_PROXY_KEY") or None
    handler = make_handler(pool, api_key, request_logger)
    httpd = _BoundedThreadingHTTPServer((host, port), handler)
    httpd.pool = pool
                                                                              
                                        
    httpd.daemon_threads = True
    return httpd


_MAX_CONNECTIONS = 128                                                                     
_CONNECTION_SLOT_WAIT_SECONDS = 0.25                                                 


class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
                                                                              
                                                                             
                                                                     

    daemon_threads = True
    request_queue_size = _MAX_CONNECTIONS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)

    def server_close(self) -> None:
        try:
            pool = getattr(self, "pool", None)
            if pool is not None:
                pool.flush()
        finally:
            super().server_close()

    def process_request(self, request, client_address):
                                                                                
                                                                                
                                                                                
                                                                               
        if not self._slots.acquire(timeout=_CONNECTION_SLOT_WAIT_SECONDS):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Connection: close\r\nContent-Length: 0\r\n\r\n"
                )
            except OSError:                                  
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
                                                                                         
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()
