# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

from __future__ import annotations

import pytest
from aeterna.config import ConfigurationBuilder, MergeError, ProviderError
from aeterna.config_yaml import YamlProvider


@pytest.mark.asyncio
async def test_yaml_provider(tmp_path: object) -> None:
    path = tmp_path / "settings.yaml"  # type: ignore[operator]
    path.write_text("server:\n  port: 8080\n", encoding="utf-8")
    config = await ConfigurationBuilder().add(YamlProvider(path)).build()
    assert config.require("server:port") == 8080


@pytest.mark.asyncio
async def test_empty_yaml_is_empty_mapping(tmp_path: object) -> None:
    path = tmp_path / "settings.yaml"  # type: ignore[operator]
    path.write_text("", encoding="utf-8")
    config = await ConfigurationBuilder().add(YamlProvider(path)).build()
    assert dict(config.as_mapping()) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["- one\n- two\n", "---\na: 1\n---\nb: 2\n"])
async def test_yaml_requires_one_mapping_document(tmp_path: object, content: str) -> None:
    path = tmp_path / "settings.yaml"  # type: ignore[operator]
    path.write_text(content, encoding="utf-8")

    builder = ConfigurationBuilder().add(YamlProvider(path))

    with pytest.raises(MergeError):
        await builder.build()


@pytest.mark.asyncio
async def test_yaml_rejects_duplicate_keys(tmp_path: object) -> None:
    path = tmp_path / "settings.yaml"  # type: ignore[operator]
    path.write_text("value: 1\nvalue: 2\n", encoding="utf-8")

    builder = ConfigurationBuilder().add(YamlProvider(path))

    with pytest.raises(ProviderError) as caught:
        await builder.build()
    assert caught.value.provider.startswith("yaml:")
