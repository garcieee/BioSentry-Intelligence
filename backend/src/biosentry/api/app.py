"""The HTTP API: the routes the frontend's http provider calls (frontend/src/api/providers/http.ts).

Identity is a bearer token that names a clinician (the CP6 auth stub). Missing or malformed
credentials get 401; a token that names nobody gets 403 and nothing is served. Identity comes
first on every route, including for a body that fails validation. Everything else is scoped
to the caller's patients on the server, on every call, and a patient who does not exist and
one who is not yours get the same 404. A write whose body fails validation leaves a
`rejected` audit row (ids only, no values). Responses are `Cache-Control: no-store`. The
service serves nothing unauthenticated except /healthz: no docs or schema routes (the
contract is contracts/openapi.json).
"""

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from biosentry.core.audit import AuditLog, Clock, utc_now
from biosentry.core.config import Settings
from biosentry.repositories.memory import store as memory_store
from biosentry.schemas import (
    AbstainedRow,
    AdmitPatientInput,
    ClinicalNote,
    LabPanel,
    NewNote,
    NurseVitalsInput,
    PartialLabInput,
    PatientDetail,
    PatientSummary,
    VitalsRecorded,
    WardResponse,
)
from biosentry.services.patients import PatientService, RejectedError
from biosentry.services.ward import WardService

NOT_FOUND = "Not found"

# The body-bearing write routes and the action their audit rows carry. A body that fails
# validation never reaches the handler, so its audit row is written by the validation handler.
WRITE_ACTIONS = {
    ("POST", "/patients"): "admit_patient",
    ("POST", "/patients/{patient_id}/notes"): "add_note",
    ("POST", "/patients/{patient_id}/labs"): "enter_labs",
    ("POST", "/patients/{patient_id}/vitals"): "record_vitals",
}


@dataclass(slots=True)
class Context:
    store: memory_store.MemoryStore
    audit: AuditLog
    wards: WardService
    patients: PatientService


class AuditEntry(BaseModel):
    """What a clinician may read back about their own activity: ids and outcomes only."""

    seq: int
    at: str
    action: str
    resource: str
    outcome: str


def context(request: Request) -> Context:
    found: Context = request.app.state.ctx
    return found


Ctx = Annotated[Context, Depends(context)]


