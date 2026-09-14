from __future__ import annotations

from pathlib import Path

from sparrow.catalog_validation import validate_catalog
from sparrow.config import load_catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src" / "sparrow" / "providers.toml"


REQUESTED_TARGETS = {
    "ollama": (
        "gpt-oss:120b",
        "gpt-oss:20b",
        "deepseek-v4-pro:0813",
        "deepseek-v4-flash:0731",
    ),
    "cloudflare": (
        "@cf/openai/gpt-oss-120b",
        "@cf/openai/gpt-oss-20b",
        "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
    ),
    "nvidia": (
        "mistralai/mistral-nemotron",
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-ocr-v2",
        "moonshotai/kimi-k3",
        "deepseek-ai/deepseek-v4-flash-0731",
        "nvidia/nemotron-3.5-lightning-30b-a3b",
        "meta/muse-glimmer-30b",
        "poolside/laguna-xs-2.1",
    ),
    "gemini": (
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemma-4-26b-a4b-it",
        "gemma-4-31b-it",
    ),
    "modelscope": (
        "deepseek-ai/DeepSeek-V4-Pro",
        "deepseek-ai/DeepSeek-V4-Pro-0813",
        "deepseek-ai/DeepSeek-V4-Flash",
    ),
    "chutes": ("deepseek-ai/DeepSeek-R1",),
}


def test_task9_requested_models_are_unique_and_provider_qualified() -> None:
    providers = {provider.id: provider for provider in load_catalog(CATALOG)}

    expected_endpoints = {
        "ollama": ("openai", "https://ollama.com/v1", "OLLAMA_API_KEY"),
        "cloudflare": (
            "cloudflare",
            "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
            "CLOUDFLARE_API_TOKEN",
        ),
        "nvidia": ("openai", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
        "gemini": (
            "openai",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "GEMINI_API_KEY",
        ),
        "modelscope": (
            "openai",
            "https://api-inference.modelscope.cn/v1",
            "MODELSCOPE_API_KEY",
        ),
        "chutes": ("openai", "https://api.chutes.ai/v1", "CHUTES_API_KEY"),
    }

    for provider_id, model_names in REQUESTED_TARGETS.items():
        provider = providers[provider_id]
        assert (provider.adapter, provider.base_url, provider.key_env) == expected_endpoints[
            provider_id
        ]
        assert len({model.name for model in provider.models}) == len(provider.models)
        for model_name in model_names:
            matches = [model for model in provider.models if model.name == model_name]
            assert len(matches) == 1, (provider_id, model_name)
            assert matches[0].enabled is True
            assert matches[0].auto is True

    qualified_targets = [
        f"{provider.id}/{model.name}"
        for provider in providers.values()
        for model in provider.models
    ]
    assert len(qualified_targets) == len(set(qualified_targets))


def test_task9_malformed_and_unknown_catalog_rows_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "providers.toml"
    path.write_text(
        "[[provider]]\n"
        'id = "missing-base-url"\n'
        'models = [{ name = "ignored" }]\n\n'
        "[[provider]]\n"
        'id = "unknown-adapter"\n'
        'adapter = "not-an-adapter"\n'
        'base_url = "https://example.test/v1"\n'
        'models = [{ name = "model" }]\n\n'
        "[[provider]]\n"
        'id = "duplicate-model"\n'
        'base_url = "https://example.test/v1"\n'
        'models = [{ name = "same" }, { name = "same" }]\n',
        encoding="utf-8",
    )

    parsed = load_catalog(path)
    assert [provider.id for provider in parsed] == ["unknown-adapter", "duplicate-model"]
    errors = validate_catalog(path)
    assert any("unsupported adapter" in error for error in errors)
    assert any("duplicate model 'same'" in error for error in errors)


def test_task9_does_not_invent_unmapped_provider_endpoints() -> None:
    provider_ids = {provider.id for provider in load_catalog(CATALOG)}
    assert not provider_ids.intersection({"mistral", "glhf", "huggingface"})
