"""I5: nothing under training/ imports the application's patient or data modules or reads the
synthetic dataset. Each detection has a control that must be flagged, and each idiom training
really uses has a control that must stay clean, so the check cannot pass by being blind."""

import os
import sys
from pathlib import Path

import pytest
from training_isolation import (
    ALLOWED_IMPORTS,
    SKIP_DIRS,
    Scan,
    scan_source,
    scan_text,
    scan_tree,
)

ROOT = Path(__file__).resolve().parents[3]
TRAINING = ROOT / "training"


def _kinds(source: str, allowed: tuple[str, ...] = ()) -> set[str]:
    return {violation.kind for violation in scan_source(source, "t.py", allowed)}


def _tree(root: Path, files: dict[str, str]) -> Scan:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return scan_tree(root)


# --- the real tree -------------------------------------------------------------------------


def test_training_never_reaches_patient_data() -> None:
    assert TRAINING.is_dir(), "training/ is missing: the isolation check would pass vacuously"
    scan = scan_tree(TRAINING, ALLOWED_IMPORTS)
    assert "rhythm_head.py" in scan.scanned
    assert not scan.violations, "\n".join(str(v) for v in scan.violations)


def test_no_biosentry_module_is_allowed_to_training_yet() -> None:
    assert ALLOWED_IMPORTS == ()


# --- controls: each of these must be flagged -----------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import biosentry\n",
        "import numpy, biosentry\n",
        "import biosentry.sim.generator as generator\n",
        "from biosentry.repositories.memory import MemoryRepository\n",
        "from biosentry import sim\n",
        "from biosentry.sim import *\n",
        "def load():\n    from biosentry.services import patients\n    return patients\n",
        "try:\n    import biosentry\nexcept ImportError:\n    biosentry = None\n",
        "if TYPE_CHECKING:\n    from biosentry.schemas import X\n",
        "from .biosentry import patients\n",
    ],
    ids=[
        "plain",
        "second-name",
        "alias-submodule",
        "from-submodule",
        "from-package-import-module",
        "star",
        "inside-function",
        "inside-try",
        "type-checking-block",
        "relative-lookalike",
    ],
)
def test_import_of_the_application_package_is_flagged(source: str) -> None:
    assert _kinds(source) == {"import"}


@pytest.mark.parametrize(
    "call",
    [
        "__import__(name)",
        "exec(code)",
        "eval(code)",
        "importlib.import_module(name)",
        "builtins.__import__(name)",
        "importlib.util.spec_from_file_location(name, path)",
        "importlib.util.spec_from_loader(name, loader)",
        "importlib.util.module_from_spec(spec)",
        "loader.exec_module(module)",
        "loader.load_module(name)",
        "runpy.run_module(name)",
        "runpy.run_path(path)",
    ],
)
def test_dynamic_imports_are_flagged_because_the_scan_cannot_see_them(call: str) -> None:
    assert _kinds(f"{call}\n") == {"dynamic-import"}


@pytest.mark.parametrize(
    "source",
    [
        'DATASET = "data/synthetic/synthetic.json"\n',
        'DATASET = "../data/synthetic"\n',
        'DATASET = "data\\\\synthetic\\\\x.json"\n',
        'DATASET = "DATA/SYNTHETIC"\n',
        'DATASET = Path("data") / "synthetic"\n',
        'DATASET = ROOT / "data" / "synthetic" / "x.json"\n',
        'DATASET = Path("data", "synthetic")\n',
        'DATASET = os.path.join(root, "data", "synthetic")\n',
        'DATASET = base.joinpath("data", "synthetic")\n',
        'DATASET = "/".join(["data", "synthetic"])\n',
        'DATASET = f"{root}/data/synthetic"\n',
        'DATASET = f"data{os.sep}synthetic"\n',
        'DATASET = "data" + os.sep + "synthetic"\n',
        'DATASET = PurePosixPath("data") / "synthetic"\n',
        'DATASET = root / "synthetic.json"\n',
        'PARTS = ["data", "synthetic"]\n',
        'PARTS = ("data", "synthetic")\n',
    ],
    ids=[
        "literal",
        "relative-literal",
        "backslash",
        "case",
        "path-div",
        "path-div-chain",
        "path-args",
        "os-path-join",
        "joinpath",
        "str-join",
        "f-string",
        "f-string-separator",
        "concatenation",
        "pure-path",
        "dataset-file-name",
        "parts-list",
        "parts-tuple",
    ],
)
def test_reference_to_the_synthetic_dataset_is_flagged(source: str) -> None:
    assert _kinds(source) == {"dataset-path"}


