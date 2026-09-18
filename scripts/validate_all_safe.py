#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///

# --- How to run ---
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. From the repository root, run:
#      uv run scripts/validate_all_safe.py
# 3. The live run writes ./validation_all_report.json and removes temporary state on exit.
# ------------------

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, TypeAlias, TypedDict

import httpx

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sparrow.client import HTTPResult, default_post  # noqa: E402
from sparrow.config import (  # noqa: E402
    configured_providers,
    effective_env,
    load_catalog,
    load_config_file,
)
from sparrow.credential_config import ParseError, parse_credentials  # noqa: E402
from sparrow.credential_schema import CredentialStoreError  # noqa: E402
from sparrow.credentials import CredentialSlot  # noqa: E402
from sparrow.errors import (  # noqa: E402
    AllProvidersExhausted,
    NoProvidersConfigured,
    ProviderHTTPError,
    SparrowError,
)
from sparrow.models import Model, Provider  # noqa: E402
from sparrow.quota import QuotaStore  # noqa: E402
from sparrow.router import Pool  # noqa: E402

DOTENV_PATH: Final[Path] = ROOT / ".env"
REPORT_PATH: Final[Path] = ROOT / "validation_all_report.json"
REQUEST_PATH: Final[str] = "/chat/completions"
REQUEST_TIMEOUT: Final[float] = 15.0
MAX_TOKENS: Final[int] = 8
TEST_MESSAGES: Final[list[dict[str, str]]] = [
    {"role": "user", "content": "Reply with the single word: ok"}
]

SourceValues: TypeAlias = dict[str, tuple[tuple[str, str], ...]]
TomlValue: TypeAlias = str | int | float | bool | list["TomlValue"] | dict[str, "TomlValue"]
JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class CredentialEvidence(TypedDict):
    credential_id: str | None
    env_var: str | None
    configured: bool
    present: bool
    wire_credential_matches_selected_env: bool


class ModelResult(TypedDict):
    provider: str
    model: str
    path: str
    status: str
    classification: str
    attempt_number: int
    transport_attempts: int
    attempted: bool
    timestamp: str
    http_status: int | None
    elapsed_seconds: float
    skip_reason: str | None
    credential: CredentialEvidence
    error_class: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class CatalogItem:
    provider: Provider
    model: Model
    ordinal: int


@dataclass(frozen=True, slots=True)
class EnvironmentSources:
    dotenv: Mapping[str, str]
    process: Mapping[str, str]
    config: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class RunSetup:
    env: dict[str, str]
    catalog: tuple[Provider, ...]
    slots: tuple[CredentialSlot, ...]
    configured: frozenset[str]
    disabled: frozenset[str]
    sources: EnvironmentSources
    state_root: Path


@dataclass(frozen=True, slots=True)
class AuthObservation:
    status: str = "not_called"
    env_var: str | None = None


@dataclass(slots=True)
class RequestAudit:
    """Mutable per-model accumulator updated by Pool events and the post hook."""

    values: SourceValues = field(default_factory=dict)
    keyless: bool = False
    pool_attempts: int = 0
    post_calls: int = 0
    transport_status: int | None = None
    auth: AuthObservation = field(default_factory=AuthObservation)

    def begin(self, *, keyless: bool, values: SourceValues) -> None:
        self.values = values
        self.keyless = keyless
        self.pool_attempts = 0
        self.post_calls = 0
        self.transport_status = None
        self.auth = AuthObservation()

    def record_event(self, payload: JsonObject) -> None:
        if payload.get("event") == "attempt":
            self.pool_attempts += 1

    def __call__(self, url: str, headers: dict[str, str], body: JsonObject, timeout: float) -> HTTPResult:
        self.post_calls += 1
        if self.post_calls == 1:
            self.auth = auth_status(headers, self.keyless, self.values)
        result = default_post(url, headers, body, timeout, max_attempts=1)
        self.transport_status = result.status
        return result

    def clear_secret_index(self) -> None:
        self.values.clear()


