                                                                           

           

                            

                                     
                                                            
                     
   

from ._version import __version__
from .errors import (
    AllProvidersExhausted,
    ContextWindowExceeded,
    NoProvidersConfigured,
    SparrowError,
)
from .metrics import Metrics
from .models import EmbedReply, Model, Provider, Reply
from .plugins import register_adapter, register_provider
from .router import Pool


def __getattr__(name: str):
                                                                                 
                                                 
    if name == "AsyncPool":
        from .aio import AsyncPool

        return AsyncPool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Pool",
    "AsyncPool",
    "Provider",
    "Model",
    "Reply",
    "EmbedReply",
    "Metrics",
    "register_provider",
    "register_adapter",
    "SparrowError",
    "NoProvidersConfigured",
    "AllProvidersExhausted",
    "ContextWindowExceeded",
    "__version__",
]
