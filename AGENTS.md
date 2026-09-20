# Repository Guidelines

## Project purpose

Aeterna is a Python 3.12+ async-first framework for layered configuration,
explicit dependency injection, and predictable application lifecycle management.
It is intentionally modular: applications can use the configuration and DI
cores without adopting the runtime host, and integrations remain outside the
core packages.

The repository is a `uv` workspace. The root project is an aggregate
development project (`tool.uv.package = false`); the four installable workspace
members are all version `1.0.0.dev1` and contribute typed subpackages to the
shared `aeterna` namespace:

- `aeterna-config` — standard-library configuration providers, merging,
  immutable snapshots, provenance, and typed binding.
- `aeterna-di` — explicit async service registration, type-keyed resolution,
  scopes, lifetimes, validation, and opt-in cleanup.
- `aeterna-config-yaml` — optional PyYAML provider; YAML is deliberately not a
  dependency of the core configuration package.
- `aeterna-runtime` — composition, application context, lifecycle hooks, hosted
  services, cancellation, graceful shutdown, and standalone or embedded hosting.

## Repository structure

- `packages/*/src/aeterna/` contains package implementation. Public symbols
  are exported from each package’s `__init__.py`; keep implementation details
  in focused modules.
- `packages/*/README.md` and each package `pyproject.toml` describe the
  individual distribution and its runtime dependencies.
- `tests/` contains pytest coverage for configuration, DI, YAML, runtime
  lifecycle/hosting, package boundaries, and synchronized package versions.
- `docs/` contains Sphinx guides and API reference sources. The guides are the
  design and behavior reference for the checked-out implementation.
- `tools/benchmark.py` contains informational `pyperf` benchmarks for transient
  resolution and merging 100 configuration providers; it is not a performance
  gate.
- `.github/workflows/quality-assurance.yml` defines CI. `.readthedocs.yaml`
  defines the Read the Docs build, and `sonar-project.properties` configures
  SonarQube analysis.
- `uv.lock` is checked in and must remain synchronized with project metadata.

Do not edit or commit generated/local material such as `dist/`,
`packages/*/dist/`, `build/`, `packages/*/build/`, `docs/_build/`, `.venv/`,
`.uv-cache/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.hypothesis/`,
`.sonar/`, coverage reports, bytecode, or IDE files. Do not commit credentials,
`.env` files, or secrets.

## Architecture and constraints

### Package boundaries

`aeterna-config` and `aeterna-di` have no dependencies on another Aeterna
package and must not import adapters or the runtime. `aeterna-config-yaml` may
import only `aeterna.config`; `aeterna-runtime` may import only
`aeterna.config` and `aeterna.di`. Keep application integrations such as
FastAPI, gRPC, secret stores, and schedulers in application code or separate
adapters; they are not bundled dependencies.

All distributions are built with Hatchling and include a `py.typed` marker.
Keep versions synchronized across the root and all package manifests.

### Configuration

- Providers implement an async `name`/`load()` protocol and are loaded in
  registration order during `ConfigurationBuilder.build()`.
- Later mappings recursively overlay earlier mappings. Later scalars, lists,
  tuples, and `None` replace earlier values. The result is an immutable
  snapshot; reads never reload providers.
- Use colon-delimited paths with `get`, `require`, `contains`, `section`, and
  `source`. `as_mapping()` is immutable and records provider provenance where
  known.
- `EnvironmentProvider` uses `__` as the default nesting delimiter, supports a
  prefix and case normalization, and keeps environment values as strings until
  binding. Empty segments and normalized key collisions are errors.
- `Configuration.bind()` is intentionally strict. It supports annotated
  dataclasses, enums, primitive scalar conversions, unions, homogeneous
  sequences, concrete dictionaries, and `Any`; it rejects unknown dataclass
  fields and unsupported annotations. Do not broaden the binder implicitly.
- Provider and binding errors must not expose configuration values, secrets, or
  raw conversion exceptions. Unexpected provider failures cross the public
  boundary as sanitized `ProviderError`; providers may raise a safe
  `MergeError` for invalid data.

