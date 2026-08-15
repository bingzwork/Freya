"""Small, reusable runtime-performance primitives used by existing Freya services."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Iterable, Optional


class BoundedTTLCache:
    def __init__(self, max_size: int = 256, ttl_seconds: float = 60.0):
        self.max_size = max(1, int(max_size))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._items: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any, default: Any = None) -> Any:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                self.misses += 1
                return default
            expires, value = item
            if self.ttl_seconds and expires <= now:
                self._items.pop(key, None)
                self.misses += 1
                return default
            self._items.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._items[key] = (time.monotonic() + self.ttl_seconds, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)

    def invalidate(self, key: Any = None) -> None:
        with self._lock:
            if key is None:
                self._items.clear()
            else:
                self._items.pop(key, None)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"size": len(self._items), "max_size": self.max_size, "hits": self.hits, "misses": self.misses}


@dataclass
class ProfileSample:
    name: str
    duration_ms: float


class RuntimeProfiler:
    def __init__(self, recorder: Optional[Callable[[str, float], None]] = None):
        self._recorder = recorder

    def measure(self, name: str):
        profiler = self
        class _Measure:
            def __enter__(self):
                self.started = time.perf_counter()
                return self
            def __exit__(self, *_):
                duration = (time.perf_counter() - self.started) * 1000.0
                if profiler._recorder:
                    profiler._recorder(name, duration)
        return _Measure()


def bounded_parallel_map(fn: Callable[[Any], Any], items: Iterable[Any], max_workers: int = 4) -> list[Any]:
    values = list(items)
    if len(values) <= 1:
        return [fn(value) for value in values]
    with ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), len(values)))) as pool:
        futures = [pool.submit(fn, value) for value in values]
        return [future.result() for future in futures]


__all__ = ["BoundedTTLCache", "RuntimeProfiler", "ProfileSample", "bounded_parallel_map"]
