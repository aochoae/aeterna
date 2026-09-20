# Aeterna Config

`aeterna-config` provides asynchronous, layered configuration that becomes an immutable
snapshot after it is built. It is the standard-library-only configuration foundation for
the Aeterna packages.

## Features

- Load asynchronous configuration providers in registration order.
- Recursively overlay mappings; later scalars, lists, tuples, and `None` replace earlier
  values.
- Read values with colon-delimited paths, create section views, and inspect provenance.
- Bind values strictly to annotated dataclasses, primitive types, collections, mappings,
  enums, unions, and `Any`.
- Supply in-memory mappings and environment variables without an adapter dependency.

## Requirements

- Python 3.12 or later.
- No runtime dependencies outside the Python standard library.

## Installation

With `pip`:

```bash
pip install aeterna-config
```

With `uv`:

```bash
uv add aeterna-config
```

## Basic usage

Build the snapshot asynchronously, then read a path or bind a section to a dataclass.

```python
import asyncio
from dataclasses import dataclass

from aeterna.config import ConfigurationBuilder


@dataclass
class DatabaseSettings:
    host: str
    port: int


async def main() -> None:
    configuration = await (
        ConfigurationBuilder()
        .add_mapping({"database": {"host": "localhost", "port": "5432"}})
        .build()
    )

    settings = configuration.bind(DatabaseSettings, "database")
    print(settings.host)  # localhost


asyncio.run(main())
```

## Configuration details

`ConfigurationBuilder` loads providers in registration order. Mapping values are merged
recursively, while later scalar, list, tuple, or `None` values replace earlier values.
`build()` creates an immutable snapshot; reads never reload providers. `as_mapping()` is
also immutable, and `source()` reports the provider that last supplied a path when known.

`EnvironmentProvider` converts environment variable names to nested paths. Its default
delimiter is `__`, and it lowercases path segments unless `case_sensitive=True`. For
example, `APP_DATABASE__PORT=5432` becomes `database:port` with `prefix="APP_"`.
Environment values remain strings until binding.

```python
builder.add_environment(prefix="APP_")
```

Providers implement `ConfigurationProvider`: a stable `name` property and an asynchronous
`load()` method returning a mapping. This lets adapters such as `aeterna-config-yaml` use
the same builder. Provider failures cross the builder boundary as sanitized errors.

## Public API

Classes and protocol:

- `ConfigurationBuilder`: collects providers and asynchronously builds a snapshot.
- `Configuration`: immutable snapshot with `get()`, `require()`, `contains()`, `section()`,
  `bind()`, `as_mapping()`, and `source()`.
- `ConfigurationBinder`: binds a value to an annotated target with `bind()`.
- `ConfigurationProvider`: protocol for asynchronous mapping providers.
- `MappingProvider`: provider backed by an in-memory mapping.
- `EnvironmentProvider`: provider that reads environment variables.

Exceptions:

- `ConfigurationError`: base class for configuration failures.
- `ProviderError`: a provider failed without exposing its original details.
- `MergeError`: provider data cannot be represented as a configuration tree.
- `MissingValueError`: a requested configuration path is absent.
- `BindingError`: a value cannot be converted to the requested type.

## Tests

From the repository root:

```bash
uv sync --locked
uv run pytest tests/test_config.py
```
