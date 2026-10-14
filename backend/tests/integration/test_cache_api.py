"""The snapshot cache through the API (CP7): the cache is an optimisation and never an authority.

What these tests hold the line on:
  - answers are identical with the cache on, off, failing, expired or poisoned;
  - a read that hits the cache still writes its audit row;
  - scope is resolved first and the cache is never asked about a patient outside it;
  - rank is computed per request and never stored;
  - a write is visible at once, and a stale computation cannot overwrite a newer write.
"""

import json
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from biosentry.api.app import Context, create_app
from biosentry.cache import (
    SNAPSHOT_SCHEMA_VERSION,
    MemoryCache,
    Snapshot,
    SnapshotCache,
    is_snapshot_key,
    snapshot_key,
)
from biosentry.core.config import DEFAULT_DATASET, Settings
from biosentry.domain.scoring.fingerprint import scorer_sha
from biosentry.repositories.memory import store as memory_store
from biosentry.repositories.memory.store import MemoryStore
from biosentry.schemas import Acvpu, WardResponse
from biosentry.services.scoring import ScoringService, decide

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
DATA: dict[str, Any] = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
CLINICIANS: dict[str, list[str]] = {
    cid: list(entry["patients"]) for cid, entry in DATA["clinicians"].items()
}
ALL_IDS = sorted([r["id"] for r in DATA["ranked"]] + [a["id"] for a in DATA["abstained"]])
SHA_A = "a" * 64
SHA_B = "b" * 64


