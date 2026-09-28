# Aeterna Config YAML guidelines

## Purpose and structure

`aeterna-config-yaml` is the optional PyYAML adapter for `aeterna-config`. The public
`YamlProvider` and its parser safeguards live in `src/aeterna/config_yaml/__init__.py`.

## Contracts

- This package may import only `aeterna.config`; keep PyYAML isolated here and do not introduce
  imports from DI or runtime.
- `YamlProvider` implements the configuration-provider protocol. Read and parse files with
  `asyncio.to_thread` so async callers do not perform blocking I/O.
- Accept one mapping document or an empty document only. Reject multiple documents, sequence or
  scalar roots, duplicate keys, invalid limits, excessive byte size, aliases, nesting, and nodes.
- Preserve the configuration error boundary: invalid document shape may raise `MergeError`; I/O
  and parser failures must be safe for `ConfigurationBuilder` to expose as sanitized
  `ProviderError` values. Do not reveal file content in errors.
- Retain the default UTF-8 encoding, provider naming convention (`yaml:<path>`), and immutable
  `ConfigurationLimits` integration unless intentionally changing the public contract.

## Change and validation

Keep PyYAML as the only adapter-specific dependency and export only intentional public symbols.
Update the YAML README and configuration docs for public behavior changes. Add focused cases to
`tests/test_yaml.py`, then run `uv run pytest tests/test_yaml.py` from the repository root.
