"""Parse explicit credential records and resolve availability before filtering.

This module handles the [[credentials]] table from config.toml, validating fields,
resolving environment variables, deduplicating secrets, and synthesizing legacy
credentials from provider.key_env when no explicit rows exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .credentials import CredentialSlot
from .models import Provider

# ID validation: 1-64 ASCII letters/digits/underscore/hyphen, starting with letter or digit
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")

# env_var validation: [A-Za-z_][A-Za-z0-9_]*
_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class ParseError(Exception):
    """Raised when credential configuration is invalid."""

    message: str
    provider_id: str | None = None
    credential_id: str | None = None

    def __str__(self) -> str:
        parts = []
        if self.provider_id:
            parts.append(f"provider={self.provider_id!r}")
        if self.credential_id:
            parts.append(f"credential_id={self.credential_id!r}")
        prefix = f"[{', '.join(parts)}] " if parts else ""
        return f"{prefix}{self.message}"


def _validate_id(value: str, provider_id: str, credential_id: str | None) -> None:
    """Validate credential ID format."""
    if not _ID_RE.fullmatch(value):
        raise ParseError(
            f"invalid credential id {value!r}: must be 1-64 ASCII letters, digits, "
            "underscore, or hyphen, starting with a letter or digit",
            provider_id=provider_id,
            credential_id=credential_id,
        )


def _validate_env_var(value: str, provider_id: str, credential_id: str | None) -> None:
    """Validate environment variable name format."""
    if not _ENV_VAR_RE.fullmatch(value):
        raise ParseError(
            f"invalid env_var {value!r}: must match [A-Za-z_][A-Za-z0-9_]*",
            provider_id=provider_id,
            credential_id=credential_id,
        )


def _validate_quota_group(value: str, provider_id: str, credential_id: str | None) -> None:
    """Validate quota_group is non-empty."""
    if not value or not value.strip():
        raise ParseError(
            "quota_group must be a non-empty string",
            provider_id=provider_id,
            credential_id=credential_id,
        )


def _validate_enabled(value: object, provider_id: str, credential_id: str | None) -> bool:
    """Validate and coerce enabled field to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
    raise ParseError(
        f"enabled must be a boolean, got {type(value).__name__}",
        provider_id=provider_id,
        credential_id=credential_id,
    )


def _validate_known_fields(
    row: dict[str, Any], provider_id: str, credential_id: str | None
) -> None:
    """Reject unsupported fields in credential row."""
    known = {"id", "provider", "env_var", "quota_group", "enabled"}
    for key in row:
        if key not in known:
            raise ParseError(
                f"unsupported field {key!r} in credential row",
                provider_id=provider_id,
                credential_id=credential_id,
            )


def _resolve_secret(env_var: str, effective_env: dict[str, str]) -> str | None:
    """Resolve secret from effective environment. Returns None if missing or blank."""
    value = effective_env.get(env_var)
    if value is None or value == "":
        return None
    return value


def _provider_credential_rows(config_data: dict[str, Any]) -> list[dict[str, Any]]:
    providers = config_data.get("providers", {})
    if providers is None:
        return []
    if isinstance(providers, list):
        entries = []
        for item in providers:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ParseError("each providers entry must contain a string id")
            entries.append((item["id"], {key: value for key, value in item.items() if key != "id"}))
    elif isinstance(providers, dict):
        entries = list(providers.items())
    else:
        raise ParseError("providers must be a table or array of tables")

    rows: list[dict[str, Any]] = []
    for provider_id, provider_data in entries:
        if not isinstance(provider_data, dict):
            raise ParseError(f"provider {provider_id!r} must be a table", provider_id=provider_id)
        unknown_provider_fields = set(provider_data) - {"enabled", "api_keys"}
        if unknown_provider_fields:
            raise ParseError(
                f"unsupported provider fields: {sorted(unknown_provider_fields)!r}",
                provider_id=provider_id,
            )
        provider_enabled = _validate_enabled(provider_data.get("enabled", True), provider_id, None)
        api_keys = provider_data.get("api_keys", [])
        if not isinstance(api_keys, list):
            raise ParseError("api_keys must be a list", provider_id=provider_id)
        for index, key_data in enumerate(api_keys, start=1):
            if not isinstance(key_data, dict) or not isinstance(key_data.get("env"), str):
                raise ParseError("each api_keys entry requires a string env", provider_id=provider_id)
            unknown_key_fields = set(key_data) - {"id", "env", "quota_group", "enabled"}
            if unknown_key_fields:
                raise ParseError(
                    f"unsupported api key fields: {sorted(unknown_key_fields)!r}",
                    provider_id=provider_id,
                )
            rows.append(
                {
                    "provider": provider_id,
                    "id": str(key_data.get("id", f"key-{index}")),
                    "env_var": key_data["env"],
                    "quota_group": str(key_data.get("quota_group", provider_id)),
                    "enabled": provider_enabled and _validate_enabled(
                        key_data.get("enabled", True), provider_id, None
                    ),
                }
            )
    return rows


