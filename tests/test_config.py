# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal

import pytest
from aeterna.config import (
    BindingError,
    ConfigurationBinder,
    ConfigurationBuilder,
    EnvironmentProvider,
    MergeError,
    MissingValueError,
    ProviderError,
)
from hypothesis import given
from hypothesis import strategies as st


class Mode(Enum):
    DEV = "dev"
    PROD = "prod"


@dataclass
class Database:
    host: str
    port: int
    secure: bool = False


@dataclass
class Settings:
    database: Database
    mode: Mode
    tags: list[str]
    note: str | None = None


@pytest.mark.asyncio
async def test_precedence_merge_null_and_list_replacement() -> None:
    config = await (
        ConfigurationBuilder()
        .add_mapping({"database": {"host": "first", "port": 1000}, "items": [1, 2], "value": 1})
        .add_mapping({"database": {"port": 2000}, "items": [3], "value": None}, name="override")
        .build()
    )
    assert config.require("database:host") == "first"
    assert config.require("database:port") == 2000
    assert config.require("items") == (3,)
    assert config.contains("value")
    assert config.require("value") is None
    assert not config.contains("missing")
    assert config.source("database:port") == "override"


@pytest.mark.asyncio
async def test_environment_provider_is_explicit_and_normalized() -> None:
    config = (
        await ConfigurationBuilder()
        .add(
            EnvironmentProvider(
                prefix="APP_",
                delimiter="__",
                environ={"APP_DATABASE__HOST": "localhost", "IGNORED": "x"},
            )
        )
        .build()
    )
    assert config.require("database:host") == "localhost"
    with pytest.raises(MissingValueError):
        config.require("ignored")


@pytest.mark.asyncio
async def test_typed_binding() -> None:
    config = (
        await ConfigurationBuilder()
        .add_mapping(
            {
                "database": {"host": "localhost", "port": "5432", "secure": "true"},
                "mode": "prod",
                "tags": ["one", "two"],
                "note": None,
            }
        )
        .build()
    )
    settings = config.bind(Settings)
    assert settings == Settings(Database("localhost", 5432, True), Mode.PROD, ["one", "two"])


@pytest.mark.asyncio
async def test_binding_error_contains_precise_path() -> None:
    config = (
        await ConfigurationBuilder()
        .add_mapping({"database": {"host": "localhost", "port": "bad"}, "mode": "dev", "tags": []})
        .build()
    )
    with pytest.raises(BindingError) as caught:
        config.bind(Settings)
    assert caught.value.path == "database:port"


@pytest.mark.asyncio
async def test_snapshot_and_sections_are_immutable() -> None:
    config = await ConfigurationBuilder().add_mapping({"nested": {"value": 1}}).build()
    assert isinstance(config.as_mapping(), MappingProxyType)
    with pytest.raises(TypeError):
        config.as_mapping()["new"] = 2  # type: ignore[index]
    assert config.section("nested").require("value") == 1


@pytest.mark.asyncio
async def test_environment_collisions_are_rejected() -> None:
    provider = EnvironmentProvider(
        prefix="X_", case_sensitive=False, environ={"X_A": "one", "X_a": "two"}
    )
    builder = ConfigurationBuilder().add(provider)
    with pytest.raises(MergeError):
        await builder.build()


@pytest.mark.asyncio
async def test_provider_failure_does_not_expose_secret() -> None:
    class SecretProvider:
        name = "vault"

        async def load(self) -> dict[str, object]:
            raise RuntimeError("token=super-secret")

    builder = ConfigurationBuilder().add(SecretProvider())

    with pytest.raises(ProviderError) as caught:
        await builder.build()
    assert caught.value.provider == "vault"
    assert "super-secret" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [int, float])
async def test_binding_failure_does_not_expose_secret(target: type[object]) -> None:
    secret = "database-password-123"
    config = await ConfigurationBuilder().add_mapping({"credential": secret}).build()

    with pytest.raises(BindingError) as caught:
        config.bind(target, "credential")

    assert secret not in str(caught.value)
    assert caught.value.__cause__ is None