def as_(clinician: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {clinician}"}


class SpyCache:
    """A real in-memory cache that records every call and can be told to be down."""

    def __init__(self, inner: MemoryCache | None = None) -> None:
        self.inner = inner if inner is not None else MemoryCache(ttl_s=30)
        self.calls: list[tuple[str, str]] = []
        self.down = False

    def _call(self, operation: str, key: str) -> None:
        self.calls.append((operation, key))
        if self.down:
            raise ConnectionError("the cache is down")

    def get(self, key: str) -> Snapshot | None:
        self._call("get", key)
        return self.inner.get(key)

    def put(self, key: str, snapshot: Snapshot) -> bool:
        self._call("put", key)
        return self.inner.put(key, snapshot)

    def evict(self, key: str) -> None:
        self._call("evict", key)
        self.inner.evict(key)

    def patients_touched(self) -> set[str]:
        return {key.split(":")[0] for _, key in self.calls}


def build(
    *, cache: SnapshotCache | None = None, config: Settings | None = None
) -> tuple[Context, TestClient]:
    app = create_app(config or Settings(), clock=lambda: NOW, cache=cache)
    found: Context = app.state.ctx
    return found, TestClient(app, raise_server_exceptions=False)


def ward(client: TestClient, who: str) -> WardResponse:
    response = client.get("/wards/W4/rows", headers=as_(who))
    assert response.status_code == 200, response.text
    return WardResponse.model_validate(response.json())


# --- a hit is still a read: audited, identical, and free ---------------------------------


def test_a_repeat_read_is_served_from_the_cache_and_still_audited() -> None:
    ctx, client = build()
    first = client.get("/wards/W4/rows", headers=as_("rn-manalo"))
    assert ctx.scoring.computations == len(ALL_IDS)
    second = client.get("/wards/W4/rows", headers=as_("rn-manalo"))
    assert ctx.scoring.computations == len(ALL_IDS)  # nothing was recomputed
    assert second.json() == first.json()
    rows = ctx.audit.for_clinician("rn-manalo")
    assert [(r.action, r.resource, r.outcome) for r in rows] == [("view_ward", "W4", "ok")] * 2


def test_a_hit_on_a_detail_page_and_on_the_picker_writes_its_audit_row_too() -> None:
    ctx, client = build()
    h = as_("rn-manalo")
    for _ in range(2):
        assert client.get("/patients/p-001", headers=h).status_code == 200
        assert client.get("/patients", headers=h).status_code == 200
    assert ctx.scoring.computations == len(ALL_IDS)
    rows = ctx.audit.for_clinician("rn-manalo")
    assert [(r.action, r.outcome) for r in rows] == [
        ("view_patient", "ok"),
        ("list_patients", "ok"),
    ] * 2


def test_a_refused_read_is_audited_the_same_whether_the_cache_is_warm_or_cold() -> None:
    cold_ctx, cold = build()
    warm_ctx, warm = build()
    ward(warm, "md-aquino")  # warm the cache for aquino's patients
    for client in (cold, warm):
        client.get("/patients/p-001", headers=as_("md-aquino"))  # exists, not theirs
        client.get("/patients/p-999", headers=as_("md-aquino"))  # does not exist

    def tail(ctx: Context) -> list[tuple[str, str, str]]:
        rows = ctx.audit.for_clinician("md-aquino")
        return [(r.action, r.resource, str(r.outcome)) for r in rows][-2:]

    assert tail(cold_ctx) == tail(warm_ctx)
    assert [outcome for _, _, outcome in tail(warm_ctx)] == ["not_found", "not_found"]


# --- invalidation: a write is visible at once --------------------------------------------


def test_a_write_recomputes_exactly_that_patient() -> None:
    ctx, client = build()
    h = as_("rn-delacruz")
    ward(client, "rn-delacruz")
    warm = ctx.scoring.computations
    response = client.post(
        "/patients/p-004/vitals", headers=h, json={"systolic": 130, "diastolic": 84}
    )
    assert response.status_code == 200
    assert ctx.scoring.computations == warm + 1  # p-004 only; the rest were hits
    after = ward(client, "rn-delacruz")
    assert ctx.scoring.computations == warm + 1
    assert "p-004" in {r.id for r in after.ranked}
    client.post("/patients/p-001/labs", headers=h, json={"potassium": 4.1})
    assert ctx.scoring.computations == warm + 2  # a write drops the snapshot, labs included


def test_a_write_leaves_no_older_snapshot_in_the_cache() -> None:
    spy = SpyCache()
    ctx, client = build(cache=spy)
    ward(client, "rn-manalo")  # warm: p-001 is cached at revision 0
    key = snapshot_key("p-001", SNAPSHOT_SCHEMA_VERSION, scorer_sha())
    held = spy.inner.get(key)
    assert held is not None
    assert held.revision == 0
    client.post("/patients/p-001/labs", headers=as_("rn-manalo"), json={"potassium": 4.1})
    held = spy.inner.get(key)  # no read since the write: the write itself refreshed it
    assert held is not None
    seen = ctx.store.read("p-001")
    assert seen is not None
    assert held.revision == seen[0] == 1


def test_a_value_recorded_by_one_clinician_is_seen_by_another_at_once() -> None:
    _, client = build()
    before = ward(client, "rn-manalo")
    assert "p-004" in {a.id for a in before.abstained}
    client.post(
        "/patients/p-004/vitals", headers=as_("rn-delacruz"), json={"systolic": 45, "diastolic": 20}
    )
    after = ward(client, "rn-manalo")
    row = next(r for r in after.ranked if r.id == "p-004")
    assert row.score == 3
    assert [e.text for e in row.escalation_reasons] == ["Single parameter at 3: systolic BP"]


def test_the_cache_may_never_resurrect_a_value_that_a_write_replaced() -> None:
    """Even a writer that forgets to evict is caught by the revision check."""
    spy = SpyCache()
    ctx, client = build(cache=spy)
    ward(client, "rn-delacruz")
    base = ctx.store.patients["p-012"].state.vitals.consciousness
    unresponsive = base.model_copy(update={"data": base.data.model_copy(update={"value": Acvpu.U})})
    ctx.store.update(  # a write that bypasses the service, and so any eviction
        "p-012",
        lambda s: s.model_copy(
            update={"vitals": s.vitals.model_copy(update={"consciousness": unresponsive})}
        ),
    )
    row = next(r for r in ward(client, "rn-delacruz").ranked if r.id == "p-012")
    assert row.score == 3


# --- scope: resolved first, never cached, never bypassed ---------------------------------


def test_the_cache_is_never_asked_about_a_patient_outside_the_callers_scope() -> None:
    spy = SpyCache()
    _, client = build(cache=spy)
    ward(client, "rn-manalo")  # warms every patient
    spy.calls.clear()
    assert client.get("/patients/p-001", headers=as_("md-aquino")).status_code == 404
    assert spy.calls == []  # not even a lookup: the scope check came first
    ward(client, "md-aquino")
    assert spy.patients_touched() == set(CLINICIANS["md-aquino"])
    spy.calls.clear()
    assert client.get("/wards/W4/rows", headers=as_("rn-nobody")).status_code == 403
    assert spy.calls == []


def test_a_warm_cache_does_not_widen_what_a_clinician_sees() -> None:
    _, client = build()
    ward(client, "rn-manalo")  # the charge nurse's read warms all twelve
    seen = ward(client, "md-aquino")
    assert {r.id for r in seen.ranked} | {a.id for a in seen.abstained} == set(
        CLINICIANS["md-aquino"]
    )
    picker = client.get("/patients", headers=as_("md-aquino")).json()
    assert {p["id"] for p in picker} == set(CLINICIANS["md-aquino"])


def test_scope_that_cannot_be_looked_up_serves_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = SpyCache()
    ctx, client = build(cache=spy)
    ward(client, "rn-manalo")  # warm: the cache holds everything it could serve
    spy.calls.clear()
    audit_before = len(ctx.audit.records())

    def unavailable(self: MemoryStore, clinician_id: str) -> frozenset[str]:
        raise ConnectionError("assignment lookup is down")

    monkeypatch.setattr(MemoryStore, "assigned", unavailable)
    for path in ("/wards/W4/rows", "/patients", "/patients/p-001"):
        response = client.get(path, headers=as_("rn-manalo"))
        assert response.status_code == 500
        assert "Santos" not in response.text
    assert spy.calls == []  # a failing scope never falls back to the cache
    assert not any(r.outcome == "ok" for r in ctx.audit.records()[audit_before:])


def test_scope_is_never_cached_a_new_assignment_is_seen_at_once() -> None:
    _, client = build()
    before = ward(client, "rn-delacruz")
    admitted = client.post(
        "/patients",
        headers=as_("rn-delacruz"),
        json={
            "lastName": "Cache", "firstName": "Scope", "dateOfBirth": "1970-01-01", "age": 50,
            "sex": "F", "bed": "9Z", "admissionRoute": "transfer", "chiefComplaint": "c",
            "admittingContext": "a", "attendingPhysician": "p",
        },
    )  # fmt: skip
    assert admitted.status_code == 201
    after = ward(client, "rn-delacruz")
    assert {a.id for a in after.abstained} - {a.id for a in before.abstained} == {
        admitted.json()["id"]
    }
    assert admitted.json()["id"] not in {a.id for a in ward(client, "rn-reyes").abstained}


# --- rank is never cached ----------------------------------------------------------------


def test_rank_is_relative_to_the_callers_set_and_never_stored() -> None:
    ctx, client = build()
    everyone = ward(client, "rn-manalo")
    computed = ctx.scoring.computations
    some = ward(client, "rn-reyes")
    assert ctx.scoring.computations == computed  # the same snapshots served a different set
    assert [r.rank for r in some.ranked] == list(range(1, len(some.ranked) + 1))
    shared = {r.id for r in everyone.ranked} & {r.id for r in some.ranked}
    assert shared

    def rank_in(response: WardResponse, patient_id: str) -> int:
        return next(r.rank for r in response.ranked if r.id == patient_id)

    assert any(rank_in(everyone, pid) != rank_in(some, pid) for pid in shared)
    # Order is preserved between the two sets: only the numbers are relative.
    by_everyone = sorted(shared, key=lambda pid: rank_in(everyone, pid))
    by_some = sorted(shared, key=lambda pid: rank_in(some, pid))
    assert by_everyone == by_some


# --- the cache is optional, and wrong answers are impossible -----------------------------


def test_cached_and_uncached_apps_give_the_same_answers_and_the_same_audit_trail() -> None:
    cached_ctx, cached = build()
    plain_ctx, plain = build(config=Settings(cache="none"))
    script: list[tuple[str, str, str, Any]] = [
        ("GET", "rn-manalo", "/wards/W4/rows", None),
        ("GET", "md-santos", "/patients/p-001", None),
        ("POST", "rn-delacruz", "/patients/p-004/vitals", {"systolic": 130, "diastolic": 84}),
        ("GET", "rn-manalo", "/wards/W4/rows", None),
        ("POST", "rn-manalo", "/patients/p-012/vitals", {"acvpu": "U"}),
        ("GET", "rn-delacruz", "/wards/W4/rows", None),
        ("POST", "rn-delacruz", "/patients/p-004/vitals", {"systolic": 45, "diastolic": 20}),
        ("POST", "md-aquino", "/patients/p-001/vitals", {"systolic": 100, "diastolic": 60}),
        ("POST", "rn-manalo", "/patients/p-005/vitals", {"on_oxygen": True, "spo2_scale": 2}),
        ("POST", "rn-manalo", "/patients/p-001/labs", {"potassium": 6.2}),
        ("GET", "rn-manalo", "/patients/p-001", None),
        ("GET", "rn-reyes", "/patients", None),
        ("POST", "rn-delacruz", "/patients/p-004/vitals", {"systolic": 0, "diastolic": 0}),
        ("POST", "rn-delacruz", "/patients/p-004/vitals", {}),
        ("GET", "rn-manalo", "/wards/W4/rows", None),
    ]
    for method, who, path, body in script:
        a = cached.request(method, path, headers=as_(who), json=body)
        b = plain.request(method, path, headers=as_(who), json=body)
        assert (a.status_code, a.json()) == (b.status_code, b.json()), (method, who, path)

    def trail(ctx: Context) -> list[tuple[str | None, str | None, str, str, str]]:
        return [
            (r.clinician_id, r.role, r.action, r.resource, r.outcome) for r in ctx.audit.records()
        ]

    assert trail(cached_ctx) == trail(plain_ctx)
    assert cached_ctx.scoring.computations < plain_ctx.scoring.computations


_VITALS = st.sampled_from(
    [
        {"systolic": 130, "diastolic": 84},
        {"systolic": 45, "diastolic": 20},
        {"systolic": 220, "diastolic": 100},
        {"acvpu": "U"},
        {"acvpu": "A"},
        {"on_oxygen": True},
        {"on_oxygen": False, "spo2_scale": 2},
        {"systolic": 0, "diastolic": 0},
        {},
    ]
)
_WHO = st.sampled_from(sorted(CLINICIANS))
_PATIENT = st.sampled_from([*ALL_IDS, "p-999"])
_OPERATIONS = st.one_of(
    st.tuples(st.just("vitals"), _WHO, _PATIENT, _VITALS),
    st.tuples(
        st.just("labs"),
        _WHO,
        _PATIENT,
        st.sampled_from([{"potassium": 3.1}, {"bnp": 900.0}, {"potassium": 4.4, "bnp": 120.0}]),
    ),
    st.tuples(st.just("ward"), _WHO, st.just(""), st.just(None)),
    st.tuples(st.just("detail"), _WHO, _PATIENT, st.just(None)),
)


def _apply(client: TestClient, op: tuple[str, str, str, Any]) -> tuple[int, Any]:
    kind, who, pid, body = op
    h = as_(who)
    if kind == "vitals":
        r = client.post(f"/patients/{pid}/vitals", headers=h, json=body)
    elif kind == "labs":
        r = client.post(f"/patients/{pid}/labs", headers=h, json=body)
    elif kind == "ward":
        r = client.get("/wards/W4/rows", headers=h)
    else:
        r = client.get(f"/patients/{pid}", headers=h)
    return r.status_code, r.json()


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(st.lists(_OPERATIONS, min_size=1, max_size=14))
def test_no_sequence_of_reads_and_writes_makes_the_cache_change_an_answer(
    operations: list[tuple[str, str, str, Any]],
) -> None:
    cached_ctx, cached = build()
    plain_ctx, plain = build(config=Settings(cache="none"))
    for op in operations:
        assert _apply(cached, op) == _apply(plain, op), op
    for who in CLINICIANS:
        assert ward(cached, who) == ward(plain, who)
    assert [
        (r.clinician_id, r.action, r.resource, r.outcome) for r in cached_ctx.audit.records()
    ] == [(r.clinician_id, r.action, r.resource, r.outcome) for r in plain_ctx.audit.records()]


def test_a_cache_that_is_down_never_changes_an_answer(caplog: pytest.LogCaptureFixture) -> None:
    spy = SpyCache()
    spy.down = True
    ctx, client = build(cache=spy)
    _, plain = build(config=Settings(cache="none"))
    with caplog.at_level(logging.WARNING, logger="biosentry.cache"):
        a = client.get("/wards/W4/rows", headers=as_("rn-manalo"))
        wrote = client.post(
            "/patients/p-004/vitals",
            headers=as_("rn-delacruz"),
            json={"systolic": 130, "diastolic": 84},
        )
        b = client.get("/wards/W4/rows", headers=as_("rn-manalo"))
    plain.get("/wards/W4/rows", headers=as_("rn-manalo"))
    plain.post(
        "/patients/p-004/vitals",
        headers=as_("rn-delacruz"),
        json={"systolic": 130, "diastolic": 84},
    )
    expected = plain.get("/wards/W4/rows", headers=as_("rn-manalo"))
    assert a.status_code == wrote.status_code == b.status_code == 200
    assert b.json() == expected.json()
    assert len(spy.calls) > 0  # it was tried, and it failed open
    assert {r.action for r in ctx.audit.records()} >= {"view_ward", "record_vitals"}
    messages = " ".join(r.getMessage() for r in caplog.records if r.name == "biosentry.cache")
    assert "snapshot cache get failed (ConnectionError)" in messages
    for secret in ("Santos", "Maria", "p-00", "130", "rn-"):
        assert secret not in messages  # operations and exception classes only


def test_a_snapshot_that_does_not_belong_under_its_key_is_a_miss() -> None:
    class Swapping:
        """Hands back p-002's snapshot for every key: a poisoned or confused backend."""

        def __init__(self) -> None:
            self.inner = MemoryCache(ttl_s=30)
            self.other: Snapshot | None = None

        def get(self, key: str) -> Snapshot | None:
            return self.other

        def put(self, key: str, snapshot: Snapshot) -> bool:
            if snapshot.patient_id == "p-002":
                self.other = snapshot
            return self.inner.put(key, snapshot)

        def evict(self, key: str) -> None:
            self.inner.evict(key)

    _, client = build(cache=Swapping())
    _, plain = build(config=Settings(cache="none"))
    for _ in range(2):
        assert ward(client, "rn-manalo") == ward(plain, "rn-manalo")


def test_snapshots_expire_and_are_recomputed_with_the_same_answer() -> None:
    clock = {"now": 100.0}
    cache = MemoryCache(ttl_s=10, now=lambda: clock["now"])
    ctx, client = build(cache=cache)
    first = ward(client, "rn-manalo")
    clock["now"] += 9
    assert ward(client, "rn-manalo") == first
    assert ctx.scoring.computations == len(ALL_IDS)
    clock["now"] += 2  # past the deadline
    assert ward(client, "rn-manalo") == first
    assert ctx.scoring.computations == 2 * len(ALL_IDS)


def test_with_the_cache_off_every_read_computes() -> None:
    ctx, client = build(config=Settings(cache="none"))
    assert ctx.cache is None
    ward(client, "rn-manalo")
    ward(client, "rn-manalo")
    assert ctx.scoring.computations == 2 * len(ALL_IDS)


# --- keys hold nothing a person could be found by ----------------------------------------


def test_the_cache_is_keyed_by_patient_alone_and_holds_no_rank() -> None:
    spy = SpyCache()
    _, client = build(cache=spy)
    ward(client, "rn-manalo")
    keys = spy.inner.keys()
    assert sorted(k.split(":")[0] for k in keys) == ALL_IDS
    assert all(is_snapshot_key(k) for k in keys)
    for key in keys:  # exactly `patient:version:digest`, so no clinician, name or label fits
        patient, version, digest = key.split(":")
        assert (patient, version) == (patient, str(SNAPSHOT_SCHEMA_VERSION))
        assert len(digest) == 64
    for key in keys:
        held = spy.inner.get(key)
        assert held is not None
        assert not hasattr(held, "rank")


# --- races and versions ------------------------------------------------------------------


def _store_and_service(
    cache: MemoryCache, *, sha: str = SHA_A, decide_fn: Any = decide
) -> tuple[MemoryStore, ScoringService]:
    store = memory_store.load(DEFAULT_DATASET)
    return store, ScoringService(
        store, cache, scorer_sha=sha, clock=lambda: NOW, decide_fn=decide_fn
    )


def test_a_stale_computation_cannot_overwrite_a_newer_write() -> None:
    cache = MemoryCache(ttl_s=30)
    store = memory_store.load(DEFAULT_DATASET)
    fired: list[bool] = []
    holder: dict[str, ScoringService] = {}

    def decide_while_a_write_lands(state: Any) -> Any:
        decision = decide(state)  # computed from the OLD state (no blood pressure)
        if state.id == "p-004" and not fired:
            fired.append(True)
            donor = store.patients["p-001"].state.vitals.blood_pressure
            store.update(
                "p-004",
                lambda s: s.model_copy(
                    update={"vitals": s.vitals.model_copy(update={"blood_pressure": donor})}
                ),
            )
            holder["service"].refresh("p-004")  # the write path finishes first
        return decision

    service = ScoringService(
        store, cache, scorer_sha=SHA_A, clock=lambda: NOW, decide_fn=decide_while_a_write_lands
    )
    holder["service"] = service
    stale = service.score("p-004")
    assert stale is not None
    assert stale.snapshot.revision == 0
    assert type(stale.snapshot.decision).__name__ == "NotRanked"  # coherent with its own state

    key = snapshot_key("p-004", SNAPSHOT_SCHEMA_VERSION, SHA_A)
    held = cache.get(key)
    assert held is not None
    assert held.revision == 1  # the newer write's snapshot survived the stale put
    assert type(held.decision).__name__ == "Ranked"
    computed = service.computations
    fresh = service.score("p-004")
    assert fresh is not None
    assert fresh.snapshot.revision == 1
    assert service.computations == computed  # served from the cache


def test_a_scorer_change_makes_every_old_entry_unreachable() -> None:
    cache = MemoryCache(ttl_s=30)
    store, old = _store_and_service(cache, sha=SHA_A)
    new = ScoringService(store, cache, scorer_sha=SHA_B, clock=lambda: NOW)
    old.score("p-001")
    assert (old.computations, new.computations) == (1, 0)
    new.score("p-001")
    assert new.computations == 1  # a different scorer never reads the old entry
    old.score("p-001")
    new.score("p-001")
    assert (old.computations, new.computations) == (1, 1)  # each still hits its own


def test_concurrent_misses_on_a_cold_cache_compute_each_patient_once() -> None:
    cache = MemoryCache(ttl_s=30)
    calls: dict[str, int] = {}
    lock = threading.Lock()

    def slow_decide(state: Any) -> Any:
        time.sleep(0.05)  # long enough for the other threads to arrive and wait
        with lock:
            calls[state.id] = calls.get(state.id, 0) + 1
        return decide(state)

    _, service = _store_and_service(cache, decide_fn=slow_decide)
    barrier = threading.Barrier(8)

    def reader() -> None:
        barrier.wait()
        service.score_many(ALL_IDS)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == dict.fromkeys(ALL_IDS, 1)
    assert service.computations == len(ALL_IDS)