The YAML adapter reads asynchronously through `asyncio.to_thread`, accepts one
mapping document or an empty document, rejects sequence roots, multiple
documents, and duplicate keys, and converts unsafe parse/I/O failures through
the configuration error boundary.

### Dependency injection

- Composition is explicit: mutate `ServiceCollection`, then build an
  immutable `ServiceProvider`. Keys are types; resolution is async and
  annotation-driven, with `add_instance`, `add_type`, `add_factory`, and
  `add_async_factory` registrations.
- `SINGLETON` is provider-wide, `SCOPED` requires an explicit
  `ServiceScope`, and `TRANSIENT` creates a value for every resolution.
  `try_get` is the optional-resolution API; `get` reports missing keys.
- Provider build validates duplicate registrations, constructor annotations,
  missing dependencies, cycles, and singleton-to-scoped captive dependencies.
  Factory `dependencies=(...)` are validated at build time but are not passed
  as factory arguments; factories resolve through their `ServiceResolver`.
  Undeclared factory dependencies are allowed and fail on first resolution.
- Resource ownership is opt-in with `owns_instance=True`. Owned singleton
  resources belong to the provider; owned scoped resources belong to their
  scope. Supported cleanup is async/sync context management plus `aclose()` or
  `close()`, in reverse acquisition order. Transients are never owned and
  registering a transient as owned is rejected at build time.
- Closing a provider or scope stops new resolutions, waits for in-flight
  activations, releases caches, and is idempotent. Cancellation of the caller
  does not interrupt cleanup; cleanup cancellation is reported as a framework
  error in the resulting exception group.
- Concurrent singleton activation must remain single-instance and cross-task
  dependency cycles must raise a diagnostic error instead of deadlocking.

### Runtime and hosting

`ApplicationBuilder.build()` loads the configuration, invokes service
configurators, registers `Configuration` and `CancellationToken`, validates
the DI graph, and returns an `Application` with an immutable provider,
context, hooks, and hosted-service registrations.

- The normal state sequence is `CREATED` → `STARTING` → `RUNNING` →
  `STOPPING` → `STOPPED`; failures enter `FAILED`. `context.state` is
  read-only to application code and state changes are runtime-owned.
- Lifecycle hook starts run in registration order, followed by hosted-service
  `start()` methods. Hosted services are registered as singletons; their
  `run()` tasks are supervised by `run()` or `wait()` until cancellation or
  failure. A task that returns unexpectedly is a `HostedServiceError`.
- Shutdown requests cancellation, stops hosted services in reverse start
  order, stops hooks in reverse registration order, waits for running tasks,
  and closes the provider. The default shutdown timeout is 30 seconds and is
  configurable with `use_shutdown_timeout()`; timeouts identify stalled
  services. Cleanup failures are preserved in exception groups.
- Startup failure and cancellation clean up only components that started.
  `run()` and direct `stop()` complete graceful cleanup before re-reporting
  caller cancellation. `stop()` is idempotent.
- `aeterna.runtime.run()` owns the event loop via `asyncio.run` and, where
  supported, maps SIGINT/SIGTERM to cooperative cancellation. Embedded hosts
  must `await build()` and `start()` from their own loop, await `wait()` while
  hosted services run, then `stop()` during shutdown; they own signals/server
  lifecycle. `exit_code()` is only a mapping helper; `run()` does not call it.
- Runtime logging uses the `aeterna.runtime` logger with a `NullHandler`.
  Libraries emit nothing until the application configures logging.

## Development environment and commands

Use the locked workspace environment from the repository root. Runtime package
dependencies are intentionally small: the two core packages use only the
standard library, YAML uses `PyYAML`, and runtime depends on config and DI.
Development dependencies include pytest, pytest-asyncio, pytest-cov,
Hypothesis, Ruff, strict mypy for `packages/`, `build`, `pyperf`, and
`types-PyYAML`. Sphinx and `sphinxcontrib-mermaid` are in the separate `docs`
dependency group.

```bash
uv sync --locked
uv run pytest
uv run pytest --cov=aeterna --cov-report=term-missing --cov-report=xml --cov-fail-under=95
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv sync --locked --group docs
uv run python -m sphinx -W --keep-going -b html docs docs/_build/html
```