@dataclass(frozen=True, slots=True)
class ModelContext:
    pool: Pool | None
    provider: Provider
    model: Model
    configured: bool
    key_available: bool
    timeout: float
    audit: RequestAudit
    values: SourceValues
    slots: tuple[CredentialSlot, ...]
    env: dict[str, str]


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    classification: str
    status: int | None = None
    error_class: str | None = None
    error_message: str | None = None
    skip_reason: str | None = None


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        name, separator, value = line.partition("=")
        if not separator or not name.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        values[name.strip()] = value
    return values


def key_env_names(provider: Provider, env: Mapping[str, str]) -> tuple[str, ...]:
    if not provider.key_env:
        return ()
    base = provider.key_env
    numbered = sorted(
        (int(name[len(base) + 1 :]), name)
        for name in env
        if name.startswith(f"{base}_") and name[len(base) + 1 :].isdigit()
    )
    return (base, *(name for _, name in numbered))


def source_values(names: tuple[str, ...], sources: EnvironmentSources) -> SourceValues:
    found: dict[str, list[tuple[str, str]]] = {}
    for source, values in (
        ("dotenv", sources.dotenv),
        ("process", sources.process),
        ("config", sources.config),
    ):
        for name in names:
            value = values.get(name, "").strip()
            if value:
                found.setdefault(value, []).append((source, name))
    return {value: tuple(matches) for value, matches in found.items()}


def config_key_values(config: Mapping[str, TomlValue]) -> dict[str, str]:
    values = config.get("keys")
    if not isinstance(values, dict):
        return {}
    return {str(name): str(value) for name, value in values.items() if value}


def disabled_provider_ids(config: Mapping[str, TomlValue]) -> frozenset[str]:
    specs = config.get("providers")
    if isinstance(specs, dict):
        return frozenset(
            str(provider_id)
            for provider_id, spec in specs.items()
            if isinstance(spec, dict) and spec.get("enabled") is False
        )
    if isinstance(specs, list):
        return frozenset(
            str(spec["id"])
            for spec in specs
            if isinstance(spec, dict)
            and isinstance(spec.get("id"), str)
            and spec.get("enabled") is False
        )
    return frozenset()


def write_credential_config(path: Path, catalog: tuple[Provider, ...], env: Mapping[str, str]) -> bool:
    rows: list[str] = []
    for provider in catalog:
        if provider.auth == "none":
            continue
        for name in key_env_names(provider, env):
            if not env.get(name, "").strip():
                continue
            rows.append(
                "\n".join(
                    (
                        "[[credentials]]",
                        f"id = {json.dumps(f'slot-{provider.id}-{name}')} ",
                        f"provider = {json.dumps(provider.id)}",
                        f"env_var = {json.dumps(name)}",
                        f"quota_group = {json.dumps(provider.id)}",
                        "enabled = true",
                    )
                ).rstrip()
            )
    if not rows:
        return False
    _ = path.write_text("\n\n".join(rows) + "\n", encoding="utf-8")
    return True


@contextmanager
def isolated_state(path: Path) -> Generator[None, None, None]:
    path.mkdir(parents=True, exist_ok=True)
    values = {
        "SPARROW_CACHE_TTL": "0",
        "SPARROW_QUOTA_PATH": str(path / "quota.json"),
        "SPARROW_CREDENTIAL_STATE_FILE": str(path / "credentials.db"),
        "SPARROW_HEALTH_FILE": str(path / "health.json"),
        "SPARROW_CONFORMANCE_FILE": str(path / "conformance.json"),
        "SPARROW_STATS_PATH": str(path / "stats.json"),
        "SPARROW_QUOTA_FLUSH_EVERY": "1",
        "SPARROW_STATS_FLUSH_EVERY": "1",
        "SPARROW_ROUTE_HEALTH_FLUSH_EVERY": "1",
    }
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                _ = os.environ.pop(name, None)
            else:
                os.environ[name] = value


def auth_status(headers: Mapping[str, str], keyless: bool, values: SourceValues) -> AuthObservation:
    token: str | None = None
    for name, value in headers.items():
        lowered = name.lower()
        if lowered == "x-goog-api-key":
            token = value.strip() or None
            break
        if lowered == "authorization":
            prefix, separator, candidate = value.partition(" ")
            if separator and prefix.lower() == "bearer":
                token = candidate.strip() or None
                break
    if token is None:
        return AuthObservation("keyless_provider" if keyless else "missing_auth")
    matches = values.get(token)
    if not matches:
        return AuthObservation("unmatched_env")
    _, name = min(matches, key=lambda match: (match[0] != "process", match[0], match[1]))
    return AuthObservation("matched_env", name)


