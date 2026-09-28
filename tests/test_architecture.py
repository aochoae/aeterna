# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import yaml


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
        "aeterna-config>=1.0.0.dev2,<2",
        "aeterna-config-yaml>=1.0.0.dev2,<2",
        "aeterna-di>=1.0.0.dev2,<2",
        "aeterna-runtime>=1.0.0.dev2,<2",
    }


def test_meta_package_is_metadata_only() -> None:
    root = Path(__file__).parents[1]
    source = root / "packages" / "aeterna" / "src" / "aeterna"

    assert (source / "py.typed").is_file()
    assert not any(source.rglob("*.py"))


def test_release_workflow_builds_and_validates_the_current_artifact_set() -> None:
    root = Path(__file__).parents[1]
    workflow = yaml.safe_load((root / ".github" / "workflows" / "publish.yml").read_text())
    jobs = workflow["jobs"]

    assert jobs["build"]["needs"] == "verify_source"
    assert jobs["verify_artifacts"]["needs"] == "build"
    assert jobs["publish_components"]["needs"] == "verify_artifacts"
    assert jobs["publish_meta"]["needs"] == "publish_components"

    build_install = next(
        step["run"] for step in jobs["build"]["steps"] if step["name"] == "Install build"
    )
    assert build_install.startswith("python -m pip install --only-binary=:all:")
    assert "\n" not in build_install
    assert all(
        requirement in build_install for requirement in ("build", "packaging", "pyproject-hooks")
    )

    verification = next(
        step["run"]
        for step in jobs["verify_artifacts"]["steps"]
        if step["name"] == "Install every wheel and source distribution"
    )
    assert '"--constraint"' in verification
    assert "as_uri()" in verification


def test_artifact_smoke_test_pins_sibling_dependencies_to_built_wheels() -> None:
    root = Path(__file__).parents[1]
    workflow = yaml.safe_load(
        (root / ".github" / "workflows" / "quality-assurance.yml").read_text()
    )
    smoke_test = workflow["jobs"]["smoke_test"]
    installation = next(
        step["run"]
        for step in smoke_test["steps"]
        if step["name"] == "Install built wheel and source distribution in fresh environments"
    )

    assert '"--constraint"' in installation
    assert "as_uri()" in installation
    assert "if name != package" in installation