Apply formatting with `uv run ruff format .`. Run the informational benchmark
with `uv run python tools/benchmark.py`. Build one distribution with
`uv run python -m build --sdist --wheel packages/<package>`. CI builds all four
packages and smoke-tests each wheel, including importability and the `py.typed`
marker; it builds sdists but does not install them in the smoke-test job. For
release validation, install each wheel and sdist separately in a fresh virtual
environment, then verify the package version, public imports, and `py.typed`
marker. Keep all built artifacts in `packages/*/dist/` and do not commit them.

CI runs pytest, Ruff, format checks, and mypy on Ubuntu, macOS, and Windows
with Python 3.12, 3.13, and 3.14. A separate Ubuntu job enforces 95% branch
coverage. Read the Docs builds the Sphinx site with warnings treated as errors
using Python 3.12, and SonarQube consumes `coverage.xml` as its Python coverage
path.

`uv run mypy` checks the production packages configured in `pyproject.toml`; it
does not type-check `tests/`. Run focused tests before the full suite, for
example `uv run pytest tests/test_runtime.py tests/test_hosting.py`, then run
the complete pytest, lint, type, coverage, documentation, and package-build
checks before handing off a change.

## Coding and documentation conventions

- Use Python 3.12-compatible syntax, four-space indentation, UTF-8, LF
  newlines, type annotations, and direct English docstrings. Keep lines to
  100 columns and follow Ruff rules `E`, `F`, `I`, `UP`, `B`, and `ASYNC`.
- Use `PascalCase` for classes, `snake_case` for functions/methods/variables,
  and `UPPER_CASE` for constants. Prefer standard-library types and existing
  async APIs; do not add a third-party runtime dependency to a core package
  without an explicit architectural reason.
- Import public APIs from `aeterna.config`, `aeterna.di`,
  `aeterna.config_yaml`, or `aeterna.runtime`, not implementation modules.
  Export every intentional public addition from the relevant `__init__.py`.
- Preserve immutable configuration snapshots, explicit DI ownership and scope
  semantics, lifecycle ordering, cancellation guarantees, and sanitized error
  boundaries. Avoid blocking I/O in async paths.
- When public behavior changes, update focused tests, the relevant Sphinx guide
  and API reference, package metadata if needed, and `uv.lock` whenever
  dependency metadata changes. Keep examples aligned with the implementation.

## Testing practices

Use pytest with automatic asyncio mode (`asyncio_mode = "auto"`) and keep tests
under `tests/` with `test_*.py` filenames and `test_<behavior>` names. Add
focused coverage for the affected contract, especially:

- configuration precedence, immutability, provenance, environment parsing,
  strict binding, and secret-safe errors;
- DI lifetimes, explicit scopes, ownership/disposal order, validation,
  concurrent activation, cancellation, and cycle detection;
- YAML document shape and duplicate-key validation;
- runtime state transitions, startup/shutdown ordering, hosted-task
  supervision, timeout/failure aggregation, cancellation, logging, and
  framework-owned versus embedded hosting; and
- package import boundaries and synchronized versions.


## Instructions for AI coding agents

1. Read this file and the relevant package guide/source before editing. Check
   `git status` first and preserve unrelated user changes.
2. Keep changes within the requested scope. For implementation work, change
   the smallest appropriate package, add or update focused tests, and do not
   weaken architecture-boundary or secret-safety tests.
3. Maintain the dependency direction exactly: config and DI are independent;
   YAML depends on config; runtime depends on config and DI. Put integrations
   in adapters or application code.
4. Treat registration/build boundaries, immutable snapshots, explicit scopes,
   opt-in ownership, reverse-order cleanup, lifecycle ordering, and cancellation
   behavior as public contracts. Do not introduce global state or implicit
   container behavior.
5. Use public exports and update documentation for public API changes. Keep
   package versions synchronized and update `uv.lock` for dependency changes.
6. Run proportionate verification, report commands and results, and mention
   any check that could not run. Do not use destructive repository commands or
   modify generated artifacts to make checks pass.
