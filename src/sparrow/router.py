                                             

                                                                      
                                                                            
                                                                              
                               
   

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from . import client as _client
from .cache import Cache
from .capability import capability_table, fit_penalty, model_capability, prompt_difficulty
from .client import (
    MultipartPostFn,
    PostFn,
    StreamPostFn,
    default_multipart_post,
    default_post,
    default_stream_post,
)
from .config import (
    configured_embedders,
    configured_providers,
    configured_transcribers,
    effective_env,
    load_catalog,
    load_config_file,
    load_embedders,
    load_transcribers,
    parse_virtual_providers,
    settings,
)
from .conformance import ConformanceStore, default_conformance_path, required_features
from .context import context_limit_from_error, estimate_input_tokens
from .credential_config import parse_credentials
from .credential_errors import classify_credential_failure
from .credential_manager import CredentialManager
from .credential_store import CredentialStore
from .credentials import CredentialOperation, CredentialSelection, CredentialUnavailable
from .errors import (
    AllProvidersExhausted,
    ContextWindowExceeded,
    NoProvidersConfigured,
    ProviderHTTPError,
)
from .metrics import Metrics, score_stat
from .models import EmbedReply, Provider, Reply, TranscribeReply
from .observe import EventHook, emit
from .quota import QuotaStore
from .route_health import (
    FailureUpdate,
    HealthLease,
    RouteHealthStore,
    default_route_health_path,
    score_record,
)
from .routing_modes import normalize_routing_mode
from .stats import StatsStore
from .task_quality import (
    TASK_GENERAL,
    model_task_score,
    resolve_task,
    task_evidence_table,
    validate_task,
)
from .virtual_models import virtual_model, virtual_routing, virtual_targets

_MIN_LEARNABLE_CONTEXT = 256
                                                                                 
                                                                               
_CTX_LIMIT_TTL = 1800.0                    
                                                                         
                                                                              
                                                                                  
                                                                                     
                                                                                
                                                                 
_QUALITY_SLOW_S = 8.0
_QUALITY_UNKNOWN_LAT = 0.34
_QUALITY_UNKNOWN_TASK = 0.5
_QUALITY_TASK_WEIGHT = 1.0
                                                                                         
                                                                                    
                                                                                            
                                                                                    
                                        
_SPREAD_BUCKET = 8
_AGENT_CAPABILITY_TIER = 0.05
_ACCOUNT_BACKOFF_SECONDS = 15 * 60
_SUCCESS_BATCH_SIZE = 32
_SUCCESS_FLUSH_INTERVAL = 1.0


