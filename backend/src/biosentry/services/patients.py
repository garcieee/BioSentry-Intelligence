"""Writes: notes, lab entry and admission, all scoped to the caller and audited.

Nothing here clamps or fills in a value. A number that cannot be a real reading is rejected
with `RejectedError`; an omitted field stays as it was.
"""

from datetime import datetime

from biosentry.core.audit import AuditLog, Clock, utc_now
from biosentry.repositories.memory.store import MemoryStore, PatientRecord
from biosentry.schemas import (
    AbstainedRow,
    AdmitPatientInput,
    BloodPressure,
    ClinicalNote,
    LabPanel,
    NewNote,
    NumberMeasurement,
    PartialLabInput,
    Provenance,
    ProvenanceSource,
    QualityLevel,
)
from biosentry.schemas.common import NumberPresent

# Plausibility of a nurse-typed admission blood pressure (physical, not clinical, bounds).
SYSTOLIC_RANGE = (50, 300)
DIASTOLIC_RANGE = (20, 200)


class RejectedError(ValueError):
    """The input cannot be a real reading. The caller gets a 422; nothing is stored."""


def split_blood_pressure(text: str) -> BloodPressure:
    """ "120/80" -> {120, 80}, once, at the input boundary. Implausible values are rejected."""
    systolic_text, _, diastolic_text = text.partition("/")
    if not (systolic_text.isdigit() and diastolic_text.isdigit()):
        raise RejectedError("blood pressure must be written systolic/diastolic")
    systolic, diastolic = int(systolic_text), int(diastolic_text)
    if not SYSTOLIC_RANGE[0] <= systolic <= SYSTOLIC_RANGE[1]:
        low, high = SYSTOLIC_RANGE
        raise RejectedError(f"systolic {systolic} is outside {low}-{high}")
    if not DIASTOLIC_RANGE[0] <= diastolic <= DIASTOLIC_RANGE[1]:
        raise RejectedError(
            f"diastolic {diastolic} is outside {DIASTOLIC_RANGE[0]}-{DIASTOLIC_RANGE[1]}"
        )
    if diastolic >= systolic:
        raise RejectedError("diastolic must be below systolic")
    return BloodPressure(systolic=systolic, diastolic=diastolic)


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


class PatientService:
    def __init__(self, store: MemoryStore, audit: AuditLog, clock: Clock = utc_now) -> None:
        self._store = store
        self._audit = audit
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
        record = self._visible(clinician_id, patient_id, "enter_labs")
        if record is None:
            return None
        entered = {k: v for k, v in labs.model_dump().items() if v is not None}
        for name, value in entered.items():
            if value < 0:
                self._audit.append(clinician_id, "enter_labs", patient_id, "rejected")
                raise RejectedError(f"{name} cannot be negative")
        prov = Provenance(
            source=ProvenanceSource.lab,
            tier=None,
            observed_at=self._clock(),
            computed_at=None,
            model_id=None,
            synthetic=True,
            quality=QualityLevel.ok,
        )
        with self._store.lock:
            fields: dict[str, object] = dict.fromkeys(LabPanel.model_fields)
            if record.labs is not None:
                fields.update({n: getattr(record.labs, n) for n in LabPanel.model_fields})
            for name, value in entered.items():
                fields[name] = NumberMeasurement(
                    data=NumberPresent(present=True, value=value), provenance=prov
                )
            fields["freshness_hours"] = oldest_lab_age_hours(fields, self._clock())
            panel = LabPanel.model_validate(fields)
            record.labs = panel
            if record.ranked is not None:
                record.ranked = record.ranked.model_copy(update={"labs": panel})
        self._audit.append(clinician_id, "enter_labs", patient_id, "ok")
        return panel

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
            row = AbstainedRow(
                id=patient_id,
                name=f"{form.last_name}, {form.first_name}",
                age=form.age,
                sex=form.sex.value,
                bed=form.bed,
                admitting_context=form.admitting_context,
                reason="Patch not yet applied",
                instruction="Apply chest patch and verify signal",
                synthetic=True,  # this build only ever holds synthetic data (I6)
            )
            record = PatientRecord(
                id=patient_id,
                abstained=row,
                admitted_bp=blood_pressure,
                admitted_acvpu=form.initial_avpu,
            )
            self._store.add_patient(record, clinician_id)
        self._audit.append(clinician_id, "admit_patient", patient_id, "ok")
        return row
