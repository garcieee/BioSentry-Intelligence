.PHONY: web-install web-dev web-build web-typecheck check

FRONTEND := frontend

web-install:
	cd $(FRONTEND) && npm ci

web-dev:
	cd $(FRONTEND) && npm run dev

web-build:
	cd $(FRONTEND) && npm run build

web-typecheck:
	cd $(FRONTEND) && npx tsc -b --noEmit

check: web-typecheck

# --- Contract: Pydantic schemas -> contracts/openapi.json -> frontend/src/types/generated.ts ---
# Locally: make contract PYTHON=backend/.venv/bin/python

PYTHON ?= python3
CONTRACTS := contracts
GENERATED := $(CONTRACTS)/openapi.json frontend/src/types/generated.ts

.PHONY: contract-install contract-export contract-ts contract contract-test contract-check

contract-install:
	$(PYTHON) -m pip install -e "backend[dev]"
	cd $(CONTRACTS) && npm ci

contract-export:
	$(PYTHON) -m biosentry.schemas.openapi --out $(CONTRACTS)/openapi.json

contract-ts:
	cd $(CONTRACTS) && npm run generate

contract: contract-export contract-ts

contract-test:
	$(PYTHON) -m pytest backend/tests/contract

# CI gate: run the schema tests, regenerate, fail if the committed artifacts differ.
contract-check: contract-test contract
	@git rev-parse --git-dir >/dev/null || { echo "contract-check needs a git checkout"; exit 1; }
	@changed="$$(git status --porcelain -- $(GENERATED))" || exit 1; \
	test -z "$$changed" || { \
	  echo "contract drift: regenerate with 'make contract' and commit"; \
	  git --no-pager diff --stat -- $(GENERATED); exit 1; }
