from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from .credential_config import _provider_credential_rows


def _read_config(path: Path) -> tuple[dict[str, Any], str]:
    try:
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        return tomllib.loads(content), content
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("configuration is malformed; refusing to modify it") from exc


def _insert_key_lines(content: str, values: dict[str, str]) -> str:
    lines = content.splitlines(keepends=True)
    keys_index = next((i for i, line in enumerate(lines) if line.strip() == "[keys]"), None)
    key_lines = "".join(f"{name} = {json.dumps(value)}\n" for name, value in values.items())
    if keys_index is None:
        return content.rstrip() + f"\n\n[keys]\n{key_lines}"
    insert_at = len(lines)
    for i in range(keys_index + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            insert_at = i
            break
    lines[insert_at:insert_at] = [key_lines]
    return "".join(lines)


def _atomic_write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def set_config_keys(path: Path, values: dict[str, str]) -> Path:
    raw, content = _read_config(path)
    existing = raw.get("keys", {})
    if not isinstance(existing, dict):
        raise ValueError("configuration keys table is malformed")
    additions: dict[str, str] = {}
    for name, value in values.items():
        if name in existing and existing[name] != value:
            raise ValueError(f"configuration key {name} already has a different value")
        if name not in existing:
            additions[name] = value
    if not additions:
        return path
    return _atomic_write(path, _insert_key_lines(content, additions))


def register_credential(path: Path, *, provider: str, credential_id: str, env_var: str,
                        quota_group: str, secret: str, enabled: bool = True) -> Path:
    raw, content = _read_config(path)
    rows = raw.get("credentials", [])
    if not isinstance(rows, list) or any(
        isinstance(row, dict) and row.get("provider") == provider and row.get("id") == credential_id
        for row in rows
    ):
        raise ValueError(f"credential {provider}/{credential_id} already exists")
    existing_keys = raw.get("keys", {})
    if not isinstance(existing_keys, dict):
        raise ValueError("configuration keys table is malformed")
    if env_var in existing_keys and existing_keys[env_var] != secret:
        raise ValueError(f"configuration key {env_var} already has a different value")
    if env_var not in existing_keys:
        content = _insert_key_lines(content, {env_var: secret})
    content += (
        "\n[[credentials]]\n"
        f"provider = {json.dumps(provider)}\n"
        f"id = {json.dumps(credential_id)}\n"
        f"env_var = {json.dumps(env_var)}\n"
        f"quota_group = {json.dumps(quota_group)}\n"
        f"enabled = {str(enabled).lower()}\n"
    )
    return _atomic_write(path, content)


def remove_credential(path: Path, *, provider: str | None, credential_id: str) -> tuple[str, str]:
    """Remove one explicit credential and its unshared config key."""
    raw, content = _read_config(path)
    rows = raw.get("credentials", [])
    if not isinstance(rows, list):
        raise ValueError("configuration credentials must be an array")
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("id") == credential_id
        and (provider is None or row.get("provider") == provider)
    ]
    if not matches:
        scope = f"{provider}/{credential_id}" if provider else credential_id
        raise ValueError(f"credential {scope} not found")
    if len(matches) > 1:
        raise ValueError(f"credential id {credential_id} is ambiguous; specify --provider")
    match = matches[0]
    match_provider = str(match["provider"])
    env_var = str(match["env_var"])
    blocks = content.split("\n[[credentials]]")
    kept = [blocks[0]]
    for block in blocks[1:]:
        candidate = "[[credentials]]" + block
        parsed = tomllib.loads(candidate)
        row = parsed["credentials"][0]
        if row.get("provider") == match_provider and row.get("id") == credential_id:
            continue
        kept.append(block)
    updated = "\n[[credentials]]".join(kept)
    remaining_refs = [
        row.get("env_var")
        for row in rows
        if isinstance(row, dict)
        and not (row.get("provider") == match_provider and row.get("id") == credential_id)
    ]
    if env_var not in remaining_refs:
        updated = _remove_key_entry(updated, env_var)
    _atomic_write(path, updated)
    return match_provider, env_var


def _remove_key_entry(content: str, name: str) -> str:
    """Remove one key assignment from the TOML ``[keys]`` table."""
    lines = content.splitlines(keepends=True)
    in_keys = False
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_keys = stripped == "[keys]"
        if in_keys and stripped.startswith(f"{name} ="):
            continue
        kept.append(line)
    return "".join(kept)


def render_usage(store: Any, *, provider: str | None = None, day: str | None = None,
                 as_json: bool = False, config_path: Path | None = None) -> str:
    rows = store.usage_report(provider=provider, day=day)
    groups: dict[tuple[str, str], str] = {}
    if config_path is not None and config_path.exists():
        raw, _ = _read_config(config_path)
        config_rows = list(raw.get("credentials", []))
        legacy_providers = {item.get("provider") for item in config_rows if isinstance(item, dict)}
        config_rows.extend(
            item for item in _provider_credential_rows(raw)
            if item["provider"] not in legacy_providers
        )
        for item in config_rows:
            if isinstance(item, dict):
                groups[(str(item.get("provider", "")), str(item.get("id", "")))] = str(
                    item.get("quota_group", "shared")
                )
    for row in rows:
        row["quota_group"] = groups.get(
            (str(row["provider_id"]), str(row["credential_id"])), "shared"
        )
    if as_json:
        return json.dumps(rows, sort_keys=True)
    return "\n".join(
        f"{row['provider_id']}/{row['credential_id']} {row['quota_group']} {row['operation']} "
        f"reserved={row['reserved']} succeeded={row['succeeded']} "
        f"prompt_tokens={row['prompt_tokens']} completion_tokens={row['completion_tokens']} "
        f"usage_missing={row['usage_missing']}"
        for row in rows
    ) or "No credential usage recorded."


def render_status(path: Path, store: Any, *, env: dict[str, str] | None = None) -> str:
    raw, _ = _read_config(path)
    keys = raw.get("keys", {})
    if not isinstance(keys, dict):
        raise ValueError("configuration keys must be a table")
    effective = {str(name): str(value) for name, value in keys.items()}
    effective.update(env or os.environ)
    seen: dict[tuple[str, str], str] = {}
    output: list[str] = []
    rows = list(raw.get("credentials", []))
    legacy_providers = {item.get("provider") for item in rows if isinstance(item, dict)}
    rows.extend(
        item for item in _provider_credential_rows(raw)
        if item["provider"] not in legacy_providers
    )
    for item in rows:
        if not isinstance(item, dict):
            continue
        provider = str(item["provider"])
        credential_id = str(item["id"])
        env_var = str(item["env_var"])
        group = str(item.get("quota_group", "shared"))
        secret = effective.get(env_var, "")
        status = "disabled" if item.get("enabled") is False else "ready" if secret else "missing"
        identity = (provider, secret)
        if status == "ready" and secret and identity in seen:
            status = f"duplicate-alias:{seen[identity]}"
        elif status == "ready" and secret:
            seen[identity] = credential_id
            if store.get_cooldown(provider, "key", credential_id) or store.get_cooldown(
                provider, "quota_group", group
            ):
                status = "cooldown"
        output.append(f"{provider}/{credential_id} env={env_var} group={group} status={status}")
    return "\n".join(output) or "No explicit credentials configured."
