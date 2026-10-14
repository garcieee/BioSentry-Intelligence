"""Per-patient scoring decisions, served through the snapshot cache (CP7).

Rules this module owns:

  - A snapshot is used only if it was computed from the patient's CURRENT input revision, by
    the current scorer, in the current schema. A cache that is stale, empty or unreachable
    cannot change an answer, only how long it takes (fail open).
  - A write never trusts the cache to notice it: `refresh` drops the entry and computes the
    fresh snapshot, and the revision check catches any writer that forgot.
  - A computation that finishes after a newer write cannot overwrite it (compare-and-set on
    the revision, in the cache), and concurrent misses share one computation (single-flight).
  - Whatever is stored is keyed by patient only. Scope is resolved by the caller before this
    service is asked for anything, and the caller's identity never reaches the cache.
  - The decision and the state it was computed from are returned together, so a response is
    built from one coherent view of a patient.
"""

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from biosentry.cache import (
    SNAPSHOT_SCHEMA_VERSION,
    SingleFlight,
    Snapshot,
    SnapshotCache,
    snapshot_key,
)
from biosentry.core.audit import Clock
from biosentry.domain.arbiter import NotRanked, Ranked, arbitrate
from biosentry.domain.scoring.tier_a import inputs_from_vitals, score_news2
from biosentry.repositories.memory.store import MemoryStore
from biosentry.schemas import UnscoredPatient, Vitals

_LOG = logging.getLogger("biosentry.cache")

Decision = Ranked | NotRanked
Decide = Callable[[UnscoredPatient], Decision]


def decide(state: UnscoredPatient) -> Decision:
    """One patient's decision from their stored vitals: NEWS2, then the arbiter. Pure."""
    return arbitrate(state.id, score_news2(inputs_from_vitals(state.vitals)))


def newest_input(vitals: Vitals) -> datetime | None:
    """When the newest NEWS2 input behind a decision was observed; None if none is present."""
    measurements = (
        vitals.heart_rate,
        vitals.respiratory_rate,
        vitals.spo2,
        vitals.temperature,
        vitals.blood_pressure,
        vitals.consciousness,
        vitals.supplemental_o2,
        vitals.spo2_scale,
    )
    seen = [m.provenance.observed_at for m in measurements if m.data.present]
    return max(seen) if seen else None


@dataclass(frozen=True, slots=True)
class Scored:
    """A decision and the exact patient state it was computed from."""

    state: UnscoredPatient
    snapshot: Snapshot


class ScoringService:
    def __init__(
        self,
        store: MemoryStore,
        cache: SnapshotCache | None,
        *,
        scorer_sha: str,
        clock: Clock,
        decide_fn: Decide = decide,
    ) -> None:
        self._store = store
        self._cache = cache
        self._scorer_sha = scorer_sha
        self._clock = clock
        self._decide = decide_fn
        self._flights: SingleFlight[tuple[str, int], Snapshot] = SingleFlight()
        self._lock = threading.Lock()
        self._computations = 0

    @property
    def computations(self) -> int:
        """How many decisions were computed (not served from the cache) so far."""
        with self._lock:
            return self._computations

    # --- the cache, failing open -------------------------------------------------------------

    def _warn(self, operation: str, exc: Exception) -> None:
        # The exception class and the operation only: nothing about the patient or the value.
        _LOG.warning(
            "snapshot cache %s failed (%s); computing directly", operation, type(exc).__name__
        )

    def _cached(self, key: str) -> Snapshot | None:
        if self._cache is None:
            return None
        try:
            found = self._cache.get(key)
        except Exception as exc:
            self._warn("get", exc)
            return None
        return found if isinstance(found, Snapshot) else None

    def _store_snapshot(self, key: str, snapshot: Snapshot) -> None:
        if self._cache is None:
            return
        try:
            self._cache.put(key, snapshot)
        except Exception as exc:
            self._warn("put", exc)

    def _evict(self, key: str) -> None:
        if self._cache is None:
            return
        try:
            self._cache.evict(key)
        except Exception as exc:
            self._warn("evict", exc)

    # --- scoring -----------------------------------------------------------------------------

    def _key(self, patient_id: str) -> str:
        return snapshot_key(patient_id, SNAPSHOT_SCHEMA_VERSION, self._scorer_sha)

    def _current(self, snapshot: Snapshot, patient_id: str, revision: int) -> bool:
        return (
            snapshot.patient_id == patient_id
            and snapshot.schema_version == SNAPSHOT_SCHEMA_VERSION
            and snapshot.scorer_sha == self._scorer_sha
            and snapshot.revision == revision
        )

    def _compute(self, key: str, revision: int, state: UnscoredPatient) -> Snapshot:
        snapshot = Snapshot(
            patient_id=state.id,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            scorer_sha=self._scorer_sha,
            revision=revision,
            computed_at=self._clock(),
            inputs_as_of=newest_input(state.vitals),
            decision=self._decide(state),
        )
        with self._lock:
            self._computations += 1
        self._store_snapshot(key, snapshot)
        return snapshot

    def _lead(self, key: str, revision: int, state: UnscoredPatient) -> Snapshot:
        """Runs once per flight. A flight that landed between this caller's miss and its entry
        here has already stored the answer: look again before computing a second time."""
        again = self._cached(key)
        if again is not None and self._current(again, state.id, revision):
            return again
        return self._compute(key, revision, state)

    def score(self, patient_id: str) -> Scored | None:
        """This patient's decision and state, or None when there is no such patient."""
        seen = self._store.read(patient_id)
        if seen is None:
            return None
        revision, state = seen
        key = self._key(patient_id)
        cached = self._cached(key)
        if cached is not None and self._current(cached, patient_id, revision):
            return Scored(state, cached)
        snapshot = self._flights.run((key, revision), lambda: self._lead(key, revision, state))
        return Scored(state, snapshot)

    def score_many(self, patient_ids: Iterable[str]) -> list[Scored]:
        """Decisions for these patients, in id order. Unknown ids are skipped."""
        found = (self.score(pid) for pid in sorted(patient_ids))
        return [s for s in found if s is not None]

    def refresh(self, patient_id: str) -> Scored | None:
        """The write path: drop what is cached for this patient and compute the fresh snapshot."""
        self.evict(patient_id)
        return self.score(patient_id)

    def evict(self, patient_id: str) -> None:
        """Forget a patient (a write, a discharge). The next read computes."""
        self._evict(self._key(patient_id))
