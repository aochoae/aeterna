# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

from __future__ import annotations

import ast
import tomllib
from pathlib import Path


def _aeterna_imports(root: Path) -> set[str]:
    imported: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(
                    alias.name for alias in node.names if alias.name.startswith("aeterna")
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("aeterna"):
                    imported.add(node.module)
    return imported


def test_core_package_dependency_boundaries() -> None:
    root = Path(__file__).parents[1] / "packages"
    assert _aeterna_imports(root / "aeterna-di") == set()
    assert _aeterna_imports(root / "aeterna-config") == set()
    assert _aeterna_imports(root / "aeterna-config-yaml") <= {"aeterna.config"}
    assert _aeterna_imports(root / "aeterna-runtime") <= {"aeterna.config", "aeterna.di"}


def test_package_versions_are_synchronized() -> None:
    root = Path(__file__).parents[1]
    manifests = [root / "pyproject.toml", *sorted((root / "packages").glob("*/pyproject.toml"))]
    versions = {
        tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"] for path in manifests
    }
    assert len(versions) == 1
