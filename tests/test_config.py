"""Catalog loading + configured-provider filtering."""

from __future__ import annotations

from pathlib import Path

from sparrow.config import (
    configured_providers,
    known_aliases,
    load_catalog,
    load_embedders,
    resolve_alias,
)
from sparrow.models import Model, Provider

PACKAGED_CATALOG = Path(__file__).parents[1] / "src" / "sparrow" / "providers.toml"


def _model(provider: Provider, name: str) -> Model:
    model = provider.model(name)
    assert model is not None
    return model


def _packaged_catalog() -> list[Provider]:
    return load_catalog(PACKAGED_CATALOG)


def test_alias_default_maps_to_auto():
    assert resolve_alias("gpt-4o-mini", {}) == "auto"
    assert resolve_alias("claude-3-5-sonnet-latest", {}) == "auto"


def test_alias_unknown_passthrough():
    assert resolve_alias("groq/llama-3.1-8b-instant", {}) == "groq/llama-3.1-8b-instant"
    assert resolve_alias("auto", {}) == "auto"


def test_alias_env_override():
    env = {"SPARROW_ALIAS_GPT_4O_MINI": "groq/llama-3.3-70b-versatile"}
    assert resolve_alias("gpt-4o-mini", env) == "groq/llama-3.3-70b-versatile"


def test_unrelated_alias_environment_name_is_ignored():
    env = {"OTHER_ALIAS_GPT_4O_MINI": "groq/llama-3.3-70b-versatile"}
    assert resolve_alias("gpt-4o-mini", env) == "auto"


def test_known_aliases_include_env_alias():
    env = {"SPARROW_ALIAS_MY_MODEL": "groq/llama-3.3-70b-versatile"}
    assert "MY_MODEL" in known_aliases(env)


def test_packaged_catalog_loads():
    catalog = _packaged_catalog()
    ids = {p.id for p in catalog}
    assert len(catalog) == 21
    assert ids == {
        "pollinations",
        "llm7",
        "ovh",
        "kilo",
        "gemini",
        "groq",
        "nvidia",
        "openrouter",
        "ollama",
        "github_models",
        "kilo_code",
        "modelscope",
        "cloudflare",
        "cohere",
        "z_ai",
        "chutes",
        "agnes",
        "aion",
        "opencode",
        "bai",
        "free_ai",
    }
    for p in catalog:
        assert p.models  # every provider ships at least one model
        assert p.base_url.startswith("https://")


def test_kimi_k27_catalog_entries_declare_verified_context_window():
    providers = {provider.id: provider for provider in _packaged_catalog()}
    kimi = providers["cloudflare"].model("@cf/moonshotai/kimi-k2.7-code")
    assert kimi is not None
    assert kimi.context is None


def test_cloudflare_catalog_matches_current_free_billing_and_lifecycle():
    cloudflare = next(provider for provider in _packaged_catalog() if provider.id == "cloudflare")

    qwen = cloudflare.model("@cf/qwen/qwen3.8-27b")
    kimi = cloudflare.model("@cf/moonshotai/kimi-k2.7-code")
    assert qwen is not None and qwen.enabled
    assert kimi is not None and kimi.enabled
    assert cloudflare.model("@cf/meta/llama-3.1-70b-instruct") is None


def test_packaged_catalog_reflects_current_model_lifecycle():
    providers = {provider.id: provider for provider in _packaged_catalog()}

    expected_enabled = {
        "pollinations": {"openai-fast", "gpt-oss"},
        "llm7": {"default", "fast", "minimax-m2.7"},
        "kilo": {"openrouter/free", "kilo-auto/free"},
        "gemini": {"gemini-2.5-flash", "gemini-3.8-flash"},
        "groq": {"groq/compound", "qwen/qwen3.8-27b"},
        "cloudflare": {"@cf/qwen/qwen3.8-27b"},
        "opencode": {"nemotron-3-ultra-free", "big-pickle"},
    }
    expected_disabled = {
        "github_models": {model.name for model in providers["github_models"].models},
        "free_ai": {"dynamic-catalog"},
    }

    for provider_id, names in expected_enabled.items():
        models = {model.name: model for model in providers[provider_id].models}
        assert names <= models.keys()
        assert all(models[name].enabled for name in names)
    for provider_id, names in expected_disabled.items():
        models = {model.name: model for model in providers[provider_id].models}
        assert names <= models.keys()
        assert all(not models[name].enabled for name in names)

    pollinations = providers["pollinations"]
    assert _model(pollinations, "openai").auto is False
    assert _model(pollinations, "gpt-oss").auto is False
    assert _model(providers["free_ai"], "dynamic-catalog").auto is False