def provider_key_available(
    provider: Provider, slots: tuple[CredentialSlot, ...], env: Mapping[str, str]
) -> bool:
    provider_slots = tuple(slot for slot in slots if slot.provider == provider.id)
    if provider_slots:
        return any(slot.enabled and bool(env.get(slot.env_var, "").strip()) for slot in provider_slots)
    value = provider.api_key(dict(env))
    return bool(value and value.strip())


def credential_evidence(context: ModelContext) -> CredentialEvidence:
    provider_slots = tuple(slot for slot in context.slots if slot.provider == context.provider.id)
    present = provider_key_available(context.provider, context.slots, context.env)
    auth = context.audit.auth
    matched_slot = next(
        (slot for slot in provider_slots if slot.env_var == auth.env_var),
        None,
    )
    wire_has_credential = auth.status == "matched_env"
    optional = context.provider.api_key(context.env)
    optional_present = bool(optional and optional.strip())
    if context.provider.keyless and not optional_present:
        wire_matches = auth.status == "keyless_provider" or context.audit.post_calls == 0
    elif provider_slots:
        wire_matches = wire_has_credential and matched_slot is not None
    else:
        wire_matches = wire_has_credential and auth.env_var == context.provider.key_env
    return {
        "credential_id": matched_slot.id if matched_slot is not None else None,
        "env_var": auth.env_var if wire_has_credential else None,
        "configured": context.configured,
        "present": present,
        "wire_credential_matches_selected_env": wire_matches,
    }


def http_classification(status: int | None) -> str:
    if status in {401, 403}:
        return "AUTH_FAILURE"
    if status == 429:
        return "RATE_LIMIT"
    if status in {408, 504}:
        return "TIMEOUT"
    if status in {404, 410}:
        return "NOT_FOUND"
    if status is not None and status >= 500:
        return "SERVER_FAILURE"
    return "OTHER_FAILURE"


def result_for(context: ModelContext, outcome: AttemptOutcome, started: float) -> ModelResult:
    attempted = context.audit.post_calls > 0
    return {
        "provider": context.provider.id,
        "model": context.model.name,
        "path": REQUEST_PATH,
        "status": "ATTEMPTED" if attempted else "SKIPPED",
        "classification": outcome.classification,
        "attempt_number": max(context.audit.pool_attempts, context.audit.post_calls),
        "transport_attempts": context.audit.post_calls,
        "attempted": attempted,
        "timestamp": timestamp(),
        "http_status": (
            context.audit.transport_status
            if context.audit.transport_status is not None
            else outcome.status
        ),
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
        "skip_reason": None if attempted else (outcome.skip_reason or "request was not dispatched"),
        "credential": credential_evidence(context),
        "error_class": outcome.error_class,
        "error_message": outcome.error_message,
    }


def skipped(context: ModelContext, classification: str, reason: str) -> ModelResult:
    return result_for(context, AttemptOutcome(classification, skip_reason=reason), time.monotonic())


