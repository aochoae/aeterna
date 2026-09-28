# Aeterna Config guidelines

## Purpose and structure

`aeterna-config` is the standard-library-only foundation for asynchronous layered
configuration. Its implementation is in `src/aeterna/config/`: keep public exports in
`__init__.py`, configuration behavior in `core.py`, and error types in `errors.py`.

## Contracts

- Do not import any other Aeterna package or add a runtime dependency.
- Providers have a stable `name` and async `load()` method; builders load them in registration
  order. Later mappings recursively overlay earlier mappings, while scalars, lists, tuples,
  and `None` replace values.
- Snapshots, section views, and `as_mapping()` must remain immutable. Preserve
  colon-delimited paths and provider provenance.
- Keep environment parsing explicit: `__` nesting by default, prefix and case controls, and
  errors for empty segments or normalized-key collisions. Values remain strings until binding.
- Binding is deliberately strict. Support only the documented annotated targets, reject unknown
  dataclass fields and unsupported annotations, and retain precise paths without exposing values.
- Validate untrusted configuration depth and node limits. Public provider and binding failures
  must be sanitized: never leak secrets or raw conversion exceptions.

## Change and validation

Export intentional public additions from `aeterna.config`. Update the configuration guide and
API docs when behavior changes. Add focused coverage in `tests/test_config.py`, especially for
precedence, immutability, provenance, environment parsing, limits, strict binding, and
secret-safe errors. Run `uv run pytest tests/test_config.py` from the repository root.
