                                                             

                                                                              
                                                                          
                                                                           
                                                                  

                                                                             
                                                                                
                                                                                
   

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping

logger = logging.getLogger("sparrow")

                                                                                  
                                                                                    
EventHook = Callable[[dict], None]

_LEVELS = {
    "1": logging.INFO,
    "true": logging.INFO,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


def configure_logging_from_env(env: Mapping[str, str] | None = None) -> bool:
                                                                        

                                                                                
                                                                     
       
    env = env if env is not None else os.environ
    raw = (env.get("SPARROW_LOG") or "").strip().lower()
    if not raw:
        return False
    level = _LEVELS.get(raw, logging.INFO)
    logger.setLevel(level)
    if not any(getattr(h, "_sparrow", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("sparrow %(levelname)s %(message)s"))
        handler._sparrow = True                              
        logger.addHandler(handler)
    return True


def emit(hook: EventHook | None, event: str, **fields) -> None:
                                                                        

                                                                             
                                                      
       
    payload = {"event": event, **fields}
    if logger.isEnabledFor(logging.DEBUG) or (
        event in ("error", "cooldown", "exhausted") and logger.isEnabledFor(logging.INFO)
    ):
        _log(event, payload)
    if hook is not None:
        try:
            hook(payload)
        except Exception:                                                    
            logger.debug("event hook raised", exc_info=True)


def _log(event: str, payload: dict) -> None:
    detail = " ".join(f"{k}={v}" for k, v in payload.items() if k != "event")
    if event in ("error", "exhausted"):
        logger.info("%s %s", event, detail)
    elif event == "cooldown":
        logger.info("%s %s", event, detail)
    else:
        logger.debug("%s %s", event, detail)
