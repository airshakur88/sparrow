                                                                                          

from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from sparrow.credential_schema import (
    SCHEMA_VERSION,
    CorruptStoreError,
    LockedStoreError,
    SchemaVersionError,
    bootstrap_schema,
    check_schema_version,
    get_user_version,
)
from sparrow.credential_store import CredentialStore, default_credential_store_path
from sparrow.credentials import CooldownReason, CredentialState


class TestDefaultPath:
                                                        

    def test_default_path_structure(self):
        path = default_credential_store_path()
        assert path.name == "credential_state.db"
        assert ".config" in str(path)
        assert "sparrow" in str(path)

    def test_env_override(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = Path(tmpdir) / "custom.db"
            monkeypatch.setenv("SPARROW_CREDENTIAL_STATE_FILE", str(custom_path))
            path = default_credential_store_path()
            assert path == custom_path


class TestSchemaVersioning:
                                                                  

    def test_bootstrap_creates_tables_and_sets_version(self, tmp_path):
        db_path = tmp_path / "test.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
            version = get_user_version(con)
            assert version == SCHEMA_VERSION

                                              
            tables = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {t[0] for t in tables}
            assert "cursor" in table_names
            assert "cooldown" in table_names
            assert "attempts" in table_names
            assert "daily_usage" in table_names

    def test_check_schema_version_passes_for_current(self, tmp_path):
        db_path = tmp_path / "test.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
                              
            assert check_schema_version(con) == SCHEMA_VERSION

    def test_check_schema_version_raises_for_future_version(self, tmp_path):
        db_path = tmp_path / "test.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
                                           
            con.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
            con.commit()

        with sqlite3.connect(db_path) as con:
            with pytest.raises(SchemaVersionError) as exc:
                check_schema_version(con)
            assert "newer than supported version" in str(exc.value)

    def test_check_schema_version_returns_actual_version(self, tmp_path):
        db_path = tmp_path / "test.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
            assert check_schema_version(con) == SCHEMA_VERSION

    def test_wal_mode_enabled(self, tmp_path):
        db_path = tmp_path / "test.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
                                   
            row = con.execute("PRAGMA journal_mode").fetchone()
            assert row[0].lower() == "wal"

    def test_foreign_keys_enabled(self, tmp_path):
        db_path = tmp_path / "test.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
            row = con.execute("PRAGMA foreign_keys").fetchone()
            assert row[0] == 1

    def test_synchronous_full(self, tmp_path):
        db_path = tmp_path / "test.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
            row = con.execute("PRAGMA synchronous").fetchone()
                                                                      
            assert row[0] == 2


class TestCredentialStoreInit:
                                                                        

    def test_init_creates_database_and_schema(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        assert store.path == db_path
        assert db_path.exists()

                                   
        with sqlite3.connect(db_path) as con:
            version = get_user_version(con)
            assert version == SCHEMA_VERSION

    def test_init_rejects_memory_database(self):
        with pytest.raises(ValueError, match="In-memory databases are not allowed"):
            CredentialStore(path=Path(":memory:"))

    def test_init_rejects_file_memory_database(self):
        with pytest.raises(ValueError, match="In-memory databases are not allowed"):
            CredentialStore(path=Path("file::memory:"))

    def test_init_creates_parent_directory(self, tmp_path):
        db_path = tmp_path / "subdir" / "store.db"
        CredentialStore(path=db_path)
        assert db_path.parent.exists()
        assert db_path.exists()

    def test_custom_clock_injected(self, tmp_path):
        db_path = tmp_path / "store.db"
        fixed_time = 1234567890.0
        store = CredentialStore(path=db_path, clock=lambda: fixed_time)
        assert store._clock() == fixed_time


class TestCredentialStoreContextManager:
                                                                              

    def test_context_manager_returns_self(self, tmp_path):
        db_path = tmp_path / "store.db"
        with CredentialStore(path=db_path) as store:
            assert isinstance(store, CredentialStore)

    def test_context_manager_closes_cleanly(self, tmp_path):
        db_path = tmp_path / "store.db"
        with CredentialStore(path=db_path) as store:
            store.set_cursor("groq", "key1")
                                                 

    def test_context_manager_handles_exception(self, tmp_path):
        db_path = tmp_path / "store.db"
        try:
            with CredentialStore(path=db_path) as store:
                store.set_cursor("groq", "key1")
                raise ValueError("test error")
        except ValueError:
            pass
                                                      
        with CredentialStore(path=db_path) as store:
            cursor = store.get_cursor("groq")
            assert cursor == "key1"


class TestCursorOperations:
                                                                   

    def test_get_cursor_returns_none_for_new_provider(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        assert store.get_cursor("groq") is None

    def test_set_and_get_cursor(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.set_cursor("groq", "key2")
        assert store.get_cursor("groq") == "key2"

    def test_cursor_updates_atomically(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.set_cursor("groq", "key1")
        store.set_cursor("groq", "key2")
        store.set_cursor("groq", "key3")
        assert store.get_cursor("groq") == "key3"

    def test_cursors_independent_per_provider(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.set_cursor("groq", "key1")
        store.set_cursor("cerebras", "keyA")
        assert store.get_cursor("groq") == "key1"
        assert store.get_cursor("cerebras") == "keyA"

    def test_cursor_persists_across_reopen(self, tmp_path):
        db_path = tmp_path / "store.db"
        with CredentialStore(path=db_path) as store:
            store.set_cursor("groq", "key1")
        with CredentialStore(path=db_path) as store:
            assert store.get_cursor("groq") == "key1"


class TestCooldownOperations:
                                                                  

    def test_get_cooldown_returns_none_for_new(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        assert store.get_cooldown("groq", "key", "key1") is None

    def test_set_and_get_cooldown(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        future = time.time() + 3600
        store.set_cooldown("groq", "key", "key1", future, CooldownReason.KEY_AUTH)
        result = store.get_cooldown("groq", "key", "key1")
        assert result is not None
        assert abs(result - future) < 1.0                           

    def test_cooldown_max_semantics_extends_only(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        now = time.time()
        later = now + 3600
        even_later = now + 7200

        store.set_cooldown("groq", "key", "key1", later, CooldownReason.KEY_AUTH)
        store.set_cooldown("groq", "key", "key1", now, CooldownReason.KEY_TEMP)                               
        result = store.get_cooldown("groq", "key", "key1")
        assert abs(result - later) < 1.0

        store.set_cooldown("groq", "key", "key1", even_later, CooldownReason.KEY_TEMP)                         
        result = store.get_cooldown("groq", "key", "key1")
        assert abs(result - even_later) < 1.0

    def test_cooldown_expired_returns_none(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        past = time.time() - 3600
        store.set_cooldown("groq", "key", "key1", past, CooldownReason.KEY_AUTH)
        assert store.get_cooldown("groq", "key", "key1") is None

    def test_cooldown_independent_per_scope(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        future = time.time() + 3600
        store.set_cooldown("groq", "key", "key1", future, CooldownReason.KEY_AUTH)
        store.set_cooldown("groq", "quota_group", "groq", future, CooldownReason.QUOTA_GROUP)
        assert store.get_cooldown("groq", "key", "key1") is not None
        assert store.get_cooldown("groq", "quota_group", "groq") is not None

    def test_cooldown_persists_across_reopen(self, tmp_path):
        db_path = tmp_path / "store.db"
        future = time.time() + 3600
        with CredentialStore(path=db_path) as store:
            store.set_cooldown("groq", "key", "key1", future, CooldownReason.KEY_AUTH)
        with CredentialStore(path=db_path) as store:
            result = store.get_cooldown("groq", "key", "key1")
            assert result is not None
            assert abs(result - future) < 1.0


class TestAttemptOperations:
                                                        

    def test_insert_attempt(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.insert_attempt("attempt-1", "key1", "groq", "groq", "chat", CredentialState.RESERVED)

        with sqlite3.connect(db_path) as con:
            row = con.execute(
                "SELECT attempt_id, credential_id, provider_id, quota_group, operation, state FROM attempts WHERE attempt_id = ?",
                ("attempt-1",)
            ).fetchone()
            assert row is not None
            assert row[0] == "attempt-1"
            assert row[1] == "key1"
            assert row[2] == "groq"
            assert row[3] == "groq"
            assert row[4] == "chat"
            assert row[5] == "reserved"

    def test_update_attempt_success(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.insert_attempt("attempt-1", "key1", "groq", "groq", "chat", CredentialState.RESERVED)
        result = store.update_attempt("attempt-1", CredentialState.SUCCEEDED)
        assert result is True

        with sqlite3.connect(db_path) as con:
            row = con.execute("SELECT state, finished_at FROM attempts WHERE attempt_id = ?", ("attempt-1",)).fetchone()
            assert row[0] == "succeeded"
            assert row[1] is not None

    def test_update_attempt_failed_with_error(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.insert_attempt("attempt-1", "key1", "groq", "groq", "chat", CredentialState.RESERVED)
        result = store.update_attempt("attempt-1", CredentialState.FAILED, error_class="AuthError", error_message="Invalid key")
        assert result is True

        with sqlite3.connect(db_path) as con:
            row = con.execute("SELECT state, error_class, error_message FROM attempts WHERE attempt_id = ?", ("attempt-1",)).fetchone()
            assert row[0] == "failed"
            assert row[1] == "AuthError"
            assert row[2] == "Invalid key"

    def test_update_attempt_cas_prevents_double_terminal(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.insert_attempt("attempt-1", "key1", "groq", "groq", "chat", CredentialState.RESERVED)
        store.update_attempt("attempt-1", CredentialState.SUCCEEDED)
                                                      
        result = store.update_attempt("attempt-1", CredentialState.FAILED)
        assert result is False

    def test_update_attempt_cas_allows_reserved_to_dispatched(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.insert_attempt("attempt-1", "key1", "groq", "groq", "chat", CredentialState.RESERVED)
        result = store.update_attempt("attempt-1", CredentialState.DISPATCHED)
        assert result is True

                                         
        result = store.update_attempt("attempt-1", CredentialState.SUCCEEDED)
        assert result is True

    def test_update_attempt_nonexistent_returns_false(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        result = store.update_attempt("nonexistent", CredentialState.SUCCEEDED)
        assert result is False


class TestDailyUsageOperations:
                                                   

    def test_get_daily_usage_returns_zero_for_new(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        assert store.get_daily_usage("groq", "llama-3.1-8b") == 0

    def test_update_daily_usage_increments(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        count = store.update_daily_usage("groq", "llama-3.1-8b", 1)
        assert count == 1
        count = store.update_daily_usage("groq", "llama-3.1-8b", 1)
        assert count == 2

    def test_update_daily_usage_custom_delta(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        count = store.update_daily_usage("groq", "llama-3.1-8b", 5)
        assert count == 5

    def test_daily_usage_independent_per_day(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        def fixed_clock() -> float:
            return 1704067200.0

        store._clock = fixed_clock
        store.update_daily_usage("groq", "model1", 1)
        assert store.get_daily_usage("groq", "model1") == 1

        def next_day_clock() -> float:
            return 1704153600.0

        store._clock = next_day_clock
        assert store.get_daily_usage("groq", "model1") == 0                 
        store.update_daily_usage("groq", "model1", 1)
        assert store.get_daily_usage("groq", "model1") == 1

    def test_daily_usage_persists_across_reopen(self, tmp_path):
        db_path = tmp_path / "store.db"
        with CredentialStore(path=db_path) as store:
            store.update_daily_usage("groq", "model1", 3)
        with CredentialStore(path=db_path) as store:
            assert store.get_daily_usage("groq", "model1") == 3


class TestCredentialStateCRUD:
                                                                                                                         

    def test_upsert_credential_state(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.upsert_credential_state("key1", "groq", "active")
        state = store.get_credential_state("key1", "groq")
        assert state is not None
        assert state["credential_id"] == "key1"
        assert state["provider_id"] == "groq"
        assert state["state"] == "active"
        assert state["total_successes"] == 0
        assert state["total_failures"] == 0

    def test_upsert_credential_state_idempotent(self, tmp_path):
                                                                                 
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.upsert_credential_state("key1", "groq", "active")
        store.upsert_credential_state("key1", "groq", "active")
        states = store.list_by_provider("groq")
        assert len(states) == 1

    def test_get_credential_state(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.upsert_credential_state("key1", "groq", "active")
        state = store.get_credential_state("key1", "groq")
        assert state is not None
        assert state["credential_id"] == "key1"

    def test_get_credential_state_not_found(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        state = store.get_credential_state("nonexistent", "groq")
        assert state is None

    def test_list_by_provider(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.upsert_credential_state("key1", "groq", "active")
        store.upsert_credential_state("key2", "groq", "cooldown")
        store.upsert_credential_state("key3", "cerebras", "active")
        states = store.list_by_provider("groq")
        assert len(states) == 2
        assert {s["credential_id"] for s in states} == {"key1", "key2"}

    def test_list_by_provider_empty(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        states = store.list_by_provider("groq")
        assert states == []

    def test_update_state(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.upsert_credential_state("key1", "groq", "active")
        result = store.update_state("key1", "groq", "cooldown")
        assert result is True
        state = store.get_credential_state("key1", "groq")
        assert state["state"] == "cooldown"

    def test_update_state_not_found(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        result = store.update_state("nonexistent", "groq", "cooldown")
        assert result is False

    def test_record_success(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.upsert_credential_state("key1", "groq", "active")
        store.record_success("key1", "groq")
        state = store.get_credential_state("key1", "groq")
        assert state["total_successes"] == 1
        assert state["consecutive_failures"] == 0
        assert state["state"] == "active"
        assert state["last_success"] is not None

    def test_record_success_increments(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.upsert_credential_state("key1", "groq", "active")
        store.record_success("key1", "groq")
        store.record_success("key1", "groq")
        state = store.get_credential_state("key1", "groq")
        assert state["total_successes"] == 2

    def test_record_failure(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.upsert_credential_state("key1", "groq", "active")
        store.record_failure("key1", "groq", CooldownReason.KEY_AUTH, 900)
        state = store.get_credential_state("key1", "groq")
        assert state["total_failures"] == 1
        assert state["consecutive_failures"] == 1
        assert state["state"] == "cooldown"
        assert state["last_failure"] is not None
        assert state["cooldown_until"] > 0

    def test_record_failure_increments_consecutive(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.upsert_credential_state("key1", "groq", "active")
        store.record_failure("key1", "groq", CooldownReason.KEY_AUTH, 900)
        store.record_failure("key1", "groq", CooldownReason.KEY_TEMP, 900)
        state = store.get_credential_state("key1", "groq")
        assert state["consecutive_failures"] == 2
        assert state["total_failures"] == 2


class TestAtomicRoundRobin:
                                                              

    def test_round_robin_selects_next_credential(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
                                                        
        selected = store.select_next_credential("groq", ["key1", "key2", "key3"])
        assert selected == "key1"
                                             
        selected = store.select_next_credential("groq", ["key1", "key2", "key3"])
        assert selected == "key2"
                                            
        selected = store.select_next_credential("groq", ["key1", "key2", "key3"])
        assert selected == "key3"

    def test_round_robin_wraps_around(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.select_next_credential("groq", ["key1", "key2"])
        store.select_next_credential("groq", ["key1", "key2"])
                                     
        selected = store.select_next_credential("groq", ["key1", "key2"])
        assert selected == "key1"

    def test_round_robin_skips_unavailable(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
                                                    
        selected = store.select_next_credential("groq", ["key1", "key2", "key3"], excluded={"key2"})
        assert selected == "key1"
        selected = store.select_next_credential("groq", ["key1", "key2", "key3"], excluded={"key2"})
        assert selected == "key3"

    def test_round_robin_returns_none_when_all_excluded(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        selected = store.select_next_credential("groq", ["key1", "key2"], excluded={"key1", "key2"})
        assert selected is None

    def test_round_robin_independent_per_provider(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.select_next_credential("groq", ["key1", "key2"])
        store.select_next_credential("cerebras", ["keyA", "keyB"])
                                              
        assert store.select_next_credential("groq", ["key1", "key2"]) == "key2"
        assert store.select_next_credential("cerebras", ["keyA", "keyB"]) == "keyB"


class TestSchemaVersionProperty:
                                                             

    def test_schema_version_property(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        version = store.schema_version
        assert version == SCHEMA_VERSION

    def test_migration_support(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
                          
        store.migrate()


class TestCrashRecovery:
                                             

    def test_wal_replay_after_crash(self, tmp_path):
                                                                             
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.set_cursor("groq", "key1")
        store.set_cooldown("groq", "key", "key1", time.time() + 3600, CooldownReason.KEY_AUTH)
        store.update_daily_usage("groq", "model1", 5)

                                                                    
        store2 = CredentialStore(path=db_path)
        assert store2.get_cursor("groq") == "key1"
        assert store2.get_cooldown("groq", "key", "key1") is not None
        assert store2.get_daily_usage("groq", "model1") == 5

    def test_concurrent_access_with_wal(self, tmp_path):
                                                                             
        db_path = tmp_path / "store.db"
        store1 = CredentialStore(path=db_path)
        store2 = CredentialStore(path=db_path)

        store1.set_cursor("groq", "key1")
        store2.set_cursor("cerebras", "keyA")

        assert store1.get_cursor("groq") == "key1"
        assert store2.get_cursor("cerebras") == "keyA"
        assert store1.get_cursor("cerebras") == "keyA"                     
        assert store2.get_cursor("groq") == "key1"                     

    def test_locked_store_error_on_contention(self, tmp_path):
                                                                      
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)

                                                         
        con = sqlite3.connect(db_path, timeout=0.1, isolation_level=None)
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO cursor (provider, last_id, updated_at) VALUES ('locktest', 'x', 0)")

        try:
                                                                                           
            with pytest.raises(LockedStoreError):
                store.set_cursor("groq", "key1")
        finally:
            con.rollback()
            con.close()

    def test_round_robin_persists_after_crash(self, tmp_path):
                                                                         
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.select_next_credential("groq", ["key1", "key2", "key3"])           
        store.select_next_credential("groq", ["key1", "key2", "key3"])           

                        
        store2 = CredentialStore(path=db_path)
                                                
        selected = store2.select_next_credential("groq", ["key1", "key2", "key3"])
        assert selected == "key3"
                                  
        selected = store2.select_next_credential("groq", ["key1", "key2", "key3"])
        assert selected == "key1"


class TestPruning:
                                      

    def test_prune_old_attempts(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        now = time.time()
        old = now - (40 * 86400)               

                                     
        with sqlite3.connect(db_path) as con:
            con.execute(
                "INSERT INTO attempts (attempt_id, credential_id, provider_id, quota_group, operation, state, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("old-attempt", "key1", "groq", "groq", "chat", "succeeded", old)
            )
            con.execute(
                "INSERT INTO attempts (attempt_id, credential_id, provider_id, quota_group, operation, state, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("new-attempt", "key1", "groq", "groq", "chat", "succeeded", now)
            )
            con.commit()

        deleted = store.prune_old_attempts(max_age_days=30)
        assert deleted == 1

        with sqlite3.connect(db_path) as con:
            remaining = con.execute("SELECT attempt_id FROM attempts").fetchall()
            assert len(remaining) == 1
            assert remaining[0][0] == "new-attempt"

    def test_prune_old_cooldowns(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        now = time.time()
        past = now - 3600
        future = now + 3600

        with sqlite3.connect(db_path) as con:
            con.execute(
                "INSERT INTO cooldown (provider, scope_type, scope_id, until_utc, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("groq", "key", "key1", past, "key_auth", now)
            )
            con.execute(
                "INSERT INTO cooldown (provider, scope_type, scope_id, until_utc, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("groq", "key", "key2", future, "key_auth", now)
            )
            con.commit()

        deleted = store.prune_old_cooldowns()
        assert deleted == 1

        with sqlite3.connect(db_path) as con:
            remaining = con.execute("SELECT scope_id FROM cooldown").fetchall()
            assert len(remaining) == 1
            assert remaining[0][0] == "key2"

    def test_prune_old_daily_usage(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
                                                
        store._clock = lambda: 1704067200.0              

        with sqlite3.connect(db_path) as con:
            con.execute(
                "INSERT INTO daily_usage (day, provider_id, model, count) VALUES (?, ?, ?, ?)",
                ("2023-01-01", "groq", "model1", 10)
            )
            con.execute(
                "INSERT INTO daily_usage (day, provider_id, model, count) VALUES (?, ?, ?, ?)",
                ("2024-01-01", "groq", "model1", 5)
            )
            con.commit()

        deleted = store.prune_old_daily_usage(max_age_days=90)
        assert deleted == 1

        with sqlite3.connect(db_path) as con:
            remaining = con.execute("SELECT day FROM daily_usage").fetchall()
            assert len(remaining) == 1
            assert remaining[0][0] == "2024-01-01"


class TestConnectionCleanup:
                                                             

    def test_connection_closed_after_operation(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        store.set_cursor("groq", "key1")
                                                     

    def test_multiple_operations_dont_leak(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)
        for i in range(10):
            store.set_cursor(f"provider{i}", f"key{i}")
            store.get_cursor(f"provider{i}")
                             

    def test_context_manager_closes_on_exit(self, tmp_path):
        db_path = tmp_path / "store.db"
        with CredentialStore(path=db_path) as store:
            store.set_cursor("groq", "key1")
                                   


class TestErrorHandling:
                                                                        

    def test_corrupt_store_error(self, tmp_path):
        db_path = tmp_path / "store.db"
                                        
        db_path.write_bytes(b"not a sqlite database")

        with pytest.raises(CorruptStoreError):
            CredentialStore(path=db_path)

    def test_locked_store_error(self, tmp_path):
        db_path = tmp_path / "store.db"
        store = CredentialStore(path=db_path)

                                   
        con = sqlite3.connect(db_path, timeout=0.1, isolation_level=None)
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO cursor (provider, last_id, updated_at) VALUES ('lock', 'x', 0)")

        try:
                                                                  
            with pytest.raises(LockedStoreError):
                store.set_cursor("groq", "key1")
        finally:
            con.rollback()
            con.close()

    def test_schema_version_error_on_future_version(self, tmp_path):
        db_path = tmp_path / "store.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
            con.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
            con.commit()

        with pytest.raises(SchemaVersionError):
            CredentialStore(path=db_path)


class TestCredentialStateTable:
                                                            
                                                                                  
                                                         
       

    def test_credential_state_table_exists(self, tmp_path):
        db_path = tmp_path / "store.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
            tables = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {t[0] for t in tables}
                                                                             
                                                             
            assert "credential_state" in table_names

    def test_credential_state_table_has_required_columns(self, tmp_path):
        db_path = tmp_path / "store.db"
        with sqlite3.connect(db_path) as con:
            bootstrap_schema(con)
            cols = con.execute("PRAGMA table_info(credential_state)").fetchall()
            col_names = {c[1] for c in cols}
            required = {
                "credential_id", "provider_id", "state", "cooldown_until",
                "last_success", "last_failure", "consecutive_failures",
                "total_successes", "total_failures"
            }
            assert required.issubset(col_names), f"Missing columns: {required - col_names}"


                                                              
