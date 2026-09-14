                                                                                             

                                                                                
                                                                                  
                                                                               
                                                                            
                                                                               

                                                           

                                                                            
                                                                    
                                                                           
                                                                              
                      
                                                                                
                                                                                
                                                                              
                                                                              
                                                                                 

                                                                                   
   

from __future__ import annotations

import atexit
import contextlib
import json
import os
import threading
import weakref
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

try:
    import fcntl                             
except ImportError:                                          
    fcntl = None

                                                                               
                                                           
_FIELDS = ("requests", "prompt_tokens", "completion_tokens", "cache_hits")
                                                                               
                                                                               
_SCHEMA = 1
_LIVE_STORES: weakref.WeakSet[StatsStore] = weakref.WeakSet()


def _reset_live_stores_after_fork() -> None:
    for store in tuple(_LIVE_STORES):
        store._after_fork_child()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_live_stores_after_fork)


def default_stats_path() -> Path:
    override = os.environ.get("SPARROW_STATS_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "sparrow" / "stats.json"


class StatsStore:
                                                                 

    def __init__(
        self,
        path: Path | str | None = None,
        clock: Callable[[], datetime] | None = None,
        flush_every: int | None = None,
        flush_interval: float | None = None,
    ):
        self.path = Path(path) if path is not None else default_stats_path()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()                                                  
        if flush_every is None:
            try:
                flush_every = int(os.environ.get("SPARROW_STATS_FLUSH_EVERY", "1"))
            except ValueError:
                flush_every = 1
        if flush_interval is None:
            try:
                flush_interval = float(
                    os.environ.get("SPARROW_STATS_FLUSH_INTERVAL", "1.0")
                )
            except ValueError:
                flush_interval = 1.0
        self.flush_every = max(1, int(flush_every))
        self.flush_interval = max(0.001, float(flush_interval))
        self._pending: dict[str, int] = {}
        self._pending_ops = 0
        self._pending_first_seen: str | None = None
        self._flush_timer: threading.Timer | None = None
        self._reload_after_fork = False
        self._data: dict = self._load()
        _LIVE_STORES.add(self)
        if self.flush_every > 1:
            atexit.register(self.flush)

    def _after_fork_child(self) -> None:
                                                                            
        self._lock = threading.Lock()
        self._pending = {}
        self._pending_ops = 0
        self._pending_first_seen = None
        self._flush_timer = None
        self._reload_after_fork = True

    def _prepare_after_fork_locked(self) -> None:
        if self._reload_after_fork:
            self._data = self._load()
            self._reload_after_fork = False

    def _load(self) -> dict:
                                                                                   
                                                                                  
                                  
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return {}

    def _load_for_write(self) -> dict:
                                                                                   
                                                                              
                                                                              
                                                                                      
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError, ValueError):
            pass
                                                                                     
        with contextlib.suppress(OSError):
            if self.path.exists():
                self.path.replace(self.path.with_suffix(self.path.suffix + ".corrupt"))
        return {}

    @contextlib.contextmanager
    def _file_lock(self):
                                                                                    
                                                                                      
        if fcntl is None:
            yield
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        try:
            fh = open(lock_path, "w")
        except OSError:
            yield                                                      
            return
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f"{self.path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def add(self, **deltas: int) -> None:
                                                                            

                                                                                 
                                                                      
        clean = {k: int(v) for k, v in deltas.items() if k in _FIELDS and int(v or 0) > 0}
        if not clean:
            return
        with self._lock:
            self._prepare_after_fork_locked()
            for key, value in clean.items():
                self._data[key] = int(self._data.get(key, 0)) + value
                self._pending[key] = int(self._pending.get(key, 0)) + value
            if self._pending_first_seen is None:
                self._pending_first_seen = str(
                    self._data.get("first_seen") or self._iso_now()
                )
            self._data.setdefault("first_seen", self._pending_first_seen)
            self._data.setdefault("version", _SCHEMA)
            self._pending_ops += 1
            if self._pending_ops >= self.flush_every:
                self._flush_locked()
            if self._pending:
                self._schedule_flush_locked()

    def flush(self) -> None:
                                                                                  
        with self._lock:
            self._prepare_after_fork_locked()
            self._cancel_flush_timer_locked()
            self._flush_locked()
            if self._pending:
                self._schedule_flush_locked()

    def _flush_locked(self) -> None:
        if not self._pending:
            return
        with self._file_lock():
            merged = self._load_for_write()
            for key, value in self._pending.items():
                merged[key] = int(merged.get(key, 0)) + value
            merged.setdefault("first_seen", self._pending_first_seen or self._iso_now())
            merged.setdefault("version", _SCHEMA)
            old_data = self._data
            self._data = merged
            try:
                self._save()
            except OSError:
                self._data = old_data
                return
            self._pending.clear()
            self._pending_ops = 0
            self._pending_first_seen = None
            self._cancel_flush_timer_locked()

    def _schedule_flush_locked(self) -> None:
        if not self._pending or self._flush_timer is not None:
            return
        timer = threading.Timer(self.flush_interval, self.flush)
        timer.daemon = True
        self._flush_timer = timer
        timer.start()

    def _cancel_flush_timer_locked(self) -> None:
        timer = self._flush_timer
        self._flush_timer = None
        if timer is not None:
            timer.cancel()

    def snapshot(self) -> dict:
                                                                                 
                                                                                
                                                            
        with self._lock:
            self._prepare_after_fork_locked()
            loaded = self._load()
            for key, value in self._pending.items():
                loaded[key] = int(loaded.get(key, 0)) + value
            self._data = loaded
            out: dict = {k: int(loaded.get(k, 0)) for k in _FIELDS}
            out["first_seen"] = loaded.get("first_seen") or self._pending_first_seen
            return out

    def _iso_now(self) -> str:
        return self._clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
