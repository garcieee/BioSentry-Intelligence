"""I5 isolation check: nothing under training/ may reach BioSentry patient data.

Training reads public corpora only (README I5). This is a static tripwire over the training/
tree. It is necessary, not sufficient: it cannot see a path assembled at run time from
variables, or a data store reached over a network connection. It does catch the accidental
couplings that matter: an import of the application package (its repositories, simulator,
services and API hold or load patient rows), a reference to the committed synthetic dataset or
the variable that points at it, a link into the tree, and the dynamic-import calls that would
hide any of these from the scan.

Documentation is not code: docstrings, comments and Markdown may describe the rule freely.
"""

import ast
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = "biosentry"
# Modules training may import: an entry itself or a dotted child of it. Empty on purpose; widen
# it only in a reviewed change that says why (for example NEWS2 as the pre-registered comparator).
ALLOWED_IMPORTS: tuple[str, ...] = ()

CODE_SUFFIXES = frozenset({".py"})
TEXT_SUFFIXES = frozenset(
    {".toml", ".cfg", ".ini", ".yaml", ".yml", ".json", ".txt", ".sh", ".bash", ".zsh", ".env"}
)
TEXT_NAMES = frozenset({"Makefile", "Dockerfile", ".env"})
UNSCANNABLE_SUFFIXES = frozenset({".ipynb"})
# Environments and tool caches. None can hold committed code (all are git-ignored or git's own).
SKIP_DIRS = frozenset(
    {".git", ".venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)

# Calls that load code by a name this scan cannot see. Bare names only for exec/eval: the
# method call `model.eval()` is ordinary PyTorch.
DYNAMIC_CALL_NAMES = frozenset({"__import__", "exec", "eval"})
DYNAMIC_CALL_ATTRS = frozenset(
    {
        "__import__",
        "import_module",
        "spec_from_file_location",
        "spec_from_loader",
        "module_from_spec",
        "exec_module",
        "load_module",
        "run_module",
        "run_path",
    }
)

HOLE = "\x00"  # stands for a part of a path expression that is not a literal
DATASET_PATH = re.compile(
    r"(?<![A-Za-z0-9_])data[\\/\x00]+synthetic(?![A-Za-z0-9_])|synthetic\.json", re.IGNORECASE
)
DATASET_VARIABLE = re.compile("BIOSENTRY_DATASET", re.IGNORECASE)
PACKAGE_STRING = re.compile(r"\bbiosentry\b(?!-)")  # `biosentry-training` is our own name


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.detail}"


@dataclass
class Scan:
    violations: list[Violation] = field(default_factory=list)
    scanned: list[str] = field(default_factory=list)  # files actually read, relative to the root


def _is_allowed(module: str, allowed: Sequence[str]) -> bool:
    return any(module == entry or module.startswith(entry + ".") for entry in allowed)


def _is_package(module: str) -> bool:
    return module == PACKAGE or module.startswith(PACKAGE + ".")


def _imported_modules(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Every module an import statement can bind, with `from m import n` read as `m.n`."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    base = node.module or ""
    return [f"{base}.{alias.name}" if base else alias.name for alias in node.names]


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_path_call(name: str) -> bool:
    return name.endswith("Path") or name in {"join", "joinpath"}


def _text(node: ast.AST) -> str:
    """Best-effort text of a path-like expression; anything that is not a literal is a hole."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else HOLE
    if isinstance(node, ast.JoinedStr):
        return "".join(_text(part) for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _text(node.left) + "/" + _text(node.right)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _text(node.left) + _text(node.right)
    if isinstance(node, ast.List | ast.Tuple):
        return "/".join(_text(item) for item in node.elts)
    if isinstance(node, ast.Call) and _is_path_call(_call_name(node)):
        return "/".join(_text(arg) for arg in node.args)
    return HOLE


def _text_violations(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if DATASET_PATH.search(text):
        found.append(("dataset-path", "reaches the committed synthetic dataset"))
    if DATASET_VARIABLE.search(text):
        found.append(("dataset-variable", "reads the variable that points at the dataset"))
    if PACKAGE_STRING.search(text):
        found.append(("package-string", "names a module of the application package"))
    return found


def scan_source(
    source: str, name: str = "<source>", allowed: Sequence[str] = ()
) -> list[Violation]:
    """Violations in one Python source. A file that does not parse fails: it cannot be checked."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as error:  # ValueError: a lone surrogate, or NUL on older 3.x
        line = getattr(error, "lineno", None) or 1
        return [Violation(name, line, "unparseable", "cannot be parsed, so not checked")]
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    found: dict[tuple[int, str], Violation] = {}

    def add(node: ast.expr | ast.stmt, kind: str, detail: str) -> None:
        found.setdefault((node.lineno, kind), Violation(name, node.lineno, kind, detail))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for module in _imported_modules(node):
                if _is_package(module) and not _is_allowed(module, allowed):
                    add(node, "import", f"imports {module}")
        elif isinstance(node, ast.Call):
            called = node.func
            if (isinstance(called, ast.Name) and called.id in DYNAMIC_CALL_NAMES) or (
                isinstance(called, ast.Attribute) and called.attr in DYNAMIC_CALL_ATTRS
            ):
                add(node, "dynamic-import", f"{_call_name(node)}() loads code by a hidden name")
        if id(node) in docstrings:
            continue
        if isinstance(
            node, ast.Constant | ast.JoinedStr | ast.BinOp | ast.Call | ast.List | ast.Tuple
        ):
            for kind, detail in _text_violations(_text(node)):
                add(node, kind, detail)
    return sorted(found.values(), key=lambda v: (v.line, v.kind))


def scan_text(text: str, name: str) -> list[Violation]:
    """Violations in a configuration or script file, line by line."""
    return [
        Violation(name, number, kind, detail)
        for number, line in enumerate(text.splitlines(), start=1)
        for kind, detail in _text_violations(line)
    ]


def scan_tree(root: Path, allowed: Sequence[str] = ()) -> Scan:
    """Scan every code and configuration file under root; Markdown and data files are skipped."""
    scan = Scan()
    for directory, subdirs, files in os.walk(root):
        kept: list[str] = []
        for subdir in sorted(subdirs):
            full = Path(directory) / subdir
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                scan.violations.append(Violation(rel, 1, "symlink", "a link can leave the tree"))
            elif subdir not in SKIP_DIRS:
                kept.append(subdir)
        subdirs[:] = kept
        for filename in sorted(files):
            path = Path(directory) / filename
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                scan.violations.append(Violation(rel, 1, "symlink", "a link can leave the tree"))
            elif path.suffix in UNSCANNABLE_SUFFIXES:
                scan.violations.append(
                    Violation(rel, 1, "unscannable", "notebooks are not checked")
                )
            elif (
                path.suffix in CODE_SUFFIXES
                or path.suffix in TEXT_SUFFIXES
                or filename in TEXT_NAMES
            ):
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    scan.violations.append(Violation(rel, 1, "unscannable", "not valid UTF-8 text"))
                    continue
                scan.scanned.append(rel)
                if path.suffix in CODE_SUFFIXES:
                    scan.violations.extend(scan_source(text, rel, allowed))
                else:
                    scan.violations.extend(scan_text(text, rel))
    return scan
