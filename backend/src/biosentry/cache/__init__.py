"""Snapshot cache: protocol, in-memory TTL backend, keys and single-flight (CP7).

A Redis adapter is a drop-in behind `SnapshotCache` (it needs JSON for `Snapshot`, which a test
proves round-trips); it lands with the compose setup that gives it a real server to test
against.
"""

from .base import SNAPSHOT_SCHEMA_VERSION, Snapshot, SnapshotCache
from .keys import is_snapshot_key, snapshot_key
from .memory import MemoryCache
from .singleflight import SingleFlight

__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "MemoryCache",
    "SingleFlight",
    "Snapshot",
    "SnapshotCache",
    "is_snapshot_key",
    "snapshot_key",
]
