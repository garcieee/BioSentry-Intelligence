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

.PHONY: be-install be-lint be-fmt be-test be-check be-serve data http-contract dev

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
# One process, loopback only: identity is a stub (see README, "Run it").
API_PORT ?= 8000
be-serve:
	$(PYTHON) -m biosentry.api --port $(API_PORT)

# Shell fragment: wait up to 10 s for /healthz on port $(1), and fail if our server process
# ($$pid) is not the one answering (another process may already hold the port).
define wait_for_api
for i in $$(seq 1 40); do \
  curl -fs http://127.0.0.1:$(1)/healthz >/dev/null 2>&1 && break; sleep 0.25; \
done; \
{ kill -0 $$pid 2>/dev/null && curl -fs http://127.0.0.1:$(1)/healthz >/dev/null; } \
  || { echo "API did not start on :$(1) (is the port already in use?)"; exit 1; }
endef

# The integrated run: the API (loopback, synthetic data) and the Vite dev server wired to it
# with VITE_API_URL. The API allows exactly the dashboard's origin, so the dashboard's port is
# fixed ($(WEB_PORT), failing if taken: make dev WEB_PORT=5180). Ctrl-C stops both.
# Install first: make be-install, make web-install.
WEB_PORT ?= 5173
dev:
	@test -d $(FRONTEND)/node_modules || { echo "frontend dependencies are missing: run 'make web-install'"; exit 1; }
	@$(PYTHON) -c "import biosentry" 2>/dev/null || { echo "the backend is not installed for '$(PYTHON)': run 'make be-install' (README, \"Run it\")"; exit 1; }
	@BIOSENTRY_CORS_ORIGINS=http://localhost:$(WEB_PORT) \
	  $(PYTHON) -m biosentry.api --port $(API_PORT) --log-level warning & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null' EXIT INT TERM; \
	$(call wait_for_api,$(API_PORT)); \
	echo "API  http://127.0.0.1:$(API_PORT)  (identity is a stub: loopback only, synthetic data)"; \
	echo "Open http://localhost:$(WEB_PORT)"; \
	cd $(FRONTEND) && VITE_API_URL=http://127.0.0.1:$(API_PORT) npm run dev -- --port $(WEB_PORT) --strictPort

# One contract suite over the fixture provider AND the HTTP provider: starts the API on :8765,
# waits for /healthz, runs the suite with VITE_API_URL set, and always stops the server.
http-contract:
	@$(PYTHON) -m biosentry.api --port 8765 --log-level warning & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null' EXIT; \
	$(call wait_for_api,8765); \
	cd $(FRONTEND) && VITE_API_URL=http://127.0.0.1:8765 npx vitest run src/api/providers.contract.test.ts
