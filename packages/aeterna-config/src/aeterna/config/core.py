# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Layered immutable configuration and standard-library providers."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import MISSING, dataclass, fields, is_dataclass
from enum import Enum
from types import MappingProxyType, UnionType
from typing import Any, Protocol, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from .errors import BindingError, MergeError, MissingValueError, ProviderError

T = TypeVar("T")
_MISSING = object()
_VALUE_IS_NOT_A_MAPPING = "value is not a mapping"


class ConfigurationProvider(Protocol):
    """Protocol implemented by asynchronous configuration sources."""

    @property
    def name(self) -> str:
        """Return a stable provider identity for provenance and safe error reporting.

        :return: The resulting string.
        :rtype: str
        """

        ...

    async def load(self) -> Mapping[str, object]:
        """Load the provider's configuration mapping.

        :return: The resulting configuration mapping.
        :rtype: Mapping[str, object]
        """

        ...


@dataclass(frozen=True, slots=True)
class MappingProvider:
    """Configuration provider backed by an in-memory mapping.

    :param values: Mapping returned unchanged when the provider is loaded.
    :param name: Stable provenance name reported for supplied values.
    """

    values: Mapping[str, object]
    name: str = "mapping"

    async def load(self) -> Mapping[str, object]:
        """Return the configured mapping without modifying it.

        The mapping is the value supplied through :attr:`values`.
        :return: The resulting configuration mapping.
        :rtype: Mapping[str, object]
        """
        return self.values


@dataclass(frozen=True, slots=True)
class EnvironmentProvider:
    """Configuration provider that maps environment names to nested paths.

    :param prefix: Optional prefix that selects matching environment variables.
    :param delimiter: Separator that turns a variable name into nested path segments.
    :param case_sensitive: Whether to retain the case of derived path segments.
    :param environ: Optional environment mapping; the process environment is used when absent.
    :param name: Stable provenance name reported for supplied values.
    """

    prefix: str = ""
    delimiter: str = "__"
    case_sensitive: bool = False
    environ: Mapping[str, str] | None = None
    name: str = "environment"

    async def load(self) -> Mapping[str, object]:
        """Read and normalize matching environment variables.

        Variables are selected with :attr:`prefix`, split with :attr:`delimiter`, and normalized
        according to :attr:`case_sensitive`. :attr:`environ` supplies the source when configured.
        :return: The resulting configuration mapping.
        :rtype: Mapping[str, object]
        """
        result: dict[str, object] = {}
        source = self.environ if self.environ is not None else os.environ
        for original_key, value in source.items():
            if self.prefix and not original_key.startswith(self.prefix):
                continue
            key = original_key[len(self.prefix) :]
            parts = key.split(self.delimiter) if self.delimiter else [key]
            if not self.case_sensitive:
                parts = [part.lower() for part in parts]
            if any(not part for part in parts):
                raise MergeError(f"Environment key {original_key!r} contains an empty path segment")
            _assign_path(result, parts, value, original_key)
        return result