config_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=10),
    lambda children: (
        st.lists(children, max_size=4)
        | st.dictionaries(st.text(min_size=1, max_size=8), children, max_size=4)
    ),
    max_leaves=12,
)


@given(
    st.dictionaries(st.text(min_size=1, max_size=8), config_values, max_size=5),
    st.dictionaries(st.text(min_size=1, max_size=8), config_values, max_size=5),
)
def test_merge_is_idempotent_for_repeated_overlay(
    base: dict[str, object], overlay: dict[str, object]
) -> None:
    import asyncio

    async def build(repetitions: int) -> object:
        builder = ConfigurationBuilder().add_mapping(base)
        for _ in range(repetitions):
            builder.add_mapping(overlay)
        return (await builder.build()).as_mapping()

    assert asyncio.run(build(1)) == asyncio.run(build(2))


@pytest.mark.asyncio
async def test_environment_key_empty_segment_raises() -> None:
    provider = EnvironmentProvider(
        prefix="APP_",
        delimiter="__",
        environ={"APP_A____B": "x"},
    )
    builder = ConfigurationBuilder().add(provider)

    with pytest.raises(MergeError):
        await builder.build()


@pytest.mark.asyncio
async def test_environment_case_sensitive_preserves_case() -> None:
    provider = EnvironmentProvider(
        prefix="",
        case_sensitive=True,
        environ={"DATABASE__HOST": "localhost"},
    )
    config = await ConfigurationBuilder().add(provider).build()
    assert config.require("DATABASE:HOST") == "localhost"


@pytest.mark.asyncio
async def test_provider_returning_non_mapping_raises_merge_error() -> None:
    class ListProvider:
        name = "list"

        async def load(self) -> object:
            return [1, 2, 3]

    builder = ConfigurationBuilder().add(ListProvider())

    with pytest.raises(MergeError):
        await builder.build()  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_section_on_scalar_raises_binding_error() -> None:
    config = await ConfigurationBuilder().add_mapping({"key": "scalar"}).build()
    with pytest.raises(BindingError):
        config.section("key")


@pytest.mark.asyncio
async def test_bind_none_to_required_type_raises() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": None}).build()
    with pytest.raises(BindingError):
        config.bind(str, "v")


@pytest.mark.asyncio
async def test_bind_dataclass_unknown_fields_raises() -> None:
    @dataclass
    class Point:
        x: int
        y: int

    config = await ConfigurationBuilder().add_mapping({"p": {"x": 1, "y": 2, "z": 3}}).build()
    with pytest.raises(BindingError) as caught:
        config.bind(Point, "p")
    assert "unknown" in str(caught.value)


@pytest.mark.asyncio
async def test_bind_dataclass_missing_required_field_raises() -> None:
    @dataclass
    class Point:
        x: int
        y: int

    config = await ConfigurationBuilder().add_mapping({"p": {"x": 1}}).build()
    with pytest.raises(BindingError) as caught:
        config.bind(Point, "p")
    assert "missing" in str(caught.value)


@pytest.mark.asyncio
async def test_bind_sequence_as_tuple() -> None:
    config = await ConfigurationBuilder().add_mapping({"items": [1, 2, 3]}).build()
    assert config.bind(tuple[int], "items") == (1, 2, 3)


@pytest.mark.asyncio
async def test_bind_sequence_as_set() -> None:
    config = await ConfigurationBuilder().add_mapping({"items": [1, 2, 3]}).build()
    assert config.bind(set[int], "items") == {1, 2, 3}


@pytest.mark.asyncio
async def test_bind_sequence_as_frozenset() -> None:
    config = await ConfigurationBuilder().add_mapping({"items": [1, 2, 3]}).build()
    assert config.bind(frozenset[int], "items") == frozenset({1, 2, 3})


