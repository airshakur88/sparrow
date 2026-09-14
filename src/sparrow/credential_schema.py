                                                          

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1


class CorruptStoreError(RuntimeError):
    pass


class LockedStoreError(RuntimeError):
    pass


class SchemaVersionError(RuntimeError):
    pass


def get_user_version(connection: object) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])                              


def check_schema_version(connection: object) -> int:
    version = get_user_version(connection)
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(f"newer than supported version: {version}")
    return version


def bootstrap_schema(connection: object) -> None:
    connection.execute("PRAGMA journal_mode=WAL")                              
    connection.execute("PRAGMA synchronous=FULL")                              
    connection.execute("PRAGMA foreign_keys=ON")                              
    connection.executescript(SCHEMA_SQL)                              
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")                              


@dataclass(slots=True)
class CredentialStoreError(RuntimeError):
                                                                     

    detail: str

    def __str__(self) -> str:
        return f"credential store error: {self.detail}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS credential_state (
    provider_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN
      ('reserved','dispatched','succeeded','failed','cancelled','unknown','active','cooldown')),
    cooldown_until REAL,
    last_success REAL,
    last_failure REAL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    total_successes INTEGER NOT NULL DEFAULT 0 CHECK (total_successes >= 0),
    total_failures INTEGER NOT NULL DEFAULT 0 CHECK (total_failures >= 0),
    PRIMARY KEY (provider_id, credential_id)
);
CREATE TABLE IF NOT EXISTS cursor (
    provider TEXT PRIMARY KEY,
    last_id TEXT,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS cooldown (
    provider TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    until_utc REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (provider, scope_type, scope_id)
);
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL DEFAULT '',
    credential_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    quota_group TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reserved','dispatched','succeeded','failed','cancelled','unknown')),
    generation TEXT,
    reserved_at REAL NOT NULL DEFAULT 0,
    started_at REAL,
    lease_until REAL,
    finished_at REAL,
    prompt_tokens INTEGER CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
    completion_tokens INTEGER CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
    usage_missing INTEGER NOT NULL DEFAULT 0 CHECK (usage_missing IN (0,1)),
    error_class TEXT,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS daily_usage (
    day TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider_id, model)
);

CREATE INDEX IF NOT EXISTS attempts_state_lease_idx ON attempts(state, lease_until);
CREATE INDEX IF NOT EXISTS attempts_finished_idx ON attempts(finished_at);
CREATE TABLE IF NOT EXISTS credential_usage (
    day TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    model TEXT NOT NULL,
    operation TEXT NOT NULL,
    reserved INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    dispatched INTEGER NOT NULL DEFAULT 0 CHECK (dispatched >= 0),
    succeeded INTEGER NOT NULL DEFAULT 0 CHECK (succeeded >= 0),
    failed INTEGER NOT NULL DEFAULT 0 CHECK (failed >= 0),
    cancelled INTEGER NOT NULL DEFAULT 0 CHECK (cancelled >= 0),
    unknown INTEGER NOT NULL DEFAULT 0 CHECK (unknown >= 0),
    prompt_tokens INTEGER CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
    completion_tokens INTEGER CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
    usage_missing INTEGER NOT NULL DEFAULT 0 CHECK (usage_missing >= 0),
    PRIMARY KEY (day, provider_id, credential_id, model, operation)
);
"""
