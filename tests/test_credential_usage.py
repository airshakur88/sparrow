from sparrow.credential_store import CredentialStore
from sparrow.credential_usage import CredentialUsage, UsageOutcome
from sparrow.credentials import CredentialSelection, CredentialState


def selection() -> CredentialSelection:
    return CredentialSelection("key-a", "provider", "shared", "secret", "attempt-a", "gen")


def test_aggregate_finalize_is_idempotent_and_preserves_zero_tokens(tmp_path):
    store = CredentialStore(tmp_path / "state.db", clock=lambda: 100.0)
    usage = CredentialUsage(store)
    chosen = selection()
    usage.reserve(chosen, "request", "model", "chat")
    assert usage.mark_dispatched(chosen)
    outcome = UsageOutcome(CredentialState.SUCCEEDED, prompt_tokens=0, completion_tokens=0)

    assert usage.finalize(chosen, outcome)
    assert not usage.finalize(chosen, outcome)
    row = store.get_attempt(chosen.attempt_id)
    assert row is not None
    assert row["prompt_tokens"] == 0
    assert row["completion_tokens"] == 0


def test_duplicate_cancelled_reservation_does_not_count_dispatch(tmp_path):
    store = CredentialStore(tmp_path / "state.db", clock=lambda: 100.0)
    usage = CredentialUsage(store)
    chosen = selection()
    usage.reserve(chosen, "request", "model", "chat")

    assert usage.finalize(chosen, UsageOutcome(CredentialState.CANCELLED))
    with store._operation() as connection:
        row = connection.execute(
            "SELECT reserved,dispatched,cancelled FROM credential_usage"
        ).fetchone()
    assert tuple(row) == (1, 0, 1)


def test_expired_attempt_recovers_once(tmp_path):
    now = [100.0]
    store = CredentialStore(tmp_path / "state.db", clock=lambda: now[0])
    usage = CredentialUsage(store, lease_seconds=1)
    chosen = selection()
    usage.reserve(chosen, "request", "model", "chat")
    now[0] = 102.0

    assert usage.recover() == 1
    assert usage.recover() == 0
    row = store.get_attempt(chosen.attempt_id)
    assert row is not None and row["state"] == "unknown"
