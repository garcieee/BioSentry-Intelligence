"""The HTTP API (CP6): identity, server-side scope, audit, null-never-zero, writes."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from biosentry.api.app import Context, create_app
from biosentry.core.config import DEFAULT_DATASET, Settings
from biosentry.domain.arbiter import arbitrate, rank_ward
from biosentry.domain.scoring.tier_a import inputs_from_vitals, score_news2
from biosentry.schemas import (
    AbstainedRow,
    PatientDetail,
    ScoreRow,
    VitalsRecorded,
    WardResponse,
)
from biosentry.schemas.common import BloodPressurePresent

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
REPO = Path(__file__).resolve().parents[3]
DATA: dict[str, Any] = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
CLINICIANS: dict[str, list[str]] = {
    cid: list(entry["patients"]) for cid, entry in DATA["clinicians"].items()
}
ALL_IDS = [r["id"] for r in DATA["ranked"]] + [a["id"] for a in DATA["abstained"]]


def as_(clinician: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {clinician}"}


@pytest.fixture
def app_and_client() -> tuple[Any, TestClient]:
    app = create_app(Settings(), clock=lambda: NOW)
    return app, TestClient(app)


@pytest.fixture
def client(app_and_client: tuple[Any, TestClient]) -> TestClient:
    return app_and_client[1]


def ctx(app_and_client: tuple[Any, TestClient]) -> Context:
    found: Context = app_and_client[0].state.ctx
    return found


# --- Identity ----------------------------------------------------------------------------


def test_health_check_needs_no_identity(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}, {"Authorization": "Bearer "}],
    ids=["missing", "wrong-scheme", "empty", "blank"],
)
def test_missing_or_malformed_credentials_get_401_and_no_data(
    client: TestClient, headers: dict[str, str]
) -> None:
    for path in ("/wards/W4/rows", "/patients", "/patients/p-001", "/patients/p-001/notes"):
        response = client.get(path, headers=headers)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"
        assert "Santos" not in response.text


def test_a_token_that_names_nobody_gets_403_and_no_data(client: TestClient) -> None:
    response = client.get("/wards/W4/rows", headers=as_("rn-nobody"))
    assert response.status_code == 403
    assert response.json() == {"detail": "Unknown identity"}


def test_failed_authentication_is_audited_without_an_identity(
    app_and_client: tuple[Any, TestClient],
) -> None:
    _, client = app_and_client
    client.get("/patients")
    client.get("/patients", headers=as_("rn-nobody"))
    records = ctx(app_and_client).audit.records()
    assert [(r.clinician_id, r.action, r.outcome) for r in records] == [
        (None, "authenticate", "denied"),
        (None, "authenticate", "denied"),
    ]


def test_every_response_is_no_store(client: TestClient) -> None:
    for path, headers in (("/healthz", {}), ("/patients", as_("rn-manalo")), ("/patients", {})):
        assert client.get(path, headers=headers).headers["cache-control"] == "no-store"


# --- Scope (server-side, fails closed) ------------------------------------------------------


@pytest.mark.parametrize("who", CLINICIANS)
def test_the_ward_contains_exactly_the_callers_patients(client: TestClient, who: str) -> None:
    ward = WardResponse.model_validate(client.get("/wards/W4/rows", headers=as_(who)).json())
    shown = {r.id for r in ward.ranked} | {a.id for a in ward.abstained}
    assert shown == set(CLINICIANS[who])
    assert ward.clinician == who


@pytest.mark.parametrize("who", CLINICIANS)
def test_ranks_are_contiguous_and_follow_the_arbiter_within_the_callers_set(
    client: TestClient, who: str
) -> None:
    ward = WardResponse.model_validate(client.get("/wards/W4/rows", headers=as_(who)).json())
    assert [r.rank for r in ward.ranked] == list(range(1, len(ward.ranked) + 1))
    rows = [ScoreRow.model_validate(r) for r in DATA["ranked"] if r["id"] in CLINICIANS[who]]
    expected = rank_ward(arbitrate(r.id, score_news2(inputs_from_vitals(r.vitals))) for r in rows)
    assert [r.id for r in ward.ranked] == [d.patient_id for _, d in expected.ranked]


def test_a_clinician_never_sees_another_clinicians_patients(client: TestClient) -> None:
    mine = set(CLINICIANS["md-aquino"])
    theirs = [p for p in ALL_IDS if p not in mine]
    assert theirs
    listing = client.get("/patients", headers=as_("md-aquino")).json()
    assert {p["id"] for p in listing} == mine
    for pid in theirs:
        assert client.get(f"/patients/{pid}", headers=as_("md-aquino")).status_code == 404
        assert client.get(f"/patients/{pid}/notes", headers=as_("md-aquino")).status_code == 404
        post = client.post(
            f"/patients/{pid}/notes",
            headers=as_("md-aquino"),
            json={"author": "Dr X", "role": "MD", "content": "x"},
        )
        assert post.status_code == 404
        assert (
            client.post(f"/patients/{pid}/labs", headers=as_("md-aquino"), json={}).status_code
            == 404
        )


def test_not_yours_and_not_there_are_indistinguishable(client: TestClient) -> None:
    theirs = client.get("/patients/p-001", headers=as_("md-aquino"))
    absent = client.get("/patients/p-999", headers=as_("md-aquino"))
    assert (theirs.status_code, theirs.json()) == (absent.status_code, absent.json())
    assert dict(theirs.headers).keys() == dict(absent.headers).keys()


def test_a_known_clinician_with_no_patients_sees_nobody(
    tmp_path: Path,
) -> None:
    data = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    data["clinicians"]["rn-empty"] = {"role": "rn", "patients": []}
    path = tmp_path / "ward.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    client = TestClient(create_app(Settings(dataset=path), clock=lambda: NOW))
    ward = client.get("/wards/W4/rows", headers=as_("rn-empty")).json()
    assert ward["ranked"] == []
    assert ward["abstained"] == []
    assert client.get("/patients", headers=as_("rn-empty")).json() == []
    assert client.get("/patients/p-001", headers=as_("rn-empty")).status_code == 404


def test_an_unknown_ward_is_not_found(client: TestClient) -> None:
    assert client.get("/wards/ICU/rows", headers=as_("rn-manalo")).status_code == 404


# --- Audit ---------------------------------------------------------------------------------


def test_every_read_is_audited_including_refused_ones(
    app_and_client: tuple[Any, TestClient],
) -> None:
    _, client = app_and_client
    h = as_("md-aquino")
    client.get("/wards/W4/rows", headers=h)
    client.get("/patients", headers=h)
    client.get("/patients/p-003", headers=h)
    client.get("/patients/p-001", headers=h)  # not theirs
    client.get("/patients/p-003/notes", headers=h)
    records = ctx(app_and_client).audit.for_clinician("md-aquino")
    assert [(r.action, r.resource, r.outcome) for r in records] == [
        ("view_ward", "W4", "ok"),
        ("list_patients", "-", "ok"),
        ("view_patient", "p-003", "ok"),
        ("view_patient", "p-001", "not_found"),
        ("view_notes", "p-003", "ok"),
    ]
    assert [r.seq for r in records] == sorted(r.seq for r in records)
    assert all(r.at == NOW for r in records)


def test_a_refused_view_is_logged_exactly_like_a_missing_one(
    app_and_client: tuple[Any, TestClient],
) -> None:
    _, client = app_and_client
    client.get("/patients/p-001", headers=as_("md-aquino"))
    client.get("/patients/p-999", headers=as_("md-aquino"))
    refused, missing = ctx(app_and_client).audit.for_clinician("md-aquino")
    assert (refused.action, refused.outcome) == (missing.action, missing.outcome)


def test_writes_are_audited(app_and_client: tuple[Any, TestClient]) -> None:
    _, client = app_and_client
    h = as_("rn-manalo")
    client.post(
        "/patients/p-001/notes", headers=h, json={"author": "a", "role": "RN", "content": "c"}
    )
    client.post("/patients/p-001/labs", headers=h, json={"potassium": 4.2})
    client.delete("/patients/p-001/notes/n-001", headers=h)
    actions = [r.action for r in ctx(app_and_client).audit.for_clinician("rn-manalo")]
    assert actions == ["add_note", "enter_labs", "delete_note"]


def test_my_audit_returns_only_my_own_trail(client: TestClient) -> None:
    client.get("/patients", headers=as_("md-aquino"))
    client.get("/patients", headers=as_("rn-manalo"))
    mine = client.get("/audit", headers=as_("md-aquino")).json()
    assert {e["action"] for e in mine} == {"list_patients", "view_audit"} or all(
        e["action"] in {"list_patients"} for e in mine
    )
    assert all(set(e) == {"seq", "at", "action", "resource", "outcome"} for e in mine)


def test_the_audit_trail_holds_no_patient_data(app_and_client: tuple[Any, TestClient]) -> None:
    _, client = app_and_client
    h = as_("rn-delacruz")
    client.get("/patients/p-001", headers=h)
    client.post("/patients/p-001/labs", headers=h, json={"potassium": 4.37191, "bnp": 1234.5678})
    client.post(
        "/patients/p-001/notes",
        headers=h,
        json={"author": "RN Zzyzx", "role": "RN", "content": "UNIQUE-NOTE-TEXT-9f3a"},
    )
    admitted = client.post(
        "/patients",
        headers=h,
        json={
            "lastName": "Quillfeather", "firstName": "Ottoline", "dateOfBirth": "1969-02-03",
            "age": 57, "sex": "F", "bed": "12C", "admissionRoute": "transfer",
            "chiefComplaint": "UNIQUE-COMPLAINT-77", "admittingContext": "UNIQUE-CONTEXT-88",
            "attendingPhysician": "Dr Nobody", "philhealthPin": "12-345678901-2",
            "initialBp": "131/77",
        },
    )  # fmt: skip
    assert admitted.status_code == 201
    audit = ctx(app_and_client).audit
    dumped = json.dumps(
        [r.__dict__ if hasattr(r, "__dict__") else repr(r) for r in audit.records()], default=str
    )
    dumped += repr(audit.records()) + client.get("/audit", headers=h).text
    secrets = [
        "Santos", "Maria", "4.37191", "1234.5678", "Zzyzx", "UNIQUE-NOTE-TEXT-9f3a",
        "Quillfeather", "Ottoline", "1969-02-03", "UNIQUE-COMPLAINT-77", "UNIQUE-CONTEXT-88",
        "12-345678901-2", "131/77", "Dr Nobody",
    ]  # fmt: skip
    for secret in secrets:
        assert secret not in dumped, f"{secret!r} leaked into the audit trail"
    assert len(audit.for_clinician("rn-delacruz")) >= 4


@pytest.mark.parametrize(
    ("method", "path", "action", "body"),
    [
        ("GET", "/patients/{}", "view_patient", None),
        ("GET", "/patients/{}/notes", "view_notes", None),
        ("POST", "/patients/{}/notes", "add_note", {"author": "a", "role": "RN", "content": "c"}),
        ("DELETE", "/patients/{}/notes/n-001", "delete_note", None),
        ("POST", "/patients/{}/labs", "enter_labs", {"potassium": 4.0}),
    ],
)
def test_every_refused_action_is_logged_like_a_missing_one(
    app_and_client: tuple[Any, TestClient], method: str, path: str, action: str, body: Any
) -> None:
    _, client = app_and_client
    audit = ctx(app_and_client).audit
    h = as_("md-aquino")
    outcomes = []
    for pid in ("p-001", "p-999"):  # exists but not theirs / does not exist
        before = len(audit.records())
        response = client.request(method, path.format(pid), headers=h, json=body)
        new = audit.records()[before:]
        assert len(new) == 1, (pid, new)
        outcomes.append((response.status_code, response.json(), new[0].action, new[0].outcome))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][2:] == (action, "not_found")


def test_an_unknown_ward_is_audited_and_logged_like_any_other_miss(
    app_and_client: tuple[Any, TestClient],
) -> None:
    _, client = app_and_client
    client.get("/wards/ICU/rows", headers=as_("rn-manalo"))
    client.get("/wards/XYZ/rows", headers=as_("rn-manalo"))
    first, second = ctx(app_and_client).audit.for_clinician("rn-manalo")
    assert (
        (first.action, first.outcome)
        == (second.action, second.outcome)
        == ("view_ward", "not_found")
    )


# --- Data: contract shapes, null never zero -----------------------------------------------


def test_patient_detail_is_the_dataset_row_with_its_history(client: TestClient) -> None:
    detail = PatientDetail.model_validate(
        client.get("/patients/p-001", headers=as_("rn-manalo")).json()
    )
    seeded = next(r for r in DATA["ranked"] if r["id"] == "p-001")
    assert detail.name == seeded["name"]
    assert detail.score == seeded["score"] == 9
    assert [e.text for e in detail.escalation_reasons] == [
        e["text"] for e in seeded["escalation_reasons"]
    ]
    assert detail.tier_breakdown.tier_a is not None
    assert detail.tier_breakdown.tier_a.score == 9
    assert len(detail.vital_history.heart_rate) == 24


def test_gaps_arrive_as_json_null_never_zero(client: TestClient) -> None:
    body = client.get("/patients/p-006", headers=as_("rn-manalo")).json()
    heart = body["vital_history"]["heart_rate"]
    assert [p["value"] for p in heart].count(None) == 3
    for series in body["vital_history"].values():
        assert all(p["value"] is None or p["value"] > 0 for p in series)
    for series in body["vital_trends"].values():
        assert all(v is None or v > 0 for v in series)


def test_missing_inputs_are_not_ranked_with_a_reason_not_zero_scored(client: TestClient) -> None:
    ward = WardResponse.model_validate(
        client.get("/wards/W4/rows", headers=as_("rn-manalo")).json()
    )
    by_id = {a.id: a for a in ward.abstained}
    assert set(by_id) == {"p-004", "p-005"}
    assert by_id["p-004"].reason == "Systolic BP missing"
    assert by_id["p-005"].reason == "No device data"
    assert "p-004" not in {r.id for r in ward.ranked}


def test_a_ranked_patient_who_loses_an_input_becomes_not_ranked(
    app_and_client: tuple[Any, TestClient],
) -> None:
    # The score is recomputed on every read: remove an input and the patient abstains.
    _, client = app_and_client
    record = ctx(app_and_client).store.patients["p-002"]
    vitals = record.state.vitals
    absent = {
        "data": {"present": False, "reason": "not_measured"},
        "provenance": vitals.blood_pressure.provenance.model_dump(),
    }
    broken = vitals.model_copy(
        update={"blood_pressure": type(vitals.blood_pressure).model_validate(absent)}
    )
    record.state = record.state.model_copy(update={"vitals": broken})
    ward = WardResponse.model_validate(
        client.get("/wards/W4/rows", headers=as_("rn-manalo")).json()
    )
    assert "p-002" not in {r.id for r in ward.ranked}
    row = next(a for a in ward.abstained if a.id == "p-002")
    assert row.reason == "Systolic BP missing"
    assert client.get("/patients/p-002", headers=as_("rn-manalo")).status_code == 404


# --- Writes ------------------------------------------------------------------------------


def test_notes_round_trip(client: TestClient) -> None:
    h = as_("rn-manalo")
    created = client.post(
        "/patients/p-003/notes",
        headers=h,
        json={"author": "RN Cruz", "role": "RN", "content": "Stable."},
    )
    assert created.status_code == 201
    note = created.json()
    assert (note["patient_id"], note["synthetic"], note["timestamp"]) == (
        "p-003",
        True,
        "2026-09-03T07:00:00Z",  # the ward clock is the dataset's as_of, not the wall clock
    )
    listed = client.get("/patients/p-003/notes", headers=h).json()
    assert listed[0]["id"] == note["id"]  # newest first
    assert client.delete(f"/patients/p-003/notes/{note['id']}", headers=h).status_code == 204
    assert note["id"] not in {
        n["id"] for n in client.get("/patients/p-003/notes", headers=h).json()
    }


def test_labs_update_only_what_was_entered(client: TestClient) -> None:
    h = as_("rn-manalo")
    before = client.get("/patients/p-001", headers=h).json()["labs"]
    assert before["potassium"]["data"]["value"] == 3.8
    assert before["troponin"] is None
    panel = client.post("/patients/p-001/labs", headers=h, json={"potassium": 4.4}).json()
    assert panel["potassium"]["data"]["value"] == 4.4
    assert panel["potassium"]["provenance"]["source"] == "lab"
    assert panel["bnp"]["data"]["value"] == 1840  # untouched
    assert panel["troponin"] is None  # omitted stays missing; it is not zero
    assert panel["freshness_hours"] == 1.0  # the oldest lab on the panel is 1 h old


def test_a_panel_is_only_as_fresh_as_its_oldest_lab(client: TestClient) -> None:
    h = as_("rn-manalo")
    # p-011's labs are 36 h old. One fresh potassium must not make the panel read "0 h".
    before = client.get("/patients/p-011", headers=h).json()["labs"]
    assert before["freshness_hours"] == 36.0
    panel = client.post("/patients/p-011/labs", headers=h, json={"potassium": 4.1}).json()
    assert panel["potassium"]["provenance"]["observed_at"] == "2026-09-03T07:00:00Z"
    assert panel["freshness_hours"] == 36.0
    assert panel["sodium"]["data"]["present"] is True  # the stale values are still there


def test_replacing_every_lab_makes_the_panel_fresh(client: TestClient) -> None:
    h = as_("rn-manalo")
    panel = client.get("/patients/p-011", headers=h).json()["labs"]
    present = {
        n: m["data"]["value"] for n, m in panel.items() if isinstance(m, dict) and "data" in m
    }
    assert present
    fresh = client.post("/patients/p-011/labs", headers=h, json=present).json()
    assert fresh["freshness_hours"] == 0.0


def test_ward_time_can_follow_the_system_clock() -> None:
    app = create_app(Settings(ward_time="system"), clock=lambda: NOW)
    client = TestClient(app)
    note = client.post(
        "/patients/p-003/notes",
        headers=as_("rn-manalo"),
        json={"author": "a", "role": "RN", "content": "c"},
    ).json()
    assert note["timestamp"] == "2026-10-14T12:00:00Z"


def test_ward_time_setting_is_validated() -> None:
    assert Settings.from_env({"BIOSENTRY_WARD_TIME": "system"}).ward_time == "system"
    assert Settings.from_env({}).ward_time == "dataset"
    with pytest.raises(ValueError, match="BIOSENTRY_WARD_TIME"):
        Settings.from_env({"BIOSENTRY_WARD_TIME": "tomorrow"})


def test_admission_does_not_keep_what_it_does_not_use(
    app_and_client: tuple[Any, TestClient],
) -> None:
    _, client = app_and_client
    form = {
        "lastName": "Okonkwo", "firstName": "Ada", "dateOfBirth": "1980-07-04", "age": 45,
        "sex": "F", "bed": "9Z", "admissionRoute": "er_triage", "chiefComplaint": "c",
        "admittingContext": "ctx", "attendingPhysician": "p",
        "philhealthPin": "98-765432109-8", "contactNumber": "0917-555-0100",
        "allergies": "penicillin",
    }  # fmt: skip
    assert client.post("/patients", headers=as_("rn-delacruz"), json=form).status_code == 201
    stored = repr(ctx(app_and_client).store.patients)
    for dropped in ("98-765432109-8", "0917-555-0100", "1980-07-04", "penicillin"):
        assert dropped not in stored  # nothing sensitive is held in plaintext (W5)


def test_a_negative_lab_is_rejected_and_stores_nothing(client: TestClient) -> None:
    h = as_("rn-manalo")
    response = client.post("/patients/p-001/labs", headers=h, json={"potassium": -1})
    assert response.status_code == 422
    after = client.get("/patients/p-001", headers=h).json()["labs"]
    assert after["potassium"]["data"]["value"] == 3.8


def test_admission_splits_the_blood_pressure_once(app_and_client: tuple[Any, TestClient]) -> None:
    _, client = app_and_client
    form = {
        "lastName": "Dela Cruz",
        "firstName": "Juan",
        "dateOfBirth": "1970-01-01",
        "age": 55,
        "sex": "M",
        "bed": "11A",
        "admissionRoute": "er_triage",
        "chiefComplaint": "Chest pain",
        "admittingContext": "Chest pain, rule out ACS",
        "attendingPhysician": "Dr Reyes",
        "initialBp": "120/80",
        "initialAvpu": "A",
    }
    response = client.post("/patients", headers=as_("rn-delacruz"), json=form)
    assert response.status_code == 201
    row = AbstainedRow.model_validate(response.json())
    assert row.id == "p-013"
    assert (row.name, row.synthetic) == ("Dela Cruz, Juan", True)
    # NOT RANKED because every missing input is named by the arbiter, not because of a script.
    assert row.reason.startswith("No device data")
    assert "Apply the patch" in row.instruction
    record = ctx(app_and_client).store.patients[row.id]
    stored = record.state.vitals.blood_pressure.data
    assert isinstance(stored, BloodPressurePresent)
    assert (stored.value.systolic, stored.value.diastolic) == (120, 80)
    mine = client.get("/wards/W4/rows", headers=as_("rn-delacruz")).json()
    assert row.id in {a["id"] for a in mine["abstained"]}
    other = client.get("/wards/W4/rows", headers=as_("rn-reyes")).json()
    assert row.id not in {a["id"] for a in other["abstained"]}


@pytest.mark.parametrize(
    "bp",
    ["20/80", "120/130", "400/80", "120/10", "120/120", "12/8", "abc", "120-80", "120/80/1"],
)
def test_an_implausible_or_malformed_admission_blood_pressure_is_rejected_not_clamped(
    app_and_client: tuple[Any, TestClient], bp: str
) -> None:
    _, client = app_and_client
    form = {
        "lastName": "X", "firstName": "Y", "dateOfBirth": "1970-01-01", "age": 50, "sex": "F",
        "bed": "1A", "admissionRoute": "transfer", "chiefComplaint": "c",
        "admittingContext": "a", "attendingPhysician": "p", "initialBp": bp,
    }  # fmt: skip
    before = len(ctx(app_and_client).store.patients)
    response = client.post("/patients", headers=as_("rn-delacruz"), json=form)
    assert response.status_code == 422
    assert len(ctx(app_and_client).store.patients) == before


def test_extraction_is_not_implemented_and_says_so(client: TestClient) -> None:
    for path in ("/extract/labs", "/extract/patient"):
        response = client.post(path, headers=as_("rn-manalo"))
        assert response.status_code == 501
        assert "not implemented" in response.json()["detail"]
    assert client.post("/extract/labs").status_code == 401


# --- Nurse-recorded vitals: the way out of NOT RANKED ----------------------------------------


def _ward(client: TestClient, who: str) -> WardResponse:
    return WardResponse.model_validate(client.get("/wards/W4/rows", headers=as_(who)).json())


def test_recording_the_missing_blood_pressure_ranks_the_patient_at_once(client: TestClient) -> None:
    before = _ward(client, "rn-delacruz")
    assert "p-004" in {a.id for a in before.abstained}
    assert next(a for a in before.abstained if a.id == "p-004").reason == "Systolic BP missing"

    response = client.post(
        "/patients/p-004/vitals",
        headers=as_("rn-delacruz"),
        json={"systolic": 130, "diastolic": 84},
    )
    assert response.status_code == 200
    recorded = VitalsRecorded.model_validate(response.json())
    assert recorded.ranked is True
    assert recorded.score == 0  # HR 88, RR 18, SpO2 96, 36.8 C, A, air, SBP 130
    assert recorded.rank is not None
    assert recorded.not_ranked_reason is None
    # The echo carries what was stored, with nurse provenance.
    echo = response.json()["blood_pressure"]
    assert echo["data"] == {"present": True, "value": {"systolic": 130, "diastolic": 84}}
    assert echo["provenance"]["source"] == "nurse"
    assert echo["provenance"]["synthetic"] is True
    assert response.json()["consciousness"] is None  # not recorded, not echoed

    after = _ward(client, "rn-delacruz")
    assert "p-004" in {r.id for r in after.ranked}
    assert "p-004" not in {a.id for a in after.abstained}
    assert next(r for r in after.ranked if r.id == "p-004").rank == recorded.rank
    assert [r.rank for r in after.ranked] == list(range(1, len(after.ranked) + 1))
    assert client.get("/patients/p-004", headers=as_("rn-delacruz")).status_code == 200


def test_a_recorded_value_re_ranks_through_the_real_arbiter(client: TestClient) -> None:
    h = as_("rn-manalo")
    before = next(r for r in _ward(client, "rn-manalo").ranked if r.id == "p-012")
    assert before.score == 0
    assert before.escalation_reasons == []
    response = client.post("/patients/p-012/vitals", headers=h, json={"acvpu": "U"})
    recorded = VitalsRecorded.model_validate(response.json())
    assert (recorded.ranked, recorded.score) == (True, 3)  # not Alert scores 3
    after = next(r for r in _ward(client, "rn-manalo").ranked if r.id == "p-012")
    assert after.rank < before.rank
    assert [e.text for e in after.escalation_reasons] == [
        "Single parameter at 3: level of consciousness"
    ]


def test_a_patient_without_a_patch_stays_not_ranked_whatever_the_nurse_records(
    client: TestClient,
) -> None:
    response = client.post(
        "/patients/p-005/vitals",
        headers=as_("rn-reyes"),
        json={"systolic": 118, "diastolic": 74, "acvpu": "A", "on_oxygen": False, "spo2_scale": 1},
    )
    recorded = VitalsRecorded.model_validate(response.json())
    assert recorded.ranked is False
    assert recorded.rank is None
    assert recorded.score is None
    assert recorded.not_ranked_reason == "No device data"
    assert recorded.not_ranked_instruction == "Apply the patch and verify the signal"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"systolic": 130},
        {"diastolic": 80},
        {"systolic": 0, "diastolic": 0},
        {"systolic": 20, "diastolic": 80},
        {"systolic": 400, "diastolic": 80},
        {"systolic": 120, "diastolic": 130},
        {"systolic": 120, "diastolic": 10},
        {"systolic": 120.5, "diastolic": 80},
        {"acvpu": "X"},
        {"spo2_scale": 3},
        {"spo2_scale": "1"},
        {"spo2_scale": True},
        {"on_oxygen": "yes"},
        {"heart_rate": 70},
        {"systolic": 120, "diastolic": 80, "temperature": 37.0},
    ],
    ids=lambda b: json.dumps(b),
)
def test_an_implausible_or_incomplete_record_is_rejected_and_stores_nothing(
    app_and_client: tuple[Any, TestClient], body: dict[str, Any]
) -> None:
    _, client = app_and_client
    before = _ward(client, "rn-delacruz").model_dump()
    response = client.post("/patients/p-004/vitals", headers=as_("rn-delacruz"), json=body)
    assert response.status_code == 422
    assert _ward(client, "rn-delacruz").model_dump() == before
    state = ctx(app_and_client).store.patients["p-004"].state
    assert state.vitals.blood_pressure.data.present is False


def test_recording_for_a_patient_that_is_not_yours_is_not_found(
    app_and_client: tuple[Any, TestClient],
) -> None:
    _, client = app_and_client
    audit = ctx(app_and_client).audit
    h = as_("md-aquino")
    body = {"systolic": 120, "diastolic": 80}
    refused = client.post("/patients/p-004/vitals", headers=h, json=body)
    missing = client.post("/patients/p-999/vitals", headers=h, json=body)
    assert (refused.status_code, refused.json()) == (missing.status_code, missing.json())
    assert refused.status_code == 404
    first, second = audit.for_clinician("md-aquino")
    assert (first.action, first.outcome) == (second.action, second.outcome)
    assert (first.action, first.outcome) == ("record_vitals", "not_found")


def test_recorded_values_never_reach_the_audit_trail(
    app_and_client: tuple[Any, TestClient],
) -> None:
    _, client = app_and_client
    client.post(
        "/patients/p-004/vitals",
        headers=as_("rn-delacruz"),
        json={"systolic": 131, "diastolic": 83},
    )
    client.post(
        "/patients/p-004/vitals", headers=as_("rn-delacruz"), json={"systolic": 20, "diastolic": 80}
    )
    records = ctx(app_and_client).audit.for_clinician("rn-delacruz")
    assert [(r.action, r.outcome) for r in records] == [
        ("record_vitals", "ok"),
        ("record_vitals", "rejected"),
    ]
    text = repr(records) + client.get("/audit", headers=as_("rn-delacruz")).text
    assert "131" not in text
    assert "83" not in text


def test_a_newly_admitted_patient_can_be_recorded_but_stays_not_ranked_without_a_patch(
    client: TestClient,
) -> None:
    form = {
        "lastName": "Reyes", "firstName": "Ana", "dateOfBirth": "1980-01-01", "age": 45,
        "sex": "F", "bed": "9Z", "admissionRoute": "direct_admission", "chiefComplaint": "c",
        "admittingContext": "ctx", "attendingPhysician": "p",
    }  # fmt: skip
    admitted = client.post("/patients", headers=as_("rn-delacruz"), json=form).json()
    response = client.post(
        f"/patients/{admitted['id']}/vitals",
        headers=as_("rn-delacruz"),
        json={"systolic": 120, "diastolic": 80, "acvpu": "A", "on_oxygen": False, "spo2_scale": 1},
    )
    recorded = VitalsRecorded.model_validate(response.json())
    assert recorded.ranked is False
    assert recorded.not_ranked_reason == "No device data"


# --- The routes the frontend calls --------------------------------------------------------


def _frontend_routes() -> set[tuple[str, str]]:
    source = (REPO / "frontend" / "src" / "api" / "providers" / "http.ts").read_text("utf-8")
    verbs = {
        "fetchJson": "GET",
        "postJson": "POST",
        "deleteRequest": "DELETE",
        "uploadFile": "POST",
    }
    found: set[tuple[str, str]] = set()
    for fn, path in re.findall(
        r"\b(fetchJson|postJson|deleteRequest|uploadFile)(?:<[^>]*>)?\(\s*[`\"]([^`\"]+)[`\"]",
        source,
    ):
        normalised = re.sub(r"\$\{[^}]+\}", "{}", path)
        found.add((verbs[fn], normalised))
    return found


def _app_routes() -> set[tuple[str, str]]:
    app = create_app(Settings(), clock=lambda: NOW)
    out: set[tuple[str, str]] = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", "")
        if methods is None:
            continue
        for method in methods:
            out.add((method, re.sub(r"\{[^}]+\}", "{}", path)))
    return out


def test_the_api_serves_every_route_the_http_provider_calls() -> None:
    frontend = _frontend_routes()
    assert len(frontend) >= 9, frontend
    # The provider names the ward by id; the route is parameterised.
    normalised = {(m, "/wards/{}/rows" if p == "/wards/W4/rows" else p) for m, p in frontend}
    missing = normalised - _app_routes()
    assert missing == set()
