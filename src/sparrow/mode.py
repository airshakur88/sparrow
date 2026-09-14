                             

                                                                       
                                                                        
                                                                            
                                
   

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping
from typing import Any, TextIO

MODE_ENV = "SPARROW_MODE"
WISE_MODE = "wise"
NORMAL_MODE = "normal"
WISE_DEFAULT_MAX_TOKENS = 512
WISE_DEFAULT_ROUTING = "spread"
def current_mode(
    env: Mapping[str, str] | None = None,
    *,
    override: str | None = None,
    settings: Mapping[str, object] | None = None,
) -> str:
                                                       
    env = os.environ if env is None else env
    raw = override or env.get(MODE_ENV) or (settings or {}).get("mode") or NORMAL_MODE
    mode = str(raw).strip().lower()
    return WISE_MODE if mode == WISE_MODE else NORMAL_MODE


def is_wise_enabled(
    env: Mapping[str, str] | None = None,
    *,
    override: str | None = None,
    settings: Mapping[str, object] | None = None,
) -> bool:
    return current_mode(env, override=override, settings=settings) == WISE_MODE


def default_routing_for_mode(env: Mapping[str, str], settings: Mapping[str, object]) -> str:
                                                                                  
    env_routing = env.get("SPARROW_ROUTING")
    if env_routing:
        return str(env_routing).lower()
    cfg_routing = settings.get("routing")
    if cfg_routing:
        return str(cfg_routing).lower()
    return WISE_DEFAULT_ROUTING if is_wise_enabled(env, settings=settings) else "fair"


def target_key(target: Any) -> str:
    return f"{target.provider.id}::{target.model}"


def declared_targets(targets: Iterable[Any]) -> list[Any]:
    return [target for target in targets if int(getattr(target, "rpd", 0) or 0) > 0]


def declared_quota_exhausted(targets: Iterable[Any], snapshot: Mapping[str, int]) -> bool:
                                                                                
    declared = declared_targets(targets)
    if not declared:
        return False
    for target in declared:
        used = int(snapshot.get(target_key(target), 0))
        if used < int(target.rpd):
            return False
    return True


def targets_with_declared_headroom(
    targets: Iterable[Any], snapshot: Mapping[str, int]
) -> list[Any]:
    available: list[Any] = []
    for target in targets:
        rpd = int(getattr(target, "rpd", 0) or 0)
        if rpd <= 0:
            continue
        if int(snapshot.get(target_key(target), 0)) < rpd:
            available.append(target)
    return available


def confirm_expensive_operation(
    label: str,
    *,
    assume_yes: bool = False,
    stdin: TextIO | None = None,
    stderr: TextIO | None = None,
) -> bool:
                                                                                      
    if assume_yes:
        return True
    stdin = stdin or sys.stdin
    stderr = stderr or sys.stderr
    if stdin is None or not getattr(stdin, "isatty", lambda: False)():
        print(
            f"sparrow: wise mode refuses {label} in non-interactive mode; "
            "pass --yes or lower --max-models.",
            file=stderr,
        )
        return False
    print(f"sparrow wise mode: {label}. Continue? [y/N] ", end="", file=stderr)
    try:
        answer = stdin.readline().strip().lower()
    except OSError:
        return False
    return answer in {"y", "yes"}


