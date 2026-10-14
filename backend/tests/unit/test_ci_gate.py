"""The CI gate bars (PLAN, Gate bars: CP2) as executable checks on the workflow file.

Two kinds of check live here: the gate's own shape (ci-gate needs every required job, always
runs, fails on anything but success) and the privilege bars (P3: a workflow edit may only add
checks): the token stays read-only, no privileged trigger, and a failing job cannot be waved
through by `continue-on-error` unless it is the informational audit job.
"""

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
INFORMATIONAL = {"audit"}  # reported, never required
# What the token may be given, at the workflow and at any job: read access to the contents.
READ_ONLY = {"contents": "read"}
FORBIDDEN_TRIGGERS = {"pull_request_target"}  # runs fork code with the base repo's token


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


# --- Privilege bars: the workflow can only ever gain checks, never reach -------------------


def _workflow() -> dict[Any, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _triggers(workflow: dict[Any, Any]) -> set[str]:
    on = workflow.get("on", workflow.get(True))  # YAML 1.1 reads a bare `on` as True
    if isinstance(on, str):
        return {on}
    if isinstance(on, (list, dict)):
        return {str(trigger) for trigger in on}
    raise AssertionError(f"cannot read the workflow's triggers from {on!r}")


def _is_narrowing(granted: Any) -> bool:
    """Whether a job's `permissions` stays within the workflow's read-only contents."""
    if granted in ({}, "none"):
        return True
    if not isinstance(granted, dict):  # read-all, write-all, or anything unreadable
        return False
    return all(
        (scope, level) == ("contents", "read") or level == "none"
        for scope, level in granted.items()
    )


def privilege_violations(workflow: dict[Any, Any]) -> list[str]:
    problems: list[str] = []
    for trigger in sorted(_triggers(workflow) & FORBIDDEN_TRIGGERS):
        problems.append(f"the workflow uses {trigger}")
    if workflow.get("permissions") != READ_ONLY:
        problems.append(
            f"workflow permissions must be exactly {READ_ONLY}, not {workflow.get('permissions')!r}"
        )
    for job_id, job in workflow["jobs"].items():
        if "permissions" in job and not _is_narrowing(job["permissions"]):
            problems.append(f"job {job_id} broadens permissions: {job['permissions']!r}")
        if job_id not in INFORMATIONAL:
            if job.get("continue-on-error") not in (None, False):
                problems.append(f"job {job_id} sets continue-on-error")
            for index, step in enumerate(job.get("steps", [])):
                if step.get("continue-on-error") not in (None, False):
                    problems.append(f"job {job_id} step {index} sets continue-on-error")
    return problems


def test_the_workflow_holds_every_privilege_bar() -> None:
    assert privilege_violations(_workflow()) == []


def test_the_token_is_read_only_at_the_workflow_level() -> None:
    assert _workflow()["permissions"] == READ_ONLY


def test_no_job_is_given_more_than_the_workflow_has() -> None:
    for job_id, job in _workflow()["jobs"].items():
        if "permissions" in job:
            assert _is_narrowing(job["permissions"]), job_id


def test_no_privileged_trigger() -> None:
    assert _triggers(_workflow()).isdisjoint(FORBIDDEN_TRIGGERS)


def test_continue_on_error_appears_nowhere_a_failure_could_hide() -> None:
    for job_id, job in _workflow()["jobs"].items():
        if job_id in INFORMATIONAL:
            continue
        assert job.get("continue-on-error") in (None, False), job_id
        for step in job.get("steps", []):
            assert step.get("continue-on-error") in (None, False), job_id


def test_the_audit_job_stays_informational_so_it_cannot_gate_by_accident() -> None:
    jobs = _workflow()["jobs"]
    assert set(jobs) >= INFORMATIONAL
    needs = jobs["ci-gate"]["needs"]
    assert INFORMATIONAL.isdisjoint(needs)


# The checker itself, against workflows that break each bar: a check that cannot fail is not one.


def _mutated(change: Any) -> dict[Any, Any]:
    workflow = copy.deepcopy(_workflow())
    change(workflow)
    return workflow


def _set_top(value: Any) -> Any:
    return lambda w: w.__setitem__("permissions", value)


def _drop_top(w: dict[Any, Any]) -> None:
    del w["permissions"]


def _job(job_id: str, key: str, value: Any) -> Any:
    return lambda w: w["jobs"][job_id].__setitem__(key, value)


def _step(job_id: str, key: str, value: Any) -> Any:
    return lambda w: w["jobs"][job_id]["steps"][0].__setitem__(key, value)


def _on_key(w: dict[Any, Any]) -> Any:
    return "on" if "on" in w else True


def _trigger_dict(w: dict[Any, Any]) -> None:
    w[_on_key(w)] = {**w[_on_key(w)], "pull_request_target": {"branches": ["main"]}}


def _trigger_list(w: dict[Any, Any]) -> None:
    w[_on_key(w)] = ["pull_request", "pull_request_target"]


def _trigger_string(w: dict[Any, Any]) -> None:
    w[_on_key(w)] = "pull_request_target"


@pytest.mark.parametrize(
    ("name", "change", "mentions"),
    [
        ("workflow write token", _set_top({"contents": "write"}), "workflow permissions"),
        (
            "workflow more scopes",
            _set_top({"contents": "read", "packages": "write"}),
            "workflow permissions",
        ),
        ("workflow write-all", _set_top("write-all"), "workflow permissions"),
        ("workflow read-all", _set_top("read-all"), "workflow permissions"),
        ("workflow permissions removed", _drop_top, "workflow permissions"),
        (
            "job write",
            _job("py-test", "permissions", {"contents": "write"}),
            "job py-test broadens",
        ),
        (
            "job other scope",
            _job("lint", "permissions", {"pull-requests": "write"}),
            "job lint broadens",
        ),
        ("job id-token", _job("build", "permissions", {"id-token": "write"}), "job build broadens"),
        ("job write-all", _job("test", "permissions", "write-all"), "job test broadens"),
        ("job read-all", _job("test", "permissions", "read-all"), "job test broadens"),
        ("trigger as mapping", _trigger_dict, "pull_request_target"),
        ("trigger as list", _trigger_list, "pull_request_target"),
        ("trigger as string", _trigger_string, "pull_request_target"),
        ("job continue-on-error", _job("py-test", "continue-on-error", True), "job py-test sets"),
        ("gate continue-on-error", _job("ci-gate", "continue-on-error", True), "job ci-gate sets"),
        (
            "expression continue-on-error",
            _job("typecheck", "continue-on-error", "${{ always() }}"),
            "job typecheck sets",
        ),
        (
            "step continue-on-error",
            _step("py-lint", "continue-on-error", True),
            "job py-lint step 0",
        ),
    ],
)
def test_each_privilege_bar_fails_when_it_is_broken(name: str, change: Any, mentions: str) -> None:
    problems = privilege_violations(_mutated(change))
    assert problems, f"{name}: nothing was flagged"
    assert any(mentions in p for p in problems), (name, problems)


@pytest.mark.parametrize(
    "change",
    [
        _job("py-test", "permissions", {"contents": "read"}),
        _job("py-test", "permissions", {}),
        _job("py-test", "permissions", {"contents": "read", "packages": "none"}),
        _job("audit", "continue-on-error", True),
        _step("audit", "continue-on-error", True),
    ],
    ids=["same", "empty", "none-scope", "audit job", "audit step"],
)
def test_narrowing_and_the_informational_job_are_allowed(change: Any) -> None:
    assert privilege_violations(_mutated(change)) == []
