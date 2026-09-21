                                                                                 

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence

from .credential_errors import CredentialFailure
from .credential_store import CredentialStore
from .credentials import (
    CredentialOperation,
    CredentialSelection,
    CredentialSlot,
    CredentialUnavailable,
    UnavailableReason,
)


class CredentialManager:
                                                                           

    def __init__(
        self,
        slots: Sequence[CredentialSlot],
        env: Mapping[str, str],
        store: CredentialStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._slots = tuple(slots)
        self._env = env
        self._store = store
        self._clock = clock

    def has_credentials(self, provider_id: str) -> bool:
        return any(
            slot.provider == provider_id
            and slot.enabled
            and self._env.get(slot.env_var, "").strip()
            for slot in self._slots
        )

    def generation(self, provider_id: str) -> str:
        records = [
            {
                "id": slot.id,
                "provider": slot.provider,
                "env_var": slot.env_var,
                "quota_group": slot.quota_group,
                "enabled": slot.enabled,
            }
            for slot in self._slots
            if slot.provider == provider_id
        ]
        payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()

    def reserve(
        self,
        provider_id: str,
        model: str,
        operation: CredentialOperation | str,
        request_id: str = "",
        excluded_ids: set[str] | None = None,
        deadline: float | None = None,
    ) -> CredentialSelection | CredentialUnavailable:
        del model, request_id
        del deadline
        excluded = excluded_ids or set()
        candidates = [slot for slot in self._slots if slot.provider == provider_id]
        if not candidates:
            return CredentialUnavailable(UnavailableReason.NO_CREDENTIALS_CONFIGURED, provider_id, "no slots")
        available: list[CredentialSlot] = []
        for slot in candidates:
            if not slot.enabled or slot.id in excluded:
                continue
            secret = self._env.get(slot.env_var, "").strip()
            if not secret:
                continue
            if self._store.get_cooldown(provider_id, "key", slot.id) is not None:
                continue
            if self._store.get_cooldown(provider_id, "quota_group", slot.quota_group) is not None:
                continue
            available.append(slot)
        if not available:
            return CredentialUnavailable(UnavailableReason.COOLDOWN, provider_id, "all slots unavailable")
        selected_id = self._store.select_next_credential(provider_id, [slot.id for slot in available])
        if selected_id is None:
            return CredentialUnavailable(UnavailableReason.COOLDOWN, provider_id, "no eligible slot")
        selected = next(slot for slot in available if slot.id == selected_id)
        self._store.upsert(provider_id, selected.id)
        return CredentialSelection(
            credential_id=selected.id,
            provider_id=provider_id,
            quota_group=selected.quota_group,
            secret=self._env[selected.env_var].strip(),
            attempt_id="",
            generation=self.generation(provider_id),
        )

    def record_failure(self, selection: CredentialSelection, failure: CredentialFailure) -> None:
        until = self._clock() + max(0.0, failure.duration)
        scope = "key" if failure.reason.value.startswith("key_") else "quota_group"
        scope_id = selection.credential_id if scope == "key" else selection.quota_group
        self._store.set_cooldown(selection.provider_id, scope, scope_id, until, failure.reason)

    def availability(self, provider_id: str) -> dict[str, str]:
        result: dict[str, str] = {}
        seen_secrets: set[str] = set()
        for slot in self._slots:
            if slot.provider != provider_id:
                continue
            secret = self._env.get(slot.env_var, "").strip()
            if not slot.enabled:
                result[slot.id] = "disabled"
            elif not secret:
                result[slot.id] = "missing"
            elif secret in seen_secrets:
                result[slot.id] = "duplicate_alias"
            elif (
                self._store.get_cooldown(provider_id, "key", slot.id) is not None
                or self._store.get_cooldown(provider_id, "quota_group", slot.quota_group) is not None
            ):
                result[slot.id] = "cooldown"
            else:
                result[slot.id] = "available"
            if secret:
                seen_secrets.add(secret)
        return result
