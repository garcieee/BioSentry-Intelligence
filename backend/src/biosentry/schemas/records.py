"""Clinical notes and the signed-in session."""

from enum import StrEnum

from pydantic import AwareDatetime

from .base import Contract, Flag


class ClinicalNote(Contract):
    id: str
    patient_id: str
    author: str
    role: str
    timestamp: AwareDatetime
    content: str
    synthetic: Flag  # I6: every seed/fixture record carries the flag


class SessionRole(StrEnum):
    rn = "rn"
    md = "md"
    charge_rn = "charge_rn"


class Session(Contract):
    clinician_id: str
    ward: str
    role: SessionRole


class NewNote(Contract):
    """The body of POST /patients/{id}/notes. The server assigns id, time and the flag."""

    author: str
    role: str
    content: str
