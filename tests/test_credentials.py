                                               

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sparrow.credentials import (
    CooldownReason,
    CredentialOperation,
    CredentialSelection,
    CredentialSlot,
    CredentialState,
    CredentialUnavailable,
    UnavailableReason,
)
from sparrow.models import Model, Provider


class TestCredentialEnums:
                                              

    def test_credential_operation_values(self) -> None:
        assert CredentialOperation.CHAT.value == "chat"
        assert CredentialOperation.EMBED.value == "embed"
        assert CredentialOperation.TRANSCRIBE.value == "transcribe"
        assert CredentialOperation.DISCOVERY.value == "discovery"
        assert CredentialOperation.PROBE.value == "probe"

    def test_cooldown_reason_values(self) -> None:
        assert CooldownReason.KEY_AUTH.value == "key_auth"
        assert CooldownReason.KEY_TEMP.value == "key_temp"
        assert CooldownReason.QUOTA_GROUP.value == "quota_group"
        assert CooldownReason.ROUTE.value == "route"

    def test_credential_state_values(self) -> None:
        assert CredentialState.RESERVED.value == "reserved"
        assert CredentialState.DISPATCHED.value == "dispatched"
        assert CredentialState.SUCCEEDED.value == "succeeded"
        assert CredentialState.FAILED.value == "failed"
        assert CredentialState.CANCELLED.value == "cancelled"
        assert CredentialState.UNKNOWN.value == "unknown"

    def test_unavailable_reason_values(self) -> None:
        assert UnavailableReason.NO_SECRET.value == "no_secret"
        assert UnavailableReason.DISABLED.value == "disabled"
        assert UnavailableReason.COOLDOWN.value == "cooldown"
        assert UnavailableReason.DUPLICATE_ALIAS.value == "duplicate_alias"
        assert UnavailableReason.NO_CREDENTIALS_CONFIGURED.value == "no_credentials_configured"


class TestCredentialSlot:
                                               

    def test_credential_slot_creation(self) -> None:
        slot = CredentialSlot(
            id="slot-1",
            provider="groq",
            env_var="GROQ_API_KEY",
            quota_group="groq",
            enabled=True,
        )
        assert slot.id == "slot-1"
        assert slot.provider == "groq"
        assert slot.env_var == "GROQ_API_KEY"
        assert slot.quota_group == "groq"
        assert slot.enabled is True

    def test_credential_slot_default_enabled(self) -> None:
        slot = CredentialSlot(
            id="slot-1",
            provider="groq",
            env_var="GROQ_API_KEY",
            quota_group="groq",
        )
        assert slot.enabled is True

    def test_credential_slot_frozen_cannot_mutate(self) -> None:
        slot = CredentialSlot(
            id="slot-1",
            provider="groq",
            env_var="GROQ_API_KEY",
            quota_group="groq",
        )
        with pytest.raises(FrozenInstanceError):
            slot.enabled = False
        with pytest.raises(FrozenInstanceError):
            slot.id = "slot-2"

    def test_credential_slot_repr_safe(self) -> None:
        slot = CredentialSlot(
            id="slot-1",
            provider="groq",
            env_var="GROQ_API_KEY",
            quota_group="groq",
        )
        repr_str = repr(slot)
        assert "slot-1" in repr_str
        assert "groq" in repr_str
        assert "GROQ_API_KEY" in repr_str


class TestCredentialSelection:
                                                                   

    def test_credential_selection_creation(self) -> None:
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret="sk-test123",
            attempt_id="abc123",
            generation="gen-1",
        )
        assert selection.credential_id == "slot-1"
        assert selection.provider_id == "groq"
        assert selection.quota_group == "groq"
        assert selection.secret == "sk-test123"
        assert selection.attempt_id == "abc123"
        assert selection.generation == "gen-1"

    def test_credential_selection_secret_none_allowed(self) -> None:
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret=None,
            attempt_id="abc123",
            generation="gen-1",
        )
        assert selection.secret is None

    def test_credential_selection_auto_generates_attempt_id(self) -> None:
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret="sk-test123",
            attempt_id="",
            generation="gen-1",
        )
        assert selection.attempt_id != ""
        assert len(selection.attempt_id) == 32               

    def test_credential_selection_repr_redacts_secret(self) -> None:
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret="sk-test123",
            attempt_id="abc123",
            generation="gen-1",
        )
        repr_str = repr(selection)
        assert "sk-test123" not in repr_str
        assert "***REDACTED***" in repr_str

    def test_credential_selection_repr_none_secret(self) -> None:
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret=None,
            attempt_id="abc123",
            generation="gen-1",
        )
        repr_str = repr(selection)
        assert "None" in repr_str
        assert "***REDACTED***" not in repr_str

    def test_credential_selection_str_same_as_repr(self) -> None:
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret="sk-test123",
            attempt_id="abc123",
            generation="gen-1",
        )
        assert str(selection) == repr(selection)

    def test_credential_selection_frozen_cannot_mutate(self) -> None:
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret="sk-test123",
            attempt_id="abc123",
            generation="gen-1",
        )
        with pytest.raises(FrozenInstanceError):
            selection.secret = "new-secret"
        with pytest.raises(FrozenInstanceError):
            selection.credential_id = "slot-2"


