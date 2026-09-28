# Aeterna Runtime guidelines

## Purpose and structure

`aeterna-runtime` composes configuration and DI into an application lifecycle. Public symbols are
exported from `src/aeterna/runtime/__init__.py`; lifecycle composition is in `application.py`,
standalone hosting in `hosting.py`, and public errors in `errors.py`.

## Contracts

- Import only `aeterna.config` and `aeterna.di`. Keep web frameworks, schedulers, and other
  integrations in application code or separate adapters.
- `ApplicationBuilder.build()` loads configuration, runs service configurators, registers
  `Configuration` and `CancellationToken`, validates DI, and produces an immutable application.
- Preserve runtime-owned state transitions: `CREATED` → `STARTING` → `RUNNING` → `STOPPING` →
  `STOPPED`, with failures entering `FAILED`. Application code may observe but not mutate state.
- Start hooks and hosted services in registration order; stop services and hooks in reverse order.
  Supervise hosted `run()` tasks: unexpected return or failure is an error.
- Shutdown must request cooperative cancellation, honor one configured deadline across all cleanup,
  close the provider, preserve cleanup failures, and finish graceful cleanup before reporting
  caller cancellation. `stop()` remains idempotent.
- `run()` owns `asyncio.run` and supported signal handling. Embedded hosts own their loop and
  signals and use `build()`, `start()`, `wait()`, and `stop()`. Keep library logging quiet by
  default through the `aeterna.runtime` logger and avoid secrets in normal logs.

## Change and validation

Export intentional public additions from `aeterna.runtime`; update lifecycle or hosting docs when
behavior changes. Add focused lifecycle coverage in `tests/test_runtime.py` and standalone-host
coverage in `tests/test_hosting.py`. Run
`uv run pytest tests/test_runtime.py tests/test_hosting.py` from the repository root.
