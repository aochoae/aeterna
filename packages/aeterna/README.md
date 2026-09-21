# Aeterna

`aeterna` is the metadata-only convenience distribution for the Aeterna framework. It
installs the four component packages:

- `aeterna-config` for layered immutable configuration and typed binding.
- `aeterna-config-yaml` for the optional PyYAML configuration provider.
- `aeterna-di` for explicit asynchronous dependency injection.
- `aeterna-runtime` for application composition and lifecycle hosting.

The distribution contributes no additional runtime implementation to the shared `aeterna`
namespace. Applications continue to import from `aeterna.config`, `aeterna.config_yaml`,
`aeterna.di`, and `aeterna.runtime`.

## Requirements

- Python 3.12 or later.

## Installation

With `pip`:

```bash
pip install aeterna
```

With `uv`:

```bash
uv add aeterna
```

To install only selected framework layers, install the component distributions individually.

## Public API

This distribution defines no public Python API. Use the public APIs exported by the component
packages.