@pytest.mark.parametrize(
    "source",
    [
        'path = os.environ["BIOSENTRY_DATASET"]\n',
        'path = os.getenv("biosentry_dataset")\n',
    ],
)
def test_the_variable_that_points_at_the_dataset_is_flagged(source: str) -> None:
    assert _kinds(source) == {"dataset-variable"}


@pytest.mark.parametrize(
    "source",
    [
        'run(["python", "-m", "biosentry.sim", "--out", "x"])\n',
        'run(["python", "-m", "biosentry"])\n',
        'run("python -m biosentry --out x", shell=True)\n',
        'PACKAGE = "backend/src/biosentry/sim"\n',
        'NAME = "biosentry"\n',
    ],
    ids=["dotted-module", "bare-package", "command-string", "source-path", "package-name"],
)
def test_naming_the_application_package_in_a_string_is_flagged(source: str) -> None:
    assert _kinds(source) == {"package-string"}


@pytest.mark.parametrize(
    "source",
    ["def (:\n", "x = 1\x00\n", "x = 1  # \ud800\n"],
    ids=["syntax", "nul-byte", "lone-surrogate"],
)
def test_a_file_that_does_not_parse_fails_closed(source: str) -> None:
    assert _kinds(source) == {"unparseable"}


def test_violations_carry_file_and_line() -> None:
    found = scan_source("import numpy\n\nimport biosentry.sim\n", "pkg/mod.py")
    assert [(v.path, v.line, v.kind) for v in found] == [("pkg/mod.py", 3, "import")]


# --- controls: each of these must stay clean -----------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import numpy as np\nfrom scipy import signal\n",
        "model.eval()\nwith torch.no_grad():\n    pass\n",
        'root = Path("data") / "cinc2017" / "training2017"\n',
        'ap.add_argument("--out", default="out/tiny")\n',
        "import biosentry_training_helpers\n",
        'NAME = "biosentry-training"\n',
        'HOST = "mybiosentry.example"\n',
        'LABEL = "biosentry_training"\n',
        'print("BioSentry rhythm head spike")\n',
        "import importlib.metadata\nimportlib.metadata.version('torch')\n",
        'path = "metadata/synthetic"\n',
        'path = "data/synthetic_noise"\n',
        '"""Never reads data/synthetic or imports biosentry.sim;'
        ' BIOSENTRY_DATASET is not used."""\n',
        "def f():\n    '''Not biosentry.sim, not data/synthetic.'''\n",
        "# biosentry.sim and data/synthetic, said in a comment\nx = 1\n",
    ],
    ids=[
        "numeric-stack",
        "model-eval-method",
        "own-data-dir",
        "own-out-dir",
        "lookalike-top-level-name",
        "distribution-name",
        "inside-a-longer-word",
        "underscore-continues-the-word",
        "camel-case-brand",
        "importlib-metadata",
        "word-boundary-before",
        "word-boundary-after",
        "module-docstring",
        "function-docstring",
        "comment",
    ],
)
def test_what_training_actually_does_is_not_flagged(source: str) -> None:
    assert scan_source(source, "t.py") == []


# --- the allow-list is exact and fails closed ----------------------------------------------

TIER_A = ("biosentry.domain.scoring.tier_a",)


@pytest.mark.parametrize(
    "source",
    [
        "import biosentry.domain.scoring.tier_a\n",
        "import biosentry.domain.scoring.tier_a.news2\n",
        "from biosentry.domain.scoring.tier_a import score_news2\n",
        "from biosentry.domain.scoring import tier_a\n",
    ],
)
def test_an_allowed_module_and_its_children_pass(source: str) -> None:
    assert _kinds(source, TIER_A) == set()


