"""Minimal model validation — no retry loops, short timeouts, JSON report."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import httpx

from sparrow import client as _client
from sparrow.config import configured_providers, effective_env, load_catalog
from sparrow.errors import SparrowError

TIMEOUT = 15.0
TEST_MSG = [{"role": "user", "content": "Reply with the single word: ok"}]


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        env[key] = value
    return env


def get_api_key(provider_obj, base_env: dict[str, str]) -> str:
    """Return the first available API key for a provider."""
    if provider_obj.keyless:
        return ""
    if not provider_obj.key_env:
        return ""
    # Try numbered keys first
    for i in range(1, 20):
        k = f"{provider_obj.key_env}_{i}"
        if base_env.get(k):
            return base_env[k]
    # Then try the base key
    if base_env.get(provider_obj.key_env):
        return base_env[provider_obj.key_env]
    return ""


def test_model(provider, model_name, api_key, base_env):
    """Try a single call, return result dict."""
    t0 = time.monotonic()
    try:
        reply = _client.call(
            provider,
            model_name,
            TEST_MSG,
            api_key=api_key,
            env=base_env,
            max_tokens=8,
            temperature=0.0,
            timeout=TIMEOUT,
        )
        elapsed = round(time.monotonic() - t0, 2)
        text = reply.text.strip() if reply.text else ""
        status = 200
        classification = "SUCCESS" if text else "EMPTY_SUCCESS"
    except _client.ProviderHTTPError as exc:
        elapsed = round(time.monotonic() - t0, 2)
        status = exc.status
        if status == 429:
            classification = "RATE_LIMIT"
        elif status in (401, 403):
            classification = "AUTH"
        elif status == 404:
            classification = "NOT_FOUND"
        elif status >= 500:
            classification = "SERVER_ERROR"
        else:
            classification = "CLIENT_ERROR"
        text = ""
    except (httpx.HTTPError, OSError, TimeoutError):
        elapsed = round(time.monotonic() - t0, 2)
        status = None
        classification = "TRANSPORT"
        text = ""
    except SparrowError:
        elapsed = round(time.monotonic() - t0, 2)
        status = None
        classification = "TRANSPORT"
        text = ""
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 2)
        status = None
        classification = f"ERROR:{type(exc).__name__}"
        text = ""

    return {
        "provider": provider.id,
        "model": model_name,
        "status": status,
        "classification": classification,
        "elapsed": elapsed,
        "text_preview": text[:60] if text else "",
    }


def main():
    dotenv = load_dotenv(Path(__file__).parents[1] / ".env")
    base_env = dict(dotenv)
    base_env.update(os.environ)
    base_env = effective_env(base_env)

    catalog = load_catalog()
    configured = {p.id for p in configured_providers(catalog, base_env)}

    # Skip sparrow virtual models
    results = []
    total = sum(
        1 for p in catalog if p.id in configured
        for m in p.models if m.enabled and not p.id.startswith("sparrow")
    )

    print(f"Testing {total} models across {len(configured)} configured providers...\n")

    count = 0
    for provider in catalog:
        if provider.id not in configured or provider.id.startswith("sparrow"):
            continue
        api_key = get_api_key(provider, base_env)
        for model_obj in provider.models:
            if not model_obj.enabled:
                continue
            count += 1
            r = test_model(provider, model_obj.name, api_key, base_env)
            results.append(r)
            icon = "OK" if r["classification"] == "SUCCESS" else "XX" if r["classification"] in ("AUTH", "NOT_FOUND", "CLIENT_ERROR") else "!!" if r["classification"] in ("RATE_LIMIT", "SERVER_ERROR", "TRANSPORT") else "??"
            preview = r["text_preview"][:30] if r["text_preview"] else r["classification"]
            print(f"  [{count:3d}/{total}] {icon} {provider.id}/{model_obj.name} -> {r['classification']} ({r['elapsed']}s) {preview}")

    # Summary
    counts = {}
    for r in results:
        c = r["classification"]
        counts[c] = counts.get(c, 0) + 1

    print(f"\n{'='*60}")
    print(f"SUMMARY: {len(results)} models tested")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"{'='*60}")

    # Save JSON
    report_path = Path(__file__).parents[1] / "validation_report.json"
    report_path.write_text(json.dumps({"summary": counts, "results": results}, indent=2, sort_keys=True))
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
