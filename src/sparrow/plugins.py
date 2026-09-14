                                                                         

                                                                            
                        

                                                            
                                                                    
                                                                       
                                                                            

                                                                               
                                                                             
                                                                                
                                           

                                                                                
                                       
   

from __future__ import annotations

import threading
from collections.abc import Callable

from .models import Provider
from .observe import logger

                                                                               
_PROVIDERS: list[Provider] = []
_ADAPTERS: dict[str, Callable] = {}
_ENTRYPOINTS_LOADED = False
_ENTRYPOINT_PROVIDERS: list[Provider] = []
_ENTRYPOINT_LOCK = threading.Lock()


def register_provider(provider: Provider) -> None:
                                                                         
    if not isinstance(provider, Provider):                                
        raise TypeError(f"expected Provider, got {type(provider).__name__}")
    _PROVIDERS.append(provider)


def register_adapter(name: str, caller: Callable) -> None:
                                                          

                                                                               
                                                                         
                                                                            
       
    if not callable(caller):                                
        raise TypeError("adapter caller must be callable")
    _ADAPTERS[name] = caller


def registered_adapters() -> dict[str, Callable]:
    return dict(_ADAPTERS)


def registered_providers() -> list[Provider]:
                                                                             
    return list(_PROVIDERS) + _load_entrypoint_providers()


def _load_entrypoint_providers() -> list[Provider]:
    global _ENTRYPOINTS_LOADED
    if _ENTRYPOINTS_LOADED:                         
        return list(_ENTRYPOINT_PROVIDERS)
    with _ENTRYPOINT_LOCK:
        if _ENTRYPOINTS_LOADED:                                           
            return list(_ENTRYPOINT_PROVIDERS)
        loaded: list[Provider] = []
        try:
            from importlib.metadata import entry_points

            try:
                eps = entry_points(group="sparrow.providers")
            except TypeError:                                          
                eps = entry_points().get("sparrow.providers", [])                              
            for ep in eps:
                try:
                    obj = ep.load()
                    result = obj() if callable(obj) else obj
                    items = result if isinstance(result, (list, tuple)) else [result]
                    loaded.extend(i for i in items if isinstance(i, Provider))
                except Exception:                                                         
                    logger.debug(
                        "failed to load provider entry point %r",
                        getattr(ep, "name", ep),
                        exc_info=True,
                    )
        except Exception:                                                     
            loaded = []
                                                                                  
                                              
        _ENTRYPOINT_PROVIDERS.extend(loaded)
        _ENTRYPOINTS_LOADED = True
        return list(_ENTRYPOINT_PROVIDERS)


def _reset_for_tests() -> None:
                                                                  
    global _ENTRYPOINTS_LOADED
    _PROVIDERS.clear()
    _ADAPTERS.clear()
    _ENTRYPOINT_PROVIDERS.clear()
    _ENTRYPOINTS_LOADED = False
