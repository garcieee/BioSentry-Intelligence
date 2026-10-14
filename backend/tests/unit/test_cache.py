"""The snapshot cache (CP7): store, expiry, compare-and-set, keys, single-flight, shape."""

import dataclasses
import hashlib
import inspect
import json
import math
import re
import threading
import time
from datetime import UTC, datetime
from types import ModuleType

import pytest
from pydantic import TypeAdapter

from biosentry.cache import (
    SNAPSHOT_SCHEMA_VERSION,
    MemoryCache,
    SingleFlight,
    Snapshot,
    is_snapshot_key,
    snapshot_key,
)
from biosentry.domain.arbiter import NotRanked, Ranked, arbitrate
from biosentry.domain.scoring.fingerprint import SCORER_MODULES, scorer_sha
from biosentry.domain.scoring.tier_a import News2Inputs, score_news2
from biosentry.schemas import Acvpu, Spo2Scale

NOW = datetime(2026, 9, 3, 7, 0, tzinfo=UTC)
SHA = "a" * 64


class Tick:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def ranked(patient_id: str = "p-001", systolic: float = 120.0) -> Ranked:
    result = score_news2(
        News2Inputs(
            respiratory_rate=18,
            spo2=96,
            spo2_scale=Spo2Scale.scale_1,
            supplemental_o2=False,
            systolic_bp=systolic,
            heart_rate=70,
            consciousness=Acvpu.A,
            temperature=36.8,
        )
    )
    decision = arbitrate(patient_id, result)
    assert isinstance(decision, Ranked)
    return decision


def not_ranked(patient_id: str = "p-002") -> NotRanked:
    nothing = News2Inputs(None, None, None, None, None, None, None, None)
    decision = arbitrate(patient_id, score_news2(nothing))
    assert isinstance(decision, NotRanked)
    return decision


def snapshot(
    patient_id: str = "p-001", revision: int = 1, decision: Ranked | NotRanked | None = None
) -> Snapshot:
    return Snapshot(
        patient_id=patient_id,
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        scorer_sha=SHA,
        revision=revision,
        computed_at=NOW,
        inputs_as_of=NOW,
        decision=decision if decision is not None else ranked(patient_id),
    )


# --- the in-memory backend ----------------------------------------------------------------


def test_a_miss_is_none_and_a_put_is_got() -> None:
    cache = MemoryCache(ttl_s=10)
    assert cache.get("k") is None
    stored = snapshot()
    assert cache.put("k", stored) is True
    assert cache.get("k") == stored


def test_an_entry_lives_until_its_deadline_and_not_a_moment_longer() -> None:
    clock = Tick()
    cache = MemoryCache(ttl_s=10, now=clock)
    cache.put("k", snapshot())
    clock.now = 9.999
    assert cache.get("k") is not None
    clock.now = 10.0
    assert cache.get("k") is None
    assert len(cache) == 0  # an expired entry is swept, not kept


def test_a_put_restarts_the_deadline() -> None:
    clock = Tick()
    cache = MemoryCache(ttl_s=10, now=clock)
    cache.put("k", snapshot())
    clock.now = 8
    cache.put("k", snapshot())
    clock.now = 15
    assert cache.get("k") is not None
    clock.now = 18
    assert cache.get("k") is None


def test_compare_and_set_refuses_an_older_revision_and_accepts_equal_or_newer() -> None:
    cache = MemoryCache(ttl_s=10)
    assert cache.put("k", snapshot(revision=5))
    assert cache.put("k", snapshot(revision=4)) is False
    held = cache.get("k")
    assert held is not None
    assert held.revision == 5
    assert cache.put("k", snapshot(revision=5)) is True
    assert cache.put("k", snapshot(revision=6)) is True
    held = cache.get("k")
    assert held is not None
    assert held.revision == 6


def test_an_expired_newer_entry_does_not_block_an_older_put() -> None:
    clock = Tick()
    cache = MemoryCache(ttl_s=10, now=clock)
    cache.put("k", snapshot(revision=9))
    clock.now = 11
    assert cache.put("k", snapshot(revision=2)) is True


def test_evict_forgets_the_entry() -> None:
    cache = MemoryCache(ttl_s=10)
    cache.put("k", snapshot())
    cache.evict("k")
    cache.evict("never-there")  # not an error
    assert cache.get("k") is None


def test_the_least_recently_used_entry_leaves_first() -> None:
    cache = MemoryCache(ttl_s=10, max_entries=2)
    cache.put("a", snapshot("p-001"))
    cache.put("b", snapshot("p-002"))
    cache.get("a")  # a is now the more recent
    cache.put("c", snapshot("p-003"))
    assert cache.get("b") is None
    assert cache.get("a") is not None
    assert cache.get("c") is not None


@pytest.mark.parametrize("ttl", [0, -1, math.nan, math.inf])
def test_a_ttl_that_is_not_a_positive_number_is_refused(ttl: float) -> None:
    with pytest.raises(ValueError, match="ttl_s"):
        MemoryCache(ttl_s=ttl)


def test_a_cache_that_holds_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        MemoryCache(ttl_s=1, max_entries=0)


def test_concurrent_use_does_not_break_the_cache() -> None:
    cache = MemoryCache(ttl_s=10, max_entries=8)
    failures: list[BaseException] = []

    def worker(seed: int) -> None:
        try:
            for i in range(400):
                key = f"p-{(seed + i) % 20:03d}"
                cache.put(key, snapshot(key, revision=i))
                cache.get(key)
                if i % 7 == 0:
                    cache.evict(key)
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert failures == []
    assert len(cache) <= 8


# --- keys ---------------------------------------------------------------------------------


