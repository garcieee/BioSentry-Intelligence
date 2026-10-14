"""Writes: notes, lab entry, admission and nurse-recorded vitals, all scoped and audited.

Nothing here clamps or fills in a value. A number that cannot be a real reading is rejected
with `RejectedError`; an omitted field stays as it was. A write changes a patient's state
through the store (which bumps its revision) and then refreshes the patient's snapshot, so the
score, rank and reasons come from the real arbiter at once: `record_vitals` reports the
result in its response, and the next read of the ward sees it.
"""

from datetime import datetime, timedelta

from biosentry.core.audit import AuditLog, Clock, utc_now
from biosentry.repositories.memory.store import MemoryStore, PatientRecord
from biosentry.schemas import (
    AbstainedRow,
    AcvpuMeasurement,
    AdmitPatientInput,
    BloodPressure,
    BloodPressureMeasurement,
    ClinicalNote,
    FlagMeasurement,
    LabPanel,
    MeasurementAbsent,
    NewNote,
    NumberMeasurement,
    NurseVitalsInput,
    PartialLabInput,
    Provenance,
    ProvenanceSource,
    QualityLevel,
    Spo2ScaleMeasurement,
    Trend,
    UnscoredPatient,
    VitalHistory,
    VitalHistoryFull,
    Vitals,
    VitalsRecorded,
    VitalTrends,
)
from biosentry.schemas.common import (
    AcvpuPresent,
    BloodPressurePresent,
    FlagPresent,
    NumberPresent,
    Spo2ScalePresent,
)

from .scoring import ScoringService
from .ward import WardService

# Bounds on a nurse-typed blood pressure: physical, not clinical. The floor is deliberately
# low: a true critical reading such as 45/20 must be recordable, because refusing it would
# leave the patient silently NOT RANKED, which is worse than accepting a typo (a mistyped low
# value scores 3 and over-alarms; it cannot hide a patient). Zero is "missing" (the scorer's
# zero-fill guard), so it is always rejected.
SYSTOLIC_RANGE = (20, 300)
DIASTOLIC_RANGE = (10, 200)
SPARK_BINS = 12
HISTORY_BINS = 24
BIN_MINUTES = 15


class RejectedError(ValueError):
    """The input cannot be a real reading. The caller gets a 422; nothing is stored."""


def check_blood_pressure(systolic: int, diastolic: int) -> BloodPressure:
    """The bounds for any recorded blood pressure. Out of range is rejected, never clamped."""
    low, high = SYSTOLIC_RANGE
    if not low <= systolic <= high:
        raise RejectedError(f"systolic {systolic} is outside {low}-{high}")
    low, high = DIASTOLIC_RANGE
    if not low <= diastolic <= high:
        raise RejectedError(f"diastolic {diastolic} is outside {low}-{high}")
    if diastolic >= systolic:
        raise RejectedError("diastolic must be below systolic")
    return BloodPressure(systolic=systolic, diastolic=diastolic)


def split_blood_pressure(text: str) -> BloodPressure:
    """ "120/80" -> {120, 80}, once, at the input boundary. Implausible values are rejected."""
    systolic_text, _, diastolic_text = text.partition("/")
    if not (systolic_text.isdigit() and diastolic_text.isdigit()):
        raise RejectedError("blood pressure must be written systolic/diastolic")
    return check_blood_pressure(int(systolic_text), int(diastolic_text))


def oldest_lab_age_hours(labs: dict[str, object], now: datetime) -> float | None:
    """Age, in hours, of the OLDEST lab present in the panel; None when there is none.

    A panel is only as fresh as its stalest value: entering one new potassium must not make a
    36-hour-old BNP read as "0h".
    """
    ages: list[float] = []
    for name, measurement in labs.items():
        if name == "freshness_hours" or not isinstance(measurement, NumberMeasurement):
            continue
        if isinstance(measurement.data, NumberPresent):
            seconds = (now - measurement.provenance.observed_at).total_seconds()
            ages.append(max(0.0, seconds) / 3600)
    return round(max(ages), 1) if ages else None


def _provenance(
    source: ProvenanceSource, observed_at: datetime, quality: QualityLevel = QualityLevel.ok
) -> Provenance:
    return Provenance(
        source=source,
        tier=None,
        observed_at=observed_at,
        computed_at=None,
        model_id=None,
        synthetic=True,  # this build only ever holds synthetic data (I6)
        quality=quality,
    )


def _absent_number(reason: str, source: ProvenanceSource, at: datetime) -> NumberMeasurement:
    return NumberMeasurement(
        data=MeasurementAbsent(present=False, reason=reason),
        provenance=_provenance(source, at, QualityLevel.missing),
    )


