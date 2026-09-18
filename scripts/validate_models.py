"""Run a bounded, secret-safe validation pass over configured Sparrow models.

The runner loads the repository ``.env`` as input only, uses Sparrow's catalog
and configuration helpers, rotates numbered provider keys, and delegates all
requests to :func:`sparrow.client.call`.  Its stdout is a JSON report that
contains no response or credential contents.
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Final, Literal, TypedDict, assert_never

import httpx

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from sparrow import client as _client
from sparrow.config import configured_providers, effective_env, load_catalog
from sparrow.errors import SparrowError
from sparrow.models import Provider

MAX_ATTEMPTS: Final = 3
MAX_RETRY_DELAY: Final = 60.0
DEFAULT_TIMEOUT: Final = 20.0
BACKOFF_STEP: Final = 1.0

Classification = Literal[
    "SUCCESS",
    "EMPTY_SUCCESS",
    "RATE_LIMIT",
    "AUTH",
    "SERVER_ERROR",
    "NOT_FOUND",
    "CLIENT_ERROR",
    "TRANSPORT",
    "UNKNOWN",
]


class CallResult(TypedDict):
    """Secret-free details from one model's bounded call sequence."""

    status: int | None
    classification: Classification
    has_text: bool
    retry_after: float | None


class ValidationResult(CallResult):
    """Secret-free report row for one provider/model pair."""

    provider: str
    model: str


class Summary(TypedDict):
    """Counts of the classifications present in a validation report."""

    total: int
    success: int
    empty_success: int
    rate_limit: int
    auth: int
    server_error: int
    not_found: int
    client_error: int
    transport: int
    unknown: int


class Report(TypedDict):
    """Machine-readable validation report."""

    summary: Summary
    results: list[ValidationResult]


