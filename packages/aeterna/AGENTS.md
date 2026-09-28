# Aeterna meta-package guidelines

## Purpose and structure

`aeterna` is a metadata-only convenience distribution. It installs all four component
packages but contributes no Python modules to the shared `aeterna` namespace; only
`src/aeterna/py.typed` belongs here.

## Change rules

- Do not add runtime implementation, imports, or public APIs to this package. Put
  behavior in the appropriate component package instead.
- Keep the four component dependencies exact in scope and compatible with the shared
  major-version range. The meta-package must depend on config, config-yaml, DI, and runtime.
- Keep this package's version synchronized with the root project and every workspace member.
- When dependency metadata changes, update `uv.lock` and preserve Hatchling packaging and
  the `py.typed` marker.
- Keep `README.md` limited to installation and navigation to component public APIs.

## Validation

From the repository root, run `uv run pytest tests/test_architecture.py` for metadata and
package-boundary coverage. Build the package when changing its manifest:
`uv run python -m build --sdist --wheel packages/aeterna`.