@pytest.mark.asyncio
async def test_bind_generic_sequence() -> None:
    config = await ConfigurationBuilder().add_mapping({"items": ["one", "two"]}).build()
    assert config.bind(Sequence[str], "items") == ["one", "two"]


@pytest.mark.asyncio
async def test_bind_list_from_non_sequence_raises() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": "string"}).build()
    with pytest.raises(BindingError):
        config.bind(list[str], "v")


@pytest.mark.asyncio
async def test_bind_dict() -> None:
    config = await ConfigurationBuilder().add_mapping({"counts": {"a": 1, "b": 2}}).build()
    assert config.bind(dict[str, int], "counts") == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_bind_enum_by_name() -> None:
    config = await ConfigurationBuilder().add_mapping({"mode": "PROD"}).build()
    assert config.bind(Mode, "mode") is Mode.PROD


@pytest.mark.asyncio
async def test_bind_enum_invalid_raises() -> None:
    config = await ConfigurationBuilder().add_mapping({"mode": "INVALID"}).build()
    with pytest.raises(BindingError):
        config.bind(Mode, "mode")


@pytest.mark.asyncio
async def test_bind_bool_from_bool_value() -> None:
    config = await ConfigurationBuilder().add_mapping({"flag": True}).build()
    assert config.bind(bool, "flag") is True


@pytest.mark.asyncio
async def test_bind_bool_from_invalid_string_raises() -> None:
    config = await ConfigurationBuilder().add_mapping({"flag": "maybe"}).build()
    with pytest.raises(BindingError):
        config.bind(bool, "flag")


@pytest.mark.asyncio
async def test_bind_str_from_non_string_raises() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": 42}).build()
    with pytest.raises(BindingError):
        config.bind(str, "v")


@pytest.mark.asyncio
async def test_bind_int_from_bool_raises() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": True}).build()
    with pytest.raises(BindingError):
        config.bind(int, "v")


@pytest.mark.asyncio
async def test_bind_float_from_string() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": "3.14"}).build()
    assert config.bind(float, "v") == pytest.approx(3.14)


@pytest.mark.asyncio
async def test_bind_float_from_bool_raises() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": True}).build()
    with pytest.raises(BindingError):
        config.bind(float, "v")


@pytest.mark.asyncio
async def test_bind_unsupported_type_raises() -> None:
    class Custom:
        pass

    config = await ConfigurationBuilder().add_mapping({"v": "value"}).build()
    with pytest.raises(BindingError):
        config.bind(Custom, "v")


@pytest.mark.asyncio
async def test_bind_existing_instance_of_target_type() -> None:
    class Custom:
        pass

    instance = Custom()
    result = ConfigurationBinder().bind(instance, Custom)
    assert result is instance


@pytest.mark.asyncio
async def test_bind_any_target_returns_value_unchanged() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": 42}).build()
    assert config.bind(Any, "v") == 42  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_bind_union_all_options_fail_raises() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": 3.14}).build()
    with pytest.raises(BindingError):
        config.bind(str | int, "v")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_environment_key_conflicts_with_existing_scalar_raises() -> None:
    provider = EnvironmentProvider(
        prefix="APP_",
        environ={"APP_A": "scalar", "APP_A__B": "nested"},
    )
    builder = ConfigurationBuilder().add(provider)

    with pytest.raises(MergeError):
        await builder.build()


@pytest.mark.asyncio
async def test_add_environment_convenience_method() -> None:
    config = (
        await ConfigurationBuilder()
        .add_environment(
            prefix="APP_",
            environ={"APP_HOST": "localhost"},
        )
        .build()
    )
    assert config.require("host") == "localhost"


@pytest.mark.asyncio
async def test_get_with_default_returns_default_when_path_is_missing() -> None:
    config = await ConfigurationBuilder().add_mapping({"existing": 1}).build()
    assert config.get("missing", "fallback") == "fallback"


