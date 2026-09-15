from __future__ import annotations

from sparrow.models import Model, Provider
from sparrow.router import Pool
from sparrow.virtual_models import VIRTUAL_MODELS, virtual_model


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
