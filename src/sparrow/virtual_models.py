from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class VirtualModel:
    name: str
    routing: str
    description: str


VIRTUAL_MODELS = (
    VirtualModel(
        "sparrow/spark-flash",
        "swift",
        "Keyless models prioritized for lower latency",
    ),
    VirtualModel(
        "sparrow/spark",
        "fair",
        "Balanced rotation across configured keyless models",
    ),
    VirtualModel(
        "sparrow/galaxy",
        "apex",
        "Keyless models prioritized for capability",
    ),
)

_BY_NAME = {
    key: model
    for model in VIRTUAL_MODELS
    for key in (model.name, model.name.removeprefix("sparrow/"))
}


def virtual_model(name: str | None) -> VirtualModel | None:
    return _BY_NAME.get(name or "")


def virtual_targets(
    targets: Iterable,
    name: str | None,
    virtual_providers: Collection[str] | None = None,
) -> list:
    if virtual_model(name) is None:
        return list(targets)
    allowed_providers = virtual_providers or ()
    return [
        target
        for target in targets
        if (
            target.provider.keyless
            or (
                target.provider.billing == "paid"
                and target.provider.id in allowed_providers
            )
        )
        and not (
            (model := target.provider.model(target.model)) is not None
            and model.requires_key
        )
    ]


def virtual_routing(name: str | None, requested: str | None) -> str | None:
    if requested is not None:
        return None
    model = virtual_model(name)
    return model.routing if model is not None else None
