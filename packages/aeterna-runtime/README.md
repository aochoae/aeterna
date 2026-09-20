# Aeterna Runtime

`aeterna-runtime` composes Aeterna configuration and dependency injection into an
application lifecycle. It supports embedded use in an existing event loop and standalone
hosting that owns the event loop and handles termination signals.

## Features

- Build configuration, services, lifecycle hooks, and hosted services together.
- Run hooks in registration order on startup and reverse order on shutdown.
- Supervise hosted-service tasks, propagate unexpected completion or failure, and request
  cooperative cancellation during shutdown.
- Close the service provider during shutdown and enforce a configurable graceful-shutdown
  timeout.
- Use `run()` for framework-owned event-loop and signal handling, or build/start/wait/stop
  from an embedding framework's event loop.
- Emit runtime debug logging only when the consuming application configures logging.

## Requirements

- Python 3.12 or later.
- `aeterna-config` and `aeterna-di`.

The Aeterna dependencies are installed automatically with this package.

## Installation

With `pip`:

```bash
pip install aeterna-runtime
```

With `uv`:

```bash
uv add aeterna-runtime
```

## Basic usage

`run()` builds the application and owns the event loop. The configuration snapshot and
cancellation token are registered as services before the provider is built.

```python
from aeterna.config import Configuration, MappingProvider
from aeterna.di import ServiceLifetime
from aeterna.runtime import ApplicationBuilder, ApplicationContext, run


class Greeter:
    def __init__(self, configuration: Configuration) -> None:
        self._greeting = configuration.require("greeting")

    def message(self) -> str:
        return str(self._greeting)


builder = ApplicationBuilder().add_configuration(MappingProvider({"greeting": "hello"}))
builder.configure_services(
    lambda services, _: services.add_type(Greeter, lifetime=ServiceLifetime.SINGLETON)
)


async def main(context: ApplicationContext) -> str:
    return (await context.services.get(Greeter)).message()


print(run(builder, main))  # hello
```

## Lifecycle and integration details

Use `add_configuration()` to add a `ConfigurationProvider`, `configure_services()` to
register services after configuration has loaded, and `add_lifecycle_hook()` to register
synchronous or asynchronous start and stop callbacks. `add_hosted_service()` registers a
singleton implementing `HostedService`, whose `start()`, `run()`, and `stop()` methods
receive an `ApplicationContext`.

The normal state sequence is `CREATED`, `STARTING`, `RUNNING`, `STOPPING`, then `STOPPED`;
failures enter `FAILED`. Application code can read `context.state`, but state changes are
runtime-owned. A hosted service's `run()` method should continue until its cancellation
token is cancelled or it fails. Shutdown requests cancellation, stops services and hooks in
reverse order, waits for running tasks, then closes the provider. The default timeout is
30 seconds and `use_shutdown_timeout()` configures it.

`Application.run(main=None)` is the standalone convenience API: it owns the event loop, builds
the application, starts hooks and hosted services, supervises execution, and stops the application.
For embedding, await `ApplicationBuilder.build()` and then call `Application.start()` from the
caller's event loop. Await `Application.wait()` while the surrounding server is running so
unexpected hosted-service completion is surfaced and cleaned up. Normal cancellation returns
from `wait()`; the host should still call `Application.stop()` in its shutdown path.
Embedded hosts own their own signals and server lifecycle. `run()` owns the loop via
`asyncio.run` and temporarily maps SIGINT/SIGTERM to cooperative cancellation where
supported.

`exit_code()` maps successful completion to `0`, cancellation or `KeyboardInterrupt` to
`130`, and other errors to `1`; it is only a mapping helper and is not called by `run()`.

## Public API

Classes, protocols, and enum:

- `ApplicationBuilder`: configures and asynchronously builds an application.
- `Application`: built application with asynchronous `start()`, `wait()`, `run()`, and
  `stop()`.
- `Application.start()`: start hooks and hosted services and schedule their run tasks.
- `Application.wait()`: supervise hosted services for embedded hosts until cancellation or
  unexpected completion.
- `Application.stop()`: request cancellation, clean up started components, and close owned
  resources.
- `ApplicationContext`: services, configuration, cancellation, and current state for
  callbacks.
- `ApplicationState`: `CREATED`, `STARTING`, `RUNNING`, `STOPPING`, `STOPPED`, and `FAILED`.
- `CancellationToken`: cooperative cancellation signal with `cancel()`, `wait()`, and
  `is_cancelled`.
- `HostedService`: protocol defining asynchronous `start()`, `run()`, and `stop()`.
- `LifecycleHook`: pair of startup and shutdown callbacks.

Functions:

- `run(builder, main=None)`: build and run an application with a framework-owned loop.
- `exit_code(error)`: return a process exit code for a completion error.

Exceptions:

- `ApplicationError`: base class for runtime failures.
- `ApplicationCancellationError`: cleanup could not complete normally after cancellation.
- `InvalidStateError`: a lifecycle operation is invalid in the current state.
- `StartupError`: startup failed.
- `HostedServiceError`: a hosted service stopped unexpectedly.
- `ShutdownTimeoutError`: graceful shutdown exceeded its deadline.

## Tests

From the repository root:

```bash
uv sync --locked
uv run pytest tests/test_runtime.py tests/test_hosting.py
```
