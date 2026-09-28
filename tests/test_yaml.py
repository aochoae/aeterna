# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

from __future__ import annotations

from pathlib import Path

import pytest
from aeterna.config import ConfigurationBuilder, ConfigurationLimits, MergeError, ProviderError
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


@pytest.mark.asyncio
async def test_yaml_limits_reject_oversized_and_alias_heavy_input(tmp_path: object) -> None:
    path = tmp_path / "settings.yaml"  # type: ignore[operator]
    path.write_text("value: 12345\n", encoding="utf-8")
    with pytest.raises(MergeError, match="maximum byte count"):
        await ConfigurationBuilder().add(YamlProvider(path, max_bytes=4)).build()

    path.write_text("base: &base [one]\nfirst: *base\nsecond: *base\n", encoding="utf-8")
    with pytest.raises(MergeError, match="maximum alias count"):
        await ConfigurationBuilder().add(YamlProvider(path, max_aliases=1)).build()

    path.write_text("one:\n  two: 2\n", encoding="utf-8")
    with pytest.raises(MergeError, match="maximum nesting depth"):
        await (
            ConfigurationBuilder()
            .add(YamlProvider(path, limits=ConfigurationLimits(max_depth=1)))
            .build()
        )


@pytest.mark.asyncio
async def test_yaml_byte_limit_uses_a_bounded_read(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[int] = []

    class Source:
        def __enter__(self) -> Source:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            reads.append(size)
            return b"x" * size

    def open_source(_: Path, *args: object, **kwargs: object) -> Source:
        del args, kwargs
        return Source()

    monkeypatch.setattr(Path, "open", open_source)
    with pytest.raises(MergeError, match="maximum byte count"):
        await YamlProvider("oversized.yaml", max_bytes=4).load()
    assert reads == [5]


def test_yaml_provider_rejects_invalid_parser_limits(tmp_path: object) -> None:
    path = tmp_path / "settings.yaml"  # type: ignore[operator]
    with pytest.raises(ValueError, match="positive integer"):
        YamlProvider(path, max_bytes=0)
    with pytest.raises(ValueError, match="positive integer"):
        YamlProvider(path, max_aliases=True)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_yaml_limits_reject_excessive_parsed_nodes(tmp_path: object) -> None:
    path = tmp_path / "settings.yaml"  # type: ignore[operator]
    path.write_text("first: one\nsecond: two\n", encoding="utf-8")
    with pytest.raises(MergeError, match="maximum parsed node count"):
        await (
            ConfigurationBuilder()
            .add(YamlProvider(path, limits=ConfigurationLimits(max_nodes=2)))
            .build()
        )
