"""Build the OpenAPI 3.1 document for the contract schemas.

    python -m biosentry.schemas.openapi --out contracts/openapi.json

Output is deterministic (sorted keys, stable ordering); CI regenerates it and fails on diff.
Paths stay empty until the API lands (CP6): this document is the schema contract.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode, models_json_schema

from . import CONTRACT_MODELS

CONTRACT_VERSION = "0.1.0"
_REF_TEMPLATE = "#/components/schemas/{model}"


class _ContractSchema(GenerateJsonSchema):
    def field_title_should_be_set(self, schema: Any) -> bool:
        return False  # "Heart Rate" titles on every property are noise

    def tagged_union_schema(self, schema: Any) -> Any:
        # Keep the strict tagged-union validation but publish a plain oneOf: OpenAPI
        # discriminator mapping keys are strings, which turns `present: true` into
        # `present: "true"` in the generated TypeScript.
        json_schema = super().tagged_union_schema(schema)
        json_schema.pop("discriminator", None)
        return json_schema


def build_openapi() -> dict[str, Any]:
    mode: JsonSchemaMode = "validation"
    _, definitions = models_json_schema(
        [(model, mode) for model in CONTRACT_MODELS],
        ref_template=_REF_TEMPLATE,
        schema_generator=_ContractSchema,
    )
    schemas = dict(sorted(definitions["$defs"].items()))
    return {
        "openapi": "3.1.0",
        "info": {"title": "BioSentry Intelligence contract", "version": CONTRACT_VERSION},
        "paths": {},
        "components": {"schemas": schemas},
    }


def dumps(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dumps(build_openapi()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