@pytest.mark.parametrize(
    "source",
    [
        "import biosentry\n",
        "import biosentry.domain.scoring\n",
        "import biosentry.domain.scoring.tier_b\n",
        "import biosentry.domain.scoring.tier_a_extra\n",
        "from biosentry.domain.scoring import tier_b\n",
        "from biosentry.domain.scoring import tier_a, tier_b\n",
        "from biosentry.domain.scoring import *\n",
        "import biosentry.sim\n",
    ],
    ids=[
        "package",
        "parent",
        "sibling",
        "name-prefix",
        "from-sibling",
        "from-allowed-and-sibling",
        "star-of-parent",
        "other",
    ],
)
def test_anything_else_is_still_flagged_with_an_allow_list(source: str) -> None:
    assert _kinds(source, TIER_A) == {"import"}


# --- the tree walk -------------------------------------------------------------------------


def test_the_walk_reads_nested_code_and_reports_relative_paths(tmp_path: Path) -> None:
    scan = _tree(
        tmp_path,
        {"clean.py": "import numpy\n", "a/b/bad.py": "x = 1\nimport biosentry.sim\n"},
    )
    assert sorted(scan.scanned) == ["a/b/bad.py", "clean.py"]
    assert [(v.path, v.line, v.kind) for v in scan.violations] == [("a/b/bad.py", 2, "import")]


@pytest.mark.parametrize(
    "name",
    [
        "run.sh",
        "run.bash",
        "run.zsh",
        "conf.toml",
        "conf.cfg",
        "conf.ini",
        "ci.yaml",
        "ci.yml",
        "out.json",
        ".env",
        "prod.env",
        "pins.txt",
        "Makefile",
        "Dockerfile",
    ],
)
def test_configuration_and_scripts_are_scanned_line_by_line(tmp_path: Path, name: str) -> None:
    scan = _tree(tmp_path, {name: "ok = 1\n--data ../data/synthetic\n"})
    assert [(v.path, v.line, v.kind) for v in scan.violations] == [(name, 2, "dataset-path")]


def test_configuration_names_the_training_package_without_tripping(tmp_path: Path) -> None:
    text = '[project]\nname = "biosentry-training"\n'
    assert _tree(tmp_path, {"pyproject.toml": text}).violations == []


def test_text_scan_flags_the_variable_and_the_package() -> None:
    found = scan_text("export BIOSENTRY_DATASET=x\npython -m biosentry.sim\nplain\n", "run.sh")
    assert [(v.line, v.kind) for v in found] == [(1, "dataset-variable"), (2, "package-string")]


def test_markdown_is_documentation_and_is_not_scanned(tmp_path: Path) -> None:
    scan = _tree(tmp_path, {"README.md": "Never read data/synthetic or import biosentry.sim.\n"})
    assert scan.violations == []
    assert scan.scanned == []


def test_data_files_are_not_read(tmp_path: Path) -> None:
    scan = _tree(tmp_path, {"record.dat": "data/synthetic\n", "record.hea": "biosentry.sim\n"})
    assert scan.violations == []
    assert scan.scanned == []


def test_notebooks_fail_because_they_are_not_scanned(tmp_path: Path) -> None:
    scan = _tree(tmp_path, {"explore.ipynb": "{}"})
    assert [(v.path, v.kind) for v in scan.violations] == [("explore.ipynb", "unscannable")]


def test_text_that_is_not_utf8_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_bytes(b"\xff\xfe\x00bad")
    assert [v.kind for v in scan_tree(tmp_path).violations] == ["unscannable"]


def test_only_environment_and_cache_directories_are_skipped(tmp_path: Path) -> None:
    bad = "import biosentry\n"
    scan = _tree(
        tmp_path,
        {
            ".venv/lib/x.py": bad,
            "venv/x.py": bad,
            "data/x.py": bad,
            "out/x.py": bad,
            "training/x.py": bad,
        },
    )
    assert sorted(v.path for v in scan.violations) == [
        "data/x.py",
        "out/x.py",
        "training/x.py",
        "venv/x.py",
    ]


def test_the_skipped_directories_are_exactly_the_reviewed_set() -> None:
    reviewed = {".git", ".venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
    assert reviewed == SKIP_DIRS


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_link_out_of_the_tree_is_flagged(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "synthetic.json").write_text("{}", encoding="utf-8")
    inside = tmp_path / "training"
    inside.mkdir()
    os.symlink(outside / "synthetic.json", inside / "ward.json")
    os.symlink(outside, inside / "ward")
    found = scan_tree(inside).violations
    assert sorted((v.path, v.kind) for v in found) == [
        ("ward", "symlink"),
        ("ward.json", "symlink"),
    ]