def test_packaged_catalog_reflects_current_provider_refresh():
    providers = {provider.id: provider for provider in _packaged_catalog()}

    assert {model.name for model in providers["aion"].models} == {
        "aion-labs/aion-2.0",
        "aion-labs/aion-3.0",
        "aion-labs/aion-3.0-mini",
        "aion-labs/aion-rp-llama-3.1-8b",
    }
    assert {model.name for model in providers["modelscope"].models} == {
        "Qwen/Qwen3.8-Flash-Next",
        "Qwen/Qwen3.8-27B",
        "ZhipuAI/GLM-5.2",
        "deepseek-ai/DeepSeek-V4-Pro",
        "deepseek-ai/DeepSeek-V4-Pro-0813",
        "deepseek-ai/DeepSeek-V4-Flash",
        "deepseek-ai/DeepSeek-V4-Flash-0731",
        "MiniMax/MiniMax-M3",
        "Tencent-Hunyuan/Hy3",
        "stepfun-ai/Step-3.7-Flash",
        "Qwen/Qwen3.5-397B-A17B",
    }
    assert "siliconflow" not in providers
    assert _model(providers["llm7"], "minimax-m2.7").enabled
    assert _model(providers["ollama"], "minimax-m3").enabled
    assert load_embedders(PACKAGED_CATALOG) == []


def test_packaged_catalog_reflects_current_automatic_routes():
    providers = {provider.id: provider for provider in _packaged_catalog()}

    for provider_id in ("llm7", "kilo", "nvidia", "openrouter", "ollama"):
        provider = providers[provider_id]
        assert any(model.enabled and model.auto for model in provider.models)

    assert _model(providers["llm7"], "minimax-m2.7").enabled
    assert _model(providers["kilo"], "nvidia/nemotron-3-ultra-550b-a55b:free").enabled
    assert _model(providers["nvidia"], "moonshotai/kimi-k2.6").enabled
    assert _model(providers["ollama"], "minimax-m3").enabled

    assert load_embedders(PACKAGED_CATALOG) == []


def test_packaged_catalog_keeps_retired_github_models_disabled():
    github = next(provider for provider in _packaged_catalog() if provider.id == "github_models")
    assert github.models
    assert all(not model.enabled for model in github.models)
    assert load_embedders(PACKAGED_CATALOG) == []


def test_packaged_catalog_exposes_current_gemini_and_llm7_selectors():
    providers = {provider.id: provider for provider in _packaged_catalog()}

    gemini = providers["gemini"]
    assert _model(gemini, "gemini-2.5-flash").enabled
    assert _model(gemini, "gemini-3.8-flash").enabled
    assert gemini.model("gemini-2.0-flash") is None

    llm7 = providers["llm7"]
    assert _model(llm7, "default").enabled
    assert _model(llm7, "fast").enabled
    assert llm7.model("pro") is None


def test_packaged_catalog_reflects_current_lifecycle_entries():
    providers = {provider.id: provider for provider in _packaged_catalog()}

    assert "longcat" not in providers
    assert "github_models" in providers
    assert all(not model.enabled for model in providers["github_models"].models)
    assert _model(providers["free_ai"], "dynamic-catalog").enabled is False
    assert _model(providers["free_ai"], "dynamic-catalog").auto is False
    assert _model(providers["kilo_code"], "tencent/hy3:free").enabled
    assert _model(providers["z_ai"], "glm-4.7").enabled
    assert _model(providers["chutes"], "deepseek-ai/DeepSeek-R1").enabled
    assert _model(providers["agnes"], "agnes-2.0-flash").enabled
    assert load_embedders(PACKAGED_CATALOG) == []
def test_packaged_embedder_catalog_is_empty_until_an_embedder_is_declared():
    assert load_embedders(PACKAGED_CATALOG) == []


def test_packaged_catalog_keeps_disabled_routes_out_of_automatic_routing():
    providers = {provider.id: provider for provider in _packaged_catalog()}
    assert all(not model.enabled for model in providers["github_models"].models)
    dynamic = providers["free_ai"].model("dynamic-catalog")
    assert dynamic is not None and not dynamic.enabled and not dynamic.auto