def test_a_key_is_patient_schema_and_scorer() -> None:
    key = snapshot_key("p-004", 1, SHA)
    assert key == f"p-004:1:{SHA}"
    assert is_snapshot_key(key)


@pytest.mark.parametrize(
    "not_an_id",
    ["Santos, Maria", "Bed 12", "maria@example.com", "", " p-001", "p-001:2", "p/001", "é-001"],
)
def test_a_key_refuses_anything_that_is_plainly_a_person(not_an_id: str) -> None:
    with pytest.raises(ValueError, match="opaque"):
        snapshot_key(not_an_id, 1, SHA)
    assert not is_snapshot_key(f"{not_an_id}:1:{SHA}")


def test_a_key_needs_a_real_version_and_a_digest() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        snapshot_key("p-001", 0, SHA)
    with pytest.raises(ValueError, match="sha256"):
        snapshot_key("p-001", 1, "not-a-digest")


# --- what a snapshot is -------------------------------------------------------------------


def test_a_snapshot_holds_timestamps_and_no_rank_no_clinician_no_duration() -> None:
    names = {f.name for f in dataclasses.fields(Snapshot)}
    assert names == {
        "patient_id",
        "schema_version",
        "scorer_sha",
        "revision",
        "computed_at",
        "inputs_as_of",
        "decision",
    }
    for name in names:
        assert not re.search(r"(rank|clinician|age|duration|ttl|_s$|_ms$)", name), name


@pytest.mark.parametrize("decision", [ranked(), ranked(systolic=45), not_ranked()])
def test_a_snapshot_round_trips_through_json_for_a_remote_backend(
    decision: Ranked | NotRanked,
) -> None:
    adapter = TypeAdapter(Snapshot)
    original = snapshot(decision=decision)
    again = adapter.validate_json(adapter.dump_json(original))
    assert again == original
    assert type(again.decision) is type(decision)
    assert again.computed_at.tzinfo is not None


# Moves with the shape of `Snapshot` and of everything inside its decision. A failure here means
# a stored snapshot would no longer read back as the code expects: bump
# SNAPSHOT_SCHEMA_VERSION (new keys, so old entries are never read), then add the new digest.
SHAPE_PINS = {1: "373a6bcd99ef22da764f3f993b77a2817edefcffce417087f29e5831f8868bc4"}


def _shape_digest() -> str:
    schema = TypeAdapter(Snapshot).json_schema()
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_the_schema_version_moves_with_the_shape_of_a_snapshot() -> None:
    assert SNAPSHOT_SCHEMA_VERSION in SHAPE_PINS, (
        f"add the shape digest for version {SNAPSHOT_SCHEMA_VERSION}: {_shape_digest()}"
    )
    assert _shape_digest() == SHAPE_PINS[SNAPSHOT_SCHEMA_VERSION], (
        f"the shape of Snapshot changed: bump SNAPSHOT_SCHEMA_VERSION and pin {_shape_digest()}"
    )


# --- the scorer's identity ----------------------------------------------------------------


def test_the_scorer_sha_is_a_stable_digest_of_the_scoring_code() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", scorer_sha())
    assert scorer_sha() == scorer_sha()
    assert {m.__name__ for m in SCORER_MODULES} == {
        "biosentry.domain.scoring.tier_a.tables",
        "biosentry.domain.scoring.tier_a.news2",
        "biosentry.domain.arbiter",
    }


@pytest.mark.parametrize("module", SCORER_MODULES, ids=lambda m: m.__name__)
def test_a_change_to_any_scoring_module_changes_the_scorer_sha(module: ModuleType) -> None:
    def edited(m: ModuleType) -> bytes:
        text = inspect.getsource(m).encode("utf-8")
        return text + b"\n# an edit\n" if m is module else text

    assert scorer_sha(edited) != scorer_sha()


# --- single-flight ------------------------------------------------------------------------


def test_concurrent_misses_share_one_computation() -> None:
    flights: SingleFlight[str, int] = SingleFlight()
    callers = 10
    arrived = 0
    gate = threading.Lock()
    computations = 0
    results: list[int] = []

    def compute() -> int:
        nonlocal computations
        # Hold the flight open until every caller has asked, plus a moment for the last one
        # to be inside run(): a late arrival would (correctly) start a flight of its own.
        deadline = time.monotonic() + 5
        while arrived < callers and time.monotonic() < deadline:
            time.sleep(0.001)
        time.sleep(0.05)
        computations += 1
        return 42

    def caller() -> None:
        nonlocal arrived
        with gate:
            arrived += 1
        results.append(flights.run("k", compute))

    threads = [threading.Thread(target=caller) for _ in range(callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert computations == 1
    assert results == [42] * callers


def test_different_keys_do_not_wait_for_each_other() -> None:
    flights: SingleFlight[str, str] = SingleFlight()
    release = threading.Event()
    started = threading.Event()

    def slow() -> str:
        started.set()
        release.wait(5)
        return "slow"

    slow_result: list[str] = []
    t = threading.Thread(target=lambda: slow_result.append(flights.run("a", slow)))
    t.start()
    assert started.wait(5)
    assert flights.run("b", lambda: "fast") == "fast"  # returns while "a" is still in flight
    release.set()
    t.join()
    assert slow_result == ["slow"]


def test_a_failure_is_shared_with_the_waiters_and_never_remembered() -> None:
    flights: SingleFlight[str, int] = SingleFlight()
    calls = 0

    def boom() -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("compute failed")

    with pytest.raises(RuntimeError, match="compute failed"):
        flights.run("k", boom)
    with pytest.raises(RuntimeError, match="compute failed"):
        flights.run("k", boom)
    assert calls == 2  # the second caller computed again: nothing was cached
    assert flights.run("k", lambda: 7) == 7