def run_model(context: ModelContext) -> ModelResult:
    if not context.model.enabled:
        return skipped(context, "SKIPPED_MODEL_DISABLED", "catalog model is disabled")
    if context.model.requires_key and not context.key_available:
        return skipped(context, "SKIPPED_MODEL_REQUIRES_KEY", "model requires an unavailable provider key")
    if not context.configured:
        return skipped(context, "SKIPPED_PROVIDER_UNCONFIGURED", "provider has no available configuration")
    if context.pool is None:
        return skipped(context, "SKIPPED_PROVIDER_UNAVAILABLE", "provider was not available in the normal Pool")

    context.audit.begin(keyless=context.provider.keyless, values=context.values)
    started = time.monotonic()
    try:
        reply = context.pool.chat(
            TEST_MESSAGES,
            model=context.model.name,
            providers=(context.provider.id,),
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            timeout=context.timeout,
        )
    except ProviderHTTPError as exc:
        attempted = context.audit.post_calls > 0
        return result_for(
            context,
            AttemptOutcome(
                http_classification(exc.status) if attempted else "SKIPPED_NOT_DISPATCHED",
                status=exc.status,
                error_class=type(exc).__name__,
                error_message="provider status recorded without response data",
                skip_reason=None if attempted else "provider rejected the request before transport",
            ),
            started,
        )
    except AllProvidersExhausted as exc:
        attempted = context.audit.post_calls > 0
        status = exc.client_status
        return result_for(
            context,
            AttemptOutcome(
                http_classification(status) if attempted and status is not None else "POOL_EXHAUSTED",
                status=status,
                error_class=type(exc).__name__,
                error_message="Pool exhaustion recorded without response data",
                skip_reason=None if attempted else "Pool did not dispatch a usable candidate",
            ),
            started,
        )
    except NoProvidersConfigured as exc:
        return result_for(
            context,
            AttemptOutcome(
                "SKIPPED_NOT_DISPATCHED",
                error_class=type(exc).__name__,
                error_message="Pool selection failure recorded without response data",
                skip_reason="no matching provider/model was available in the Pool",
            ),
            started,
        )
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        attempted = context.audit.post_calls > 0
        return result_for(
            context,
            AttemptOutcome(
                "TRANSPORT_FAILURE" if attempted else "SKIPPED_NOT_DISPATCHED",
                error_class=type(exc).__name__,
                error_message="transport failure recorded without response data",
                skip_reason=None if attempted else "transport was not reached",
            ),
            started,
        )
    except SparrowError as exc:
        attempted = context.audit.post_calls > 0
        return result_for(
            context,
            AttemptOutcome(
                "SPARROW_FAILURE" if attempted else "SKIPPED_NOT_DISPATCHED",
                error_class=type(exc).__name__,
                error_message="Sparrow failure recorded without response data",
                skip_reason=None if attempted else "Sparrow rejected the request before transport",
            ),
            started,
        )
    outcome = AttemptOutcome("SUCCESS" if reply.text.strip() else "EMPTY_RESPONSE")
    return result_for(context, outcome, started)


def credential_names(item: CatalogItem, slots: tuple[CredentialSlot, ...], env: Mapping[str, str]) -> tuple[str, ...]:
    names = set(key_env_names(item.provider, env))
    names.update(slot.env_var for slot in slots if slot.provider == item.provider.id)
    return tuple(sorted(names))


def run_item(item: CatalogItem, setup: RunSetup) -> ModelResult:
    names = credential_names(item, setup.slots, setup.env)
    values = source_values(names, setup.sources)
    audit = RequestAudit()
    configured = item.provider.id in setup.configured and item.provider.id not in setup.disabled
    key_available = provider_key_available(item.provider, setup.slots, setup.env)
    context = ModelContext(
        pool=None,
        provider=item.provider,
        model=item.model,
        configured=configured,
        key_available=key_available,
        timeout=REQUEST_TIMEOUT,
        audit=audit,
        values=values,
        slots=setup.slots,
        env=setup.env,
    )
    if not item.model.enabled or (item.model.requires_key and not key_available) or not configured:
        result = run_model(context)
        audit.clear_secret_index()
        return result

    state = setup.state_root / f"model-{item.ordinal:03d}"
    pool_env = {
        **setup.env,
        "SPARROW_CACHE_TTL": "0",
        "SPARROW_HEALTH_FILE": str(state / "health.json"),
        "SPARROW_CONFORMANCE_FILE": str(state / "conformance.json"),
    }
    primary: Pool | None = None
    direct: Pool | None = None
    with isolated_state(state):
        try:
            quota = QuotaStore(state / "quota.json", flush_every=1, flush_interval=1.0)
            primary = Pool.from_default_config(
                env=pool_env,
                quota=quota,
                post=audit,
                on_event=audit.record_event,
            )
            managed = {provider.id for provider in primary.providers}
            pool = primary if item.provider.id in managed else None
            if pool is None and item.provider.keyless and item.provider.id in setup.configured:
                direct = Pool(
                    [item.provider],
                    quota=quota,
                    env=pool_env,
                    post=audit,
                    on_event=audit.record_event,
                )
                pool = direct
            context = ModelContext(
                pool=pool,
                provider=item.provider,
                model=item.model,
                configured=pool is not None,
                key_available=key_available,
                timeout=REQUEST_TIMEOUT,
                audit=audit,
                values=values,
                slots=setup.slots,
                env=pool_env,
            )
            return run_model(context)
        finally:
            if direct is not None:
                direct.flush()
            if primary is not None:
                primary.flush()
            audit.clear_secret_index()