def test_groq_catalog_matches_current_free_plan_routes():
    groq = next(provider for provider in _packaged_catalog() if provider.id == "groq")
    models = {model.name: model for model in groq.models}

    assert set(models) == {
        "qwen/qwen3.8-27b",
        "qwen/qwen3.6-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "groq/compound",
        "groq/compound-mini",
        "meta-llama/llama-prompt-guard-2-86m",
        "meta-llama/llama-prompt-guard-2-22m",
    }
    assert models["qwen/qwen3.8-27b"].enabled is True
    assert models["qwen/qwen3.8-27b"].auto is True
    assert models["groq/compound"].rpd == 0
    assert models["groq/compound-mini"].rpd == 0


def test_packaged_catalog_includes_current_provider_metadata():
    providers = {provider.id: provider for provider in _packaged_catalog()}

    cloudflare = providers["cloudflare"]
    assert cloudflare.extra_env == ("CLOUDFLARE_ACCOUNT_ID",)
    assert cloudflare.is_configured(
        {"CLOUDFLARE_API_TOKEN": "token", "CLOUDFLARE_ACCOUNT_ID": "account"}
    )

    assert providers["gemini"].base_url.endswith("/v1beta/openai")
    assert providers["cohere"].base_url == "https://api.cohere.com/v2"
    assert providers["modelscope"].key_env == "MODELSCOPE_API_KEY"
    assert all(model.rpd == 0 for model in providers["modelscope"].models)


def test_keyless_providers_always_configured():
    # OVH (auth=none) and LLM7 (key_optional) are usable with an empty env.
    catalog = _packaged_catalog()
    ids = {p.id for p in configured_providers(catalog, {})}
    assert "ovh" in ids  # keyless
    assert "llm7" in ids  # key optional
    assert "pollinations" in ids  # keyless
    assert "groq" not in ids  # needs a key


def test_pollinations_catalog_matches_current_chat_selectors():
    pollinations = next(provider for provider in _packaged_catalog() if provider.id == "pollinations")
    models = {model.name: model for model in pollinations.models}

    assert set(models) == {
        "openai",
        "openai-fast",
        "gpt-oss",
    }
    assert models["gpt-oss"].enabled is True
    assert models["openai-fast"].auto is True
    assert models["openai"].auto is False
    assert models["gpt-oss"].auto is False


def test_configured_filter_by_env():
    catalog = _packaged_catalog()
    ids = {p.id for p in configured_providers(catalog, {"GROQ_API_KEY": "x"})}
    assert "groq" in ids
    assert "nvidia" not in ids  # no key → excluded
    assert "ovh" in ids  # keyless → always present


def test_cloudflare_requires_extra_env():
    catalog = _packaged_catalog()
    # token alone is not enough; account id is also required
    with_token = {p.id for p in configured_providers(catalog, {"CLOUDFLARE_API_TOKEN": "t"})}
    assert "cloudflare" not in with_token
    with_both = {
        p.id
        for p in configured_providers(
            catalog, {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "acc"}
        )
    }
    assert "cloudflare" in with_both


def test_user_override(tmp_path):
    override = tmp_path / "providers.toml"
    override.write_text(
        "[[provider]]\n"
        'id = "groq"\n'
        'label = "My Groq"\n'
        'adapter = "openai"\n'
        'base_url = "https://example.test/v1"\n'
        'key_env = "GROQ_API_KEY"\n'
        'models = [{ name = "custom-model", rpd = 42 }]\n'
    )
    catalog = load_catalog(path=override)
    groq = next(p for p in catalog if p.id == "groq")
    assert groq.label == "My Groq"
    assert groq.models[0].name == "custom-model"


def test_split_provider_model_guards_against_slash_model_names():
    from sparrow.config import split_provider_model

    pids = {"groq", "huggingface", "kilo", "openrouter"}
    # real provider prefix → split
    assert split_provider_model("groq/llama-3.1-8b", pids) == (["groq"], "llama-3.1-8b")
    # slash-bearing model on a real provider → only first slash is the provider boundary
    assert split_provider_model("huggingface/Qwen/Qwen3-Coder-30B-A3B-Instruct", pids) == (
        ["huggingface"],
        "Qwen/Qwen3-Coder-30B-A3B-Instruct",
    )
    # bare slash-model (no valid provider prefix) → kept whole, NOT mis-split into "Qwen"
    assert split_provider_model("Qwen/Qwen3-Coder-30B-A3B-Instruct", pids) == (
        None,
        "Qwen/Qwen3-Coder-30B-A3B-Instruct",
    )
    assert split_provider_model("deepseek-ai/DeepSeek-R1", pids) == (None, "deepseek-ai/DeepSeek-R1")
    # no slash, or no provider set → unchanged
    assert split_provider_model("gpt-4o-mini", pids) == (None, "gpt-4o-mini")
    assert split_provider_model("groq/x", None) == (None, "groq/x")