class ConfigurationBuilder:
    """Collect providers and build an immutable configuration snapshot."""

    def __init__(self) -> None:
        """Create an empty provider pipeline."""
        self._providers: list[ConfigurationProvider] = []

    def add(self, provider: ConfigurationProvider) -> ConfigurationBuilder:
        """Append a provider and return this builder.

        :param provider: Asynchronous source to load in registration order.
        :return: This configuration builder.
        :rtype: ConfigurationBuilder
        """
        self._providers.append(provider)
        return self

    def add_mapping(
        self, values: Mapping[str, object], *, name: str = "mapping"
    ) -> ConfigurationBuilder:
        """Append an in-memory mapping provider.

        :param values: Mapping to expose through the provider.
        :param name: Provenance name reported for values from this mapping.
        :return: This configuration builder.
        :rtype: ConfigurationBuilder
        """
        return self.add(MappingProvider(values, name))

    def add_environment(
        self,
        *,
        prefix: str = "",
        delimiter: str = "__",
        case_sensitive: bool = False,
        environ: Mapping[str, str] | None = None,
    ) -> ConfigurationBuilder:
        """Append an environment provider with the given parsing options.

        :param prefix: Optional environment-variable prefix used to select and remove from keys.
        :param delimiter: Delimiter that separates nested configuration path segments.
        :param case_sensitive: Whether to retain the original case of path segments.
        :param environ: Optional mapping to read instead of the process environment.
        :return: This configuration builder.
        :rtype: ConfigurationBuilder
        """
        return self.add(EnvironmentProvider(prefix, delimiter, case_sensitive, environ))

    async def build(self) -> Configuration:
        """Load providers in order and merge later values over earlier values.

        :return: The resulting `Configuration` value.
        :rtype: Configuration
        """
        merged: dict[str, object] = {}
        sources: dict[str, str] = {}
        for provider in self._providers:
            try:
                values = await provider.load()
                if not isinstance(values, Mapping):
                    raise MergeError(f"Provider {provider.name!r} returned a non-mapping root")
                merged = _merge(merged, values, provider.name, "", sources)
            except MergeError:
                raise
            except Exception:
                # Provider exceptions may contain secret payloads. The stable boundary retains
                # only provider identity; adapters can expose sanitized details as MergeError.
                raise ProviderError(provider.name) from None
        return Configuration(merged, sources=sources)


class Configuration:
    """An immutable snapshot of merged provider values."""

    def __init__(
        self,
        values: Mapping[str, object],
        *,
        sources: Mapping[str, str] | None = None,
        path: str = "",
    ) -> None:
        """Create an immutable configuration view.

        :param values: Mapping containing values for this view.
        :param sources: Optional mapping from fully qualified paths to provider names.
        :param path: Fully qualified path represented by this view.
        """
        frozen = _freeze(values)
        if not isinstance(frozen, Mapping):  # pragma: no cover - constructor contract
            raise TypeError("Configuration root must be a mapping")
        self._values: Mapping[str, object] = frozen
        self._sources = MappingProxyType(dict(sources or {}))
        self._path = path

    def get(self, path: str, default: object = _MISSING) -> object:
        """Return a value by colon-delimited path, or ``default`` if absent.

        :param path: Colon-delimited path relative to this configuration view.
        :param default: Value to return when the path is absent; omitting it raises an error.
        :return: The resulting value.
        :rtype: object
        """
        try:
            return self._lookup(path)
        except MissingValueError:
            if default is _MISSING:
                raise
            return default

    def require(self, path: str) -> object:
        """Return a value by path or raise :class:`MissingValueError`.

        :param path: Colon-delimited path relative to this configuration view.
        :return: The resulting value.
        :rtype: object
        """
        return self._lookup(path)

    def contains(self, path: str) -> bool:
        """Return whether a path exists, including paths whose value is ``None``.

        :param path: Colon-delimited path relative to this configuration view.
        :return: Whether the condition is true.
        :rtype: bool
        """
        try:
            self._lookup(path)
        except MissingValueError:
            return False
        return True

    def section(self, path: str) -> Configuration:
        """Return an immutable configuration view rooted at a mapping path.

        :param path: Colon-delimited path whose value must be a mapping.
        :return: The resulting `Configuration` value.
        :rtype: Configuration
        """
        value = self._lookup(path)
        if not isinstance(value, Mapping):
            raise BindingError(
                self._qualify(path),
                Mapping[str, object],
                _VALUE_IS_NOT_A_MAPPING,
            )
        return Configuration(value, sources=self._sources, path=self._qualify(path))

    def bind[T](self, target: type[T], path: str = "") -> T:
        """Convert the value at ``path`` to the annotated type ``target``.

        :param target: Target type or annotated dataclass used for strict conversion.
        :param path: Optional colon-delimited path; an empty path binds the current view.
        :return: The converted or resolved value.
        :rtype: T
        """
        value = self._lookup(path) if path else self._values
        qualified = self._qualify(path)
        return ConfigurationBinder().bind(value, target, qualified)

    def as_mapping(self) -> Mapping[str, object]:
        """Return the immutable mapping containing this snapshot's values.

        :return: The resulting configuration mapping.
        :rtype: Mapping[str, object]
        """
        return self._values

    def source(self, path: str) -> str | None:
        """Return the provider name that last supplied ``path``, if known.

        :param path: Colon-delimited path relative to this configuration view.
        :return: The result, or `None` when unavailable.
        :rtype: str | None
        """
        return self._sources.get(self._qualify(path))

    def _lookup(self, path: str) -> object:
        """Look up a value relative to this view.

        :param path: Colon-delimited path to traverse, or an empty path for the view root.
        :return: The resulting value.
        :rtype: object
        """
        if not path:
            return self._values
        current: object = self._values
        traversed: list[str] = []
        for part in _split_path(path):
            traversed.append(part)
            if not isinstance(current, Mapping) or part not in current:
                raise MissingValueError(self._qualify(":".join(traversed)))
            current = current[part]
        return current

    def _qualify(self, path: str) -> str:
        """Return a path qualified by this view's root path.

        :param path: Path relative to this view.
        :return: The resulting string.
        :rtype: str
        """
        return ":".join(item for item in (self._path, path) if item)