def load_dotenv(path: Path) -> dict[str, str]:
    """Read simple dotenv assignments without exposing their values."""

    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and (
            (value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")
        ):
            value = value[1:-1]
        env[key] = value
    return env


def multi_key_env(provider: Provider, base_env: dict[str, str]) -> list[str]:
    """Return configured primary and numbered key values in stable order."""

    keys: list[str] = []
    if provider.key_env:
        names = [provider.key_env, *(f"{provider.key_env}_{i}" for i in range(1, 20))]
        keys = [base_env[name] for name in names if base_env.get(name)]
    return list(dict.fromkeys(keys)) or [""]


def _safe_retry_after(value: float | None) -> float | None:
    """Keep only finite, non-negative numeric retry metadata."""

    if value is None or not math.isfinite(value):
        return None
    return max(0.0, value)


def classify(
    status: int | None,
    retry_after: float | None,
    has_text: bool = True,
) -> Classification:
    """Classify a response without retaining response or exception contents."""

    if status == 200:
        return "SUCCESS" if has_text else "EMPTY_SUCCESS"
    if status == 429:
        return "RATE_LIMIT"
    if status in (401, 403):
        return "AUTH"
    if status and status >= 500:
        return "SERVER_ERROR"
    if status == 404:
        return "NOT_FOUND"
    if status and 400 <= status < 500:
        return "CLIENT_ERROR"
    return "UNKNOWN"


def _retry_delay(retry_after: float | None, attempt: int, remaining: float) -> float | None:
    """Return a bounded delay that fits inside the remaining call budget."""

    safe_retry_after = _safe_retry_after(retry_after)
    base = (
        min(safe_retry_after, MAX_RETRY_DELAY)
        if safe_retry_after is not None
        else min(MAX_RETRY_DELAY, BACKOFF_STEP * (attempt + 1))
    )
    if base == 0:
        return 0.0 if remaining > 0 else None
    jitter = random.uniform(0.0, min(0.1, base * 0.1))
    delay = base + jitter
    return delay if delay < remaining else None


def _transport_result() -> CallResult:
    """Return a transport failure without serializing the exception."""

    return {
        "status": None,
        "classification": "TRANSPORT",
        "has_text": False,
        "retry_after": None,
    }


def call_with_retry(
    provider: Provider,
    model: str,
    api_key: str,
    base_env: dict[str, str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_attempts: int = MAX_ATTEMPTS,
) -> CallResult:
    budget = timeout if math.isfinite(timeout) and timeout > 0 else 0.0
    deadline = time.monotonic() + budget
    attempt_limit = max(1, min(max_attempts, MAX_ATTEMPTS))
    last_status: int | None = None
    last_retry_after: float | None = None

    for attempt in range(attempt_limit):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            reply = _client.call(
                provider,
                model,
                [{"role": "user", "content": "Reply with the single word: ok"}],
                api_key=api_key,
                env=base_env,
                max_tokens=8,
                temperature=0.0,
                timeout=remaining,
            )
        except _client.ProviderHTTPError as exc:
            last_status = exc.status
            last_retry_after = _safe_retry_after(exc.retry_after)
            if exc.status == 429:
                delay = _retry_delay(last_retry_after, attempt, deadline - time.monotonic())
                if delay is None:
                    break
                if delay > 0:
                    time.sleep(delay)
                continue
            if exc.status in (401, 403) and attempt + 1 < max_attempts:
                continue
            if exc.status >= 500 and attempt + 1 < max_attempts:
                delay = _retry_delay(last_retry_after, attempt, deadline - time.monotonic())
                if delay is None:
                    break
                if delay > 0:
                    time.sleep(delay)
                continue
            break
        except (httpx.HTTPError, OSError, TimeoutError):
            return _transport_result()
        except SparrowError:
            return _transport_result()

        has_text = bool(reply.text.strip())
        return {
            "status": 200,
            "classification": classify(200, None, has_text=has_text),
            "has_text": has_text,
            "retry_after": None,
        }

    return {
        "status": last_status,
        "classification": classify(last_status, last_retry_after, has_text=False),
        "has_text": False,
        "retry_after": last_retry_after,
    }


def _increment_summary(summary: Summary, classification: Classification) -> None:
    """Increment the one summary bucket matching a result classification."""

    match classification:
        case "SUCCESS":
            summary["success"] += 1
        case "EMPTY_SUCCESS":
            summary["empty_success"] += 1
        case "RATE_LIMIT":
            summary["rate_limit"] += 1
        case "AUTH":
            summary["auth"] += 1
        case "SERVER_ERROR":
            summary["server_error"] += 1
        case "NOT_FOUND":
            summary["not_found"] += 1
        case "CLIENT_ERROR":
            summary["client_error"] += 1
        case "TRANSPORT":
            summary["transport"] += 1
        case "UNKNOWN":
            summary["unknown"] += 1
        case unreachable:
            assert_never(unreachable)


def run_validation() -> Report:
    """Validate every enabled model on every configured catalog provider."""

    dotenv = load_dotenv(Path(__file__).parents[1] / ".env")
    source_env = dict(dotenv)
    source_env.update(os.environ)
    base_env = effective_env(source_env)
    catalog = load_catalog()
    configured = {provider.id for provider in configured_providers(catalog, base_env)}
    results: list[ValidationResult] = []
    summary: Summary = {
        "total": 0,
        "success": 0,
        "empty_success": 0,
        "rate_limit": 0,
        "auth": 0,
        "server_error": 0,
        "not_found": 0,
        "client_error": 0,
        "transport": 0,
        "unknown": 0,
    }
    for provider in catalog:
        if provider.id not in configured:
            continue
        for model_obj in provider.models:
            if not model_obj.enabled:
                continue
            model_name = model_obj.name
            api_keys = (
                [""]
                if provider.keyless
                else [key for key in multi_key_env(provider, base_env) if key]
            )
            if not api_keys:
                continue
            result: ValidationResult = {
                "provider": provider.id,
                "model": model_name,
                "status": None,
                "classification": "UNKNOWN",
                "has_text": False,
                "retry_after": None,
            }
            for key in api_keys:
                attempt_result = call_with_retry(provider, model_name, key, base_env)
                result["status"] = attempt_result["status"]
                result["classification"] = attempt_result["classification"]
                result["has_text"] = attempt_result["has_text"]
                result["retry_after"] = attempt_result["retry_after"]
                if result["status"] == 200:
                    break
            results.append(result)
            summary["total"] += 1
            _increment_summary(summary, result["classification"])
    return {"summary": summary, "results": results}


def main() -> None:
    """Print the validation report as JSON without any secret-bearing fields."""

    print(json.dumps(run_validation(), sort_keys=True))


if __name__ == "__main__":
    main()
