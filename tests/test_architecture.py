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


def test_meta_package_declares_all_core_packages() -> None:
    root = Path(__file__).parents[1]
    manifest = tomllib.loads(
        (root / "packages" / "aeterna" / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = set(manifest["project"]["dependencies"])

    assert dependencies == {
        "aeterna-config>=1.0.0.dev1,<2",
        "aeterna-config-yaml>=1.0.0.dev1,<2",
        "aeterna-di>=1.0.0.dev1,<2",
        "aeterna-runtime>=1.0.0.dev1,<2",
    }


def test_meta_package_is_metadata_only() -> None:
    root = Path(__file__).parents[1]
    source = root / "packages" / "aeterna" / "src" / "aeterna"

    assert (source / "py.typed").is_file()
    assert not any(source.rglob("*.py"))
