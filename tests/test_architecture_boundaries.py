import ast
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
APP_ROOT = PROJECT_ROOT / "app"

MANA_AI_FORBIDDEN_PREFIXES = (
    "app.core.config",
    "app.main",
    "app.mana_operation_ai",
    "app.services.marketing",
    "app.services.meta",
    "alembic",
    "fastapi",
    "openai",
    "redis",
    "sqlalchemy",
)
PRODUCT_AI_RUNTIME_FORBIDDEN_PREFIXES = (
    "app.mana_operation_ai",
    "app.services.marketing",
    "app.services.meta",
    "aiosqlite",
    "alembic",
    "asyncpg",
    "sqlalchemy",
)
OPERATION_DOMAIN_FORBIDDEN_PREFIXES = (
    "app.core",
    "app.mana_operation_ai.api",
    "app.mana_operation_ai.application",
    "app.mana_operation_ai.background",
    "app.mana_operation_ai.infrastructure",
    "app.services",
    "alembic",
    "fastapi",
    "openai",
    "sqlalchemy",
)
OPERATION_APPLICATION_FORBIDDEN_PREFIXES = (
    "app.core",
    "app.mana_operation_ai.api",
    "app.mana_operation_ai.background",
    "app.mana_operation_ai.infrastructure",
    "app.services",
    "alembic",
    "fastapi",
    "openai",
    "sqlalchemy",
)
MANA_AI_FORBIDDEN_FASTAPI_SYMBOLS = {"BackgroundTasks", "Depends", "Request"}


def _module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return result


def _import_graph() -> dict[str, set[str]]:
    graph: defaultdict[str, set[str]] = defaultdict(set)
    known_modules = {_module_name(path) for path in APP_ROOT.rglob("*.py")}
    for path in APP_ROOT.rglob("*.py"):
        module = _module_name(path)
        for imported in _imports(path):
            candidates = [
                candidate
                for candidate in known_modules
                if imported == candidate or imported.startswith(f"{candidate}.")
            ]
            local = max(candidates, key=len) if candidates else None
            graph[module].add(local or imported)
    return dict(graph)


def _reachable_imports(start_prefix: str) -> dict[str, set[str]]:
    graph = _import_graph()
    reachable: dict[str, set[str]] = {}
    for start in (module for module in graph if module.startswith(start_prefix)):
        seen: set[str] = set()
        pending = list(graph.get(start, set()))
        while pending:
            imported = pending.pop()
            if imported in seen:
                continue
            seen.add(imported)
            pending.extend(graph.get(imported, set()))
        reachable[start] = seen
    return reachable


def _boundary_violations(start_prefix: str, forbidden: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for source, reachable in _reachable_imports(start_prefix).items():
        for imported in sorted(reachable):
            if imported.startswith(forbidden):
                violations.append(f"{source} reaches {imported}")
    return violations


def test_mana_ai_has_no_direct_or_transitive_operational_dependencies() -> None:
    assert _boundary_violations("app.mana_ai", MANA_AI_FORBIDDEN_PREFIXES) == []


def test_product_ai_runtime_has_no_database_or_operation_dependencies() -> None:
    assert (
        _boundary_violations(
            "app.product_ai_main",
            PRODUCT_AI_RUNTIME_FORBIDDEN_PREFIXES,
        )
        == []
    )


def test_mana_ai_cannot_use_fastapi_di_background_tasks_or_app_state() -> None:
    violations: list[str] = []
    for path in (APP_ROOT / "mana_ai").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
                forbidden = MANA_AI_FORBIDDEN_FASTAPI_SYMBOLS.intersection(
                    alias.name for alias in node.names
                )
                violations.extend(
                    f"{path.relative_to(PROJECT_ROOT)} imports fastapi.{name}"
                    for name in sorted(forbidden)
                )
            if isinstance(node, ast.Attribute) and node.attr == "state":
                violations.append(f"{path.relative_to(PROJECT_ROOT)} accesses .state")
            if isinstance(node, ast.Name) and node.id == "get_settings":
                violations.append(f"{path.relative_to(PROJECT_ROOT)} accesses get_settings")
    assert violations == []


def test_operation_domain_has_no_framework_or_outer_layer_dependencies() -> None:
    assert (
        _boundary_violations(
            "app.mana_operation_ai.domain",
            OPERATION_DOMAIN_FORBIDDEN_PREFIXES,
        )
        == []
    )


def test_operation_application_does_not_depend_on_transport_or_infrastructure() -> None:
    assert (
        _boundary_violations(
            "app.mana_operation_ai.application",
            OPERATION_APPLICATION_FORBIDDEN_PREFIXES,
        )
        == []
    )
