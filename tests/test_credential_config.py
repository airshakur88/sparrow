                                                                                        

from __future__ import annotations

import pytest

from sparrow.credential_config import ParseError, filter_available_slots, parse_credentials
from sparrow.credentials import CredentialSlot
from sparrow.models import Model, Provider


                                     
def make_provider(
    provider_id: str,
    *,
    key_env: str | None = "TEST_KEY",
    auth: str = "bearer",
    key_optional: bool = False,
    extra_env: tuple[str, ...] = (),
) -> Provider:
    return Provider(
        id=provider_id,
        label=provider_id,
        adapter="openai",
        base_url="https://api.example.com/v1",
        models=(Model(name="test-model"),),
        key_env=key_env,
        auth=auth,
        key_optional=key_optional,
        extra_env=extra_env,
    )


class TestParseCredentialsValid:
                                             

    def test_parse_single_valid_credential(self):
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                    "enabled": True,
                }
            ]
        }
        providers = [make_provider("groq")]
        env = {"GROQ_API_KEY": "sk-test123"}

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 1
        slot = slots[0]
        assert slot.id == "key1"
        assert slot.provider == "groq"
        assert slot.env_var == "GROQ_API_KEY"
        assert slot.quota_group == "groq"
        assert slot.enabled is True

    def test_parse_multiple_credentials_same_provider(self):
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "GROQ_API_KEY_1",
                    "quota_group": "groq",
                    "enabled": True,
                },
                {
                    "provider": "groq",
                    "id": "key2",
                    "env_var": "GROQ_API_KEY_2",
                    "quota_group": "groq",
                    "enabled": True,
                },
            ]
        }
        providers = [make_provider("groq")]
        env = {"GROQ_API_KEY_1": "sk-1", "GROQ_API_KEY_2": "sk-2"}

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 2
        assert {s.id for s in slots} == {"key1", "key2"}

    def test_parse_credentials_different_providers(self):
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                    "enabled": True,
                },
                {
                    "provider": "cohere",
                    "id": "key1",
                    "env_var": "COHERE_API_KEY",
                    "quota_group": "cohere",
                    "enabled": True,
                },
            ]
        }
        providers = [make_provider("groq"), make_provider("cohere")]
        env = {"GROQ_API_KEY": "sk-g", "COHERE_API_KEY": "sk-c"}

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 2
        assert {s.provider for s in slots} == {"groq", "cohere"}

    def test_parse_credentials_with_env_var_from_config_toml_keys(self):
                                                                                     
        config = {
            "keys": {"GROQ_API_KEY": "from-config"},
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                    "enabled": True,
                }
            ]
        }
        providers = [make_provider("groq")]
        env = {}                                                       

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 1
                                                                                                          

    def test_parse_credentials_precedence_real_env_overrides_config_toml(self):
                                                                                       
        config = {
            "keys": {"GROQ_API_KEY": "from-config"},
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                    "enabled": True,
                }
            ]
        }
        providers = [make_provider("groq")]
        env = {"GROQ_API_KEY": "from-real-env"}                 

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 1

    def test_parse_credentials_enabled_false_is_preserved(self):
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                    "enabled": False,
                }
            ]
        }
        providers = [make_provider("groq")]
        env = {"GROQ_API_KEY": "sk-test"}

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 1
        assert slots[0].enabled is False

    def test_parse_credentials_enabled_defaults_to_true(self):
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                }
            ]
        }
        providers = [make_provider("groq")]
        env = {"GROQ_API_KEY": "sk-test"}

        slots = parse_credentials(config, providers, env)

        assert slots[0].enabled is True

    def test_parse_credentials_enabled_string_coercion(self):
                                                    
        for val, expected in [("true", True), ("false", False), ("1", True), ("0", False)]:
            config = {
                "credentials": [
                    {
                        "provider": "groq",
                        "id": "key1",
                        "env_var": "GROQ_API_KEY",
                        "quota_group": "groq",
                        "enabled": val,
                    }
                ]
            }
            providers = [make_provider("groq")]
            env = {"GROQ_API_KEY": "sk-test"}

            slots = parse_credentials(config, providers, env)
            assert slots[0].enabled is expected, f"failed for {val!r}"


