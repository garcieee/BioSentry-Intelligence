"""In-memory TTL snapshot cache: the default backend, valid for ONE process.

Thread-safe, bounded (least recently used goes first) and expiring. Expiry is a stored
deadline compared with a monotonic clock, not a countdown, so a late read is judged by when the
entry was written. The deadline clock is deliberately not the ward clock: the synthetic ward is
frozen in time and its entries must still expire.

Per-process by construction: a second worker would hold its own copy and serve it after the
first had moved on. `Settings` refuses to start more than one worker while this backend is on.
"""

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from .base import Snapshot

DEFAULT_MAX_ENTRIES = 4096


class MemoryCache:
    def __init__(
        self,
        *,
        ttl_s: float,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if not (math.isfinite(ttl_s) and ttl_s > 0):
            raise ValueError("ttl_s must be a positive number of seconds")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._now = now
        self._entries: OrderedDict[str, tuple[Snapshot, float]] = OrderedDict()
        self._lock = threading.Lock()

    def _live(self, key: str, at: float) -> Snapshot | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        snapshot, expires_at = entry
        if at >= expires_at:
            del self._entries[key]
            return None
        return snapshot

    def get(self, key: str) -> Snapshot | None:
        with self._lock:
            snapshot = self._live(key, self._now())
            if snapshot is not None:
                self._entries.move_to_end(key)
            return snapshot

    def put(self, key: str, snapshot: Snapshot) -> bool:
        with self._lock:
            at = self._now()
            held = self._live(key, at)
            if held is not None and held.revision > snapshot.revision:
                return False
            self._entries[key] = (snapshot, at + self._ttl_s)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return True

    def evict(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def keys(self) -> tuple[str, ...]:
        """The keys currently held (live or not yet swept). For tests and diagnostics."""
        with self._lock:
            return tuple(self._entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
