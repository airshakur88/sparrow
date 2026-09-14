                                     

                                                                                
                                                                          
                                   
   

from __future__ import annotations

ROUTING_MODES = (
    "fair",
    "fast",
    "quality",
    "agent",
    "spread",
    "legacy",
    "model",
    "model-fast",
    "apex",
    "swift",
    "adaptive",
)
PUBLIC_ROUTING_ALIASES = (
    "auto",
    "agent",
    "spread",
    "fast",
    "quality",
    "fair",
    "apex",
    "swift",
    "adaptive",
)
_ROUTING_SET = frozenset(ROUTING_MODES)


def normalize_routing_mode(value: str | None, default: str = "fair") -> str:
                                                                            
    mode = value.strip().lower() if isinstance(value, str) else ""
    if mode in _ROUTING_SET:
        return mode
    fallback = default.strip().lower() if isinstance(default, str) else "fair"
    return fallback if fallback in _ROUTING_SET else "fair"


def routing_override(value: object) -> str | None:
                                                                                
    if not isinstance(value, str):
        return None
    mode = value.strip().lower()
    if mode == "auto":
        return None
    return mode if mode in _ROUTING_SET else None