class TestParseCredentialsInvalid:
                                                                                

    def test_duplicate_provider_id_raises(self):
        config = {
            "credentials": [
                {"provider": "groq", "id": "key1", "env_var": "K1", "quota_group": "g"},
                {"provider": "groq", "id": "key1", "env_var": "K2", "quota_group": "g"},
            ]
        }
        providers = [make_provider("groq")]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)
        assert "duplicate credential id" in str(exc.value)

    def test_invalid_id_format_raises(self):
        for bad_id in ["", "key with spaces", "key@invalid", "a" * 65, "-starts-with-hyphen"]:
            config = {
                "credentials": [
                    {"provider": "groq", "id": bad_id, "env_var": "K1", "quota_group": "g"}
                ]
            }
            providers = [make_provider("groq")]
            env = {}

            with pytest.raises(ParseError) as exc:
                parse_credentials(config, providers, env)
            assert "invalid credential id" in str(exc.value)

    def test_invalid_env_var_format_raises(self):
        for bad_env in ["", "123STARTS_WITH_DIGIT", "HAS-DASH", "HAS SPACE", "HAS@SIGN"]:
            config = {
                "credentials": [
                    {"provider": "groq", "id": "key1", "env_var": bad_env, "quota_group": "g"}
                ]
            }
            providers = [make_provider("groq")]
            env = {}

            with pytest.raises(ParseError) as exc:
                parse_credentials(config, providers, env)
            assert "invalid env_var" in str(exc.value)

    def test_missing_required_fields_raises(self):
        for missing in ["provider", "id", "env_var", "quota_group"]:
            row = {"provider": "groq", "id": "key1", "env_var": "K1", "quota_group": "g"}
            del row[missing]
            config = {"credentials": [row]}
            providers = [make_provider("groq")]
            env = {}

            with pytest.raises(ParseError) as exc:
                parse_credentials(config, providers, env)
            assert "missing required" in str(exc.value).lower() or "must be a" in str(exc.value).lower()

    def test_unknown_provider_raises(self):
        config = {
            "credentials": [
                {"provider": "unknown", "id": "key1", "env_var": "K1", "quota_group": "g"}
            ]
        }
        providers = [make_provider("groq")]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)
        assert "unknown provider" in str(exc.value)

    def test_auth_none_provider_rejects_credentials(self):
        config = {
            "credentials": [
                {"provider": "opencode", "id": "key1", "env_var": "K1", "quota_group": "g"}
            ]
        }
        providers = [make_provider("opencode", auth="none", key_env=None)]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)
        assert 'auth="none"' in str(exc.value)

    def test_unsupported_field_raises(self):
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "K1",
                    "quota_group": "g",
                    "unsupported_field": "value",
                }
            ]
        }
        providers = [make_provider("groq")]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)
        assert "unsupported field" in str(exc.value)

    def test_invalid_enabled_type_raises(self):
        config = {
            "credentials": [
                {"provider": "groq", "id": "key1", "env_var": "K1", "quota_group": "g", "enabled": "not-a-bool"}
            ]
        }
        providers = [make_provider("groq")]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)
        assert "enabled must be a boolean" in str(exc.value)

    def test_empty_quota_group_raises(self):
        config = {
            "credentials": [
                {"provider": "groq", "id": "key1", "env_var": "K1", "quota_group": ""}
            ]
        }
        providers = [make_provider("groq")]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)
        assert "quota_group must be a non-empty string" in str(exc.value)

    def test_credentials_not_a_list_raises(self):
        config = {"credentials": "not-a-list"}
        providers = [make_provider("groq")]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)
        assert "[credentials] must be an array" in str(exc.value)

    def test_credential_entry_not_a_table_raises(self):
        config = {"credentials": ["not-a-dict"]}
        providers = [make_provider("groq")]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)
        assert "must be a table" in str(exc.value)


