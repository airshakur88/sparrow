from __future__ import annotations

import pytest

from sparrow.config import load_catalog
from sparrow.conformance import ConformanceStore
from sparrow.models import Model, Provider
from sparrow.router import Pool, Target
from sparrow.virtual_models import (
    VIRTUAL_MODELS,
    virtual_model,
    virtual_routing,
    virtual_targets,
)


def test_virtual_models_are_declared_with_routing_presets():
    assert [model.name for model in VIRTUAL_MODELS] == [
        "sparrow/spark-flash",
        "sparrow/spark",
        "sparrow/galaxy",
    ]
    spark_flash = virtual_model("sparrow/spark-flash")
    spark = virtual_model("sparrow/spark")
    galaxy = virtual_model("sparrow/galaxy")
    assert spark_flash is not None and spark_flash.routing == "swift"
    assert spark is not None and spark.routing == "fair"
    assert galaxy is not None and galaxy.routing == "apex"
    assert virtual_model("spark-flash") is spark_flash
    assert virtual_model("spark") is spark
    assert virtual_model("galaxy") is galaxy


def test_virtual_model_targets_include_only_keyless_providers(env, quota):
    keyed = Provider(
        id="keyed",
        label="Keyed",
        adapter="openai",
        base_url="https://keyed.test/v1",
        key_env="KEYED_KEY",
        models=(Model("keyed-model"),),
    )
    keyless = Provider(
        id="free",
        label="Free",
        adapter="openai",
        base_url="https://free.test/v1",
        auth="none",
        models=(Model("free-model"),),
    )
    pool = Pool([keyed, keyless], env={"KEYED_KEY": "secret"}, quota=quota)

    for name in ("sparrow/spark-flash", "sparrow/spark", "sparrow/galaxy"):
        targets = pool.rank_targets([], model=name)
        assert [target.name for target in targets] == ["free/free-model"]


def test_real_model_filter_remains_exact(env, quota):
    keyed = Provider(
        id="keyed",
        label="Keyed",
        adapter="openai",
        base_url="https://keyed.test/v1",
        key_env="KEYED_KEY",
        models=(Model("shared"),),
    )
    keyless = Provider(
        id="free",
        label="Free",
        adapter="openai",
        base_url="https://free.test/v1",
        auth="none",
        models=(Model("shared"),),
    )
    pool = Pool([keyed, keyless], env={"KEYED_KEY": "secret"}, quota=quota)

    assert {target.name for target in pool.rank_targets([], model="shared")} == {
        "keyed/shared",
        "free/shared",
    }


def test_virtual_routing_uses_keyless_not_billing_classification(env, quota):
    paid_keyless = Provider(
        id="paid-keyless",
        label="Paid Keyless",
        adapter="openai",
        base_url="https://paid-keyless.test/v1",
        auth="none",
        billing="paid",
        models=(Model("model"),),
    )
    free_keyed = Provider(
        id="free-keyed",
        label="Free Keyed",
        adapter="openai",
        base_url="https://free-keyed.test/v1",
        key_env="FREE_KEYED_API_KEY",
        billing="free",
        models=(Model("model"),),
    )
    pool = Pool([paid_keyless, free_keyed], env={}, quota=quota)

    assert [target.name for target in pool.rank_targets([], model="sparrow/spark")] == [
        "paid-keyless/model"
    ]


def test_virtual_model_targets_exclude_key_required_models(env, quota):
    provider = Provider(
        id="optional",
        label="Optional",
        adapter="openai",
        base_url="https://optional.test/v1",
        key_env="OPTIONAL_KEY",
        key_optional=True,
        models=(Model("free-model"), Model("gemini", requires_key=True)),
    )
    pool = Pool([provider], env={}, quota=quota)

    targets = pool.rank_targets([], model="sparrow/spark-flash")

    assert [target.name for target in targets] == ["optional/free-model"]


def test_virtual_model_excludes_key_required_model_even_when_optional_key_is_set(env, quota):
    provider = Provider(
        id="optional",
        label="Optional",
        adapter="openai",
        base_url="https://optional.test/v1",
        key_env="OPTIONAL_KEY",
        key_optional=True,
        models=(Model("free-model"), Model("gemini", requires_key=True)),
    )
    pool = Pool([provider], env={"OPTIONAL_KEY": "secret"}, quota=quota)

    targets = pool.rank_targets([], model="sparrow/spark")

    assert [target.name for target in targets] == ["optional/free-model"]


