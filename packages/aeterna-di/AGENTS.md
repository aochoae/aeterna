# Aeterna DI guidelines

## Purpose and structure

`aeterna-di` is a standard-library-only, explicit async DI container. Its public API is exported
from `src/aeterna/di/__init__.py`; container mechanics live in `container.py` and public errors
in `errors.py`.

## Contracts

- Do not import another Aeterna package or add runtime dependencies. Services are keyed by types
  and composition remains explicit: mutate `ServiceCollection`, then build an immutable provider.
- Preserve async resolution and explicit scopes. `SINGLETON` is provider-wide, `SCOPED` requires
  `ServiceScope`, and `TRANSIENT` creates a new value each resolution.
- Build-time validation covers duplicate registrations, constructor annotations, declared factory
  dependencies, missing registrations, dependency cycles, and singleton-to-scoped captures.
  Declared factory dependencies validate the graph but are not factory arguments.
- Ownership is opt-in. Only owned singleton and scoped resources are cleaned up, in reverse
  acquisition order; transients are never owned. Support context managers and `aclose()`/`close()`.
- Closing a provider or scope must be idempotent, reject new resolutions, wait for in-flight
  activations, and complete cleanup despite caller cancellation. Avoid deadlocks in concurrent
  activation and keep cycle diagnostics useful.

## Change and validation

Export intentional public additions from `aeterna.di` and update the DI guide for behavior
changes. Add focused coverage in `tests/test_di.py` for lifetimes, validation, ownership,
concurrency, cancellation, scopes, and cleanup order. Run `uv run pytest tests/test_di.py`.
