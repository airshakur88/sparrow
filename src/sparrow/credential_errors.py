                                                                    

from __future__ import annotations

from dataclasses import dataclass

from .credentials import CooldownReason


@dataclass(frozen=True, slots=True)
class CredentialFailure:
                                                             

    reason: CooldownReason
    duration: float
    detail: str = ""


def classify_credential_failure(
    status_code: int | None,
    *,
    retry_after: float | None = None,
    credential_specific: bool = False,
    cooldown_seconds: float = 900.0,
) -> CredentialFailure | None:
                                                                                   
    duration = retry_after if retry_after is not None else cooldown_seconds
    duration = max(0.0, duration)
    if status_code in {401, 403} and credential_specific:
        return CredentialFailure(CooldownReason.KEY_AUTH, duration, "credential authentication")
    if status_code == 429:
        return CredentialFailure(CooldownReason.QUOTA_GROUP, max(900.0, duration), "quota or rate limit")
    return None
