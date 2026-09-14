"""Immutable credential contracts for provider key rotation.

This module defines frozen dataclasses and enums for credential selection,
cooldown tracking, and legacy Provider compatibility.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class CredentialOperation(StrEnum):
    """Operation type for credential selection."""

    CHAT = "chat"
    EMBED = "embed"
    TRANSCRIBE = "transcribe"
    DISCOVERY = "discovery"
    PROBE = "probe"


class CooldownReason(StrEnum):
    """Reason a credential is in cooldown."""

    KEY_AUTH = "key_auth"
    KEY_TEMP = "key_temp"
    QUOTA_GROUP = "quota_group"
    ROUTE = "route"


class CredentialState(StrEnum):
    """State of a credential selection attempt."""

    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class UnavailableReason(StrEnum):
    """Reason a credential is unavailable for selection."""

    NO_SECRET = "no_secret"
    DISABLED = "disabled"
    COOLDOWN = "cooldown"
    DUPLICATE_ALIAS = "duplicate_alias"
    NO_CREDENTIALS_CONFIGURED = "no_credentials_configured"


@dataclass(frozen=True)
class CredentialSlot:
    """A single credential slot configuration.

    Represents one API key environment variable and its metadata.
    """

    id: str
    provider: str
    env_var: str
    quota_group: str
    enabled: bool = True

    def __repr__(self) -> str:
        return (
            f"CredentialSlot(id={self.id!r}, provider={self.provider!r}, "
            f"env_var={self.env_var!r}, quota_group={self.quota_group!r}, "
            f"enabled={self.enabled!r})"
        )


@dataclass(frozen=True)
class CredentialSelection:
    """Result of selecting a credential for an operation.

    The secret field contains the actual API key value but is never
    exposed in __repr__ or __str__.
    """

    credential_id: str
    provider_id: str
    quota_group: str
    secret: str | None
    attempt_id: str
    generation: str

    def __post_init__(self) -> None:
        if not self.attempt_id:
            object.__setattr__(self, "attempt_id", uuid.uuid4().hex)

    def __repr__(self) -> str:
        secret_repr = "***REDACTED***" if self.secret is not None else "None"
        return (
            f"CredentialSelection(credential_id={self.credential_id!r}, "
            f"provider_id={self.provider_id!r}, quota_group={self.quota_group!r}, "
            f"secret={secret_repr}, attempt_id={self.attempt_id!r}, "
            f"generation={self.generation!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class CredentialUnavailable:
    """Reason a credential could not be selected."""

    reason: UnavailableReason
    provider_id: str
    detail: str

    def __repr__(self) -> str:
        return (
            f"CredentialUnavailable(reason={self.reason!r}, "
            f"provider_id={self.provider_id!r}, detail={self.detail!r})"
        )