def items(catalog: tuple[Provider, ...]) -> tuple[CatalogItem, ...]:
    result: list[CatalogItem] = []
    ordinal = 1
    for provider in catalog:
        for model in sorted(provider.models, key=lambda value: value.name):
            result.append(CatalogItem(provider, model, ordinal))
            ordinal += 1
    return tuple(result)


def run() -> int:
    dotenv = load_dotenv(DOTENV_PATH)
    process = dict(os.environ)
    source_env = {**dotenv, **process}
    catalog = tuple(sorted(load_catalog(), key=lambda provider: provider.id))
    if not catalog:
        raise ValueError("catalog is empty")
    user_config = load_config_file(source_env)
    runtime_env = effective_env(source_env)
    sources = EnvironmentSources(dotenv, process, config_key_values(user_config))
    with TemporaryDirectory(prefix="sparrow-validation-") as temporary:
        root = Path(temporary)
        generated_path = root / "credentials.toml"
        generated = not ("credentials" in user_config or "providers" in user_config) and write_credential_config(
            generated_path, catalog, runtime_env
        )
        if generated:
            runtime_env = effective_env({**runtime_env, "SPARROW_CONFIG_FILE": str(generated_path)})
        pool_config = load_config_file(runtime_env)
        catalog_list = list(catalog)
        slots = tuple(parse_credentials(pool_config, catalog_list, runtime_env))
        configured = frozenset(provider.id for provider in configured_providers(catalog_list, runtime_env))
        setup = RunSetup(
            env=runtime_env,
            catalog=catalog,
            slots=slots,
            configured=configured,
            disabled=disabled_provider_ids(user_config),
            sources=sources,
            state_root=root / "state",
        )
        model_items = items(catalog)
        results: list[ModelResult] = []
        for index, item in enumerate(model_items, start=1):
            result = run_item(item, setup)
            results.append(result)
            print(f"[{index:3d}/{len(model_items)}] {item.provider.id}/{item.model.name} -> {result['classification']}")

        attempted = [f"{row['provider']}/{row['model']}" for row in results if row["attempted"]]
        skipped_models = [f"{row['provider']}/{row['model']}" for row in results if not row["attempted"]]
        summary = {
            "total_catalog_models": len(results),
            "attempted": len(attempted),
            "skipped": len(skipped_models),
            "successes": sum(row["classification"] == "SUCCESS" for row in results),
            "auth_failures": sum(row["classification"] == "AUTH_FAILURE" for row in results),
            "other_failures": sum(
                row["attempted"] and row["classification"] not in {"SUCCESS", "AUTH_FAILURE"}
                for row in results
            ),
            "credential_match_failures": sum(
                row["attempted"] and not row["credential"]["wire_credential_matches_selected_env"]
                for row in results
            ),
        }
        report = {
            "report_version": 1,
            "generated_at": timestamp(),
            "output_path": str(REPORT_PATH),
            "dotenv_path": ".env",
            "temporary_state_removed_on_exit": True,
            "pool_mode": "Pool.from_default_config plus Pool.chat; keyless fallback uses Pool",
            "request_policy": {
                "serial": True,
                "timeout_seconds": REQUEST_TIMEOUT,
                "transport_attempts": 1,
                "fallback_providers": False,
            },
            "summary": summary,
            "attempted_models": attempted,
            "skipped_models": skipped_models,
            "results": results,
        }
        _ = REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Report saved: {REPORT_PATH}")
    print(f"Summary: {summary}")
    return 0


def main() -> int:
    try:
        return run()
    except (
        ParseError,
        CredentialStoreError,
        OSError,
        UnicodeError,
        ValueError,
        RuntimeError,
        SparrowError,
    ) as exc:
        print(f"validation setup failed ({type(exc).__name__}); no report was written.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
