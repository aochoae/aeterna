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
from aeterna.config import MergeError
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
        documents = await asyncio.to_thread(_load_documents, Path(self.path), self.encoding)
        if len(documents) > 1:
            raise MergeError(f"YAML provider {self.path!s} requires exactly one document")
        document: Any = documents[0] if documents else None
        if document is None:
            return {}
        if not isinstance(document, Mapping):
            raise MergeError(f"YAML provider {self.path!s} requires a mapping root")
        return document


def _load_documents(path: Path, encoding: str) -> list[Any]:
    """Read and parse all YAML documents in a worker thread.

    :param path: Filesystem path of the YAML source.
    :param encoding: Text encoding used to read the source.
    :return: Parsed YAML documents.
    :rtype: list[Any]
    """
    content = path.read_text(encoding=encoding)
    return list(yaml.load_all(content, Loader=_UniqueKeyLoader))
