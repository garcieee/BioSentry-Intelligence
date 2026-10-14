"""The CI gate bars (PLAN, Gate bars: CP2) as executable checks on the workflow file."""

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
INFORMATIONAL = {"audit"}  # reported, never required


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job_blocks() -> dict[str, str]:
    """Job id -> its YAML block (the workflow keeps jobs at two-space indentation)."""
    jobs_section = _text().split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\s*$", jobs_section, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_ci_gate_needs_every_required_job() -> None:
    blocks = _job_blocks()
    assert "ci-gate" in blocks
    match = re.search(r"^    needs:\s*\[([^\]]*)\]", blocks["ci-gate"], flags=re.M)
    assert match, "ci-gate must declare `needs: [..]`"
    needs = {n.strip() for n in match.group(1).split(",") if n.strip()}
    required = set(blocks) - {"ci-gate"} - INFORMATIONAL
    assert needs == required, (
        f"ci-gate.needs must list every required job; missing {sorted(required - needs)}, "
        f"unexpected {sorted(needs - required)}"
    )


def test_ci_gate_runs_always_and_fails_on_any_non_success() -> None:
    block = _job_blocks()["ci-gate"]
    assert re.search(r"^    if:\s*always\(\)\s*$", block, flags=re.M)
    assert "toJSON(needs)" in block
    assert '.result == "success"' in block  # skipped, cancelled and failure all fail


def test_no_path_filters() -> None:
    assert not re.search(r"^\s*paths(-ignore)?:", _text(), flags=re.M)


def test_continue_on_error_only_on_informational_jobs() -> None:
    for job, block in _job_blocks().items():
        if re.search(r"continue-on-error:\s*true", block):
            assert job in INFORMATIONAL, f"{job} must not set continue-on-error"
