"""What the snapshot cache stores, and the protocol every backend implements (CP7).

A snapshot is one patient's scoring decision at one input revision, with the timestamps it was
computed from. Deliberately absent from it:

  - the rank: rank is relative to the set of patients a clinician may see, so it is computed
    per request from the snapshots in that clinician's scope and is never stored;
  - the clinician: scope is resolved first, on every request, and is never cached;
  - names, beds and every measurement value beyond what the decision itself cites.

Everything stored is a timestamp or a count, never a duration: an age is `now - inputs_as_of`,
computed when a response is built, so a snapshot served late is not served with a stale
"12 s ago".

The cache is an optimisation and never an authority. It may be down, empty, or wrong about
being fresh; the service that owns it re-checks a snapshot against the patient's current input
revision before using it and computes directly when the cache cannot answer.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from biosentry.domain.arbiter import NotRanked, Ranked

# Bump when the shape of `Snapshot` changes. A test pins the JSON schema to this number, so a
# change to the shape cannot ship without the bump that keeps old entries from being read.
SNAPSHOT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Snapshot:
    patient_id: str
    schema_version: int
    scorer_sha: str  # digest of the code that produced `decision`
    revision: int  # the patient's input revision this was computed from (compare-and-set)
    computed_at: datetime  # ward time when it was computed
    inputs_as_of: datetime | None  # when the newest NEWS2 input was observed; None if none
    decision: Ranked | NotRanked


class SnapshotCache(Protocol):
    """A keyed store of snapshots with expiry. Implementations may raise: callers fail open."""

    def get(self, key: str) -> Snapshot | None:
        """The live snapshot under `key`, or None when absent or expired."""
        ...

    def put(self, key: str, snapshot: Snapshot) -> bool:
        """Store `snapshot`, unless a snapshot of a NEWER revision already holds the key.

        This is the compare-and-set that stops a slow, stale computation from overwriting the
        result of a write that finished first. Returns whether the snapshot was stored.
        """
        ...

    def evict(self, key: str) -> None:
        """Drop whatever is stored under `key`."""
        ...