def test_custom_provider_rejects_unsafe_environment_variable_names():
    from sparrow.config import _parse_rows

    def row(provider_id, **fields):
        return {
            "id": provider_id,
            "base_url": "https://provider.example/v1",
            "models": [{"name": "model"}],
            **fields,
        }

    providers = _parse_rows(
        [
            row("valid", key_env="PROVIDER_KEY", extra_env=["ACCOUNT_ID"]),
            row("newline", key_env="BAD\nKEY"),
            row("space", extra_env=["BAD NAME"]),
            row("scalar-extra", extra_env="ACCOUNT_ID"),
        ]
    )

    assert [provider.id for provider in providers] == ["valid"]
    assert providers[0].key_env == "PROVIDER_KEY"
    assert providers[0].extra_env == ("ACCOUNT_ID",)


def test_catalog_toml_is_parsed_once_across_surfaces(tmp_path, monkeypatch):
    import sparrow.config as config_module

    path = tmp_path / "all.toml"
    path.write_text(
        "[[provider]]\n"
        'id = "chat"\nbase_url = "https://chat.test/v1"\n'
        'models = [{ name = "chat-model" }]\n'
        "[[embedder]]\n"
        'id = "embed"\nbase_url = "https://embed.test/v1"\n'
        'models = [{ name = "embed-model" }]\n'
        "[[transcriber]]\n"
        'id = "audio"\nbase_url = "https://audio.test/v1"\n'
        'models = [{ name = "audio-model" }]\n'
    )
    original = config_module.tomllib.load
    calls = 0

    def counted(handle):
        nonlocal calls
        calls += 1
        return original(handle)

    monkeypatch.setattr(config_module.tomllib, "load", counted)

    assert load_catalog(path)[0].id == "chat"
    assert load_embedders(path)[0].id == "embed"
    assert config_module.load_transcribers(path)[0].id == "audio"
    assert calls == 1

    first = load_catalog(path)
    first.clear()
    assert load_catalog(path)[0].id == "chat"


def test_local_catalog_marker_only_accepts_canonical_literal_loopback(monkeypatch):
    from sparrow.config import _parse_rows

    monkeypatch.delenv("SPARROW_ALLOW_LOCAL_PROVIDERS", raising=False)

    def row(provider_id, base_url):
        return {
            "id": provider_id,
            "base_url": base_url,
            "local": True,
            "models": [{"name": "model"}],
        }

    parsed = _parse_rows(
        [
            row("v4", "http://127.0.0.2:11434/v1"),
            row("v6", "http://[::1]:1234/v1"),
            row("lan", "http://192.168.1.2:11434/v1"),
            row("localhost", "http://localhost:11434/v1"),
            row("short", "http://127.1:11434/v1"),
            row("mapped", "http://[::ffff:127.0.0.1]:11434/v1"),
            row("public", "https://api.example.test/v1"),
        ]
    )

    assert [provider.id for provider in parsed] == ["v4", "v6"]


def test_catalog_cache_invalidates_on_local_opt_in_and_same_size_replace(
    tmp_path, monkeypatch
):
    import os

    path = tmp_path / "providers.toml"
    first = (
        "[[provider]]\n"
        'id = "local"\nbase_url = "http://192.168.1.2:1234/v1"\n'
        'models = [{ name = "model-a" }]\n'
    )
    second = first.replace("model-a", "model-b")
    path.write_text(first)
    original_stat = path.stat()

    monkeypatch.delenv("SPARROW_ALLOW_LOCAL_PROVIDERS", raising=False)
    assert load_catalog(path) == []
    monkeypatch.setenv("SPARROW_ALLOW_LOCAL_PROVIDERS", "1")
    assert load_catalog(path)[0].models[0].name == "model-a"

    path.write_text(second)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert load_catalog(path)[0].models[0].name == "model-b"