def identify(ctx: Context, authorization: str | None) -> str:
    """The clinician a bearer token names. Otherwise 401/403, audited without an identity."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        ctx.audit.append(None, "authenticate", "-", "denied")
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    identity = token.strip()
    if not ctx.store.knows_clinician(identity):
        ctx.audit.append(None, "authenticate", "-", "denied")
        raise HTTPException(status_code=403, detail="Unknown identity")
    return identity


def clinician(
    ctx: Ctx,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    return identify(ctx, authorization)


Who = Annotated[str, Depends(clinician)]


def create_app(settings: Settings | None = None, clock: Clock = utc_now) -> FastAPI:
    settings = settings or Settings.from_env()
    store = memory_store.load(settings.dataset)
    audit = AuditLog(clock, role_of=store.role_of)
    ward_clock: Clock = (lambda: store.as_of) if settings.ward_time == "dataset" else clock
    logging.getLogger("biosentry.api").warning(
        "Identity is a stub: the bearer token IS the clinician id. Never expose this server "
        "beyond loopback; real authentication replaces it before any non-synthetic use."
    )
    wards = WardService(store, audit)
    ctx = Context(
        store=store,
        audit=audit,
        wards=wards,
        patients=PatientService(store, audit, wards, ward_clock),
    )

    app = FastAPI(
        title="BioSentry Intelligence API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def no_store(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RejectedError)
    async def rejected(_: Request, exc: RejectedError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> Response:
        # Identity first, as on every route: a body that is not JSON fails before the
        # dependencies run, and an unidentified caller must be told nothing about it.
        try:
            who = identify(ctx, request.headers.get("authorization"))
        except HTTPException as denied:
            return JSONResponse(
                status_code=denied.status_code,
                content={"detail": denied.detail},
                headers=denied.headers,
            )
        route = request.scope.get("route")
        action = WRITE_ACTIONS.get((request.method, getattr(route, "path", "")))
        if action is not None:  # ids and outcome only: the rejected values are never logged
            resource = str(request.path_params.get("patient_id", "-"))
            ctx.audit.append(who, action, resource, "rejected")
        return await request_validation_exception_handler(request, exc)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/wards/{ward}/rows", response_model=WardResponse)
    def ward_rows(ward: str, ctx: Ctx, who: Who) -> WardResponse:
        if ward != ctx.store.ward:
            ctx.audit.append(who, "view_ward", ward, "not_found")
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return ctx.wards.ward(who)

    @app.get("/patients", response_model=list[PatientSummary])
    def list_patients(ctx: Ctx, who: Who) -> list[PatientSummary]:
        return ctx.wards.summaries(who)

    @app.get("/patients/{patient_id}", response_model=PatientDetail)
    def get_patient(patient_id: str, ctx: Ctx, who: Who) -> PatientDetail:
        found = ctx.wards.patient(who, patient_id)
        if found is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return found

    @app.post("/patients", response_model=AbstainedRow, status_code=201)
    def admit_patient(form: AdmitPatientInput, ctx: Ctx, who: Who) -> AbstainedRow:
        return ctx.patients.admit(who, form)

    @app.get("/patients/{patient_id}/notes", response_model=list[ClinicalNote])
    def get_notes(patient_id: str, ctx: Ctx, who: Who) -> list[ClinicalNote]:
        notes = ctx.patients.notes(who, patient_id)
        if notes is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return notes

    @app.post("/patients/{patient_id}/notes", response_model=ClinicalNote, status_code=201)
    def add_note(patient_id: str, body: NewNote, ctx: Ctx, who: Who) -> ClinicalNote:
        note = ctx.patients.add_note(who, patient_id, body)
        if note is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return note

    @app.delete("/patients/{patient_id}/notes/{note_id}", status_code=204)
    def delete_note(patient_id: str, note_id: str, ctx: Ctx, who: Who) -> Response:
        if not ctx.patients.delete_note(who, patient_id, note_id):
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return Response(status_code=204)

    @app.post("/patients/{patient_id}/labs", response_model=LabPanel)
    def enter_labs(patient_id: str, labs: PartialLabInput, ctx: Ctx, who: Who) -> LabPanel:
        panel = ctx.patients.enter_labs(who, patient_id, labs)
        if panel is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return panel

    @app.post("/patients/{patient_id}/vitals", response_model=VitalsRecorded)
    def record_vitals(
        patient_id: str, body: NurseVitalsInput, ctx: Ctx, who: Who
    ) -> VitalsRecorded:
        recorded = ctx.patients.record_vitals(who, patient_id, body)
        if recorded is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return recorded

    @app.post("/extract/labs", status_code=501)
    def extract_labs(who: Who) -> JSONResponse:
        return JSONResponse(
            status_code=501, content={"detail": "Document extraction is not implemented (v2)"}
        )

    @app.post("/extract/patient", status_code=501)
    def extract_patient(who: Who) -> JSONResponse:
        return JSONResponse(
            status_code=501, content={"detail": "Document extraction is not implemented (v2)"}
        )

    @app.get("/audit", response_model=list[AuditEntry])
    def my_audit(ctx: Ctx, who: Who) -> list[AuditEntry]:
        """The caller's own audit trail: not a window onto anyone else's activity."""
        return [
            AuditEntry(
                seq=r.seq,
                at=r.at.isoformat().replace("+00:00", "Z"),
                action=r.action,
                resource=r.resource,
                outcome=r.outcome,
            )
            for r in ctx.audit.for_clinician(who)
        ]

    return app