class TestCredentialUnavailable:
                                                      

    def test_credential_unavailable_creation(self) -> None:
        unavailable = CredentialUnavailable(
            reason=UnavailableReason.NO_SECRET,
            provider_id="groq",
            detail="GROQ_API_KEY not set",
        )
        assert unavailable.reason == UnavailableReason.NO_SECRET
        assert unavailable.provider_id == "groq"
        assert unavailable.detail == "GROQ_API_KEY not set"

    def test_credential_unavailable_repr(self) -> None:
        unavailable = CredentialUnavailable(
            reason=UnavailableReason.COOLDOWN,
            provider_id="groq",
            detail="key_auth cooldown until 2026-01-01",
        )
        repr_str = repr(unavailable)
        assert "COOLDOWN" in repr_str or "cooldown" in repr_str
        assert "groq" in repr_str
        assert "key_auth cooldown" in repr_str

    def test_credential_unavailable_frozen_cannot_mutate(self) -> None:
        unavailable = CredentialUnavailable(
            reason=UnavailableReason.NO_SECRET,
            provider_id="groq",
            detail="GROQ_API_KEY not set",
        )
        with pytest.raises(FrozenInstanceError):
            unavailable.reason = UnavailableReason.DISABLED


class TestLegacyProviderCompatibility:
                                                                     

    def test_provider_is_configured_with_key(self) -> None:
        provider = Provider(
            id="groq",
            label="Groq",
            adapter="openai",
            base_url="https://api.groq.com/openai/v1",
            key_env="GROQ_API_KEY",
            models=(Model("llama-3.1-8b-instant", rpd=0),),
        )
        env = {"GROQ_API_KEY": "sk-test"}
        assert provider.is_configured(env) is True

    def test_provider_is_configured_without_key(self) -> None:
        provider = Provider(
            id="groq",
            label="Groq",
            adapter="openai",
            base_url="https://api.groq.com/openai/v1",
            key_env="GROQ_API_KEY",
            models=(Model("llama-3.1-8b-instant", rpd=0),),
        )
        env = {}
        assert provider.is_configured(env) is False

    def test_provider_is_configured_keyless(self) -> None:
        provider = Provider(
            id="opencode",
            label="OpenCode",
            adapter="openai",
            base_url="https://opencode.ai/zen/v1",
            auth="none",
            models=(Model("nemotron-3-ultra-free", rpd=0),),
        )
        env = {}
        assert provider.is_configured(env) is True

    def test_provider_is_configured_key_optional_with_key(self) -> None:
        provider = Provider(
            id="llm7",
            label="LLM7",
            adapter="openai",
            base_url="https://api.llm7.io/v1",
            key_env="LLM7_API_KEY",
            key_optional=True,
            models=(Model("llm7-model", rpd=0),),
        )
        env = {"LLM7_API_KEY": "sk-test"}
        assert provider.is_configured(env) is True

    def test_provider_is_configured_key_optional_without_key(self) -> None:
        provider = Provider(
            id="llm7",
            label="LLM7",
            adapter="openai",
            base_url="https://api.llm7.io/v1",
            key_env="LLM7_API_KEY",
            key_optional=True,
            models=(Model("llm7-model", rpd=0),),
        )
        env = {}
        assert provider.is_configured(env) is True

    def test_provider_is_configured_extra_env_required(self) -> None:
        provider = Provider(
            id="synthetic",
            label="Synthetic",
            adapter="openai",
            base_url="https://synthetic.test/v1",
            key_env="SYNTHETIC_API_KEY",
            extra_env=("SYNTHETIC_ACCOUNT_ID",),
            models=(Model("synthetic-model", rpd=0),),
        )
        env = {"SYNTHETIC_API_KEY": "token", "SYNTHETIC_ACCOUNT_ID": "account"}
        assert provider.is_configured(env) is True

    def test_provider_is_configured_missing_extra_env(self) -> None:
        provider = Provider(
            id="synthetic",
            label="Synthetic",
            adapter="openai",
            base_url="https://synthetic.test/v1",
            key_env="SYNTHETIC_API_KEY",
            extra_env=("SYNTHETIC_ACCOUNT_ID",),
            models=(Model("synthetic-model", rpd=0),),
        )
        env = {"SYNTHETIC_API_KEY": "token"}
        assert provider.is_configured(env) is False

    def test_provider_api_key_returns_key(self) -> None:
        provider = Provider(
            id="groq",
            label="Groq",
            adapter="openai",
            base_url="https://api.groq.com/openai/v1",
            key_env="GROQ_API_KEY",
            models=(Model("llama-3.1-8b-instant", rpd=0),),
        )
        env = {"GROQ_API_KEY": "sk-test123"}
        assert provider.api_key(env) == "sk-test123"

    def test_provider_api_key_returns_none_when_missing(self) -> None:
        provider = Provider(
            id="groq",
            label="Groq",
            adapter="openai",
            base_url="https://api.groq.com/openai/v1",
            key_env="GROQ_API_KEY",
            models=(Model("llama-3.1-8b-instant", rpd=0),),
        )
        env = {}
        assert provider.api_key(env) is None

    def test_provider_api_key_returns_none_when_no_key_env(self) -> None:
        provider = Provider(
            id="opencode",
            label="OpenCode",
            adapter="openai",
            base_url="https://opencode.ai/zen/v1",
            auth="none",
            models=(Model("nemotron-3-ultra-free", rpd=0),),
        )
        env = {}
        assert provider.api_key(env) is None

    def test_provider_keyless_property(self) -> None:
        provider = Provider(
            id="opencode",
            label="OpenCode",
            adapter="openai",
            base_url="https://opencode.ai/zen/v1",
            auth="none",
            models=(Model("nemotron-3-ultra-free", rpd=0),),
        )
        assert provider.keyless is True

    def test_provider_keyless_false_when_key_required(self) -> None:
        provider = Provider(
            id="groq",
            label="Groq",
            adapter="openai",
            base_url="https://api.groq.com/openai/v1",
            key_env="GROQ_API_KEY",
            models=(Model("llama-3.1-8b-instant", rpd=0),),
        )
        assert provider.keyless is False

    def test_provider_keyless_true_when_key_optional(self) -> None:
        provider = Provider(
            id="llm7",
            label="LLM7",
            adapter="openai",
            base_url="https://api.llm7.io/v1",
            key_env="LLM7_API_KEY",
            key_optional=True,
            models=(Model("llm7-model", rpd=0),),
        )
        assert provider.keyless is True

    def test_provider_keyless_true_when_no_key_env(self) -> None:
        provider = Provider(
            id="custom",
            label="Custom",
            adapter="openai",
            base_url="https://custom.test/v1",
            key_env=None,
            models=(Model("custom-model", rpd=0),),
        )
        assert provider.keyless is True

    def test_provider_model_lookup(self) -> None:
        provider = Provider(
            id="groq",
            label="Groq",
            adapter="openai",
            base_url="https://api.groq.com/openai/v1",
            key_env="GROQ_API_KEY",
            models=(
                Model("llama-3.1-8b-instant", rpd=0),
                Model("llama-3.3-70b-versatile", rpd=100),
            ),
        )
        model = provider.model("llama-3.1-8b-instant")
        assert model is not None
        assert model.name == "llama-3.1-8b-instant"
        assert model.rpd == 0

        missing = provider.model("nonexistent")
        assert missing is None


class TestCredentialSelectionSecretHandling:
                                                                                     

    def test_secret_not_in_repr(self) -> None:
                                                     
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret="sk-very-secret-key-12345",
            attempt_id="abc123",
            generation="gen-1",
        )
        repr_str = repr(selection)
        assert "sk-very-secret-key-12345" not in repr_str
        assert "very-secret" not in repr_str

    def test_secret_not_in_str(self) -> None:
                                                    
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret="sk-another-secret",
            attempt_id="abc123",
            generation="gen-1",
        )
        str_repr = str(selection)
        assert "sk-another-secret" not in str_repr
        assert "another-secret" not in str_repr

    def test_secret_field_accessible_directly(self) -> None:
                                                                        
        selection = CredentialSelection(
            credential_id="slot-1",
            provider_id="groq",
            quota_group="groq",
            secret="sk-direct-access",
            attempt_id="abc123",
            generation="gen-1",
        )
        assert selection.secret == "sk-direct-access"
