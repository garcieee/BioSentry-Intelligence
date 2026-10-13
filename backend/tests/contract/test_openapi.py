"""The OpenAPI document: deterministic, complete, and equal to what is committed."""

import json
import re
from pathlib import Path
from typing import Any

from biosentry.schemas.openapi import build_openapi, dumps

REPO = Path(__file__).resolve().parents[3]
COMMITTED = REPO / "contracts" / "openapi.json"
FRONTEND_TYPES = REPO / "frontend" / "src" / "types" / "index.ts"

# Every name the hand-written frontend/src/types/index.ts exported before CP1.
FRONTEND_TYPES_BEFORE_CP1 = [
    "ProvenanceSource",
    "Tier",
    "QualityLevel",
    "Provenance",
    "Trend",
    "VitalHistory",
    "Vitals",
    "VitalTrends",
    "VitalHistoryFull",
    "LabPanel",
    "TierStatus",
    "TierBFinding",
    "TierBData",
    "TierCAttribution",
    "TierCData",
    "EscalationRule",
    "EscalationReason",
    "ScoreRow",
    "AbstainedRow",
    "WardResponse",
    "PatientDetail",
    "ClinicalNote",
    "SessionRole",
    "Session",
    "AdmissionCondition",
    "AdmitPatientInput",
    "PartialLabInput",
    "LabExtractionResult",
    "PatientExtractionResult",
]
# Generic in TypeScript (hand-written wrappers, checked at compile time against the
# concrete generated types); Pydantic has one concrete model per value type instead.
GENERIC_WRAPPERS = {"Measurement", "MeasurementValue"}
NEW_IN_CP1 = {"Acvpu", "BloodPressure", "Spo2Scale", "TierCInput"}


def _schemas() -> dict[str, Any]:
    schemas: dict[str, Any] = build_openapi()["components"]["schemas"]
    return schemas


def test_output_is_deterministic() -> None:
    assert dumps(build_openapi()) == dumps(build_openapi())


def test_committed_openapi_matches_the_schemas() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == dumps(build_openapi()), (
        "contracts/openapi.json is stale: run `make contract` and commit the result"
    )


def test_is_openapi_31_with_components_only() -> None:
    doc = build_openapi()
    assert doc["openapi"] == "3.1.0"
    assert doc["paths"] == {}
    assert set(doc) == {"openapi", "info", "paths", "components"}


def test_every_frontend_type_is_covered() -> None:
    schemas = _schemas()
    missing = [n for n in FRONTEND_TYPES_BEFORE_CP1 if n not in schemas]
    assert missing == []
    assert set(schemas) >= NEW_IN_CP1


def test_every_name_the_frontend_exports_exists_in_the_contract() -> None:
    source = FRONTEND_TYPES.read_text(encoding="utf-8")
    exported: set[str] = set()
    for block in re.findall(r"export type \{([^}]*)\} from", source):
        exported |= {n.strip() for n in block.split(",") if n.strip()}
    exported |= set(re.findall(r"^export (?:type|interface) (\w+)", source, flags=re.M))
    exported -= GENERIC_WRAPPERS | {"MeasurementContractChecks"}
    assert exported, "no exports parsed from frontend/src/types/index.ts"
    assert sorted(exported - set(_schemas())) == []


def test_no_discriminator_objects_leak_into_the_document() -> None:
    # openapi-typescript renders `present: true` as `present: "true"` when a boolean
    # discriminator mapping is present; the exporter strips them.
    assert '"discriminator"' not in dumps(build_openapi())


def test_presence_flags_are_boolean_constants() -> None:
    schemas = _schemas()
    for name in ("NumberPresent", "FlagPresent", "AcvpuPresent", "MeasurementAbsent"):
        prop = schemas[name]["properties"]["present"]
        assert prop["type"] == "boolean"
        assert prop["const"] is (name != "MeasurementAbsent")


def test_committed_file_is_valid_json_with_sorted_keys() -> None:
    text = COMMITTED.read_text(encoding="utf-8")
    assert json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n" == text