def parse_credentials(
    config_data: dict[str, Any],
    providers: list[Provider],
    env: dict[str, str],
) -> list[CredentialSlot]:
    """Parse [[credentials]] from config.toml and resolve availability.

    Args:
        config_data: Parsed config.toml dict (from load_config_file)
        providers: List of Provider objects from the catalog
        env: Effective environment (real env with config.toml [keys] as defaults)

    Returns:
        List of CredentialSlot objects with resolved availability.

    Raises:
        ParseError: On validation failures (duplicate ids, invalid types, etc.)
    """
    # Build provider lookup by id
    provider_by_id = {p.id: p for p in providers}

    # Collect explicit credential rows from config
    credentials_rows = config_data.get("credentials", [])
    if not isinstance(credentials_rows, list):
        raise ParseError("[credentials] must be an array of tables")
    legacy_providers = {
        row.get("provider") for row in credentials_rows if isinstance(row, dict)
    }
    credentials_rows = credentials_rows + [
        row for row in _provider_credential_rows(config_data)
        if row["provider"] not in legacy_providers
    ]

    # Track explicit credentials by (provider_id, credential_id)
    explicit_by_provider: dict[str, list[dict[str, Any]]] = {}
    seen_pairs: set[tuple[str, str]] = set()

    for row in credentials_rows:
        if not isinstance(row, dict):
            raise ParseError("each [[credentials]] entry must be a table")

        # Validate required fields
        provider_id = row.get("provider")
        if not isinstance(provider_id, str):
            raise ParseError("credential row missing required 'provider' field (string)")

        credential_id = row.get("id")
        if not isinstance(credential_id, str):
            raise ParseError(
                f"credential row for provider {provider_id!r} missing required 'id' field (string)",
                provider_id=provider_id,
            )

        _validate_id(credential_id, provider_id, credential_id)

        # Check for duplicate (provider, id)
        pair = (provider_id, credential_id)
        if pair in seen_pairs:
            raise ParseError(
                f"duplicate credential id {credential_id!r} for provider {provider_id!r}",
                provider_id=provider_id,
                credential_id=credential_id,
            )
        seen_pairs.add(pair)

        # Validate provider exists
        if provider_id not in provider_by_id:
            raise ParseError(
                f"credential references unknown provider {provider_id!r}",
                provider_id=provider_id,
                credential_id=credential_id,
            )

        provider = provider_by_id[provider_id]

        # auth="none" providers reject explicit credential rows
        if provider.auth == "none":
            raise ParseError(
                f"provider {provider_id!r} has auth=\"none\" and cannot have explicit credential rows",
                provider_id=provider_id,
                credential_id=credential_id,
            )

        # Validate env_var
        env_var = row.get("env_var")
        if not isinstance(env_var, str):
            raise ParseError(
                "credential row missing required 'env_var' field (string)",
                provider_id=provider_id,
                credential_id=credential_id,
            )
        _validate_env_var(env_var, provider_id, credential_id)

        # Validate quota_group
        quota_group = row.get("quota_group")
        if not isinstance(quota_group, str):
            raise ParseError(
                "credential row missing required 'quota_group' field (string)",
                provider_id=provider_id,
                credential_id=credential_id,
            )
        _validate_quota_group(quota_group, provider_id, credential_id)

        # Validate enabled (optional, defaults to True)
        enabled = _validate_enabled(row.get("enabled", True), provider_id, credential_id)

        # Reject unknown fields
        _validate_known_fields(row, provider_id, credential_id)

        explicit_by_provider.setdefault(provider_id, []).append(
            {
                "id": credential_id,
                "env_var": env_var,
                "quota_group": quota_group,
                "enabled": enabled,
            }
        )

    # Now build CredentialSlot list
    slots: list[CredentialSlot] = []

    # Process providers with explicit credentials
    for provider_id, creds in explicit_by_provider.items():
        provider = provider_by_id[provider_id]

        # Resolve secrets and deduplicate equal secrets within this provider
        seen_secrets: dict[str, CredentialSlot] = {}  # secret -> first slot with that secret

        for cred in creds:
            secret = _resolve_secret(cred["env_var"], env)

            # Create slot (secret not stored, only env_var reference)
            slot = CredentialSlot(
                id=cred["id"],
                provider=provider_id,
                env_var=cred["env_var"],
                quota_group=cred["quota_group"],
                enabled=cred["enabled"],
            )

            # Deduplicate: if secret is same as an earlier slot, skip this one
            # (but only if both have actual secrets; None secrets are not deduped)
            if secret is not None and secret in seen_secrets:
                # Duplicate secret - skip this slot (it's unavailable due to duplicate)
                continue

            if secret is not None:
                seen_secrets[secret] = slot

            slots.append(slot)

    # Process providers WITHOUT explicit credentials - synthesize "legacy" from key_env
    for provider in providers:
        if provider.id in explicit_by_provider:
            continue  # explicit rows replace implicit

        # Only synthesize for providers that have a key_env
        if provider.key_env:
            # Validate the key_env format (should already be valid from provider parsing)
            _validate_env_var(provider.key_env, provider.id, "legacy")

            # Check if this provider is key_optional with explicit rows - but we already
            # skipped providers with explicit rows, so this is the implicit case
            secret = _resolve_secret(provider.key_env, env)

            slot = CredentialSlot(
                id="legacy",
                provider=provider.id,
                env_var=provider.key_env,
                quota_group=provider.id,  # quota_group defaults to provider id
                enabled=True,
            )
            slots.append(slot)

    return slots


def filter_available_slots(
    slots: list[CredentialSlot], env: dict[str, str]
) -> tuple[list[CredentialSlot], list[tuple[CredentialSlot, str]]]:
    """Filter slots to only available ones, returning (available, unavailable_with_reason).

    A slot is available if:
    - enabled=True
    - env_var resolves to a non-empty secret in the environment

    Returns:
        Tuple of (available_slots, list of (slot, reason) for unavailable)
    """
    available: list[CredentialSlot] = []
    unavailable: list[tuple[CredentialSlot, str]] = []

    for slot in slots:
        if not slot.enabled:
            unavailable.append((slot, "disabled"))
            continue

        secret = _resolve_secret(slot.env_var, env)
        if secret is None:
            unavailable.append((slot, "no_secret"))
            continue

        available.append(slot)

    return available, unavailable
