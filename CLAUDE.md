# BioSentry-Intelligence

## Commits and PRs
- Every commit message ends with `Co-Authored-By: Claude <model name> <noreply@anthropic.com>` (e.g. `Claude Sonnet 5.5`).
- Every PR description ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

## Workflow
- All changes go through a branch and a PR to `main`. Never push to `main`.
- Required checks: `typecheck` and `build`. `audit (informational)` is non-gating; do not make it required.
- Never merge without the user's OK.

## Commands (repo root)
- `make web-install` (npm ci) · `make check` (typecheck) · `make web-build` · `make web-dev`
- Node `^20.19 || >=22.12`. Dependencies are exact-pinned (no `^` or `~`).

## State
- Only `frontend/` is real (React 19, Vite 8, TypeScript 6). `backend/` and `models/` are empty placeholders.
- No test or lint scripts exist yet.
