# Aeterna

Aeterna is an async-first framework for building Python applications with layered
configuration, explicit dependency injection, and predictable lifecycle management. It
supports Python 3.12 and later.

Aeterna draws inspiration from the composition patterns of .NET—especially in configuration,
dependency injection, and application hosting—but implements them in Python with
async-first primitives, explicit ownership boundaries, and clear shutdown semantics.

It is designed for applications that need strong lifecycle control without a global container
or framework-specific application model. The configuration and DI packages can be used on
their own, while the runtime composes them when Aeterna owns or participates in an
application's startup and shutdown flow.

## Why Aeterna

Aeterna is a good fit when you want:

- Explicit service ownership instead of hidden global state
- Typed, layered configuration with recursive merging and immutable snapshots
- Lifecycle-aware dependency resolution with singleton, scoped, and transient lifetimes
- Controlled startup and shutdown ordering for hosted services and application hooks
- A modular architecture that lets you adopt only the layers your application needs

It is less suitable for projects that want framework magic, implicit runtime behavior, or a
single monolithic application shell with hidden composition rules.

## What is included

| Package               | Purpose                                                                                                      |
|-----------------------|--------------------------------------------------------------------------------------------------------------|
| `aeterna-config`      | Async configuration providers, recursive overlays, immutable snapshots, provenance, and strict typed binding |
| `aeterna-di`          | Type-keyed service registration and async resolution with singleton, scoped, and transient lifetimes         |
| `aeterna-config-yaml` | Optional YAML configuration provider using PyYAML                                                            |
| `aeterna-runtime`     | Application composition, lifecycle hooks, hosted services, cancellation, and standalone hosting              |

`aeterna-config` and `aeterna-di` have no dependencies on another aeterna package. The YAML
adapter depends on configuration; the runtime depends on configuration and DI.

## Quick example

```python
from dataclasses import dataclass

from aeterna.config import Configuration, MappingProvider
from aeterna.di import ServiceCollection, ServiceLifetime
from aeterna.runtime import ApplicationBuilder, ApplicationContext, run


@dataclass
class Greeter:
    configuration: Configuration

    def greet(self) -> str:
        return str(self.configuration.require("greeting"))


def register(services: ServiceCollection, _: Configuration) -> None:
    services.add_type(Greeter, lifetime=ServiceLifetime.SINGLETON)


async def main(context: ApplicationContext) -> str:
    return (await context.services.get(Greeter)).greet()


builder = ApplicationBuilder()
builder.add_configuration(MappingProvider({"greeting": "Hello, world!"}))
builder.configure_services(register)

if __name__ == "__main__":
    print(run(builder, main))
```

`run()` creates the event loop, builds the application, runs the callback, and performs shutdown.
For an existing event loop, use `await builder.build()`, `await application.start()`,
`await application.wait()` while the surrounding server is running, and
`await application.stop()` during shutdown. For applications with hosted services,
`wait()` surfaces unexpected hosted-service completion and cleans up before re-raising;
normal cancellation returns from `wait()`, and the host remains responsible for calling
`stop()`.

## Development

This repository is a `uv` workspace. From its root:

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

The test suite covers configuration precedence and binding, DI lifetimes and disposal, runtime
lifecycle and hosting, YAML validation, and package dependency boundaries. CI runs the locked sync,
tests with a branch-coverage floor, Ruff lint and format checks, and mypy on Python 3.12, 3.13, and
3.14. Read the Docs builds the documentation with warnings treated as errors on Python 3.12.

Run focused tests before the full suite when changing one area, for example:

```bash
uv run pytest tests/test_runtime.py tests/test_hosting.py
```

`uv run mypy` checks the production packages listed in `pyproject.toml`; tests are not included in
its configured target.

Build the Sphinx documentation with:

```bash
uv sync --locked --group docs
uv run python -m sphinx -W --keep-going -b html docs docs/_build/html
```

Build distributions with:

```bash
uv run python -m build --sdist --wheel packages/<package>
```

CI smoke-tests the built wheels for importability and the `py.typed` marker. For release validation,
install each wheel and sdist separately in a fresh virtual environment and verify the package
version, public imports, and `py.typed` marker. Built artifacts are written to `packages/*/dist/`
and should not be committed.

## License

Aeterna is released under the [MIT License](LICENSE).
