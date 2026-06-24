"""Tiny in-process rate limiter (fixed window per key).

Dependency-free. Used to throttle the admin auth endpoint against password brute-force.
Single-process only — behind multiple workers each process keeps its own window, which
is acceptable for this defensive purpose (it still caps per-worker attempts sharply).
For a hard global limit across replicas, move this to Redis.
"""
from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, max_hits: int, window_s: int) -> None:
        self.max_hits = max_hits
        self.window_s = window_s
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """Return True if the call is allowed; False if the key is over its limit."""
        now = time.monotonic()
        floor = now - self.window_s
        with self._lock:
            times = [t for t in self._hits.get(key, ()) if t > floor]
            if len(times) >= self.max_hits:
                self._hits[key] = times  # keep pruned window; don't record this attempt
                return False
            times.append(now)
            self._hits[key] = times
            # Opportunistic cleanup so the dict can't grow without bound.
            if len(self._hits) > 4096:
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > floor}
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


def client_ip(request) -> str:
    """Best-effort client IP, honouring a single proxy hop via X-Forwarded-For."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
