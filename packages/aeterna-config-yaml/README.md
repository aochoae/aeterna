# Aeterna Config YAML

`aeterna-config-yaml` is the optional PyYAML adapter for `aeterna-config`. It loads a
single YAML mapping document through the standard configuration-provider interface.

## Features

- Reads and parses YAML files in a worker thread so the async event loop is not blocked.
- Accepts one mapping document or an empty document, which becomes an empty mapping.
- Rejects duplicate keys, multiple documents, sequence roots, and other non-mapping roots.
- Keeps YAML and its dependency outside the core `aeterna-config` package.

## Requirements

- Python 3.12 or later.
- `aeterna-config`.
- PyYAML 6.0 or later.

Both dependencies are installed automatically with this package.

## Installation

With `pip`:

```bash
pip install aeterna-config-yaml
```

With `uv`:

```bash
uv add aeterna-config-yaml
```

## Basic usage

Given a `settings.yaml` file:

```yaml
service:
  host: localhost
  port: 8080
```

load it into an Aeterna configuration snapshot:

```python
import asyncio

from aeterna.config import ConfigurationBuilder
from aeterna.config_yaml import YamlProvider


async def main() -> None:
    configuration = await ConfigurationBuilder().add(YamlProvider("settings.yaml")).build()
    print(configuration.require("service:port"))  # 8080


asyncio.run(main())
```

## Integration details

`YamlProvider` implements `aeterna.config.ConfigurationProvider`, so it can be added to
`ConfigurationBuilder` alongside mapping, environment, or other providers. Its provider
name is `yaml:<path>` and its `encoding` defaults to `"utf-8"`.

Multiple documents and non-mapping roots raise `aeterna.config.MergeError`; duplicate
keys are rejected by the YAML loader. When loaded through `ConfigurationBuilder`, unsafe
parse or I/O failures cross the public boundary as `aeterna.config.ProviderError`.

## Public API

- `YamlProvider(path, encoding="utf-8")`: asynchronous provider for one YAML mapping
  document.

The package defines no public exceptions; it uses errors from `aeterna.config`.

## Tests

From the repository root:

```bash
uv sync --locked
uv run pytest tests/test_yaml.py
```
