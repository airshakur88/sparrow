"""Attempt lifecycle and per-credential usage accounting."""

from __future__ import annotations

from dataclasses import dataclass

from .credential_store import CredentialStore
from .credentials import CredentialSelection, CredentialState


@dataclass(frozen=True, slots=True)
class UsageOutcome:
    """The immutable inputs needed to finalize one provider attempt."""

    state: CredentialState
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    usage_missing: bool = False
    error_class: str | None = None
    error_message: str | None = None


class CredentialUsage:
    """Coordinate durable reservation, dispatch and idempotent finalization."""

    def __init__(self, store: CredentialStore, lease_seconds: float = 60.0) -> None:
        self._store = store
        self._lease_seconds = max(0.0, lease_seconds)

    def reserve(
        self, selection: CredentialSelection, request_id: str, model: str, operation: str,
    ) -> None:
        self._store.reserve_attempt(
            selection.attempt_id, request_id, selection.provider_id, selection.credential_id,
            selection.quota_group, model, operation, selection.generation,
            self._store._clock() + self._lease_seconds,
        )

    def mark_dispatched(self, selection: CredentialSelection) -> bool:
        return self._store.mark_dispatched(selection.attempt_id)

    def finalize(self, selection: CredentialSelection, outcome: UsageOutcome) -> bool:
        return self._store.finalize_attempt(
            selection.attempt_id, outcome.state, prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens, usage_missing=outcome.usage_missing,
            error_class=outcome.error_class, error_message=outcome.error_message,
        )

    def recover(self) -> int:
        return self._store.recover_expired_attempts()
