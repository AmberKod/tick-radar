import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "cross_market"


def test_dependency_direction_and_no_api_scheduler():
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        for name in imports:
            if relative.parts[0] in {"modules", "shared"}:
                assert not name.startswith("cross_market.apps"), (path, name)
            if relative.parts[:2] == ("apps", "api"):
                assert "worker" not in name and "scheduler" not in name.lower(), (path, name)
            if relative.parts[0] == "shared":
                assert not name.startswith("cross_market.modules"), (path, name)
            assert not name.startswith(("modules.", "apps.", "shared.")), (path, name)
        assert "create_all" not in path.read_text(encoding="utf-8")


def test_business_router_and_cross_module_boundaries():
    for module in ("watchlist", "securities", "indicators", "portfolio", "alerts", "notifications"):
        module_root = ROOT / "modules" / module
        for path in module_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                    if node.module == "cross_market.modules":
                        names += [f"{node.module}.{alias.name}" for alias in node.names]
                for name in names:
                    if path.parent.name == "interfaces":
                        assert not name.startswith("sqlalchemy"), (path, name)
                        assert "infrastructure" not in name.split("."), (path, name)
                    if name.startswith("cross_market.modules."):
                        parts = name.split(".")
                        if len(parts) > 4 and parts[2] != module:
                            assert parts[3] == "application", (path, name)
            if path.parent.name == "interfaces":
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        assert (
                            node.func.attr
                            not in {
                                "execute",
                                "scalar",
                                "scalars",
                                "add",
                                "add_all",
                                "flush",
                                "commit",
                                "rollback",
                                "delete",
                                "connection",
                            }
                            or not isinstance(node.func.value, ast.Name)
                            or (node.func.value.id != "session")
                        ), (path, node.lineno)
    shared = (ROOT / "shared" / "database.py").read_text(encoding="utf-8")
    assert "watchlist" not in shared
    for filename in ("models.py", "schemas.py", "service.py"):
        assert not (ROOT / "modules" / "watchlist" / filename).exists()


def test_indicator_domain_has_no_io_or_other_module_dependencies():
    paths = [
        path
        for module in ("indicators", "portfolio", "alerts")
        for path in (ROOT / "modules" / module / "domain").rglob("*.py")
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in {
                    "fastapi",
                    "sqlalchemy",
                    "redis",
                    "httpx",
                    "pandas",
                    "requests",
                }, (path, name)
                assert not name.startswith("cross_market.modules."), (path, name)
