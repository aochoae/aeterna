#!/usr/bin/env python3
"""Build the source and wheel artifacts for Aeterna's packages."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = PROJECT_ROOT / "packages"


def discover_packages() -> dict[str, Path]:
    """Return installable workspace packages keyed by distribution name."""
    packages: dict[str, Path] = {}
    for manifest in sorted(PACKAGES_ROOT.glob("*/pyproject.toml")):
        metadata = tomllib.loads(manifest.read_text(encoding="utf-8"))
        name = metadata.get("project", {}).get("name")
        if not isinstance(name, str):
            raise RuntimeError(f"Missing project.name in {manifest}")
        if name in packages:
            raise RuntimeError(f"Duplicate package name discovered: {name}")
        packages[name] = manifest.parent
    if not packages:
        raise RuntimeError(f"No package manifests found in {PACKAGES_ROOT}")
    return packages


def parse_args(package_names: list[str]) -> argparse.Namespace:
    """Parse optional distribution names to build."""
    parser = argparse.ArgumentParser(
        description="Build sdist and wheel artifacts for Aeterna packages.",
    )
    parser.add_argument(
        "package",
        nargs="*",
        choices=package_names,
        metavar="PACKAGE",
        help="distribution name(s) to build; defaults to every workspace package",
    )
    return parser.parse_args()


def build_package(package_dir: Path) -> None:
    """Build both supported distribution formats for one package."""
    relative_dir = package_dir.relative_to(PROJECT_ROOT)
    command = [
        "uv",
        "run",
        "python",
        "-m",
        "build",
        "--sdist",
        "--wheel",
        str(relative_dir),
    ]
    print(f"Building {relative_dir}...", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    """Build selected packages and return a process exit code."""
    if shutil.which("uv") is None:
        print("error: uv is required but was not found on PATH", file=sys.stderr)
        return 1

    try:
        packages = discover_packages()
        args = parse_args(sorted(packages))
    except (OSError, RuntimeError, tomllib.TOMLDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    selected = args.package or sorted(packages)
    try:
        for name in selected:
            build_package(packages[name])
    except subprocess.CalledProcessError as error:
        return error.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