def _admitted_state(
    patient_id: str,
    form: AdmitPatientInput,
    blood_pressure: BloodPressure | None,
    now: datetime,
) -> UnscoredPatient:
    """A newly admitted patient: no patch yet, so no device data and no series."""
    nurse = _provenance(ProvenanceSource.nurse, now)
    missing_nurse = _provenance(ProvenanceSource.nurse, now, QualityLevel.missing)
    absent = MeasurementAbsent(present=False, reason="not_measured")
    not_recorded = MeasurementAbsent(present=False, reason="not_recorded")
    vitals = Vitals(
        heart_rate=_absent_number("no_patch", ProvenanceSource.device, now),
        respiratory_rate=_absent_number("no_patch", ProvenanceSource.device, now),
        spo2=_absent_number("no_patch", ProvenanceSource.device, now),
        temperature=_absent_number("no_patch", ProvenanceSource.device, now),
        blood_pressure=(
            BloodPressureMeasurement(
                data=BloodPressurePresent(present=True, value=blood_pressure), provenance=nurse
            )
            if blood_pressure is not None
            else BloodPressureMeasurement(data=absent, provenance=missing_nurse)
        ),
        consciousness=(
            AcvpuMeasurement(
                data=AcvpuPresent(present=True, value=form.initial_avpu), provenance=nurse
            )
            if form.initial_avpu is not None
            else AcvpuMeasurement(data=absent, provenance=missing_nurse)
        ),
        supplemental_o2=FlagMeasurement(data=not_recorded, provenance=missing_nurse),
        spo2_scale=Spo2ScaleMeasurement(data=not_recorded, provenance=missing_nurse),
    )
    gaps: list[float | None] = [None] * SPARK_BINS

    def empty_series() -> list[VitalHistory]:
        return [
            VitalHistory(time=now - timedelta(minutes=(HISTORY_BINS - b) * BIN_MINUTES), value=None)
            for b in range(HISTORY_BINS)
        ]

    return UnscoredPatient(
        id=patient_id,
        name=f"{form.last_name}, {form.first_name}",
        age=form.age,
        sex=form.sex.value,
        bed=form.bed,
        admitting_context=form.admitting_context,
        trend=Trend.insufficient,
        mechanism="Admitted; not ranked until a patch is applied and every input is recorded.",
        supporting="",
        vitals=vitals,
        vital_trends=VitalTrends(
            heart_rate=list(gaps),
            respiratory_rate=list(gaps),
            spo2=list(gaps),
            temperature=list(gaps),
        ),
        vital_history=VitalHistoryFull(
            heart_rate=empty_series(), respiratory_rate=empty_series(), spo2=empty_series()
        ),
        labs=LabPanel.model_validate(dict.fromkeys(LabPanel.model_fields)),
        tier_b=None,
        tier_c=None,
        signal_quality=None,
        last_update_s=None,
        synthetic=True,
    )


