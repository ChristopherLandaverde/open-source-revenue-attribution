"""The attribution package must stay pure Python: no Django (or other framework) imports."""

import ast
from pathlib import Path

ATTRIBUTION_DIR = Path(__file__).resolve().parent.parent / "attribution"
FORBIDDEN_ROOTS = {"django", "reports", "config"}


def imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_attribution_package_exists():
    assert list(ATTRIBUTION_DIR.glob("*.py")), "attribution/ has no modules"


def test_attribution_does_not_import_django_or_app_code():
    offenders = {
        str(path.relative_to(ATTRIBUTION_DIR.parent)): sorted(
            imported_roots(path) & FORBIDDEN_ROOTS
        )
        for path in ATTRIBUTION_DIR.rglob("*.py")
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert offenders == {}, f"attribution/ must not import Django or app code: {offenders}"
