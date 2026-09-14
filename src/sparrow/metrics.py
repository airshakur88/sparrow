                                                                       

                                                                                 
                                                                                  
                                                                  

                                                                                 
                                                                                
                                                     
   

from __future__ import annotations

import threading
from dataclasses import dataclass

_ALPHA = 0.3                                            
_FAIL_MIN_SAMPLES = 3                                                         
_FAIL_RATE = 0.5                                                             
                                                                              
                                                                              
                                                                                
                                                                
_UNKNOWN_SCORE = 0.5


@dataclass
class Stat:
                                                               

    ok: int = 0
    fail: int = 0
    ewma_ms: float | None = None                                        
    last_ms: float | None = None
    last_error: str | None = None

    @property
    def total(self) -> int:
        return self.ok + self.fail

    @property
    def success_rate(self) -> float:
        return 1.0 if self.total == 0 else self.ok / self.total

    @property
    def failing(self) -> bool:
                                                                          
        return self.total >= _FAIL_MIN_SAMPLES and self.success_rate < _FAIL_RATE


class Metrics:
                                                         

    def __init__(self, alpha: float = _ALPHA):
        self._alpha = alpha
        self._stats: dict[str, Stat] = {}
        self._lock = threading.Lock()

    def record_success(self, key: str, latency_ms: float) -> None:
        with self._lock:
            st = self._stats.setdefault(key, Stat())
            st.ok += 1
            st.last_ms = latency_ms
            st.ewma_ms = (
                latency_ms
                if st.ewma_ms is None
                else self._alpha * latency_ms + (1 - self._alpha) * st.ewma_ms
            )

    def record_failure(self, key: str, error: str = "") -> None:
        with self._lock:
            st = self._stats.setdefault(key, Stat())
            st.fail += 1
            st.last_error = (error[:200] or None) if error else st.last_error

    def get(self, key: str) -> Stat | None:
        with self._lock:
            st = self._stats.get(key)
            return None if st is None else _copy(st)

    def snapshot(self) -> dict[str, Stat]:
        with self._lock:
            return {k: _copy(v) for k, v in self._stats.items()}

    def failing(self, key: str) -> bool:
        with self._lock:
            st = self._stats.get(key)
            return bool(st and st.failing)

    def score(self, key: str) -> float:
                                                          

                                                                               
                                                                             
                                                                                 
           
        with self._lock:
            return score_stat(self._stats.get(key))


def _copy(st: Stat) -> Stat:
    return Stat(st.ok, st.fail, st.ewma_ms, st.last_ms, st.last_error)


def score_stat(st: Stat | None) -> float:
                                                                                    
    if st is None or st.total == 0:
        return _UNKNOWN_SCORE
    lat_s = (st.ewma_ms or 0.0) / 1000.0
    return (1.0 - st.success_rate) * 10.0 + min(lat_s, 10.0) * 0.1