class PatientService:
    def __init__(
        self,
        store: MemoryStore,
        audit: AuditLog,
        wards: WardService,
        scoring: ScoringService,
        clock: Clock = utc_now,
    ) -> None:
        self._store = store
        self._audit = audit
        self._wards = wards
        self._scoring = scoring
        self._clock = clock

    def _visible(self, clinician_id: str, patient_id: str, action: str) -> PatientRecord | None:
        record = self._store.patients.get(patient_id)
        if record is None or patient_id not in self._store.assigned(clinician_id):
            self._audit.append(clinician_id, action, patient_id, "not_found")
            return None
        return record

    # --- notes -----------------------------------------------------------------------------

    def notes(self, clinician_id: str, patient_id: str) -> list[ClinicalNote] | None:
        if self._visible(clinician_id, patient_id, "view_notes") is None:
            return None
        self._audit.append(clinician_id, "view_notes", patient_id, "ok")
        return list(reversed(self._store.notes.get(patient_id, [])))

    def add_note(self, clinician_id: str, patient_id: str, body: NewNote) -> ClinicalNote | None:
        if self._visible(clinician_id, patient_id, "add_note") is None:
            return None
        with self._store.lock:
            note = ClinicalNote(
                id=self._store.next_note_id(),
                patient_id=patient_id,
                author=body.author,
                role=body.role,
                timestamp=self._clock(),
                content=body.content,
                synthetic=True,
            )
            self._store.notes.setdefault(patient_id, []).append(note)
        self._audit.append(clinician_id, "add_note", patient_id, "ok")
        return note

    def delete_note(self, clinician_id: str, patient_id: str, note_id: str) -> bool:
        if self._visible(clinician_id, patient_id, "delete_note") is None:
            return False
        with self._store.lock:
            notes = self._store.notes.get(patient_id, [])
            self._store.notes[patient_id] = [n for n in notes if n.id != note_id]
        self._audit.append(clinician_id, "delete_note", patient_id, "ok")
        return True

    # --- labs ------------------------------------------------------------------------------

    def enter_labs(
        self, clinician_id: str, patient_id: str, labs: PartialLabInput
    ) -> LabPanel | None:
        if self._visible(clinician_id, patient_id, "enter_labs") is None:
            return None
        entered = {k: v for k, v in labs.model_dump().items() if v is not None}
        for name, value in entered.items():
            if value < 0:
                self._audit.append(clinician_id, "enter_labs", patient_id, "rejected")
                raise RejectedError(f"{name} cannot be negative")
        now = self._clock()
        prov = _provenance(ProvenanceSource.lab, now)

        def merge(state: UnscoredPatient) -> UnscoredPatient:
            fields: dict[str, object] = {
                name: getattr(state.labs, name) for name in LabPanel.model_fields
            }
            for name, value in entered.items():
                fields[name] = NumberMeasurement(
                    data=NumberPresent(present=True, value=value), provenance=prov
                )
            fields["freshness_hours"] = oldest_lab_age_hours(fields, now)
            return state.model_copy(update={"labs": LabPanel.model_validate(fields)})

        _, state = self._store.update(patient_id, merge)
        self._audit.append(clinician_id, "enter_labs", patient_id, "ok")
        self._scoring.refresh(patient_id)  # a lab is not a NEWS2 input, but a write drops it
        return state.labs

    # --- admission -------------------------------------------------------------------------

    def admit(self, clinician_id: str, form: AdmitPatientInput) -> AbstainedRow:
        """Admit a patient: NOT RANKED until a patch is applied and the signal is verified.

        Kept: name, age, sex, bed, admitting context, and the nurse-entered blood pressure
        (split once, structured) and ACVPU. Accepted but NOT stored in this build: date of
        birth, civil status, contact number, PhilHealth PIN, route, condition on admission,
        chief complaint, attending physician, allergies, weight and height. The PIN is
        sensitive personal information (RA 10173): when it is persisted it must be stored
        ciphertext-only and never logged or cached (W5).
        """
        blood_pressure: BloodPressure | None = None
        if form.initial_bp is not None:
            try:
                blood_pressure = split_blood_pressure(form.initial_bp)
            except RejectedError:
                self._audit.append(clinician_id, "admit_patient", "-", "rejected")
                raise
        with self._store.lock:
            patient_id = self._store.next_patient_id()
            state = _admitted_state(patient_id, form, blood_pressure, self._clock())
            self._store.add_patient(PatientRecord(patient_id, state), clinician_id)
        self._audit.append(clinician_id, "admit_patient", patient_id, "ok")
        _, abstained = self._wards.compute(frozenset({patient_id}))
        return next(a for a in abstained if a.id == patient_id)

    # --- nurse-recorded vitals ---------------------------------------------------------------

    def record_vitals(
        self, clinician_id: str, patient_id: str, body: NurseVitalsInput
    ) -> VitalsRecorded | None:
        """Record nurse-entered NEWS2 inputs and report where the patient now stands.

        Bounds are physical, not clinical, and are never clamped. The recorded measurement is
        echoed with its provenance; the rank is relative to the caller's own set.
        """
        if self._visible(clinician_id, patient_id, "record_vitals") is None:
            return None
        try:
            blood_pressure = (
                check_blood_pressure(body.systolic, body.diastolic)
                if body.systolic is not None and body.diastolic is not None
                else None
            )
        except RejectedError:
            self._audit.append(clinician_id, "record_vitals", patient_id, "rejected")
            raise

        prov = _provenance(ProvenanceSource.nurse, self._clock())
        updates: dict[str, object] = {}
        echo_bp: BloodPressureMeasurement | None = None
        echo_acvpu: AcvpuMeasurement | None = None
        echo_o2: FlagMeasurement | None = None
        echo_scale: Spo2ScaleMeasurement | None = None
        if blood_pressure is not None:
            echo_bp = BloodPressureMeasurement(
                data=BloodPressurePresent(present=True, value=blood_pressure), provenance=prov
            )
            updates["blood_pressure"] = echo_bp
        if body.acvpu is not None:
            echo_acvpu = AcvpuMeasurement(
                data=AcvpuPresent(present=True, value=body.acvpu), provenance=prov
            )
            updates["consciousness"] = echo_acvpu
        if body.on_oxygen is not None:
            echo_o2 = FlagMeasurement(
                data=FlagPresent(present=True, value=body.on_oxygen), provenance=prov
            )
            updates["supplemental_o2"] = echo_o2
        if body.spo2_scale is not None:
            echo_scale = Spo2ScaleMeasurement(
                data=Spo2ScalePresent(present=True, value=body.spo2_scale), provenance=prov
            )
            updates["spo2_scale"] = echo_scale

        self._store.update(
            patient_id,
            lambda state: state.model_copy(
                update={"vitals": state.vitals.model_copy(update=updates)}
            ),
        )
        self._audit.append(clinician_id, "record_vitals", patient_id, "ok")

        # The read below recomputes this patient's snapshot (its revision just moved), so the
        # response is built from the fresh decision.
        ranked, abstained = self._wards.compute(self._store.assigned(clinician_id))
        row = next((r for r in ranked if r.id == patient_id), None)
        not_ranked = next((a for a in abstained if a.id == patient_id), None)
        return VitalsRecorded(
            patient_id=patient_id,
            blood_pressure=echo_bp,
            consciousness=echo_acvpu,
            supplemental_o2=echo_o2,
            spo2_scale=echo_scale,
            ranked=row is not None,
            rank=row.rank if row is not None else None,
            score=row.score if row is not None else None,
            not_ranked_reason=not_ranked.reason if not_ranked is not None else None,
            not_ranked_instruction=not_ranked.instruction if not_ranked is not None else None,
        )
