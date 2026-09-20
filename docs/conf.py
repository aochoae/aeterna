# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Sphinx configuration for aeterna."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

DOCS_DIR = Path(__file__).parent
ROOT_DIR = DOCS_DIR.parent
for source_dir in (
    ROOT_DIR / "packages" / "aeterna-config" / "src",
    ROOT_DIR / "packages" / "aeterna-config-yaml" / "src",
    ROOT_DIR / "packages" / "aeterna-di" / "src",
    ROOT_DIR / "packages" / "aeterna-runtime" / "src",
):
    sys.path.insert(0, str(source_dir))


def _package_version() -> str:
    """Read the released version from package metadata.

    Hardcoding the version here let the documentation drift behind the packages it
    documents, so it is read from the runtime package's manifest instead.

    :return: The version string shared by every aeterna package.
    :rtype: str
    """
    manifest = ROOT_DIR / "packages" / "aeterna-runtime" / "pyproject.toml"
    with manifest.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


project = "Aeterna"
copyright = "2026, Alberto Ochoa"
author = "Alberto Ochoa"
release = _package_version()
version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinxcontrib.mermaid",
]
autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
autodoc_typehints = "description"
autodoc_member_order = "bysource"
templates_path: list[str] = []
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_theme = "alabaster"
html_title = "Aeterna documentation"
html_static_path: list[str] = []
nitpicky = False