def _positive_int_setting(env: dict[str, str], name: str, default: int) -> int:
    try:
        return max(1, int(env.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _positive_float_setting(
    env: dict[str, str], name: str, default: float
) -> float:
    try:
        return max(0.001, float(env.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _is_health_failure(exc: Exception) -> bool:
                                                                                
                                                                               
                                             

                                                                               
                                                                              
                                                                               
                                                           
       
    if isinstance(exc, ProviderHTTPError):
        return exc.status in (429, 408) or exc.status >= 500
    return True                                   


def _is_account_quota_exhaustion(
    exc: ProviderHTTPError,
    provider_id: str | None = None,
) -> bool:
                                                                              
    if exc.status not in (402, 429):
        return False
    message = str(exc).lower()
    if provider_id == "vercel" and exc.status == 402:
        return True
    return any(
        marker in message
        for marker in (
            "depleted your monthly",
            "used up your daily free allocation",
            "insufficient credits",
            "quota exhausted",
            "quota has been exhausted",
            "credit balance",
        )
    )


def _health_failure_class(exc: Exception, provider_id: str | None = None) -> str:
                                                                                
    if isinstance(exc, ProviderHTTPError):
        if _is_account_quota_exhaustion(exc, provider_id):
            return "provider_quota"
        if exc.status == 429:
            return "rate_limit"
        if exc.status == 408:
            return "timeout"
        if exc.status >= 500:
            return "availability"
        if exc.status in (401, 403):
            return "auth"
        if exc.status in (404, 410):
            return "retirement"
        if exc.status == 402:
            return "capability"
        return "client"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "transport"


@dataclass(frozen=True)
class Target:
                                                                

    provider: Provider
    model: str
    rpd: int
    context: int | None = None                                                   

    @property
    def name(self) -> str:
        return f"{self.provider.id}/{self.model}"


@dataclass(frozen=True)
class _ChatAttempt:
    target: Target
    allow_defer: bool = False
    retry_error: Exception | None = None
    lease: HealthLease | None = None


def _provider_first_wave(targets: list[Target]) -> tuple[list[Target], list[Target]]:
                                                                                  
    seen: set[str] = set()
    first: list[Target] = []
    remaining: list[Target] = []
    for target in targets:
        bucket = first if target.provider.id not in seen else remaining
        bucket.append(target)
        seen.add(target.provider.id)
    return first, remaining


@dataclass
class _ProviderOrderStats:
                                                                        

    targets: list[Target]
    used: int = 0
    all_over: bool = True
    all_failing: bool = True
    best_score: float = float("inf")


class Pool:
    def __init__(
        self,
        providers: list[Provider],
        *,
        quota: QuotaStore | None = None,
        env: dict[str, str] | None = None,
        post: PostFn = default_post,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
        embedders: list[Provider] | None = None,
        transcribers: list[Provider] | None = None,
        stream_post: StreamPostFn = default_stream_post,
        transcribe_post: MultipartPostFn = default_multipart_post,
        cache: Cache | None = None,
        metrics: Metrics | None = None,
        routing: str = "fair",
        on_event: EventHook | None = None,
        stats_store: StatsStore | None = None,
        route_health: RouteHealthStore | None = None,
        conformance: ConformanceStore | None = None,
        credential_manager: CredentialManager | None = None,
        virtual_providers: Iterable[str] | None = None,
    ):
        self.providers = providers
        self._virtual_providers = frozenset(virtual_providers or ())
        targets: list[Target] = []
        enabled_targets: list[Target] = []
        targets_by_provider: dict[str, list[Target]] = {}
        enabled_by_provider: dict[str, list[Target]] = {}
        targets_by_model: dict[str, list[Target]] = {}
        enabled_by_model: dict[str, list[Target]] = {}
        for provider in providers:
            for model_obj in provider.models:
                target = Target(provider, model_obj.name, model_obj.rpd, model_obj.context)
                targets.append(target)
                targets_by_provider.setdefault(provider.id, []).append(target)
                targets_by_model.setdefault(model_obj.name, []).append(target)
                if model_obj.enabled and model_obj.auto:
                    enabled_targets.append(target)
                    enabled_by_provider.setdefault(provider.id, []).append(target)
                    enabled_by_model.setdefault(model_obj.name, []).append(target)
        self._targets = tuple(targets)
        self._enabled_targets = tuple(enabled_targets)
        self._targets_by_provider = {k: tuple(v) for k, v in targets_by_provider.items()}
        self._enabled_targets_by_provider = {k: tuple(v) for k, v in enabled_by_provider.items()}
        self._targets_by_model = {k: tuple(v) for k, v in targets_by_model.items()}
        self._enabled_targets_by_model = {k: tuple(v) for k, v in enabled_by_model.items()}
        self.embedders = embedders or []
        self.transcribers = transcribers or []
        self.env = env if env is not None else dict(os.environ)
        self._transcribe_post = transcribe_post
        self.quota = quota or QuotaStore(
            flush_every=_positive_int_setting(
                self.env, "SPARROW_QUOTA_FLUSH_EVERY", _SUCCESS_BATCH_SIZE
            ),
            flush_interval=_positive_float_setting(
                self.env,
                "SPARROW_QUOTA_FLUSH_INTERVAL",
                _SUCCESS_FLUSH_INTERVAL,
            ),
        )
        self._post = post
        self._stream_post = stream_post
        self._cache = cache
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock or time.monotonic
        self.metrics = metrics or Metrics()
        self.route_health = route_health
        self.conformance = conformance
        self._credential_manager = credential_manager
        self.credential_manager = credential_manager
                                                                                  
                                                                              
                                                                                    
                                                                                    
                                                                                 
        self.routing = normalize_routing_mode(routing)
        self._on_event = on_event
                                                                               
        self._cooldown_until: dict[str, float] = {}
        self._cooldown_lock = threading.Lock()
                                                                               
                                                                               
                                                           
        self._account_backoff_until: dict[str, float] = {}
                                                                             
                                                                                
                                                                                  
        self.stats = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cache_hits": 0}
        self._stats_store = stats_store
        self._stats_lock = threading.Lock()                                             
                                                                                      
                                                                                    
                                                                  
        self._ctx_limits: dict[str, tuple[int, float]] = {}                               
        self._ctx_lock = threading.Lock()

    def _bump_stats(self, **deltas: int) -> None:
                                                                              
                                                                                  
                                                            
        with self._stats_lock:
            for key, delta in deltas.items():
                self.stats[key] = self.stats.get(key, 0) + delta
        if self._stats_store is not None:
            self._stats_store.add(**deltas)

    def stats_snapshot(self) -> dict:
                                                                                  
                                                                             
        with self._stats_lock:
            return dict(self.stats)

    def flush(self) -> None:
                                                                                  
        for store in (self.quota, self._stats_store, self.route_health):
            flush = getattr(store, "flush", None)
            if callable(flush):
                flush()

    def _chat_post_once(self, url: str, headers: dict, body: dict, timeout: float):
                                                                                     
        if self._post is default_post:
            return default_post(url, headers, body, timeout, max_attempts=1)
        return self._post(url, headers, body, timeout)

    def cooldown_snapshot(self, now: float) -> dict[str, float]:
                                                                                   
        with self._cooldown_lock:
            provider_ids = self._cooldown_until.keys() | self._account_backoff_until.keys()
            result = {
                provider_id: max(
                    0.0,
                    self._cooldown_until.get(provider_id, 0.0) - now,
                    self._account_backoff_until.get(provider_id, 0.0) - now,
                )
                for provider_id in provider_ids
            }
        if self.route_health is not None:
            for provider_id, remaining in self.route_health.provider_cooldowns().items():
                result[provider_id] = max(result.get(provider_id, 0.0), remaining)
        return result

    def lifetime_stats(self) -> dict:
                                                                              
                                                  
        if self._stats_store is not None:
            return self._stats_store.snapshot()
        return {**self.stats_snapshot(), "first_seen": None}

    def route_health_snapshot(self):
                                                                              
        return self.route_health.snapshot() if self.route_health is not None else {}

    def route_cooldown_snapshot(self) -> dict[str, float]:
                                                                              
        return self.route_health.route_cooldowns() if self.route_health is not None else {}

    def conformance_snapshot(self) -> dict:
                                                                              

        return self.conformance.snapshot() if self.conformance is not None else {
            "version": 1,
            "targets": {},
        }

    def _acquire_route(self, target: Target) -> HealthLease | None:
        if self.route_health is None:
            return HealthLease(started_at=time.time(), generations={})
        return self.route_health.acquire_many(
            (f"{target.provider.id}/*", target.name)
        )

    def _record_route_success(
        self,
        target: Target,
        latency_ms: float,
        lease: HealthLease,
    ) -> None:
        if self.route_health is None:
            return
        self.route_health.record_success_many(
            (target.name, f"{target.provider.id}/*"),
            latency_ms,
            lease=lease,
        )

    def _record_route_failure(
        self,
        target: Target,
        exc: Exception,
        lease: HealthLease,
    ) -> None:
        if self.route_health is None:
            return
        failure_class = _health_failure_class(exc, target.provider.id)
        counts = _is_health_failure(exc)
        retry_after = exc.retry_after if isinstance(exc, ProviderHTTPError) else None
        updates = [
            FailureUpdate(
                key=target.name,
                failure_class=failure_class,
                retry_after=retry_after,
                counts_for_health=counts,
                open_immediately=(
                    isinstance(exc, ProviderHTTPError) and exc.status == 429
                ),
            )
        ]
        if failure_class in {"rate_limit", "provider_quota", "auth"}:
            provider_retry = retry_after
            if failure_class == "provider_quota":
                provider_retry = max(
                    retry_after or 0.0,
                    _ACCOUNT_BACKOFF_SECONDS,
                    self.cooldown_seconds,
                )
            updates.append(
                FailureUpdate(
                    key=f"{target.provider.id}/*",
                    failure_class=failure_class,
                    retry_after=provider_retry,
                    counts_for_health=failure_class != "auth",
                    open_immediately=(
                        failure_class in {"rate_limit", "provider_quota"}
                    ),
                )
            )
        self.route_health.record_failures(
            updates,
            lease=lease,
        )

    def _record_route_empty(self, target: Target, lease: HealthLease) -> None:
        if self.route_health is not None:
            self.route_health.record_failure(target.name, "empty", lease=lease)

    def _refresh_route_lease(self, lease: HealthLease) -> HealthLease:
                                                                                
        if self.route_health is None:
            return lease
        return self.route_health.refresh_lease(lease)

    def _release_local_saturation(
        self, target: Target, lease: HealthLease
    ) -> None:
                                                                        
        if self.route_health is not None:
            self.route_health.release_many(
                (f"{target.provider.id}/*", target.name), lease=lease
            )

    def rank_targets(
        self,
        messages: list[dict[str, Any]],
        *,
        routing: str | None = None,
        model: str | None = None,
        providers: Iterable[str] | None = None,
        task: str | None = None,
    ) -> list[Target]:
                                                                                    
                                                                             
                                                                                      
                                                                           
        provider_list = list(providers) if providers else None
        model_routing = virtual_routing(model, routing)
        eff = normalize_routing_mode(model_routing or routing, self.routing)
        difficulty = prompt_difficulty(messages) if eff in ("quality", "adaptive") else None
        if eff in ("quality", "adaptive"):
            resolved_task = resolve_task(messages, task)
        else:
            validate_task(task)
            resolved_task = TASK_GENERAL
        return self._order(
            self._all_targets(include=provider_list, model=model),
            difficulty=difficulty,
            routing=eff,
            task=resolved_task,
        )

    def _mark_cooldown(self, provider_id: str, now: float) -> None:
        until = now + self.cooldown_seconds
        with self._cooldown_lock:
            self._cooldown_until[provider_id] = max(
                self._cooldown_until.get(provider_id, 0.0), until
            )

    def _cooled(self, provider_id: str, now: float) -> bool:
        with self._cooldown_lock:
            return self._cooldown_until.get(provider_id, 0.0) > now

    def _mark_account_backoff(self, provider_id: str, now: float) -> None:
        until = now + max(_ACCOUNT_BACKOFF_SECONDS, self.cooldown_seconds)
        with self._cooldown_lock:
            self._account_backoff_until[provider_id] = max(
                self._account_backoff_until.get(provider_id, 0.0), until
            )

    def _account_backed_off(self, provider_id: str, now: float) -> bool:
        with self._cooldown_lock:
            return self._account_backoff_until.get(provider_id, 0.0) > now

                                                                         

    def _effective_context(self, target: Target) -> int | None:
                                                                             
                                                                                
        learned = None
        with self._ctx_lock:
            entry = self._ctx_limits.get(target.name)
        if entry is not None and self._clock() - entry[1] < _CTX_LIMIT_TTL:
            learned = entry[0]
        sizes = [v for v in (target.context, learned) if v is not None]
        return min(sizes) if sizes else None

    def _learn_context_limit(self, target_name: str, limit: int) -> None:
                                                                                    
                                                                                   
                        
        if limit < _MIN_LEARNABLE_CONTEXT:
            return
        now = self._clock()
        with self._ctx_lock:
            prev = self._ctx_limits.get(target_name)
                                                                                    
                                                                                      
                                                                                    
                                                         
            if prev is not None and now - prev[1] < _CTX_LIMIT_TTL and prev[0] <= limit:
                return
            self._ctx_limits[target_name] = (limit, now)

                                                                         

    @classmethod
    def from_default_config(
        cls,
        *,
        env: dict[str, str] | None = None,
        quota: QuotaStore | None = None,
        post: PostFn = default_post,
        on_event: EventHook | None = None,
    ) -> Pool:
        from .plugins import registered_providers

                                                                   
        env = effective_env(env)
                                                                                
                                                                                
                                                   
        by_id = {p.id: p for p in load_catalog()}
        for p in registered_providers():
            by_id[p.id] = p
        catalog = list(by_id.values())
        config_data = load_config_file(env)
        provider_specs = config_data.get("providers")
        disabled_ids: set[str] = set()
        if isinstance(provider_specs, dict):
            disabled_ids = {
                str(provider_id)
                for provider_id, spec in provider_specs.items()
                if isinstance(spec, dict) and spec.get("enabled") is False
            }
        providers = [
            provider for provider in configured_providers(catalog, env)
            if provider.id not in disabled_ids
        ]
        if "credentials" in config_data or provider_specs is not None:
            slots = parse_credentials(config_data, catalog, env)
            configured_ids = {
                slot.provider
                for slot in slots
                if slot.enabled and env.get(slot.env_var, "").strip()
            }
            providers = [provider for provider in catalog if provider.id in configured_ids]
            store = CredentialStore()
            credential_manager = CredentialManager(slots, env, store)
        else:
            credential_manager = None
        embedders = configured_embedders(load_embedders(), env)
        transcribers = configured_transcribers(load_transcribers(), env)
        cfg = settings(env)
        cooldown = float(cfg.get("cooldown_seconds", 60.0))
        ttl = float(env.get("SPARROW_CACHE_TTL") or cfg.get("cache_ttl", 0) or 0)
        cache = Cache(ttl) if ttl > 0 else None
        from .mode import default_routing_for_mode

        routing = default_routing_for_mode(env, cfg)
        return cls(
            providers,
            quota=quota,
            env=env,
            post=post,
            cooldown_seconds=cooldown,
            embedders=embedders,
            transcribers=transcribers,
            cache=cache,
            routing=routing,
            virtual_providers=parse_virtual_providers(cfg),
            on_event=on_event,
            stats_store=StatsStore(
                flush_every=_positive_int_setting(
                    env, "SPARROW_STATS_FLUSH_EVERY", _SUCCESS_BATCH_SIZE
                ),
                flush_interval=_positive_float_setting(
                    env,
                    "SPARROW_STATS_FLUSH_INTERVAL",
                    _SUCCESS_FLUSH_INTERVAL,
                ),
            ),
            route_health=RouteHealthStore(
                path=default_route_health_path(env),
                base_cooldown=cooldown,
                success_flush_every=_positive_int_setting(
                    env,
                    "SPARROW_ROUTE_HEALTH_FLUSH_EVERY",
                    _SUCCESS_BATCH_SIZE,
                ),
                success_flush_interval=_positive_float_setting(
                    env,
                    "SPARROW_ROUTE_HEALTH_FLUSH_INTERVAL",
                    _SUCCESS_FLUSH_INTERVAL,
                ),
            ),
            conformance=ConformanceStore(default_conformance_path(env)),
            credential_manager=credential_manager,
        )

    def embed(
        self,
        texts: str | list[str],
        *,
        model: str | None = None,
        providers: Iterable[str] | None = None,
        timeout: float = 90.0,
    ) -> EmbedReply:
                                                                                
        inputs = [texts] if isinstance(texts, str) else list(texts)
        if not self.embedders:
            raise NoProvidersConfigured(
                "no embedder configured; set a key for one of: cohere, github, "
                "cloudflare, mistral, nvidia"
            )
        include = {p.strip() for p in providers} if providers else None
        attempts: list[tuple[str, str]] = []
        excluded_credentials: dict[str, set[str]] = {}
        client_error: ProviderHTTPError | None = None
        for emb in self.embedders:
            if include is not None and emb.id not in include:
                continue
            for m in emb.models:
                if not m.enabled:
                    continue
                if model is not None and m.name != model:
                    continue
                target = Target(emb, m.name, m.rpd, m.context)
                lease = self._acquire_route(target)
                if lease is None:
                    attempts.append((target.name, "skipped (persistent circuit open)"))
                    continue
                started = self._clock()
                selected_credential: CredentialSelection | None = None
                api_key = emb.api_key(self.env)
                manager = self.credential_manager
                if manager is not None and not emb.keyless:
                    selected = manager.reserve(
                        emb.id,
                        m.name,
                        CredentialOperation.EMBED,
                        excluded_ids=excluded_credentials.get(emb.id),
                        deadline=started + max(0.0, timeout),
                    )
                    if isinstance(selected, CredentialUnavailable):
                        attempts.append((target.name, f"skipped ({selected.reason.value})"))
                        continue
                    selected_credential = selected
                    api_key = selected.secret
                if api_key is None and not emb.keyless:
                    attempts.append((target.name, "missing api key"))
                    continue
                try:
                    reply = _client.embed(
                        emb,
                        m.name,
                        inputs,
                        api_key=api_key,
                        env=self.env,
                        timeout=timeout,
                        post=self._post,
                    )
                except Exception as exc:                                        
                    attempts.append((target.name, f"{type(exc).__name__}: {exc}"))
                    if selected_credential is not None and isinstance(exc, ProviderHTTPError):
                        failure = classify_credential_failure(
                            exc.status,
                            retry_after=exc.retry_after,
                            credential_specific=exc.status in {401, 403},
                            cooldown_seconds=self.cooldown_seconds,
                        )
                        if failure is not None:
                            assert manager is not None
                            assert selected_credential is not None
                            manager.record_failure(selected_credential, failure)
                            excluded_credentials.setdefault(emb.id, set()).add(
                                selected_credential.credential_id
                            )
                    self._record_route_failure(target, exc, lease)
                    if (
                        isinstance(exc, ProviderHTTPError)
                        and not exc.retryable
                        and not _is_account_quota_exhaustion(exc, target.provider.id)
                        and client_error is None
                    ):
                        client_error = exc
                    continue
                                                                                      
                                                                                      
                self._record_route_success(
                    target,
                    max(0.0, (self._clock() - started) * 1000.0),
                    lease,
                )
                self.quota.record(emb.id, m.name)
                self._bump_stats(requests=1, prompt_tokens=reply.prompt_tokens or 0)
                return reply
        if not attempts:                                                      
            raise NoProvidersConfigured("no candidate embedder/model matched the given filters")
        if client_error is not None:
            raise AllProvidersExhausted(
                attempts,
                client_status=client_error.status,
                client_message=str(client_error),
            )
        raise AllProvidersExhausted(attempts)

    def transcribe(
        self,
        audio: bytes,
        filename: str,
        *,
        model: str | None = None,
        providers: Iterable[str] | None = None,
        language: str | None = None,
        response_format: str = "json",
        timeout: float = 90.0,
    ) -> TranscribeReply:
                                                                                           
        if not self.transcribers:
            raise NoProvidersConfigured(
                "no transcriber configured; set a key for groq"
            )
        include = {p.strip() for p in providers} if providers else None
        attempts: list[tuple[str, str]] = []
        excluded_credentials: dict[str, set[str]] = {}
        client_error: ProviderHTTPError | None = None
        for tr in self.transcribers:
            if include is not None and tr.id not in include:
                continue
            for m in tr.models:
                if not m.enabled:
                    continue
                if model is not None and m.name != model:
                    continue
                target = Target(tr, m.name, m.rpd, m.context)
                lease = self._acquire_route(target)
                if lease is None:
                    attempts.append((target.name, "skipped (persistent circuit open)"))
                    continue
                started = self._clock()
                selected_credential: CredentialSelection | None = None
                api_key = tr.api_key(self.env)
                manager = self.credential_manager
                if manager is not None and not tr.keyless:
                    selected = manager.reserve(
                        tr.id,
                        m.name,
                        CredentialOperation.TRANSCRIBE,
                        excluded_ids=excluded_credentials.get(tr.id),
                        deadline=started + max(0.0, timeout),
                    )
                    if isinstance(selected, CredentialUnavailable):
                        attempts.append((target.name, f"skipped ({selected.reason.value})"))
                        continue
                    selected_credential = selected
                    api_key = selected.secret
                if api_key is None and not tr.keyless:
                    attempts.append((target.name, "missing api key"))
                    continue
                try:
                    reply = _client.transcribe(
                        tr,
                        m.name,
                        audio,
                        filename,
                        api_key=api_key,
                        env=self.env,
                        language=language,
                        response_format=response_format,
                        timeout=timeout,
                        post=self._transcribe_post,
                    )
                except Exception as exc:                                           
                    attempts.append((target.name, f"{type(exc).__name__}: {exc}"))
                    if selected_credential is not None and isinstance(exc, ProviderHTTPError):
                        failure = classify_credential_failure(
                            exc.status,
                            retry_after=exc.retry_after,
                            credential_specific=exc.status in {401, 403},
                            cooldown_seconds=self.cooldown_seconds,
                        )
                        if failure is not None:
                            assert manager is not None
                            assert selected_credential is not None
                            manager.record_failure(selected_credential, failure)
                            excluded_credentials.setdefault(tr.id, set()).add(
                                selected_credential.credential_id
                            )
                            self._record_route_failure(target, exc, lease)
                            continue
                    self._record_route_failure(target, exc, lease)
                    if (
                        isinstance(exc, ProviderHTTPError)
                        and not exc.retryable
                        and not _is_account_quota_exhaustion(exc, target.provider.id)
                        and client_error is None
                    ):
                        client_error = exc
                    continue
                self._record_route_success(
                    target,
                    max(0.0, (self._clock() - started) * 1000.0),
                    lease,
                )
                self.quota.record(tr.id, m.name)
                self._bump_stats(requests=1, prompt_tokens=reply.prompt_tokens or 0)
                return reply
        if not attempts:                                                         
            raise NoProvidersConfigured("no candidate transcriber/model matched the given filters")
        if client_error is not None:
            raise AllProvidersExhausted(
                attempts,
                client_status=client_error.status,
                client_message=str(client_error),
            )
        raise AllProvidersExhausted(attempts)

                                                                         

    def _all_targets(
        self,
        include: Iterable[str] | None = None,
        model: str | None = None,
    ) -> list[Target]:
        include_set = {p.strip() for p in include} if include else None
        source = (
            self._enabled_targets
            if virtual_model(model) is not None
            else self._targets_by_model.get(model, ())
            if model is not None
            else self._enabled_targets
        )
        source = virtual_targets(source, model, self._virtual_providers)
        if include_set is None:
            return list(source)
        return [target for target in source if target.provider.id in include_set]

    def _feature_targets(
        self,
        targets: list[Target],
        features: Iterable[str],
        *,
        exact_pin: bool,
        model: str | None = None,
    ) -> list[Target]:
                                                                                        

        wanted = frozenset(features)
        if not wanted or exact_pin or self.conformance is None:
            return targets
        if virtual_model(model) is not None:
            # Virtual models are explicit routes, usable before local canaries run.
            # Missing evidence is not evidence that an upstream lacks a feature.
            snapshot = self.conformance.snapshot()
            return [
                target
                for target in targets
                if all(
                    row.get("status") not in {"fail", "unsupported"}
                    for feature, row in self.conformance.evidence(
                        target.provider, target.model, snapshot=snapshot
                    ).items()
                    if feature in wanted
                )
            ]
        return self.conformance.verified_targets(targets, wanted)

    def _order(
        self,
        targets: list[Target],
        difficulty: float | None = None,
        routing: str | None = None,
        task: str = TASK_GENERAL,
    ) -> list[Target]:
                                                

                                                                                   
                                                                                  
                                        

                                                                                
                            

                                                                                          
                                                                                           
                                                                                         
                                                           

                                                                                   
                                                                                 
                                                                                    
                                                                         
                                                                        

                                                                                  
                                                                                 
                                                                               
                                                   

                                                                                   
                                                            
           

                                                                                    
                                                     
        snap = self.quota.snapshot()
        metrics = self.metrics
        msnap = metrics.snapshot()
        hsnap = self.route_health_snapshot()
        mode = normalize_routing_mode(routing, self.routing)

        def used_of(t: Target) -> int:
            return int(snap.get(f"{t.provider.id}::{t.model}", 0))

        def over_of(t: Target) -> int:
            return 1 if (t.rpd > 0 and used_of(t) >= t.rpd) else 0

        def stat_of(t: Target):
            return msnap.get(t.name)

        def health_of(t: Target):
            return hsnap.get(t.name)

        def failing_of(t: Target) -> bool:
            health = health_of(t)
            if health is not None and (
                health.state != "closed"
                or (
                    self.route_health is not None
                    and health.consecutive_failures >= self.route_health.failure_threshold
                )
            ):
                return True
            st = stat_of(t)
            return bool(st and st.failing)

        def score_of(t: Target) -> float:
            health = health_of(t)
            if health is not None:
                return score_record(health)
            return score_stat(stat_of(t))

        def latency_of(t: Target) -> float:
            stat = stat_of(t)
            if stat is not None and stat.ewma_ms is not None:
                return stat.ewma_ms
            health = health_of(t)
            if health is not None and health.ewma_ms is not None:
                return health.ewma_ms
            return float("inf")

        if mode == "adaptive":
            if difficulty is not None and difficulty < 0.34:
                return self._order(
                    targets,
                    difficulty=difficulty,
                    routing="swift",
                    task=task,
                )
            if difficulty is not None and difficulty > 0.66:
                return self._order(
                    targets,
                    difficulty=difficulty,
                    routing="apex",
                    task=task,
                )
            return self._order(
                targets,
                difficulty=difficulty,
                routing="quality",
                task=task,
            )

        if mode in ("apex", "swift"):
            table = capability_table()

            def apex_key(t: Target) -> tuple[int, int, float, float, str, str]:
                return (
                    over_of(t),
                    1 if failing_of(t) else 0,
                    -model_capability(t.model, table),
                    latency_of(t),
                    t.provider.id,
                    t.model,
                )

            def swift_key(t: Target) -> tuple[int, int, float, float, int, str, str]:
                health = health_of(t)
                return (
                    over_of(t),
                    1 if failing_of(t) else 0,
                    0 if model_capability(t.model, table) <= 0.45 else 1,
                    latency_of(t),
                    1 if health is not None and health.state != "closed" else 0,
                    t.provider.id,
                    t.model,
                )

            if mode == "apex":
                return sorted(targets, key=apex_key)

            if not any(model_capability(target.model, table) <= 0.45 for target in targets):
                return self._order(targets, routing="fast")
            return sorted(targets, key=swift_key)

        if mode == "agent":
            table = capability_table()
            provider_used: dict[str, int] = {}
            for target in targets:
                provider_id = target.provider.id
                provider_used[provider_id] = provider_used.get(provider_id, 0) + used_of(target)

            def agent_key(
                t: Target,
            ) -> tuple[int, int, int, int, int, float, float, int, int]:
                capability = model_capability(t.model, table)
                tier = int((capability + 1e-9) / _AGENT_CAPABILITY_TIER)
                account_used = provider_used[t.provider.id]
                return (
                    over_of(t),
                    1 if failing_of(t) else 0,
                    -tier,
                    account_used // _SPREAD_BUCKET,
                    used_of(t) // _SPREAD_BUCKET,
                    score_of(t),
                    -capability,
                    account_used,
                    used_of(t),
                )

            return sorted(targets, key=agent_key)

        if mode == "quality":
            table = capability_table()
            need = difficulty if difficulty is not None else 0.5
            task_table = task_evidence_table(task) if task != TASK_GENERAL else {}
            has_task_evidence = any(
                model_task_score(target.model, task_table) is not None
                for target in targets
            )

            def lat_pen(t: Target) -> float:
                                                                                
                                                                                
                                                                                 
                                                                                 
                                                                                
                                                                                    
                                                                                       
                st = stat_of(t)
                latency = st.ewma_ms if st is not None else None
                if latency is None:
                    health = health_of(t)
                    latency = health.ewma_ms if health is not None else None
                if latency is None:
                    return _QUALITY_UNKNOWN_LAT
                return min(latency / 1000.0, _QUALITY_SLOW_S) / _QUALITY_SLOW_S

            def quality_key(t: Target) -> tuple[int, int, float, int]:
                                                                                     
                                                                                 
                                                                             
                task_penalty = 0.0
                if has_task_evidence:
                    measured = model_task_score(t.model, task_table)
                    task_score = _QUALITY_UNKNOWN_TASK if measured is None else measured
                    task_penalty = (1.0 - task_score) * _QUALITY_TASK_WEIGHT
                return (
                    over_of(t),
                    1 if failing_of(t) else 0,
                    fit_penalty(model_capability(t.model, table), need)
                    + task_penalty
                    + lat_pen(t),
                    used_of(t),
                )

            return sorted(targets, key=quality_key)

        if mode in ("legacy", "model", "model-fast"):

            def legacy_fast_key(t: Target) -> tuple[int, float, int]:
                return (over_of(t), score_of(t), used_of(t))

            def legacy_fair_key(t: Target) -> tuple[int, int, int]:
                return (over_of(t), 1 if failing_of(t) else 0, used_of(t))

            key = legacy_fast_key if mode == "model-fast" else legacy_fair_key
            return sorted(targets, key=key)

        by_provider: dict[str, _ProviderOrderStats] = {}
        for target in targets:
            provider_id = target.provider.id
            stats = by_provider.setdefault(provider_id, _ProviderOrderStats(targets=[]))
            stats.targets.append(target)
            target_used = used_of(target)
            target_over = over_of(target)
            target_failing = failing_of(target)
            stats.used += target_used
            stats.all_over = stats.all_over and bool(target_over)
            stats.all_failing = stats.all_failing and target_failing
            stats.best_score = min(stats.best_score, score_of(target))

        def target_fair_key(t: Target) -> tuple[int, int, int]:
            return (over_of(t), 1 if failing_of(t) else 0, used_of(t))

        def target_fast_key(t: Target) -> tuple[int, float, int]:
            return (over_of(t), score_of(t), used_of(t))

        def target_spread_key(t: Target) -> tuple[int, int, int, float]:
                                                                                             
            return (
                over_of(t),
                1 if failing_of(t) else 0,
                used_of(t) // _SPREAD_BUCKET,
                score_of(t),
            )

        if mode == "fast":

            def provider_fast_key(provider_id: str) -> tuple[int, float, int]:
                stats = by_provider[provider_id]
                return (1 if stats.all_over else 0, stats.best_score, stats.used)

            provider_order = sorted(by_provider, key=provider_fast_key)
            target_key = target_fast_key
        elif mode == "spread":

            def provider_spread_key(provider_id: str) -> tuple[int, int, int, float]:
                                                                                        
                                                                                          
                stats = by_provider[provider_id]
                return (
                    1 if stats.all_over else 0,
                    1 if stats.all_failing else 0,
                    stats.used // _SPREAD_BUCKET,
                    stats.best_score,
                )

            provider_order = sorted(by_provider, key=provider_spread_key)
            target_key = target_spread_key
        else:

            def provider_fair_key(provider_id: str) -> tuple[int, int, int]:
                stats = by_provider[provider_id]
                return (
                    1 if stats.all_over else 0,
                    1 if stats.all_failing else 0,
                    stats.used,
                )

            provider_order = sorted(by_provider, key=provider_fair_key)
            target_key = target_fair_key

        ordered: list[Target] = []
        for provider_id in provider_order:
            ordered.extend(sorted(by_provider[provider_id].targets, key=target_key))
        return ordered

                                                                         

    def ask(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        providers: Iterable[str] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 90.0,
        tools: list | None = None,
        tool_choice=None,
        routing: str | None = None,
        task: str | None = None,
    ) -> Reply:
                                                               

                                                                        
                                                                               
                                                                      
                                                                 
           
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(
            messages,
            model=model,
            providers=providers,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            tools=tools,
            tool_choice=tool_choice,
            routing=routing,
            task=task,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        providers: Iterable[str] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 90.0,
        tools: list | None = None,
        tool_choice=None,
        response_format=None,
        protocol: str | None = None,
        routing: str | None = None,
        task: str | None = None,
    ) -> Reply:
                                                                    

                                                                             
           
        if not self.providers:
            raise NoProvidersConfigured(
                "no provider has an API key set; see .env.example for the env vars"
            )

        provider_list = list(providers) if providers else None
        features = required_features(
            messages,
            tools=tools,
            response_format=response_format,
            protocol=protocol,
        )
        exact_pin = (
            model is not None and provider_list is not None and len(provider_list) == 1
        )
        candidates = self._feature_targets(
            self._all_targets(include=provider_list, model=model),
            features,
            exact_pin=exact_pin,
            model=model,
        )
                                                                             
                                                                                  
                                                                        
        model_routing = virtual_routing(model, routing)
        eff = normalize_routing_mode(model_routing or routing, self.routing)
        if eff in ("quality", "adaptive"):
            resolved_task = resolve_task(messages, task)
        else:
            validate_task(task)
            resolved_task = TASK_GENERAL
        cache_key = None
        if self._cache is not None:
            cache_key = self._cache.make_key(
                messages,
                model,
                provider_list,
                max_tokens,
                temperature,
                tools,
                tool_choice,
                eff,
                response_format=response_format,
                protocol=protocol,
                task=resolved_task,
            )
            hit = self._cache.get(cache_key)
            feature_cache_eligible = (
                hit is not None
                and (
                    not features
                    or exact_pin
                    or self.conformance is None
                    or any(
                        target.provider.id == hit.get("provider_id")
                        and target.model == hit.get("model")
                        for target in candidates
                    )
                )
            )
            if hit is not None and feature_cache_eligible:
                emit(self._on_event, "cache_hit", key=cache_key)
                self._bump_stats(cache_hits=1)
                return Reply(
                    text=hit.get("text", ""),
                    provider_id=hit.get("provider_id", "cache"),
                    model=hit.get("model", "?"),
                    raw={},
                    prompt_tokens=hit.get("prompt_tokens"),
                    completion_tokens=hit.get("completion_tokens"),
                    message=hit.get("message"),
                    cached=True,
                )
            emit(self._on_event, "cache_miss", key=cache_key)

        difficulty = (
            prompt_difficulty(messages, max_tokens, tools)
            if eff in ("quality", "adaptive")
            else None
        )
        targets = self._order(
            candidates,
            difficulty=difficulty,
            routing=eff,
            task=resolved_task,
        )
        if not targets:
            raise NoProvidersConfigured("no candidate (provider, model) matched the given filters")

                                                                                
                                                                             
                                                                                  
                                      
        now = self._clock()
        deadline = now + max(0.0, timeout)
        states = [
            (
                t,
                self._cooled(t.provider.id, now)
                or self._account_backed_off(t.provider.id, now),
            )
            for t in targets
        ]
        sequence = [t for t, c in states if not c] + [t for t, c in states if c]

        usable_provider_ids = {
            target.provider.id
            for target in sequence
            if target.provider.keyless or target.provider.api_key(self.env) is not None
        }
        diversity_retry = not exact_pin and len(usable_provider_ids) > 1
        if diversity_retry:
            first_wave, later_targets = _provider_first_wave(sequence)
            pending = deque(_ChatAttempt(target, allow_defer=True) for target in first_wave)
            fallback = deque(_ChatAttempt(target) for target in later_targets)
        else:
            pending = deque(_ChatAttempt(target) for target in sequence)
            fallback = deque()
        deferred: deque[_ChatAttempt] = deque()

        attempts: list[tuple[str, str]] = []
        unavailable_providers: set[str] = set()                                             
        credential_exclusions: dict[str, set[str]] = {}
        client_error: ProviderHTTPError | None = None                                
                                                                                  
                                                                      
        est_tokens = estimate_input_tokens(messages, tools)
        needed = est_tokens + max_tokens
        ctx_overflow = False
        non_ctx_failure = False
        while pending or deferred or fallback:
            if pending:
                attempt = pending.popleft()
            elif deferred:
                attempt = deferred.popleft()
            else:
                attempt = fallback.popleft()
            target = attempt.target
            is_deferred = attempt.retry_error is not None
            if is_deferred:
                retry_after = (
                    attempt.retry_error.retry_after
                    if isinstance(attempt.retry_error, ProviderHTTPError)
                    else None
                )
                delay = _client._retry_delay_seconds(
                    retry_after,
                    0,
                    deadline,
                    self._clock,
                )
                if delay is None:
                    attempts.append((target.name, "skipped (retry delay exceeds timeout)"))
                    continue
                time.sleep(delay)
            if target.provider.id in unavailable_providers and not is_deferred:
                                                                                 
                                                                              
                attempts.append((target.name, "skipped (provider quota unavailable this request)"))
                continue
            cap = self._effective_context(target)
            if cap is not None and needed > cap:
                attempts.append(
                    (target.name, f"skipped (context ~{cap} < needed ~{needed} tokens)")
                )
                emit(self._on_event, "context_skip", target=target.name, context=cap, needed=needed)
                ctx_overflow = True
                continue
            started = self._clock()
            remaining = deadline - started
            if remaining <= 0:
                attempts.append((target.name, "skipped (overall request timeout exhausted)"))
                break
            selection: CredentialSelection | None = None
            if self._credential_manager is not None:
                reserved = self._credential_manager.reserve(
                    target.provider.id,
                    target.model,
                    CredentialOperation.CHAT,
                    excluded_ids=credential_exclusions.setdefault(target.provider.id, set()),
                    deadline=deadline,
                )
                if not isinstance(reserved, CredentialSelection):
                    non_ctx_failure = True
                    attempts.append((target.name, f"skipped (credential unavailable: {reserved.reason.value})"))
                    continue
                selection = reserved
                api_key = selection.secret
            else:
                api_key = target.provider.api_key(self.env)
                if api_key is None and not target.provider.keyless:                    
                    non_ctx_failure = True
                    attempts.append((target.name, "missing api key"))
                    continue
            lease = attempt.lease
            if lease is None:
                lease = self._acquire_route(target)
            if lease is None:
                non_ctx_failure = True
                attempts.append((target.name, "skipped (persistent circuit open)"))
                emit(self._on_event, "circuit_skip", target=target.name)
                continue
            emit(self._on_event, "attempt", target=target.name, n=len(attempts) + 1)
            try:
                reply = _client.call(
                    target.provider,
                    target.model,
                    messages,
                    api_key=api_key,
                    env=self.env,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=remaining,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    post=(
                        self._chat_post_once
                        if attempt.allow_defer or is_deferred
                        else self._post
                    ),
                )
            except ProviderHTTPError as exc:
                credential_failure = None
                is_ctx, limit = context_limit_from_error(exc.status, str(exc))
                if is_ctx:
                    self._record_route_failure(target, exc, lease)
                    ctx_overflow = True
                    if limit is not None:
                        self._learn_context_limit(target.name, limit)
                    emit(self._on_event, "error", target=target.name, reason=str(exc))
                    attempts.append(
                        (target.name, f"context window exceeded (limit ~{limit or '?'})")
                    )
                    continue
                account_exhausted = _is_account_quota_exhaustion(exc, target.provider.id)
                defer_retry = (
                    attempt.allow_defer
                    and _client._retryable(exc.status)
                    and not account_exhausted
                )
                if exc.status == 429:
                    self._mark_cooldown(target.provider.id, self._clock())
                    unavailable_providers.add(target.provider.id)
                    emit(self._on_event, "cooldown", target=target.name, status=429)
                if selection is not None:
                    failure = classify_credential_failure(
                        exc.status,
                        retry_after=exc.retry_after,
                        credential_specific=exc.status in {401, 403},
                        cooldown_seconds=self.cooldown_seconds,
                    )
                    if failure is not None:
                        if self.credential_manager is not None:
                            self.credential_manager.record_failure(selection, failure)
                        credential_exclusions.setdefault(target.provider.id, set()).add(
                            selection.credential_id
                        )
                if account_exhausted:
                    self._mark_account_backoff(target.provider.id, self._clock())
                    unavailable_providers.add(target.provider.id)
                                                                                    
                                                                                 
                non_ctx_failure = True
                                                                                  
                                                                                  
                                                                                   
                                                  
                if not exc.retryable and not account_exhausted and client_error is None:
                    client_error = exc
                if _is_health_failure(exc) and credential_failure is None:
                    self.metrics.record_failure(target.name, str(exc))
                                                                            
                                                                             
                                                                                  
                if credential_failure is None or credential_failure.reason.value == "quota_group":
                    self._record_route_failure(target, exc, lease)
                if defer_retry:
                    deferred.append(
                        _ChatAttempt(
                            target,
                            retry_error=exc,
                            lease=self._refresh_route_lease(lease),
                        )
                    )
                emit(self._on_event, "error", target=target.name, reason=str(exc))
                attempts.append((target.name, str(exc)))
                continue
            except Exception as exc:                                          
                non_ctx_failure = True
                defer_retry = attempt.allow_defer and _client._retryable_transport_exception(exc)
                local_saturation = _client._is_local_pool_timeout(exc)
                if local_saturation:
                    self._release_local_saturation(target, lease)
                else:
                    self.metrics.record_failure(target.name, f"{type(exc).__name__}: {exc}")
                    self._record_route_failure(target, exc, lease)
                if defer_retry:
                    deferred.append(
                        _ChatAttempt(
                            target,
                            retry_error=exc,
                            lease=(
                                None
                                if local_saturation
                                else self._refresh_route_lease(lease)
                            ),
                        )
                    )
                emit(self._on_event, "error", target=target.name, reason=f"{type(exc).__name__}")
                attempts.append((target.name, f"{type(exc).__name__}: {exc}"))
                continue

            has_tool_calls = bool(reply.message and reply.message.get("tool_calls"))
            if not reply.text and not has_tool_calls:
                non_ctx_failure = True
                self.metrics.record_failure(target.name, "empty completion")
                self._record_route_empty(target, lease)
                emit(self._on_event, "error", target=target.name, reason="empty completion")
                attempts.append((target.name, "empty completion"))
                continue

            latency_ms = max(0.0, (self._clock() - started) * 1000.0)
            self.metrics.record_success(target.name, latency_ms)
            self._record_route_success(target, latency_ms, lease)
            emit(
                self._on_event,
                "success",
                target=target.name,
                latency_ms=round(latency_ms, 1),
                attempts=len(attempts) + 1,
            )
            self.quota.record(target.provider.id, target.model)
            reply.attempts = len(attempts) + 1
            self._bump_stats(
                requests=1,
                prompt_tokens=reply.prompt_tokens or 0,
                completion_tokens=reply.completion_tokens or 0,
            )
            if self._cache is not None and cache_key is not None:
                self._cache.put(
                    cache_key,
                    {
                        "text": reply.text,
                        "provider_id": reply.provider_id,
                        "model": reply.model,
                        "prompt_tokens": reply.prompt_tokens,
                        "completion_tokens": reply.completion_tokens,
                        "message": reply.message,
                    },
                )
                emit(self._on_event, "cache_store", key=cache_key, target=target.name)
            return reply

        emit(self._on_event, "exhausted", attempts=len(attempts))
        if ctx_overflow and not non_ctx_failure:
            raise ContextWindowExceeded(attempts, est_tokens=est_tokens)
        if client_error is not None:
            raise AllProvidersExhausted(
                attempts, client_status=client_error.status, client_message=str(client_error)
            )
        raise AllProvidersExhausted(attempts)

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        providers: Iterable[str] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 90.0,
        protocol: str | None = None,
        routing: str | None = None,
        task: str | None = None,
    ):
                                                            

                                                                              
                                                                               
                                                                      
                                                                          
                                                                     
           
        if not self.providers:
            raise NoProvidersConfigured("no provider has an API key set")
        model_routing = virtual_routing(model, routing)
        eff = normalize_routing_mode(model_routing or routing, self.routing)
        difficulty = (
            prompt_difficulty(messages, max_tokens)
            if eff in ("quality", "adaptive")
            else None
        )
        if eff in ("quality", "adaptive"):
            resolved_task = resolve_task(messages, task)
        else:
            validate_task(task)
            resolved_task = TASK_GENERAL
        provider_list = list(providers) if providers else None
        candidates = self._all_targets(include=provider_list, model=model)
        candidates = self._feature_targets(
            candidates,
            required_features(messages, stream=True, protocol=protocol),
            exact_pin=model is not None and provider_list is not None and len(provider_list) == 1,
            model=model,
        )
        targets = self._order(
            candidates,
            difficulty=difficulty,
            routing=eff,
            task=resolved_task,
        )
        targets = [t for t in targets if t.provider.adapter != "gemini"]
        if not targets:
            raise NoProvidersConfigured("no streamable (provider, model) matched the filters")

        now = self._clock()
        deadline = now + max(0.0, timeout)
        states = [
            (
                t,
                self._cooled(t.provider.id, now)
                or self._account_backed_off(t.provider.id, now),
            )
            for t in targets
        ]
        sequence = [t for t, c in states if not c] + [t for t, c in states if c]
        attempts: list[tuple[str, str]] = []
        unavailable_providers: set[str] = set()
        credential_exclusions: dict[str, set[str]] = {}
        client_error: ProviderHTTPError | None = None
        est_tokens = estimate_input_tokens(messages)
        needed = est_tokens + max_tokens
        ctx_overflow = False
        non_ctx_failure = False
        for target in sequence:
            if target.provider.id in unavailable_providers:
                attempts.append((target.name, "skipped (provider quota unavailable this request)"))
                continue
            selected_credential: CredentialSelection | None = None
            if self.credential_manager is not None:
                selected = self.credential_manager.reserve(
                    target.provider.id,
                    target.model,
                    CredentialOperation.CHAT,
                    excluded_ids=credential_exclusions.get(target.provider.id),
                    deadline=deadline,
                )
                if isinstance(selected, CredentialUnavailable):
                    attempts.append((target.name, f"skipped ({selected.reason.value})"))
                    non_ctx_failure = True
                    continue
                selected_credential = selected
                api_key = selected.secret
            else:
                api_key = target.provider.api_key(self.env)
            if api_key is None and not target.provider.keyless:
                non_ctx_failure = True
                attempts.append((target.name, "missing api key"))
                continue
            cap = self._effective_context(target)
            if cap is not None and needed > cap:
                attempts.append(
                    (target.name, f"skipped (context ~{cap} < needed ~{needed} tokens)")
                )
                emit(self._on_event, "context_skip", target=target.name, context=cap, needed=needed)
                ctx_overflow = True
                continue
            started = self._clock()
            remaining = deadline - started
            if remaining <= 0:
                attempts.append((target.name, "skipped (overall request timeout exhausted)"))
                break
            lease = self._acquire_route(target)
            if lease is None:
                non_ctx_failure = True
                attempts.append((target.name, "skipped (persistent circuit open)"))
                emit(self._on_event, "circuit_skip", target=target.name, stream=True)
                continue
            emit(self._on_event, "attempt", target=target.name, stream=True)
            stream_usage: dict[str, int] = {}
            gen = _client.stream_call(
                target.provider,
                target.model,
                messages,
                api_key=api_key,
                env=self.env,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=remaining,
                stream_post=self._stream_post,
                usage_callback=stream_usage.update,
            )
            try:
                first = next(gen)                                      
            except StopIteration:
                non_ctx_failure = True
                self.metrics.record_failure(target.name, "empty stream")
                self._record_route_empty(target, lease)
                emit(self._on_event, "error", target=target.name, reason="empty stream")
                attempts.append((target.name, "empty stream"))
                continue
            except ProviderHTTPError as exc:
                is_ctx, limit = context_limit_from_error(exc.status, str(exc))
                if is_ctx:
                    self._record_route_failure(target, exc, lease)
                    ctx_overflow = True
                    if limit is not None:
                        self._learn_context_limit(target.name, limit)
                    emit(self._on_event, "error", target=target.name, reason=str(exc))
                    attempts.append(
                        (target.name, f"context window exceeded (limit ~{limit or '?'})")
                    )
                    continue
                if exc.status == 429:
                    self._mark_cooldown(target.provider.id, self._clock())
                    unavailable_providers.add(target.provider.id)
                    emit(self._on_event, "cooldown", target=target.name, status=429)
                if selected_credential is not None:
                    failure = classify_credential_failure(
                        exc.status,
                        retry_after=exc.retry_after,
                        credential_specific=exc.status in {401, 403},
                        cooldown_seconds=self.cooldown_seconds,
                    )
                    if failure is not None and self.credential_manager is not None:
                        self.credential_manager.record_failure(selected_credential, failure)
                        credential_exclusions.setdefault(target.provider.id, set()).add(
                            selected_credential.credential_id
                        )
                account_exhausted = _is_account_quota_exhaustion(exc, target.provider.id)
                if account_exhausted:
                    self._mark_account_backoff(target.provider.id, self._clock())
                    unavailable_providers.add(target.provider.id)
                                                                                    
                                                                                 
                non_ctx_failure = True
                if not exc.retryable and not account_exhausted and client_error is None:
                    client_error = exc
                if _is_health_failure(exc):
                    self.metrics.record_failure(target.name, str(exc))
                self._record_route_failure(target, exc, lease)
                emit(self._on_event, "error", target=target.name, reason=str(exc))
                attempts.append((target.name, str(exc)))
                continue
            except Exception as exc:                
                non_ctx_failure = True
                self.metrics.record_failure(target.name, f"{type(exc).__name__}: {exc}")
                self._record_route_failure(target, exc, lease)
                emit(self._on_event, "error", target=target.name, reason=f"{type(exc).__name__}")
                attempts.append((target.name, f"{type(exc).__name__}: {exc}"))
                continue

                                                                               
            latency_ms = max(0.0, (self._clock() - started) * 1000.0)
            self.metrics.record_success(target.name, latency_ms)
            emit(
                self._on_event,
                "success",
                target=target.name,
                latency_ms=round(latency_ms, 1),
                stream=True,
            )
            self.quota.record(target.provider.id, target.model)
            self._bump_stats(requests=1)
            yield {
                "provider": target.provider.id,
                "model": target.model,
                "attempts": len(attempts) + 1,
            }
                                                                                       
                                                                                        
                                                                                           
                                                                                    
                                                                            
            streamed: list[str] = [first] if isinstance(first, str) else []
            drained = False
            try:
                yield first
                for chunk in gen:
                    if isinstance(chunk, str):
                        streamed.append(chunk)
                    yield chunk
            except Exception as exc:
                self.metrics.record_failure(
                    target.name,
                    f"{type(exc).__name__}: {exc}",
                )
                self._record_route_failure(target, exc, lease)
                emit(
                    self._on_event,
                    "error",
                    target=target.name,
                    reason=f"mid-stream {type(exc).__name__}",
                )
                raise
            else:
                drained = True
                self._record_route_success(target, latency_ms, lease)
            finally:
                                                                                           
                                                                                          
                                                                                         
                                                                                        
                                                           
                closer = getattr(gen, "close", None)
                if callable(closer):
                    closer()
                if drained:
                    self._bump_stats(
                        prompt_tokens=max(
                            0, int(stream_usage.get("prompt_tokens", est_tokens))
                        ),
                        completion_tokens=max(
                            0,
                            int(
                                stream_usage.get(
                                    "completion_tokens", sum(len(s) for s in streamed) // 4
                                )
                            ),
                        ),
                    )
            return

        emit(self._on_event, "exhausted", attempts=len(attempts))
        if ctx_overflow and not non_ctx_failure:
            raise ContextWindowExceeded(attempts, est_tokens=est_tokens)
        if client_error is not None:
            raise AllProvidersExhausted(
                attempts, client_status=client_error.status, client_message=str(client_error)
            )
        raise AllProvidersExhausted(attempts)
