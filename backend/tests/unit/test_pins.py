"""Dependency pins: every direct pin in pyproject.toml is repeated in constraints.txt."""

import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _constraints() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in (BACKEND / "constraints.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        match = PIN.match(line.strip())
        assert match, f"constraints.txt line is not an exact pin: {line!r}"
        pins[_normalise(match.group(1))] = match.group(2)
    return pins


def _direct_pins() -> dict[str, str]:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    specs = [
        *project["build-system"]["requires"],
        *project["project"]["dependencies"],
        *project["project"]["optional-dependencies"]["dev"],
    ]
    pins: dict[str, str] = {}
    for spec in specs:
        match = PIN.match(spec)
        assert match, f"direct dependency is not an exact pin: {spec!r}"
        pins[_normalise(match.group(1))] = match.group(2)
    return pins


def test_every_direct_dependency_is_an_exact_pin() -> None:
    assert _direct_pins()


def test_constraints_repeat_every_runtime_and_dev_pin() -> None:
    constraints = _constraints()
    # setuptools is a build-time requirement only and is installed by pip's isolated build.
    direct = {k: v for k, v in _direct_pins().items() if k != "setuptools"}
    mismatched = {k: (v, constraints.get(k)) for k, v in direct.items() if constraints.get(k) != v}
    assert mismatched == {}