class TestImplicitLegacySynthesis:
                                                                            

    def test_no_explicit_credentials_synthesizes_legacy(self):
        config = {"credentials": []}
        providers = [make_provider("groq", key_env="GROQ_API_KEY")]
        env = {"GROQ_API_KEY": "sk-test"}

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 1
        slot = slots[0]
        assert slot.id == "legacy"
        assert slot.provider == "groq"
        assert slot.env_var == "GROQ_API_KEY"
        assert slot.quota_group == "groq"                           
        assert slot.enabled is True

    def test_explicit_credentials_replace_implicit(self):
                                                                                     
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "explicit-key",
                    "env_var": "GROQ_API_KEY_EXPLICIT",
                    "quota_group": "groq",
                    "enabled": True,
                }
            ]
        }
        providers = [make_provider("groq", key_env="GROQ_API_KEY")]
        env = {"GROQ_API_KEY": "implicit", "GROQ_API_KEY_EXPLICIT": "explicit"}

        slots = parse_credentials(config, providers, env)

                                                          
        assert len(slots) == 1
        assert slots[0].id == "explicit-key"
        assert slots[0].env_var == "GROQ_API_KEY_EXPLICIT"

    def test_provider_without_key_env_no_legacy(self):
                                                                           
        config = {"credentials": []}
        providers = [make_provider("opencode", auth="none", key_env=None)]
        env = {}

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 0

    def test_key_optional_provider_with_explicit_never_anonymous(self):
                                                                                        
        config = {
            "credentials": [
                {
                    "provider": "llm7",
                    "id": "explicit",
                    "env_var": "LLM7_API_KEY",
                    "quota_group": "llm7",
                    "enabled": True,
                }
            ]
        }
        providers = [make_provider("llm7", key_env="LLM7_API_KEY", key_optional=True)]
        env = {"LLM7_API_KEY": "sk-test"}

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 1
        assert slots[0].id == "explicit"
                                          

    def test_multiple_providers_some_explicit_some_legacy(self):
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "explicit",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                    "enabled": True,
                }
            ]
        }
        providers = [
            make_provider("groq", key_env="GROQ_API_KEY"),
            make_provider("cohere", key_env="COHERE_API_KEY"),
        ]
        env = {"GROQ_API_KEY": "sk-g", "COHERE_API_KEY": "sk-c"}

        slots = parse_credentials(config, providers, env)

        assert len(slots) == 2
        ids = {s.id for s in slots}
        assert "explicit" in ids
        assert "legacy" in ids
        providers_set = {s.provider for s in slots}
        assert providers_set == {"groq", "cohere"}


class TestDeduplication:
                                                                     

    def test_deduplicate_equal_secrets_same_provider(self):
                                                                           
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "GROQ_API_KEY_1",
                    "quota_group": "groq",
                    "enabled": True,
                },
                {
                    "provider": "groq",
                    "id": "key2",
                    "env_var": "GROQ_API_KEY_2",
                    "quota_group": "groq",
                    "enabled": True,
                },
            ]
        }
        providers = [make_provider("groq")]
                                                  
        env = {"GROQ_API_KEY_1": "sk-same", "GROQ_API_KEY_2": "sk-same"}

        slots = parse_credentials(config, providers, env)

                                              
        assert len(slots) == 1
        assert slots[0].id == "key1"

    def test_deduplication_only_within_same_provider(self):
                                                                         
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                    "enabled": True,
                },
                {
                    "provider": "cohere",
                    "id": "key1",
                    "env_var": "COHERE_API_KEY",
                    "quota_group": "cohere",
                    "enabled": True,
                },
            ]
        }
        providers = [make_provider("groq"), make_provider("cohere")]
        env = {"GROQ_API_KEY": "sk-same", "COHERE_API_KEY": "sk-same"}

        slots = parse_credentials(config, providers, env)

                                                   
        assert len(slots) == 2

    def test_none_secrets_not_deduplicated(self):
                                                                                                    
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "key1",
                    "env_var": "MISSING_1",
                    "quota_group": "groq",
                    "enabled": True,
                },
                {
                    "provider": "groq",
                    "id": "key2",
                    "env_var": "MISSING_2",
                    "quota_group": "groq",
                    "enabled": True,
                },
            ]
        }
        providers = [make_provider("groq")]
        env = {}                         

        slots = parse_credentials(config, providers, env)

                                                                          
        assert len(slots) == 2
        assert {s.id for s in slots} == {"key1", "key2"}

    def test_disabled_slot_not_deduplicated(self):
                                                                                                   
        config = {
            "credentials": [
                {
                    "provider": "groq",
                    "id": "enabled-key",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                    "enabled": True,
                },
                {
                    "provider": "groq",
                    "id": "disabled-key",
                    "env_var": "GROQ_API_KEY",
                    "quota_group": "groq",
                    "enabled": False,
                },
            ]
        }
        providers = [make_provider("groq")]
        env = {"GROQ_API_KEY": "sk-same"}

        slots = parse_credentials(config, providers, env)

                                                                              
                                                                                           
                                                         
        assert len(slots) == 1
        assert slots[0].id == "enabled-key"