class ConfigurationBinder:
    """Strict conversion from neutral configuration values to annotated Python types."""

    def bind(self, value: object, target: type[T], path: str = "") -> T:
        """Convert ``value`` to ``target`` and wrap conversion failures.

        :param value: Neutral configuration value to convert.
        :param target: Runtime type or annotated dataclass to create.
        :param path: Path used in a conversion error; empty denotes the configuration root.
        :return: The converted or resolved value.
        :rtype: T
        """
        try:
            return self._convert(value, target, path)  # type: ignore[return-value]
        except BindingError:
            raise
        except (TypeError, ValueError):
            # Conversion errors frequently include the rejected value in their text.
            # Configuration values may be secrets, so neither the public message nor
            # the exception chain may expose the original exception.
            raise BindingError(path, target, "conversion failed") from None

    def _convert(self, value: object, target: object, path: str) -> object:
        """Convert a neutral value into the requested runtime type.

        :return: The resulting value.
        :rtype: object
        """
        origin = get_origin(target)
        arguments = get_args(target)

        if origin in {Union, UnionType}:
            return self._convert_union(value, target, arguments, path)
        if value is None:
            return self._convert_null(target, path)
        if target is Any or target is object:
            return value
        if isinstance(target, type) and is_dataclass(target):
            return self._convert_dataclass(value, target, path)
        if origin in {list, set, frozenset, tuple, Sequence}:
            return self._convert_sequence(value, origin, arguments, path)
        if origin is dict:
            return self._convert_mapping(value, arguments, path)
        if isinstance(target, type) and issubclass(target, Enum):
            return self._convert_enum(value, target, path)
        if isinstance(target, type):
            return self._convert_scalar(value, target, path)

        raise BindingError(path, target, f"unsupported target type for {type(value).__name__}")

    def _convert_union(
        self,
        value: object,
        target: object,
        arguments: tuple[object, ...],
        path: str,
    ) -> object:
        """Try each union member in order until one binds successfully.

        :return: The resulting value.
        :rtype: object
        """
        if value is None and type(None) in arguments:
            return None

        failures: list[str] = []
        for option in arguments:
            if option is type(None):
                continue
            try:
                return self._convert(value, option, path)
            except BindingError as error:
                failures.append(str(error))

        raise BindingError(path, target, "; ".join(failures) or "no union member matched")

    def _convert_null(self, target: object, path: str) -> object:
        """Allow null only for explicit nullable or Any targets.

        :return: The resulting value.
        :rtype: object
        """
        if target is type(None) or target is Any:
            return None
        raise BindingError(path, target, "value is null")

    def _convert_dataclass(self, value: object, target: type[object], path: str) -> object:
        """Instantiate a dataclass after validating its mapping payload.

        :return: The resulting value.
        :rtype: object
        """
        if not isinstance(value, Mapping):
            raise BindingError(path, target, _VALUE_IS_NOT_A_MAPPING)

        dataclass_type = cast(type[Any], target)
        hints = get_type_hints(dataclass_type)
        dataclass_fields = fields(dataclass_type)
        known = {field.name for field in dataclass_fields}
        unknown = set(value) - known
        if unknown:
            raise BindingError(path, target, f"unknown fields: {sorted(unknown)!r}")

        kwargs: dict[str, object] = {}
        for field in dataclass_fields:
            if field.name in value:
                field_path = _join(path, field.name)
                kwargs[field.name] = self._convert(
                    value[field.name],
                    hints[field.name],
                    field_path,
                )
                continue
            if field.default is MISSING and field.default_factory is MISSING:
                raise BindingError(
                    _join(path, field.name),
                    hints[field.name],
                    "value is missing",
                )

        try:
            return target(**kwargs)
        except TypeError:
            raise BindingError(path, target, "dataclass initialization failed") from None

    def _convert_sequence(
        self,
        value: object,
        origin: object,
        arguments: tuple[object, ...],
        path: str,
    ) -> object:
        """Convert a sequence to a concrete Python collection.

        :return: The resulting value.
        :rtype: object
        """
        if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
            raise BindingError(path, origin, "value is not a sequence")

        item_type = arguments[0] if arguments else Any
        converted = [
            self._convert(item, item_type, _join(path, str(index)))
            for index, item in enumerate(value)
        ]

        if origin is tuple:
            return tuple(converted)
        if origin is set:
            return set(converted)
        if origin is frozenset:
            return frozenset(converted)
        return converted

    def _convert_mapping(self, value: object, arguments: tuple[object, ...], path: str) -> object:
        """Convert keys and values in a mapping to their annotated types.

        :return: The resulting value.
        :rtype: object
        """
        if not isinstance(value, Mapping):
            raise BindingError(path, dict, _VALUE_IS_NOT_A_MAPPING)

        key_type, value_type = arguments or (Any, Any)
        return {
            self._convert(key, key_type, _join(path, str(key))): self._convert(
                item,
                value_type,
                _join(path, str(key)),
            )
            for key, item in value.items()
        }

    def _convert_enum(self, value: object, target: type[Enum], path: str) -> object:
        """Resolve enum values from either their stored value or member name.

        :return: The resulting value.
        :rtype: object
        """
        try:
            return target(value)
        except ValueError:
            if isinstance(value, str):
                try:
                    return target[value]
                except KeyError:
                    pass
            raise BindingError(path, target, "value is not a valid enum member") from None

    def _convert_scalar(self, value: object, target: type[object], path: str) -> object:
        """Dispatch scalar conversion to the matching primitive converter.

        :return: The resulting value.
        :rtype: object
        """
        converters = {
            bool: self._convert_bool,
            str: self._convert_string,
            int: self._convert_int,
            float: self._convert_float,
        }
        converter = converters.get(target)
        if converter is not None:
            return converter(value, path)
        if isinstance(value, target):
            return value
        raise BindingError(path, target, f"unsupported target type for {type(value).__name__}")

    def _convert_bool(self, value: object, path: str) -> bool:
        """Convert a value to a boolean using the project conventions.

        :return: Whether the condition is true.
        :rtype: bool
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise BindingError(path, bool, "expected a boolean")

    def _convert_string(self, value: object, path: str) -> str:
        """Convert a value to a string.

        :return: The resulting string.
        :rtype: str
        """
        if not isinstance(value, str):
            raise BindingError(path, str, "expected a string")
        return value

    def _convert_int(self, value: object, path: str) -> int:
        """Convert a value to an integer.

        :return: The resulting integer.
        :rtype: int
        """
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise BindingError(path, int, "boolean is not accepted as a number")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise BindingError(path, int, "expected an integer") from None

    def _convert_float(self, value: object, path: str) -> float:
        """Convert a value to a float.

        :return: The resulting floating-point value.
        :rtype: float
        """
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise BindingError(path, float, "expected a number")
        try:
            return float(value)
        except (TypeError, ValueError):
            raise BindingError(path, float, "expected a number") from None


def _split_path(path: str) -> list[str]:
    """Split and validate a colon-delimited path.

    :param path: Path whose non-empty segments should be returned.
    :return: The path segments.
    :rtype: list[str]
    """
    parts = path.split(":")
    if any(not part for part in parts):
        raise MissingValueError(path)
    return parts


def _join(left: str, right: str) -> str:
    """Join two configuration path components.

    :param left: Existing path, possibly empty.
    :param right: Segment or relative path to append.
    :return: The resulting string.
    :rtype: str
    """
    return f"{left}:{right}" if left else right


def _freeze(value: object) -> object:
    """Recursively make configuration containers immutable.

    :param value: Mapping, sequence, or scalar value to freeze.
    :return: The resulting value.
    :rtype: object
    """
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _merge(
    base: Mapping[str, object],
    overlay: Mapping[str, object],
    provider: str,
    path: str,
    sources: MutableMapping[str, str],
) -> dict[str, object]:
    """Overlay one configuration mapping onto another.

    :param base: Earlier mapping whose values provide the starting tree.
    :param overlay: Later mapping whose values take precedence.
    :param provider: Name of the provider supplying ``overlay``.
    :param path: Fully qualified path of the mappings currently being merged.
    :param sources: Mutable provenance mapping updated for replacement values.
    :return: The merged configuration mapping.
    :rtype: dict[str, object]
    """
    result = dict(base)
    for raw_key, value in overlay.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise MergeError(f"Configuration keys must be non-empty strings, got {raw_key!r}")
        key_path = _join(path, raw_key)
        existing = result.get(raw_key, _MISSING)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            result[raw_key] = _merge(existing, value, provider, key_path, sources)
        else:
            result[raw_key] = _copy_tree(value, key_path)
            _record_sources(value, provider, key_path, sources)
    return result


def _copy_tree(value: object, path: str) -> object:
    """Copy and validate a mutable configuration subtree.

    :param value: Subtree to copy into an intermediate configuration tree.
    :param path: Fully qualified location of ``value`` for validation errors.
    :return: The resulting value.
    :rtype: object
    """
    if isinstance(value, Mapping):
        return {
            _valid_key(key, path): _copy_tree(item, _join(path, str(key)))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_copy_tree(item, _join(path, str(index))) for index, item in enumerate(value)]
    return value


def _valid_key(key: object, path: str) -> str:
    """Validate and return a configuration mapping key.

    :param key: Candidate key from a nested configuration mapping.
    :param path: Parent path used to report invalid keys.
    :return: The resulting string.
    :rtype: str
    """
    if not isinstance(key, str) or not key:
        raise MergeError(f"Configuration keys below {path!r} must be non-empty strings")
    return key


def _record_sources(
    value: object, provider: str, path: str, sources: MutableMapping[str, str]
) -> None:
    """Record provenance for a value and its nested mapping values.

    :param value: Value whose supplied paths should be recorded.
    :param provider: Name of the provider that supplied ``value``.
    :param path: Fully qualified path of ``value``.
    :param sources: Mutable provenance mapping to update.
    :return: None.
    :rtype: None
    """
    sources[path] = provider
    if isinstance(value, Mapping):
        for key, item in value.items():
            _record_sources(item, provider, _join(path, str(key)), sources)


def _assign_path(
    target: MutableMapping[str, object], parts: Sequence[str], value: str, original: str
) -> None:
    """Assign an environment value to a nested mapping path.

    :param target: Mutable mapping that receives the value.
    :param parts: Validated path segments derived from the environment key.
    :param value: String value read from the environment.
    :param original: Original environment key used in error messages.
    :return: None.
    :rtype: None
    """
    current = target
    for part in parts[:-1]:
        existing = current.setdefault(part, {})
        if not isinstance(existing, MutableMapping):
            raise MergeError(f"Environment key {original!r} conflicts with another key")
        current = existing
    leaf = parts[-1]
    if leaf in current:
        raise MergeError(f"Environment key {original!r} is duplicated after normalization")
    current[leaf] = value