def test_virtual_model_has_no_targets_when_only_keyed_provider_matches(env, quota):
    provider = Provider(
        id="keyed",
        label="Keyed",
        adapter="openai",
        base_url="https://keyed.test/v1",
        key_env="KEYED_KEY",
        models=(Model("model"),),
    )
    pool = Pool([provider], env={"KEYED_KEY": "secret"}, quota=quota)

    assert pool.rank_targets([], model="sparrow/spark") == []


@pytest.mark.parametrize("name", [model.name for model in VIRTUAL_MODELS])
def test_packaged_catalog_virtual_targets_are_keyless(name, quota):
    catalog = load_catalog()
    pool = Pool(catalog, env={}, quota=quota)

    targets = pool.rank_targets([], model=name)
    expected = {
        (provider.id, model.name)
        for provider in catalog
        if provider.keyless
        for model in provider.models
        if model.enabled and not model.requires_key
    }

    assert {(target.provider.id, target.model) for target in targets} == expected
    assert all(target.provider.keyless for target in targets)
    assert all(
        model is None or not model.requires_key
        for target in targets
        for model in (target.provider.model(target.model),)
    )


@pytest.mark.parametrize("name", [model.name for model in VIRTUAL_MODELS])
def test_packaged_catalog_requires_key_model_is_never_virtual_target(name, quota):
    pool = Pool(load_catalog(), env={"LLM7_API_KEY": "secret"}, quota=quota)

    targets = pool.rank_targets([], model=name)

    assert ("llm7", "gemini-3.1-flash-lite") not in {
        (target.provider.id, target.model) for target in targets
    }


@pytest.mark.parametrize("name", [model.name for model in VIRTUAL_MODELS])
def test_packaged_catalog_provider_filter_cannot_enable_keyed_target(name, quota):
    pool = Pool(load_catalog(), env={"GROQ_API_KEY": "secret"}, quota=quota)

    keyless_targets = pool.rank_targets([], model=name, providers=["ovh"])
    keyed_targets = pool.rank_targets([], model=name, providers=["groq"])

    assert keyless_targets
    assert all(target.provider.id == "ovh" for target in keyless_targets)
    assert keyed_targets == []


def test_virtual_targets_filters_provider_and_model_requirements():
    keyed = Provider(
        id="keyed",
        label="Keyed",
        adapter="openai",
        base_url="https://keyed.test/v1",
        key_env="KEYED_KEY",
        models=(Model("plain"), Model("required", requires_key=True)),
    )
    keyless = Provider(
        id="free",
        label="Free",
        adapter="openai",
        base_url="https://free.test/v1",
        auth="none",
        models=(Model("plain"), Model("required", requires_key=True)),
    )
    targets = [
        Target(provider, model.name, 0, None)
        for provider in (keyed, keyless)
        for model in provider.models
    ]

    filtered = virtual_targets(targets, "sparrow/galaxy")

    assert [(target.provider.id, target.model) for target in filtered] == [("free", "plain")]
    assert virtual_targets(targets, "shared-model") == targets


def test_virtual_routing_preserves_explicit_routing():
    assert virtual_routing("sparrow/spark", None) == "fair"
    assert virtual_routing("sparrow/spark", "fast") is None
    assert virtual_routing("not-virtual", None) is None


@pytest.mark.parametrize("name", ["sparrow/galaxy", "sparrow/spark", "sparrow/spark-flash"])
def test_virtual_features_allow_unknown_but_reject_known_failures(tmp_path, quota, name):
    provider = Provider("free", "Free", "openai", "https://free.test/v1",
                        (Model("unknown"), Model("incompatible")), auth="none")
    store = ConformanceStore(tmp_path / "conformance.json")
    store.record(provider, "incompatible", "tools", status="unsupported",
                 classification="unsupported")
    pool = Pool([provider], env={}, quota=quota, conformance=store)

    targets = pool._feature_targets(pool._all_targets(model=name), {"tools", "streaming"},
                                    exact_pin=False, model=name)

    assert [target.model for target in targets] == ["unknown"]
