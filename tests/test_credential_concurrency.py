from __future__ import annotations

import multiprocessing as mp
import sqlite3

import pytest

from sparrow.credential_manager import CredentialManager
from sparrow.credential_schema import CorruptStoreError, LockedStoreError, SchemaVersionError
from sparrow.credential_store import CredentialStore
from sparrow.credential_usage import CredentialUsage, UsageOutcome
from sparrow.credentials import (
    CredentialOperation,
    CredentialSelection,
    CredentialSlot,
    CredentialState,
)


def _slots() -> tuple[CredentialSlot, ...]:
    return tuple(
        CredentialSlot(
            id=name,
            provider="alpha",
            env_var=f"ALPHA_{name.upper()}",
            quota_group="team",
        )
        for name in ("one", "two", "three")
    )


def _reservation_worker(path: str, barrier: object, output: object) -> None:
    try:
        store = CredentialStore(path, busy_timeout_ms=250)
        manager = CredentialManager(
            _slots(),
            {slot.env_var: f"secret-{slot.id}" for slot in _slots()},
            store,
        )
        usage = CredentialUsage(store)
        barrier.wait(timeout=30)
        for index in range(30):
            for _ in range(20):
                try:
                    selection = manager.reserve("alpha", "model", CredentialOperation.CHAT)
                    break
                except LockedStoreError:
                    continue
            else:
                raise AssertionError("reservation remained locked after retries")
            if not isinstance(selection, CredentialSelection):
                raise AssertionError(f"reservation unavailable: {selection}")
            barrier.wait(timeout=30)
            for _ in range(20):
                try:
                    usage.reserve(selection, f"request-{index}", "model", "chat")
                    break
                except LockedStoreError:
                    continue
            else:
                raise AssertionError("usage reservation remained locked after retries")
            for _ in range(20):
                try:
                    if usage.mark_dispatched(selection):
                        break
                except LockedStoreError:
                    continue
            else:
                raise AssertionError("dispatch remained locked after retries")
            for _ in range(20):
                try:
                    if usage.finalize(
                        selection,
                        UsageOutcome(CredentialState.SUCCEEDED, prompt_tokens=1, completion_tokens=2),
                    ):
                        break
                except LockedStoreError:
                    continue
            else:
                raise AssertionError("finalization remained locked after retries")
            output.append(selection.attempt_id)
            barrier.wait(timeout=30)
    except Exception as exc:
        output.append(f"ERROR:{type(exc).__name__}:{exc}")


def test_spawned_workers_preserve_round_robin_and_usage(tmp_path):
    path = str(tmp_path / "credential-state.db")
    context = mp.get_context("spawn")
    barrier = context.Barrier(4)
    manager = context.Manager()
    output = manager.list()
    processes = [
        context.Process(target=_reservation_worker, args=(path, barrier, output))
        for _ in range(4)
    ]
    CredentialStore(path)
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
    attempts = list(output)
    manager.shutdown()
    assert all(process.exitcode == 0 for process in processes)
    assert not [item for item in attempts if item.startswith("ERROR:")], attempts
    assert len(attempts) == 120, attempts[-10:]
    assert all(isinstance(item, str) and not item.startswith("ERROR:") for item in attempts)
    assert len(set(attempts)) == 120

    rows = CredentialStore(path).usage_report(provider="alpha")
    assert {row["credential_id"] for row in rows} == {"one", "two", "three"}
    assert {row["succeeded"] for row in rows} == {40}
    assert {row["prompt_tokens"] for row in rows} == {40}
    assert {row["completion_tokens"] for row in rows} == {80}


def test_expired_dispatched_attempt_recovers_once(tmp_path):
    now = [100.0]
    store = CredentialStore(tmp_path / "state.db", clock=lambda: now[0])
    manager = CredentialManager(
        _slots()[:1], {"ALPHA_ONE": "secret"}, store, clock=lambda: now[0]
    )
    selection = manager.reserve("alpha", "model", "chat")
    assert isinstance(selection, CredentialSelection)
    usage = CredentialUsage(store, lease_seconds=10)
    usage.reserve(selection, "request", "model", "chat")
    assert usage.mark_dispatched(selection)
    now[0] = 111.0
    assert usage.recover() == 1
    assert usage.recover() == 0
    row = store.get_attempt(selection.attempt_id)
    assert row is not None
    assert row["state"] == "unknown"
    report = store.usage_report(provider="alpha")
    assert report[0]["unknown"] == 1


def test_corrupt_and_newer_store_fail_closed(tmp_path):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(CorruptStoreError):
        CredentialStore(corrupt)

    newer = tmp_path / "newer.db"
    connection = sqlite3.connect(newer)
    connection.execute("PRAGMA user_version=999")
    connection.commit()
    connection.close()
    with pytest.raises(SchemaVersionError):
        CredentialStore(newer)


def test_locked_store_fails_closed_without_selection(tmp_path):
    path = tmp_path / "locked.db"
    store = CredentialStore(path, busy_timeout_ms=10)
    connection = sqlite3.connect(path)
    connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LockedStoreError):
            store.reserve_round_robin("alpha", ["one", "two"])
    finally:
        connection.rollback()
        connection.close()


def test_local_slot_set_ignores_persisted_cursor_for_removed_id(tmp_path):
    store = CredentialStore(tmp_path / "state.db")
    store.set_cursor("alpha", "removed")
    slots = _slots()[1:]
    manager = CredentialManager(
        slots,
        {slot.env_var: f"secret-{slot.id}" for slot in slots},
        store,
    )
    selection = manager.reserve("alpha", "model", "chat")
    assert isinstance(selection, CredentialSelection)
    assert selection.credential_id == "two"
