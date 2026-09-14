from sparrow.credential_manager import CredentialManager
from sparrow.credential_store import CredentialStore
from sparrow.credentials import CredentialOperation, CredentialSelection, CredentialSlot


def test_reserve_round_robin_skips_missing_and_rotates(tmp_path):
    store = CredentialStore(tmp_path / "state.db")
    manager = CredentialManager(
        [
            CredentialSlot("missing", "groq", "MISSING", "shared"),
            CredentialSlot("a", "groq", "A", "shared"),
            CredentialSlot("b", "groq", "B", "shared"),
        ],
        {"A": "secret-a", "B": "secret-b"},
        store,
    )
    first = manager.reserve("groq", "model", CredentialOperation.CHAT)
    second = manager.reserve("groq", "model", CredentialOperation.CHAT)
    assert isinstance(first, CredentialSelection)
    assert isinstance(second, CredentialSelection)
    assert first.credential_id == "a"
    assert second.credential_id == "b"
