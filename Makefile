.PHONY: web-install web-dev web-build web-typecheck web-lint web-test check

FRONTEND := frontend

web-install:
	cd $(FRONTEND) && npm ci

web-dev:
	cd $(FRONTEND) && npm run dev

web-build:
	cd $(FRONTEND) && npm run build

web-typecheck:
	cd $(FRONTEND) && npx tsc -b --noEmit

web-lint:
	cd $(FRONTEND) && npm run lint

web-test:
	cd $(FRONTEND) && npm test

check: web-typecheck

# --- Contract: Pydantic schemas -> contracts/openapi.json -> frontend/src/types/generated.ts ---
# Locally: make contract PYTHON=backend/.venv/bin/python

PYTHON ?= python3
CONTRACTS := contracts
GENERATED := $(CONTRACTS)/openapi.json frontend/src/types/generated.ts

.PHONY: contract-install contract-export contract-ts contract contract-test contract-check

contract-install: be-install
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

# --- Backend (Python 3.11). Locally: make be-check PYTHON=backend/.venv/bin/python ---

BACKEND := backend

.PHONY: be-install be-lint be-fmt be-test be-check be-serve data http-contract

# Direct deps are exact in pyproject.toml; constraints.txt pins the transitive closure.
be-install:
	$(PYTHON) -m pip install -c $(BACKEND)/constraints.txt -e "$(BACKEND)[dev]"

be-lint:
	$(PYTHON) -m ruff check $(BACKEND)
	$(PYTHON) -m ruff format --check $(BACKEND)
	$(PYTHON) -m mypy --config-file $(BACKEND)/pyproject.toml $(BACKEND)/src $(BACKEND)/tests

be-fmt:
	$(PYTHON) -m ruff check --fix $(BACKEND)
	$(PYTHON) -m ruff format $(BACKEND)

# pytest exits 5 when nothing is collected, which fails this target (an empty suite is a failure).
be-test:
	$(PYTHON) -m pytest $(BACKEND)

be-check: be-lint be-test

# Regenerate data/synthetic/synthetic.json (py-test fails if the committed file is stale).
data:
	$(PYTHON) -m biosentry.sim --out data/synthetic/synthetic.json

# Serve the API on :8000 from the committed synthetic dataset (writes are in memory).
be-serve:
	$(PYTHON) -m uvicorn biosentry.api.main:app --port 8000

# One contract suite over the fixture provider AND the HTTP provider: starts the API on :8765,
# waits for /healthz, runs the suite with VITE_API_URL set, and always stops the server.
http-contract:
	@$(PYTHON) -m uvicorn biosentry.api.main:app --port 8765 --log-level warning & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null' EXIT; \
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
	  curl -fs http://127.0.0.1:8765/healthz >/dev/null 2>&1 && break; sleep 0.5; \
	done; \
	curl -fs http://127.0.0.1:8765/healthz >/dev/null || { echo "API did not start"; exit 1; }; \
	cd $(FRONTEND) && VITE_API_URL=http://127.0.0.1:8765 npx vitest run src/api/providers.contract.test.ts
