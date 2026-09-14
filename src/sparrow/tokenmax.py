                                                                        

                                                                          
                                             

                                                                             
                                                                       
                                                                                
                                                                              
                                                                               
                                                                    

                                                                           
   

from __future__ import annotations

import concurrent.futures as _cf
import itertools
import sys
import threading
from collections.abc import Callable

from .router import Pool

                                                                                  
                                                                                  
HARD_CAP = 256
WORKERS = 32

                                                                                 
                                                         
RAINBOW_BANNER = "🟥🟧🟨🟩🟦🟪"

                                                                
_ANSI_COLORS = (196, 208, 226, 46, 51, 21, 201)
_PULSE = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"


class RainbowThrob:
                                                                         

                                                                                  
                                                                                  
                                                                        
       

    def __init__(self, label: str):
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tty = bool(getattr(sys.stderr, "isatty", lambda: False)())

    def __enter__(self) -> RainbowThrob:
        if self._tty:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        else:
            sys.stderr.write(f"🌈 {self.label} …\n")
            sys.stderr.flush()
        return self

    def _run(self) -> None:
        for i in itertools.count():
            if self._stop.wait(0.1):
                break
            c = _ANSI_COLORS[i % len(_ANSI_COLORS)]
            p = _PULSE[i % len(_PULSE)]
            sys.stderr.write(f"\r\033[38;5;{c}m{p} 🌈 {self.label} {p}\033[0m\033[K")
            sys.stderr.flush()

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            sys.stderr.write("\r\033[K")                           
            sys.stderr.flush()
        elif not self._tty:
            sys.stderr.write(f"🌈 {self.label} — done\n")
            sys.stderr.flush()


def select_targets(
    pool: Pool,
    messages: list[dict],
    max_models=None,
    *,
    routing: str | None = None,
) -> tuple[list, int]:
                                                                              

                                                                                  
                                                                                 
                                                                                  
                                        

                                                                                  
                                                                          
       
    by_provider: dict[str, list] = {}
    for t in pool.rank_targets(messages, routing=routing):
        by_provider.setdefault(t.provider.id, []).append(t)
    interleaved = [t for tier in itertools.zip_longest(*by_provider.values()) for t in tier if t]
    default_limit = min(len(interleaved), HARD_CAP)
    if max_models is None:
        limit = default_limit
    else:
        try:
            limit = max(1, min(HARD_CAP, int(max_models)))
        except (TypeError, ValueError):
            limit = default_limit
    picks = interleaved[:limit]
    n_providers = len({t.provider.id for t in picks})
    return picks, n_providers


def fan_out(
    pool: Pool,
    messages: list[dict],
    picks: list,
    *,
    max_tokens: int,
    timeout: float = 90.0,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[list[tuple[str, str | None]], list[str]]:
                                                                    

                                                                                  
                                                                                
                              
       
    total = len(picks)
    counter = itertools.count(1)
    lock = threading.Lock()

    def ask_one(t):
        try:
            r = pool.chat(
                messages,
                model=t.model,
                providers=[t.provider.id],
                max_tokens=max_tokens,
                timeout=timeout,
            )
            out = (f"{r.provider_id}/{r.model}", r.text, None)
        except Exception as exc:                                                             
            out = (f"{t.provider.id}/{t.model}", None, f"{type(exc).__name__}: {exc}")
        if progress is not None:
            with lock:
                done = next(counter)
            progress(done, total, out[0])
        return out

    if total == 0:
        return [], []
    with _cf.ThreadPoolExecutor(max_workers=min(WORKERS, total)) as ex:
        results = list(ex.map(ask_one, picks))
    answered = [(lbl, txt) for lbl, txt, err in results if not err]
    failed = [lbl for lbl, _txt, err in results if err]
    return answered, failed
