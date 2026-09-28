# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""YAML configuration adapter for :mod:`aeterna.config`."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from aeterna.config import ConfigurationLimits, MergeError
from yaml.constructor import ConstructorError


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    """Construct a YAML mapping while rejecting duplicate keys.

    :param loader: PyYAML loader constructing the mapping.
    :param node: YAML mapping node to construct.
    :param deep: Whether PyYAML should recursively construct nested values first.
    :return: The constructed mapping.
    :rtype: dict[object, object]
    """
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


@dataclass(frozen=True, slots=True)
class YamlProvider:
    """Load one YAML mapping document as a configuration provider.

    :param path: Filesystem path of the YAML document to load.
    :param encoding: Text encoding used to read the document.
    """

    path: str | Path
    encoding: str = "utf-8"
    max_bytes: int = 1_048_576
    max_aliases: int = 128
    limits: ConfigurationLimits = ConfigurationLimits()

    def __post_init__(self) -> None:
        """Validate parser limits before any file content is read."""
        for name, value in (("max_bytes", self.max_bytes), ("max_aliases", self.max_aliases)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"YAML limit {name} must be a positive integer")

    @property
    def name(self) -> str:
        """Return the provider identity derived from its file path.

        :return: The resulting string.
        :rtype: str
        """
        return f"yaml:{self.path}"

    async def load(self) -> Mapping[str, object]:
        """Read and parse the YAML file without blocking the event loop.

        :attr:`path` identifies the file and :attr:`encoding` specifies how to decode it.
        :return: The resulting configuration mapping.
        :rtype: Mapping[str, object]
        """
        document = await asyncio.to_thread(
            _load_document,
            Path(self.path),
            self.encoding,
            self.max_bytes,
            self.max_aliases,
            self.limits,
        )
        if document is None:
            return {}
        if not isinstance(document, Mapping):
            raise MergeError(f"YAML provider {self.path!s} requires a mapping root")
        return document


def _load_document(
    path: Path,
    encoding: str,
    max_bytes: int,
    max_aliases: int,
    limits: ConfigurationLimits,
) -> Any:
    """Read and parse one bounded YAML document in a worker thread.

    :param path: Filesystem path of the YAML source.
    :param encoding: Text encoding used to read the source.
    :return: The parsed document, or ``None`` for an empty document.
    :rtype: list[Any]
    """
    with path.open("rb") as source:
        content = source.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise MergeError("YAML input exceeds the maximum byte count")
    text = content.decode(encoding)
    _validate_yaml_events(text, max_aliases, limits)
    documents = iter(yaml.load_all(text, Loader=_UniqueKeyLoader))
    sentinel = object()
    first = next(documents, sentinel)
    return None if first is sentinel else first


def _validate_yaml_events(text: str, max_aliases: int, limits: ConfigurationLimits) -> None:
    """Bound YAML parser work before constructing the configuration object graph."""
    aliases = 0
    depth = 0
    nodes = 0
    documents = 0
    for event in yaml.parse(text, Loader=_UniqueKeyLoader):
        if isinstance(event, yaml.events.DocumentStartEvent):
            documents += 1
            if documents > 1:
                raise MergeError("YAML provider requires exactly one document")
        if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
            depth += 1
            nodes += 1
        elif isinstance(event, yaml.events.ScalarEvent):
            nodes += 1
        elif isinstance(event, yaml.events.AliasEvent):
            aliases += 1
            if aliases > max_aliases:
                raise MergeError("YAML input exceeds the maximum alias count")
        if depth > limits.max_depth:
            raise MergeError("YAML input exceeds the maximum nesting depth")
        if nodes > limits.max_nodes:
            raise MergeError("YAML input exceeds the maximum parsed node count")
        if isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
            depth -= 1
