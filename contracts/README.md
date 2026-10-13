# contracts

Dev-only toolchain. The Pydantic schemas in `backend/src/biosentry/schemas` are the source of truth.

    backend schemas --(make contract-export)--> contracts/openapi.json
                    --(make contract-ts)------> frontend/src/types/generated.ts

- Regenerate both: `make contract` (set `PYTHON=backend/.venv/bin/python` for a local venv).
- Never edit `openapi.json` or `generated.ts` by hand. CI job `contract-drift` regenerates and fails on any diff.
- This is a separate npm package because `openapi-typescript` peers on `typescript ^5`, while `frontend/` is on TypeScript 6.
