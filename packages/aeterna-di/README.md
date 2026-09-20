# Aeterna DI

`aeterna-di` is an explicit, annotation-driven asynchronous dependency-injection
container. Applications compose a `ServiceCollection`, build a provider, and resolve
services through that provider or an explicit scope.

## Features

- Register existing instances, implementation types, and synchronous or asynchronous
  factories.
- Resolve constructor dependencies from type annotations.
- Choose singleton, scoped, or transient lifetimes.
- Validate duplicate registrations, missing services, dependency cycles, constructor
  annotations, and singleton graphs that capture scoped services.
- Opt into ownership and close supported resources in reverse acquisition order.
- Detect cross-task singleton cycles and report cleanup cancellation as a framework error.

## Requirements

- Python 3.12 or later.
- No runtime dependencies outside the Python standard library.

## Installation

With `pip`:

```bash
pip install aeterna-di
```

With `uv`:

```bash
uv add aeterna-di
```

## Basic usage

Constructor dependencies must have resolvable type annotations. Resolution and provider
cleanup are asynchronous.

```python
import asyncio

from aeterna.di import ServiceCollection, ServiceLifetime


class Clock:
    def now(self) -> str:
        return "12:00"


class GreetingService:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def greet(self) -> str:
        return f"Hello at {self._clock.now()}"


async def main() -> None:
    services = ServiceCollection()
    services.add_type(Clock, lifetime=ServiceLifetime.SINGLETON)
    services.add_type(GreetingService)

    async with services.build_provider() as provider:
        greeting = await provider.get(GreetingService)
        print(greeting.greet())  # Hello at 12:00


asyncio.run(main())
```

## Registration, scopes, and ownership

`add_type()` creates instances from annotated constructor dependencies. `add_factory()`
and `add_async_factory()` receive a `ServiceResolver`; their optional `dependencies=(...)`
sequence enables build-time validation of services the factory will resolve. Without that
declaration, factory resolution failures are deferred until first use.

`add_instance()` registers an existing singleton. `add_type()` and factory registrations
accept `lifetime` and `owns_instance`; ownership is opt-in. Owned singleton resources belong
to the provider, owned scoped resources belong to their scope, and transient services may
not be owned. Supported cleanup includes sync/async context management, `close()`, and
`aclose()`.

Scoped services require an explicit scope:

```python
async with provider.create_scope() as scope:
    service = await scope.get(RequestService)
```

`ServiceCollection` is immutable after `build_provider()`. Provider and scope closing is
idempotent and prevents new resolutions.

## Public API

Classes, protocol, and enum:

- `ServiceCollection`: mutable registration builder.
- `ServiceDescriptor`: immutable description of one registration.
- `ServiceLifetime`: `SINGLETON`, `SCOPED`, and `TRANSIENT` lifetime policies.
- `ServiceProvider`: root resolver and singleton ownership boundary.
- `ServiceScope`: scoped resolver and scoped ownership boundary.
- `ServiceResolver`: protocol providing asynchronous `get()` and `try_get()` methods.

Exceptions:

- `ResolutionError`: base class for service-resolution failures.
- `RegistrationError`: an invalid registration or mutation after build.
- `MissingRegistrationError`: no registration exists for a required service.
- `AmbiguousRegistrationError`: more than one registration uses the same key.
- `CircularDependencyError`: the dependency graph contains a cycle.
- `CaptiveDependencyError`: a singleton graph depends on a scoped service.
- `ActivationError`: a registered service could not be created.
- `ScopeClosedError`: a provider or scope was used after it closed.
- `ServiceCancellationError`: cleanup could not complete normally after cancellation.

## Tests

From the repository root:

```bash
uv sync --locked
uv run pytest tests/test_di.py
```
