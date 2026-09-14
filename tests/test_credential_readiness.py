from sparrow.credential_manager import CredentialManager
from sparrow.credential_store import CredentialStore
from sparrow.credentials import CredentialSlot
from sparrow.readiness import readiness_snapshot


def test_readiness_uses_secondary_slot_without_advancing_cursor(providers, tmp_path):
    manager = CredentialManager(
        [
            CredentialSlot("primary", "alpha", "PRIMARY", "shared"),
            CredentialSlot("secondary", "alpha", "SECONDARY", "shared"),
        ],
        {"SECONDARY": "managed-secret"},
        CredentialStore(tmp_path / "state.db"),
    )

    snapshot = readiness_snapshot(
        providers[:1], env={}, quota={}, cooldowns={}, credential_manager=manager
    )

    row = snapshot.providers[0]
    assert row.configured is True
    assert row.ready is True
    assert row.credential_status is None
    assert manager.availability("alpha") == {"primary": "missing", "secondary": "available"}


def test_readiness_reports_cooling_credentials_without_reserving(providers, tmp_path):
    manager = CredentialManager(
        [CredentialSlot("primary", "alpha", "PRIMARY", "shared")],
        {"PRIMARY": "managed-secret"},
        CredentialStore(tmp_path / "state.db"),
    )
    manager._store.set_cooldown("alpha", "key", "primary", 9_999_999_999_999, None)  # type: ignore[arg-type]

    snapshot = readiness_snapshot(
        providers[:1], env={}, quota={}, cooldowns={}, credential_manager=manager
    )

    assert snapshot.providers[0].credential_status == "cooldown"
