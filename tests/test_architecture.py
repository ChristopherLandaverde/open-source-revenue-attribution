"""Pure packages (attribution/, contracts/, the MCP server) must not import Django or app code."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PURE_PACKAGES = ["attribution", "contracts", "mcp-server/osra_mcp"]
FORBIDDEN_ROOTS = {"django", "reports", "config", "api", "collection"}


def imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("package", PURE_PACKAGES)
def test_pure_package_exists(package):
    assert list((ROOT / package).glob("*.py")), f"{package}/ has no modules"


@pytest.mark.parametrize("package", PURE_PACKAGES)
def test_pure_package_does_not_import_django_or_app_code(package):
    offenders = {
        str(path.relative_to(ROOT)): sorted(imported_roots(path) & FORBIDDEN_ROOTS)
        for path in (ROOT / package).rglob("*.py")
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert offenders == {}, f"{package}/ must not import Django or app code: {offenders}"
