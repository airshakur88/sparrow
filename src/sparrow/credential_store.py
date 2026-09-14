                                                             

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from .credential_schema import (
    SCHEMA_VERSION,
    CorruptStoreError,
    CredentialStoreError,
    LockedStoreError,
    SchemaVersionError,
    bootstrap_schema,
    check_schema_version,
)
from .credentials import CredentialState

DEFAULT_STORE_PATH: Final = Path.home() / ".config" / "sparrow" / "credential_state.db"


def default_credential_store_path() -> Path:
    raw_path = os.environ.get("SPARROW_CREDENTIAL_STATE_FILE")
    return Path(raw_path).expanduser() if raw_path else DEFAULT_STORE_PATH


class CredentialStore:
                                                                                

    def __init__(self, path: Path | str | None = None,
                 clock: Callable[[], float] | None = None,
                 busy_timeout_ms: int = 1000) -> None:
        self.path = Path(path).expanduser() if path else default_credential_store_path()
        if str(self.path) == ":memory:" or str(self.path).startswith("file:"):
            raise ValueError("In-memory databases are not allowed")
        self._clock = clock or time.time
        self._busy_timeout_ms = max(0, min(5_000, busy_timeout_ms))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(5):
            try:
                self._bootstrap()
                break
            except LockedStoreError:
                if attempt == 4:
                    raise
                time.sleep(min(0.02 * (2**attempt), 0.2))

    @property
    def schema_version(self) -> int:
                                                
        with self._operation() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def __enter__(self) -> CredentialStore:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def upsert(self, provider_id: str, credential_id: str,
               state: CredentialState = CredentialState.RESERVED) -> None:
                                                                                  
        with self._operation() as connection, connection:
            connection.execute(
                """INSERT INTO credential_state(provider_id, credential_id, state)
                   VALUES (?, ?, ?)
                   ON CONFLICT(provider_id, credential_id) DO UPDATE SET state=excluded.state""",
                (provider_id, credential_id, state.value),
            )

    def upsert_credential_state(self, credential_id: str, provider_id: str, state: str) -> None:
        value = CredentialState(state) if state in {item.value for item in CredentialState} else state
        with self._operation() as connection, connection:
            connection.execute(
                "INSERT INTO credential_state(provider_id,credential_id,state) VALUES (?,?,?) "
                "ON CONFLICT(provider_id,credential_id) DO UPDATE SET state=excluded.state",
                (provider_id, credential_id, getattr(value, "value", value)),
            )

    def get_credential_state(self, credential_id: str, provider_id: str) -> dict[str, str | int | float | None] | None:
        return self.get(provider_id, credential_id)

    def get(self, provider_id: str, credential_id: str) -> dict[str, str | int | float | None] | None:
                                                                       
        with self._operation() as connection:
            row = connection.execute(
                "SELECT * FROM credential_state WHERE provider_id=? AND credential_id=?",
                (provider_id, credential_id),
            ).fetchone()
        return dict(row) if row else None

    def list_by_provider(self, provider_id: str) -> list[dict[str, str | int | float | None]]:
                                                                        
        with self._operation() as connection:
            rows = connection.execute(
                "SELECT * FROM credential_state WHERE provider_id=? ORDER BY credential_id",
                (provider_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def usage_report(
        self, *, provider: str | None = None, day: str | None = None
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[str] = []
        if provider:
            filters.append("provider_id=?")
            params.append(provider)
        if day:
            filters.append("day=?")
            params.append(day)
        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        with self._operation() as connection:
            rows = connection.execute(
                "SELECT day,provider_id,credential_id,model,operation,reserved,dispatched,"
                "succeeded,failed,cancelled,unknown,prompt_tokens,completion_tokens,usage_missing "
                "FROM credential_usage" + where + " ORDER BY day,provider_id,credential_id,model,operation",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_state(self, credential_id: str, provider_id: str, state: CredentialState | str) -> bool:
                                                         
        with self._operation() as connection, connection:
            connection.execute(
                "UPDATE credential_state SET state=? WHERE provider_id=? AND credential_id=?",
                (getattr(state, "value", state), provider_id, credential_id),
            )
            row = connection.execute("SELECT changes()").fetchone()
            return bool(row and row[0] == 1)

    def set_cursor(self, provider_id: str, last_id: str) -> None:
        with self._operation() as connection, connection:
            connection.execute(
                "INSERT INTO cursor(provider,last_id,updated_at) VALUES (?,?,?) "
                "ON CONFLICT(provider) DO UPDATE SET last_id=excluded.last_id, updated_at=excluded.updated_at",
                (provider_id, last_id, self._clock()),
            )

    def get_cursor(self, provider_id: str) -> str | None:
        with self._operation() as connection:
            row = connection.execute("SELECT last_id FROM cursor WHERE provider=?", (provider_id,)).fetchone()
        return str(row[0]) if row else None

    def set_cooldown(self, provider: str, scope_type: str, scope_id: str,
                     until_utc: float, reason: object) -> None:
        with self._operation() as connection, connection:
            connection.execute(
                "INSERT INTO cooldown(provider,scope_type,scope_id,until_utc,reason,created_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(provider,scope_type,scope_id) DO UPDATE SET "
                "until_utc=max(cooldown.until_utc, excluded.until_utc), reason=excluded.reason",
                (provider, scope_type, scope_id, until_utc, str(getattr(reason, "value", reason)), self._clock()),
            )

    def get_cooldown(self, provider: str, scope_type: str, scope_id: str) -> float | None:
        with self._operation() as connection:
            row = connection.execute(
                "SELECT until_utc FROM cooldown WHERE provider=? AND scope_type=? AND scope_id=?",
                (provider, scope_type, scope_id),
            ).fetchone()
        return float(row[0]) if row and float(row[0]) > self._clock() else None

    def update_daily_usage(self, provider_id: str, model: str, delta: int = 1) -> int:
        day = time.strftime("%Y-%m-%d", time.gmtime(self._clock()))
        with self._operation() as connection, connection:
            connection.execute(
                "INSERT INTO daily_usage(day,provider_id,model,count) VALUES (?,?,?,?) "
                "ON CONFLICT(day,provider_id,model) DO UPDATE SET count=count+excluded.count",
                (day, provider_id, model, delta),
            )
            return int(connection.execute(
                "SELECT count FROM daily_usage WHERE day=? AND provider_id=? AND model=?",
                (day, provider_id, model),
            ).fetchone()[0])

    def get_daily_usage(self, provider_id: str, model: str) -> int:
        day = time.strftime("%Y-%m-%d", time.gmtime(self._clock()))
        with self._operation() as connection:
            row = connection.execute(
                "SELECT count FROM daily_usage WHERE day=? AND provider_id=? AND model=?",
                (day, provider_id, model),
            ).fetchone()
        return int(row[0]) if row else 0

    def record_success(self, credential_id: str, provider_id: str,
                       when: float | None = None) -> None:
                                                                         
        timestamp = self._clock() if when is None else when
        with self._operation() as connection, connection:
            connection.execute(
                """UPDATE credential_state SET state=?, last_success=?,
                   consecutive_failures=0, total_successes=total_successes+1
                   WHERE provider_id=? AND credential_id=?""",
                ("active", timestamp, provider_id, credential_id),
            )

    def record_failure(self, credential_id: str, provider_id: str,
                       cooldown_until: float | object | None = None,
                       when: float | None = None) -> None:
                                                                   

                                                                           
                                                                             
                                                                         
                         
           
        now = self._clock()
        timestamp = now if when is None else when
        expiry: float | None
        if isinstance(cooldown_until, (int, float)):
            expiry = float(cooldown_until)
        elif cooldown_until is not None and isinstance(when, (int, float)):
            expiry = now + float(when)
            timestamp = now
        else:
            expiry = None
        with self._operation() as connection, connection:
            connection.execute(
                """UPDATE credential_state SET state=?, cooldown_until=?, last_failure=?,
                   consecutive_failures=consecutive_failures+1, total_failures=total_failures+1
                   WHERE provider_id=? AND credential_id=?""",
                ("cooldown" if expiry is not None else CredentialState.FAILED.value,
                 expiry, timestamp,
                 provider_id, credential_id),
            )

    def insert_attempt(
        self,
        attempt_id: str,
        credential_id: str,
        provider_id: str,
        quota_group: str,
        operation: str,
        state: CredentialState | str,
    ) -> None:
                                                                         
        with self._operation() as connection, connection:
            connection.execute(
                """INSERT INTO attempts
                   (attempt_id, credential_id, provider_id, quota_group, operation, state, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (attempt_id, credential_id, provider_id, quota_group, operation,
                 getattr(state, "value", state), self._clock()),
            )

    def reserve_attempt(
        self, attempt_id: str, request_id: str, provider_id: str, credential_id: str,
        quota_group: str, model: str, operation: str, generation: str,
        lease_until: float,
    ) -> None:
                                                            
        now = self._clock()
        with self._operation() as connection, connection:
            connection.execute(
                """INSERT INTO attempts
                   (attempt_id,request_id,credential_id,provider_id,quota_group,model,
                    operation,state,generation,reserved_at,lease_until)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (attempt_id, request_id, credential_id, provider_id, quota_group, model,
                 operation, CredentialState.RESERVED.value, generation, now, lease_until),
            )

    def get_attempt(self, attempt_id: str) -> dict[str, str | int | float | None] | None:
        with self._operation() as connection:
            row = connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        return dict(row) if row else None

    def mark_dispatched(self, attempt_id: str) -> bool:
        with self._operation() as connection, connection:
            result = connection.execute(
                "UPDATE attempts SET state=?, started_at=? WHERE attempt_id=? AND state=?",
                (CredentialState.DISPATCHED.value, self._clock(), attempt_id, CredentialState.RESERVED.value),
            )
            return result.rowcount == 1

    def finalize_attempt(
        self, attempt_id: str, state: CredentialState | str, *,
        prompt_tokens: int | None = None, completion_tokens: int | None = None,
        usage_missing: bool = False, error_class: str | None = None,
        error_message: str | None = None,
    ) -> bool:
                                                                                   
        value = getattr(state, "value", state)
        if value not in {"succeeded", "failed", "cancelled", "unknown"}:
            raise ValueError("attempt finalization requires a terminal state")
        with self._operation() as connection, connection:
            row = connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None or row["state"] in {"succeeded", "failed", "cancelled", "unknown"}:
                return False
            result = connection.execute(
                """UPDATE attempts SET state=?,finished_at=?,prompt_tokens=?,completion_tokens=?,
                   usage_missing=?,error_class=?,error_message=?
                   WHERE attempt_id=? AND state IN ('reserved','dispatched')""",
                (value, self._clock(), prompt_tokens, completion_tokens, int(usage_missing),
                 error_class, error_message, attempt_id),
            )
            if result.rowcount != 1:
                return False
            day = time.strftime("%Y-%m-%d", time.gmtime(row["reserved_at"] or row["started_at"] or self._clock()))
            connection.execute(
                """INSERT INTO daily_usage(day,provider_id,model,count) VALUES (?,?,?,1)
                   ON CONFLICT(day,provider_id,model) DO UPDATE SET count=count+1""",
                (day, row["provider_id"], row["model"]),
            )
            connection.execute(
                """INSERT INTO credential_usage
                   (day,provider_id,credential_id,model,operation,reserved,dispatched,
                    succeeded,failed,cancelled,unknown,prompt_tokens,completion_tokens,usage_missing)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(day,provider_id,credential_id,model,operation) DO UPDATE SET
                    reserved=credential_usage.reserved+excluded.reserved,
                    dispatched=credential_usage.dispatched+excluded.dispatched,
                    succeeded=credential_usage.succeeded+excluded.succeeded,
                    failed=credential_usage.failed+excluded.failed,
                    cancelled=credential_usage.cancelled+excluded.cancelled,
                    unknown=credential_usage.unknown+excluded.unknown,
                    prompt_tokens=CASE WHEN excluded.prompt_tokens IS NULL THEN credential_usage.prompt_tokens
                                       ELSE COALESCE(credential_usage.prompt_tokens,0)+excluded.prompt_tokens END,
                    completion_tokens=CASE WHEN excluded.completion_tokens IS NULL THEN credential_usage.completion_tokens
                                           ELSE COALESCE(credential_usage.completion_tokens,0)+excluded.completion_tokens END,
                    usage_missing=credential_usage.usage_missing+excluded.usage_missing""",
                (day, row["provider_id"], row["credential_id"], row["model"] or "",
                 row["operation"], 1, int(row["state"] == "dispatched"),
                 int(value == "succeeded"), int(value == "failed"), int(value == "cancelled"),
                 int(value == "unknown"), prompt_tokens, completion_tokens,
                 int(usage_missing)),
            )
            return True

    def recover_expired_attempts(self) -> int:
        now = self._clock()
        with self._operation() as connection:
            rows = connection.execute(
                "SELECT attempt_id FROM attempts WHERE state IN ('reserved','dispatched') "
                "AND lease_until IS NOT NULL AND lease_until <= ?", (now,),
            ).fetchall()
        return sum(int(self.finalize_attempt(row[0], CredentialState.UNKNOWN)) for row in rows)

    def update_attempt(
        self,
        attempt_id: str,
        state: CredentialState | str,
        *,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> bool:
                                                                             
        terminal = {"succeeded", "failed", "cancelled"}
        value = str(getattr(state, "value", state))
        with self._operation() as connection, connection:
            result = connection.execute(
                """UPDATE attempts SET state=?, finished_at=?, error_class=?, error_message=?
                   WHERE attempt_id=? AND state NOT IN (?, ?, ?)""",
                (value, self._clock() if value in terminal else None,
                 error_class, error_message, attempt_id, *terminal),
            )
            return result.rowcount == 1

    def prune_old_attempts(self, max_age_days: int) -> int:
                                                                        
        cutoff = self._clock() - max_age_days * 86400
        with self._operation() as connection, connection:
            result = connection.execute("DELETE FROM attempts WHERE started_at < ?", (cutoff,))
            return result.rowcount

    def prune_old_cooldowns(self) -> int:
                                                              
        with self._operation() as connection, connection:
            result = connection.execute("DELETE FROM cooldown WHERE until_utc <= ?", (self._clock(),))
            return result.rowcount

    def prune_old_daily_usage(self, max_age_days: int) -> int:
                                                                   
        cutoff = time.strftime("%Y-%m-%d", time.gmtime(self._clock() - max_age_days * 86400))
        with self._operation() as connection, connection:
            result = connection.execute("DELETE FROM daily_usage WHERE day < ?", (cutoff,))
            return result.rowcount

    def migrate(self) -> None:
        self._bootstrap()

    def reserve_round_robin(self, provider_id: str, credential_ids: list[str]) -> str | None:
                                                                             
        if not credential_ids:
            return None
        with self._operation() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT last_id FROM cursor WHERE provider=?", (provider_id,),
            ).fetchone()
            start = credential_ids.index(row[0]) + 1 if row and row[0] in credential_ids else 0
            selected = next((credential_ids[(start + offset) % len(credential_ids)]
                             for offset in range(len(credential_ids))), None)
            if selected is not None:
                connection.execute(
                    "INSERT INTO cursor(provider,last_id,updated_at) VALUES (?,?,?) "
                    "ON CONFLICT(provider) DO UPDATE SET last_id=excluded.last_id, updated_at=excluded.updated_at",
                    (provider_id, selected, self._clock()),
                )
            return selected

    def select_next_credential(self, provider_id: str, credential_ids: list[str],
                               excluded: set[str] | None = None) -> str | None:
        eligible = [item for item in credential_ids if item not in (excluded or set())]
        return self.reserve_round_robin(provider_id, eligible)

    def _bootstrap(self) -> None:
        try:
            with self._operation() as connection, connection:
                version = check_schema_version(connection)
                if version > SCHEMA_VERSION:
                    raise SchemaVersionError(f"unsupported schema version {version}")
                bootstrap_schema(connection)
        except CredentialStoreError:
            raise
        except sqlite3.OperationalError as error:
            raise LockedStoreError("database operation could not acquire its lock") from error
        except sqlite3.DatabaseError as error:
            raise CorruptStoreError("database is corrupt or unavailable") from error

    @contextmanager
    def _operation(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self.path, timeout=self._busy_timeout_ms / 1000)
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
        except sqlite3.DatabaseError as error:
            raise CorruptStoreError("database is corrupt or unavailable") from error
        try:
            yield connection
        except sqlite3.OperationalError as error:
            raise LockedStoreError("database operation could not acquire its lock") from error
        except sqlite3.DatabaseError as error:
            raise CredentialStoreError("database operation failed") from error
        finally:
            connection.close()