class TestFilterAvailableSlots:
                                                    

    def test_available_slot_with_secret(self):
        slot = CredentialSlot(
            id="key1", provider="groq", env_var="GROQ_API_KEY", quota_group="groq", enabled=True
        )
        env = {"GROQ_API_KEY": "sk-test"}

        available, unavailable = filter_available_slots([slot], env)

        assert len(available) == 1
        assert available[0].id == "key1"
        assert len(unavailable) == 0

    def test_unavailable_missing_secret(self):
        slot = CredentialSlot(
            id="key1", provider="groq", env_var="MISSING_KEY", quota_group="groq", enabled=True
        )
        env = {}

        available, unavailable = filter_available_slots([slot], env)

        assert len(available) == 0
        assert len(unavailable) == 1
        assert unavailable[0][0].id == "key1"
        assert unavailable[0][1] == "no_secret"

    def test_unavailable_blank_secret(self):
        slot = CredentialSlot(
            id="key1", provider="groq", env_var="EMPTY_KEY", quota_group="groq", enabled=True
        )
        env = {"EMPTY_KEY": ""}

        available, unavailable = filter_available_slots([slot], env)

        assert len(available) == 0
        assert len(unavailable) == 1
        assert unavailable[0][1] == "no_secret"

    def test_unavailable_disabled(self):
        slot = CredentialSlot(
            id="key1", provider="groq", env_var="GROQ_API_KEY", quota_group="groq", enabled=False
        )
        env = {"GROQ_API_KEY": "sk-test"}

        available, unavailable = filter_available_slots([slot], env)

        assert len(available) == 0
        assert len(unavailable) == 1
        assert unavailable[0][1] == "disabled"

    def test_mixed_available_and_unavailable(self):
        slots = [
            CredentialSlot(id="a", provider="groq", env_var="K1", quota_group="g", enabled=True),
            CredentialSlot(id="b", provider="groq", env_var="K2", quota_group="g", enabled=False),
            CredentialSlot(id="c", provider="groq", env_var="K3", quota_group="g", enabled=True),
        ]
        env = {"K1": "sk-1", "K3": "sk-3"}              

        available, unavailable = filter_available_slots(slots, env)

        assert len(available) == 2
        assert {s.id for s in available} == {"a", "c"}
        assert len(unavailable) == 1
        assert unavailable[0][0].id == "b"
        assert unavailable[0][1] == "disabled"


class TestCredentialSlotImmutability:
                                                         

    def test_slot_is_frozen(self):
        slot = CredentialSlot(
            id="key1", provider="groq", env_var="K1", quota_group="g", enabled=True
        )
        with pytest.raises(AttributeError):
            slot.enabled = False
        with pytest.raises(AttributeError):
            slot.id = "other"


class TestParseErrorAttributes:
                                                                           

    def test_parse_error_has_provider_and_credential(self):
        config = {
            "credentials": [
                {"provider": "groq", "id": "bad@id", "env_var": "K1", "quota_group": "g"}
            ]
        }
        providers = [make_provider("groq")]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)

        assert exc.value.provider_id == "groq"
        assert exc.value.credential_id == "bad@id"

    def test_parse_error_for_unknown_provider(self):
        config = {
            "credentials": [
                {"provider": "unknown", "id": "key1", "env_var": "K1", "quota_group": "g"}
            ]
        }
        providers = [make_provider("groq")]
        env = {}

        with pytest.raises(ParseError) as exc:
            parse_credentials(config, providers, env)

        assert exc.value.provider_id == "unknown"
        assert exc.value.credential_id == "key1"