@pytest.mark.asyncio
async def test_get_without_default_raises_when_path_is_missing() -> None:
    config = await ConfigurationBuilder().add_mapping({}).build()
    with pytest.raises(MissingValueError):
        config.get("missing")


@pytest.mark.asyncio
async def test_get_existing_path_returns_value() -> None:
    config = await ConfigurationBuilder().add_mapping({"key": 42}).build()
    assert config.get("key") == 42


@pytest.mark.asyncio
async def test_require_empty_path_returns_full_mapping() -> None:
    config = await ConfigurationBuilder().add_mapping({"key": 1}).build()
    result = config.require("")
    assert result is config.as_mapping()


@pytest.mark.asyncio
async def test_bind_none_to_none_type_returns_none() -> None:
    result = ConfigurationBinder().bind(None, type(None))
    assert result is None


@pytest.mark.asyncio
async def test_bind_union_none_type_option_is_skipped_for_non_none_value() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": "text"}).build()
    result = config.bind(type(None) | str, "v")  # type: ignore[arg-type]
    assert result == "text"


@pytest.mark.asyncio
async def test_bind_dataclass_from_non_mapping_raises() -> None:
    @dataclass
    class Point:
        x: int

    binder = ConfigurationBinder()

    with pytest.raises(BindingError):
        binder.bind("not-a-mapping", Point)


@pytest.mark.asyncio
async def test_bind_dict_from_non_mapping_raises() -> None:
    binder = ConfigurationBinder()

    with pytest.raises(BindingError):
        binder.bind("not-a-mapping", dict[str, int])


@pytest.mark.asyncio
async def test_bind_bool_false_from_string() -> None:
    config = await ConfigurationBuilder().add_mapping({"flag": "false"}).build()
    assert config.bind(bool, "flag") is False


@pytest.mark.asyncio
async def test_bind_float_from_invalid_string_raises() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": "notanumber"}).build()
    with pytest.raises(BindingError):
        config.bind(float, "v")


@pytest.mark.asyncio
async def test_lookup_path_with_empty_segment_raises_missing_value_error() -> None:
    config = await ConfigurationBuilder().add_mapping({"a": {"b": 1}}).build()
    with pytest.raises(MissingValueError):
        config.require("a::b")


@pytest.mark.asyncio
async def test_merge_with_empty_string_key_raises() -> None:
    class EmptyKeyProvider:
        name = "empty"

        async def load(self) -> dict[str, object]:
            return {"": "value"}

    builder = ConfigurationBuilder().add(EmptyKeyProvider())

    with pytest.raises(MergeError):
        await builder.build()  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_merge_with_nested_empty_string_key_raises() -> None:
    class NestedEmptyKeyProvider:
        name = "nested"

        async def load(self) -> dict[str, object]:
            return {"parent": {"": "value"}}

    builder = ConfigurationBuilder().add(NestedEmptyKeyProvider())

    with pytest.raises(MergeError):
        await builder.build()  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_bind_dict_with_insufficient_type_args_raises() -> None:
    binder = ConfigurationBinder()

    with pytest.raises(BindingError):
        binder.bind({"a": 1}, dict[str])  # type: ignore[type-arg]


@pytest.mark.asyncio
async def test_bind_dataclass_post_init_type_error_raises_binding_error() -> None:
    @dataclass
    class FailsOnInit:
        x: int

        def __post_init__(self) -> None:
            raise TypeError("post init failed")

    config = await ConfigurationBuilder().add_mapping({"p": {"x": 1}}).build()
    with pytest.raises(BindingError) as caught:
        config.bind(FailsOnInit, "p")
    assert "post init failed" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_bind_non_type_annotation_raises_binding_error() -> None:
    config = await ConfigurationBuilder().add_mapping({"v": "a"}).build()
    # Literal is neither a runtime type nor a supported generic origin, so it reaches
    # the binder's unsupported-target fallthrough.
    with pytest.raises(BindingError, match="unsupported target type"):
        config.bind(Literal["a", "b"], "v")  # type: ignore[arg-type]
