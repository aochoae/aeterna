# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

from __future__ import annotations

import asyncio

import pytest
from aeterna.di import (
    ActivationError,
    CaptiveDependencyError,
    CircularDependencyError,
    MissingRegistrationError,
    RegistrationError,
    ScopeClosedError,
    ServiceCancellationError,
    ServiceCollection,
    ServiceDescriptor,
    ServiceLifetime,
)


class Clock:
    pass


class Handler:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock


@pytest.mark.asyncio
async def test_lifetimes_and_explicit_scope() -> None:
    services = ServiceCollection()
    services.add_type(Clock, lifetime=ServiceLifetime.SINGLETON)
    services.add_type(Handler, lifetime=ServiceLifetime.SCOPED)
    provider = services.build_provider()

    with pytest.raises(ScopeClosedError):
        await provider.get(Handler)
    async with provider.create_scope() as first:
        one = await first.get(Handler)
        two = await first.get(Handler)
        assert one is two
    async with provider.create_scope() as second:
        three = await second.get(Handler)
        assert three is not one
        assert three.clock is one.clock
    await provider.close()


@pytest.mark.asyncio
async def test_transient_is_new_each_time() -> None:
    provider = ServiceCollection().add_type(Clock).build_provider()
    assert await provider.get(Clock) is not await provider.get(Clock)
    await provider.close()


@pytest.mark.asyncio
async def test_missing_registration_is_validated_at_build() -> None:
    services = ServiceCollection().add_type(Handler)
    with pytest.raises(MissingRegistrationError) as caught:
        services.build_provider()
    assert caught.value.path == (Handler, Clock)


@pytest.mark.asyncio
async def test_singleton_cannot_capture_scope() -> None:
    services = ServiceCollection()
    services.add_type(Clock, lifetime=ServiceLifetime.SCOPED)
    services.add_type(Handler, lifetime=ServiceLifetime.SINGLETON)
    provider = services.build_provider()
    async with provider.create_scope() as scope:
        with pytest.raises(CaptiveDependencyError):
            await scope.get(Handler)
    await provider.close()


@pytest.mark.asyncio
async def test_factory_cycle_reports_path() -> None:
    class A:
        pass

    class B:
        pass

    async def make_a(resolver: object) -> A:
        await resolver.get(B)  # type: ignore[attr-defined]
        return A()

    async def make_b(resolver: object) -> B:
        await resolver.get(A)  # type: ignore[attr-defined]
        return B()

    provider = ServiceCollection().add_factory(A, make_a).add_factory(B, make_b).build_provider()
    with pytest.raises(CircularDependencyError) as caught:
        await provider.get(A)
    assert caught.value.path == (A, B, A)
    await provider.close()


@pytest.mark.asyncio
async def test_singleton_factory_runs_once_concurrently() -> None:
    calls = 0

    async def create(_: object) -> Clock:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return Clock()

    provider = (
        ServiceCollection()
        .add_factory(Clock, create, lifetime=ServiceLifetime.SINGLETON)
        .build_provider()
    )
    resolved = await asyncio.gather(*(provider.get(Clock) for _ in range(20)))
    assert calls == 1
    assert all(item is resolved[0] for item in resolved)
    await provider.close()


@pytest.mark.asyncio
async def test_owned_resources_close_in_reverse_order() -> None:
    events: list[str] = []

    class Resource:
        def __init__(self, name: str) -> None:
            self.name = name

        async def aclose(self) -> None:
            events.append(self.name)

    class First(Resource):
        pass

    class Second(Resource):
        pass

    services = ServiceCollection()
    services.add_factory(
        First, lambda _: First("first"), lifetime=ServiceLifetime.SINGLETON, owns_instance=True
    )
    services.add_factory(
        Second, lambda _: Second("second"), lifetime=ServiceLifetime.SINGLETON, owns_instance=True
    )
    provider = services.build_provider()
    await provider.get(First)
    await provider.get(Second)
    await provider.close()
    assert events == ["second", "first"]


@pytest.mark.asyncio
async def test_transient_resources_are_not_retained_by_the_root_provider() -> None:
    closed = 0

    class Resource:
        async def aclose(self) -> None:
            nonlocal closed
            closed += 1

    provider = ServiceCollection().add_factory(Resource, lambda _: Resource()).build_provider()
    for _ in range(1000):
        await provider.get(Resource)

    # A tracked transient would append one close callback per resolution and retain
    # every instance until the provider closed.
    assert provider._owned == []
    await provider.close()
    assert closed == 0


@pytest.mark.asyncio
async def test_transient_resources_are_not_retained_by_a_scope() -> None:
    class Resource:
        async def aclose(self) -> None:  # pragma: no cover - must never be called
            raise AssertionError("the container must not close a transient")

    services = ServiceCollection()
    services.add_factory(Resource, lambda _: Resource(), lifetime=ServiceLifetime.TRANSIENT)
    provider = services.build_provider()
    async with provider.create_scope() as scope:
        for _ in range(100):
            await scope.get(Resource)
        assert scope._owned == []
    await provider.close()


def test_transient_ownership_is_rejected_at_build() -> None:
    class Resource:
        async def aclose(self) -> None:  # pragma: no cover - never activated
            pass

    services = ServiceCollection().add_factory(
        Resource,
        lambda _: Resource(),
        lifetime=ServiceLifetime.TRANSIENT,
        owns_instance=True,
    )
    # Silently ignoring the request would be the old leak wearing an explicit flag.
    with pytest.raises(RegistrationError, match="cannot be owned"):
        services.build_provider()


@pytest.mark.asyncio
async def test_unowned_service_with_close_method_is_not_closed() -> None:
    closed = False

    class NotAResource:
        """Exposes close() incidentally; the container must not call it."""

        def close(self) -> None:
            nonlocal closed
            closed = True

    provider = (
        ServiceCollection()
        .add_factory(NotAResource, lambda _: NotAResource(), lifetime=ServiceLifetime.SINGLETON)
        .build_provider()
    )
    await provider.get(NotAResource)
    await provider.close()
    assert not closed


@pytest.mark.asyncio
async def test_unowned_context_manager_is_not_entered() -> None:
    entered = False

    class NotAResource:
        async def __aenter__(self) -> NotAResource:
            nonlocal entered
            entered = True
            return self

        async def __aexit__(self, *_: object) -> None:  # pragma: no cover - never entered
            pass

    provider = (
        ServiceCollection()
        .add_factory(NotAResource, lambda _: NotAResource(), lifetime=ServiceLifetime.SINGLETON)
        .build_provider()
    )
    resolved = await provider.get(NotAResource)
    # Without ownership the container hands back the object it was given, un-entered.
    assert isinstance(resolved, NotAResource)
    assert not entered
    await provider.close()


def test_collection_is_frozen_and_duplicate_registrations_fail() -> None:
    services = ServiceCollection().add_type(Clock)
    services.build_provider()
    with pytest.raises(RegistrationError):
        services.add_type(Clock)

    duplicate = ServiceCollection().add_type(Clock).add_type(Clock)
    with pytest.raises(RegistrationError):
        duplicate.build_provider()


def test_replace_supports_test_composition() -> None:
    replacement = Clock()
    services = ServiceCollection().add_type(Clock)
    services.replace(
        ServiceDescriptor(
            Clock,
            ServiceLifetime.SINGLETON,
            instance=replacement,
            owns_instance=False,
        )
    )
    assert services.build_provider() is not None


@pytest.mark.asyncio
async def test_try_get_returns_none_for_unregistered_service() -> None:
    provider = ServiceCollection().add_type(Clock).build_provider()
    result = await provider.try_get(Handler)
    assert result is None
    await provider.close()


@pytest.mark.asyncio
async def test_try_get_returns_service_when_registered() -> None:
    provider = ServiceCollection().add_type(Clock).build_provider()
    result = await provider.try_get(Clock)
    assert isinstance(result, Clock)
    await provider.close()


@pytest.mark.asyncio
async def test_add_async_factory_registers_awaitable_factory() -> None:
    async def create_clock(_: object) -> Clock:
        return Clock()

    provider = ServiceCollection().add_async_factory(Clock, create_clock).build_provider()
    result = await provider.get(Clock)
    assert isinstance(result, Clock)
    await provider.close()


@pytest.mark.asyncio
async def test_service_provider_as_async_context_manager() -> None:
    services = ServiceCollection().add_type(Clock)
    async with services.build_provider() as provider:
        clock = await provider.get(Clock)
    assert isinstance(clock, Clock)


@pytest.mark.asyncio
async def test_service_scope_as_async_context_manager() -> None:
    services = ServiceCollection()
    services.add_type(Clock, lifetime=ServiceLifetime.SCOPED)
    provider = services.build_provider()
    async with provider.create_scope() as scope:
        clock = await scope.get(Clock)
    assert isinstance(clock, Clock)
    await provider.close()


@pytest.mark.asyncio
async def test_closed_scope_raises_scope_closed_error() -> None:
    services = ServiceCollection()
    services.add_type(Clock, lifetime=ServiceLifetime.SCOPED)
    provider = services.build_provider()
    scope = provider.create_scope()
    await scope.close()
    with pytest.raises(ScopeClosedError):
        await scope.get(Clock)
    await provider.close()


@pytest.mark.asyncio
async def test_scope_close_is_idempotent() -> None:
    services = ServiceCollection()
    services.add_type(Clock, lifetime=ServiceLifetime.SCOPED)
    provider = services.build_provider()
    scope = provider.create_scope()
    await scope.close()
    await scope.close()
    await provider.close()


@pytest.mark.asyncio
async def test_closed_provider_raises_scope_closed_error() -> None:
    provider = ServiceCollection().add_type(Clock).build_provider()
    await provider.close()
    with pytest.raises(ScopeClosedError):
        await provider.get(Clock)


@pytest.mark.asyncio
async def test_create_scope_on_closed_provider_raises() -> None:
    provider = ServiceCollection().add_type(Clock).build_provider()
    await provider.close()
    with pytest.raises(ScopeClosedError):
        provider.create_scope()


@pytest.mark.asyncio
async def test_activation_error_wraps_factory_exception() -> None:
    def failing_factory(_: object) -> Clock:
        raise ValueError("factory failed")

    provider = ServiceCollection().add_factory(Clock, failing_factory).build_provider()
    with pytest.raises(ActivationError) as caught:
        await provider.get(Clock)
    assert caught.value.key is Clock
    assert isinstance(caught.value.__cause__, ValueError)
    await provider.close()


@pytest.mark.asyncio
async def test_scoped_service_owns_resource_in_scope() -> None:
    events: list[str] = []

    class Resource:
        async def aclose(self) -> None:
            events.append("closed")

    services = ServiceCollection()
    services.add_factory(
        Resource, lambda _: Resource(), lifetime=ServiceLifetime.SCOPED, owns_instance=True
    )
    provider = services.build_provider()
    async with provider.create_scope() as scope:
        await scope.get(Resource)
    assert events == ["closed"]
    await provider.close()


@pytest.mark.asyncio
async def test_provider_close_is_idempotent() -> None:
    provider = ServiceCollection().add_type(Clock).build_provider()
    await provider.close()
    await provider.close()


@pytest.mark.asyncio
async def test_get_unregistered_service_raises_at_resolution_time() -> None:
    provider = ServiceCollection().add_type(Clock).build_provider()
    with pytest.raises(MissingRegistrationError):
        await provider.get(Handler)
    await provider.close()


def test_constructor_with_parameter_default_and_no_annotation_is_skipped() -> None:
    class WithDefault:
        # y has a default but no annotation.
        def __init__(self, clock: Clock, y=42) -> None:  # noqa: ANN001
            pass

    services = ServiceCollection()
    services.add_type(Clock)
    services.add_type(WithDefault, lifetime=ServiceLifetime.TRANSIENT)
    assert services.build_provider() is not None


def test_unannotated_required_parameter_raises_registration_error() -> None:
    class MissingAnnotation:
        def __init__(self, x) -> None:  # type: ignore[no-untyped-def]  # noqa: ANN001
            pass

    services = ServiceCollection()

    with pytest.raises(RegistrationError):
        services.add_type(MissingAnnotation)


def test_unsupported_generic_annotation_raises_registration_error() -> None:
    class GenericParam:
        def __init__(self, items: list[int]) -> None:
            pass

    services = ServiceCollection()

    with pytest.raises(RegistrationError):
        services.add_type(GenericParam)


def test_uninspectable_constructor_raises_registration_error() -> None:
    class ForwardRefClass:
        def __init__(self, x: NonExistentType) -> None:  # type: ignore[name-defined]  # noqa: F821
            pass

    services = ServiceCollection()

    with pytest.raises(RegistrationError):
        services.add_type(ForwardRefClass)


@pytest.mark.asyncio
async def test_owned_async_context_manager_is_entered_and_exited() -> None:
    entered = False
    exited = False

    class AsyncCtx:
        async def __aenter__(self) -> AsyncCtx:
            nonlocal entered
            entered = True
            return self

        async def __aexit__(self, *_: object) -> None:
            nonlocal exited
            exited = True

    provider = (
        ServiceCollection()
        .add_factory(
            AsyncCtx, lambda _: AsyncCtx(), lifetime=ServiceLifetime.SINGLETON, owns_instance=True
        )
        .build_provider()
    )
    await provider.get(AsyncCtx)
    await provider.close()
    assert entered
    assert exited


@pytest.mark.asyncio
async def test_owned_sync_context_manager_is_entered_and_exited() -> None:
    entered = False
    exited = False

    class SyncCtx:
        def __enter__(self) -> SyncCtx:
            nonlocal entered
            entered = True
            return self

        def __exit__(self, *_: object) -> None:
            nonlocal exited
            exited = True

    provider = (
        ServiceCollection()
        .add_factory(
            SyncCtx, lambda _: SyncCtx(), lifetime=ServiceLifetime.SINGLETON, owns_instance=True
        )
        .build_provider()
    )
    await provider.get(SyncCtx)
    await provider.close()
    assert entered
    assert exited


@pytest.mark.asyncio
async def test_owned_sync_close_method_is_called() -> None:
    closed = False

    class SyncClose:
        def close(self) -> None:
            nonlocal closed
            closed = True

    provider = (
        ServiceCollection()
        .add_factory(
            SyncClose, lambda _: SyncClose(), lifetime=ServiceLifetime.SINGLETON, owns_instance=True
        )
        .build_provider()
    )
    await provider.get(SyncClose)
    await provider.close()
    assert closed


@pytest.mark.asyncio
async def test_owned_async_close_method_is_called() -> None:
    closed = False

    class AsyncClose:
        async def close(self) -> None:
            nonlocal closed
            closed = True

    provider = (
        ServiceCollection()
        .add_factory(
            AsyncClose,
            lambda _: AsyncClose(),
            lifetime=ServiceLifetime.SINGLETON,
            owns_instance=True,
        )
        .build_provider()
    )
    await provider.get(AsyncClose)
    await provider.close()
    assert closed


@pytest.mark.asyncio
async def test_concurrent_cross_task_singleton_cycle_raises_rather_than_deadlocks() -> None:
    class First:
        pass

    class Second:
        pass

    started = asyncio.Event()

    async def make_first(resolver: object) -> First:
        started.set()
        await asyncio.sleep(0.01)
        await resolver.get(Second)  # type: ignore[attr-defined]
        return First()

    async def make_second(resolver: object) -> Second:
        await started.wait()
        await asyncio.sleep(0.01)
        await resolver.get(First)  # type: ignore[attr-defined]
        return Second()

    provider = (
        ServiceCollection()
        .add_factory(First, make_first, lifetime=ServiceLifetime.SINGLETON)
        .add_factory(Second, make_second, lifetime=ServiceLifetime.SINGLETON)
        .build_provider()
    )

    # Each task holds one singleton lock while awaiting the other's. The per-resolution
    # path check cannot see across tasks, so without the wait-for graph this hangs
    # forever; wait_for makes a regression fail as a timeout instead of stalling the run.
    results = await asyncio.wait_for(
        asyncio.gather(provider.get(First), provider.get(Second), return_exceptions=True),
        timeout=5.0,
    )
    assert all(isinstance(item, CircularDependencyError) for item in results)
    await provider.close()


def test_factory_declared_dependencies_are_validated_at_build() -> None:
    class Missing:
        pass

    class Needs:
        pass

    services = ServiceCollection().add_factory(Needs, lambda _: Needs(), dependencies=(Missing,))
    with pytest.raises(MissingRegistrationError) as caught:
        services.build_provider()
    assert caught.value.path == (Needs, Missing)


@pytest.mark.asyncio
async def test_factory_without_declared_dependencies_still_resolves() -> None:
    class Needs:
        pass

    async def make(resolver: object) -> Needs:
        await resolver.get(Clock)  # type: ignore[attr-defined]
        return Needs()

    provider = ServiceCollection().add_type(Clock).add_factory(Needs, make).build_provider()
    assert isinstance(await provider.get(Needs), Needs)
    await provider.close()


@pytest.mark.asyncio
async def test_factory_declared_dependencies_are_not_passed_as_arguments() -> None:
    resolved: list[type] = []

    class Needs:
        pass

    async def make(resolver: object) -> Needs:
        resolved.append(Clock)
        await resolver.get(Clock)  # type: ignore[attr-defined]
        return Needs()

    provider = (
        ServiceCollection()
        .add_type(Clock)
        .add_factory(Needs, make, dependencies=(Clock,))
        .build_provider()
    )
    # Declaring dependencies buys build-time validation only; the factory still
    # resolves them itself through the resolver it is handed.
    assert isinstance(await provider.get(Needs), Needs)
    assert resolved == [Clock]
    await provider.close()


@pytest.mark.asyncio
async def test_provider_close_waits_for_in_flight_owned_activation() -> None:
    activation_started = asyncio.Event()
    activation_release = asyncio.Event()
    closed = asyncio.Event()

    class Resource:
        async def aclose(self) -> None:
            closed.set()

    async def create(_: object) -> Resource:
        activation_started.set()
        await activation_release.wait()
        return Resource()

    provider = (
        ServiceCollection()
        .add_factory(
            Resource,
            create,
            lifetime=ServiceLifetime.SINGLETON,
            owns_instance=True,
        )
        .build_provider()
    )

    resolving = asyncio.create_task(provider.get(Resource))
    await activation_started.wait()
    closing = asyncio.create_task(provider.close())
    await asyncio.sleep(0)
    assert not closing.done()

    activation_release.set()
    assert isinstance(await resolving, Resource)
    await closing

    assert closed.is_set()
    assert provider._singletons == {}
    assert provider._owned == []


@pytest.mark.asyncio
async def test_provider_close_completes_before_reporting_caller_cancellation() -> None:
    close_started = asyncio.Event()
    close_release = asyncio.Event()

    class Resource:
        async def aclose(self) -> None:
            close_started.set()
            await close_release.wait()

    provider = (
        ServiceCollection()
        .add_factory(
            Resource,
            lambda _: Resource(),
            lifetime=ServiceLifetime.SINGLETON,
            owns_instance=True,
        )
        .build_provider()
    )
    await provider.get(Resource)

    closing = asyncio.create_task(provider.close())
    await close_started.wait()
    closing.cancel()
    close_release.set()

    with pytest.raises(asyncio.CancelledError):
        await closing
    assert provider._closed
    assert provider._singletons == {}


@pytest.mark.asyncio
async def test_resource_cancellation_becomes_framework_cleanup_error() -> None:
    class Resource:
        async def aclose(self) -> None:
            raise asyncio.CancelledError

    provider = (
        ServiceCollection()
        .add_factory(
            Resource,
            lambda _: Resource(),
            lifetime=ServiceLifetime.SINGLETON,
            owns_instance=True,
        )
        .build_provider()
    )
    await provider.get(Resource)

    with pytest.raises(ExceptionGroup) as caught:
        await provider.close()
    assert isinstance(caught.value.exceptions[0], ServiceCancellationError)


@pytest.mark.asyncio
async def test_scope_close_waits_for_in_flight_activation_and_releases_cache() -> None:
    activation_started = asyncio.Event()
    activation_release = asyncio.Event()
    closed = asyncio.Event()

    class Resource:
        async def aclose(self) -> None:
            closed.set()

    async def create(_: object) -> Resource:
        activation_started.set()
        await activation_release.wait()
        return Resource()

    provider = (
        ServiceCollection()
        .add_factory(
            Resource,
            create,
            lifetime=ServiceLifetime.SCOPED,
            owns_instance=True,
        )
        .build_provider()
    )
    scope = provider.create_scope()
    resolving = asyncio.create_task(scope.get(Resource))
    await activation_started.wait()
    closing = asyncio.create_task(scope.close())
    await asyncio.sleep(0)
    assert not closing.done()

    activation_release.set()
    assert isinstance(await resolving, Resource)
    await closing

    assert closed.is_set()
    assert scope._scoped == {}
    assert scope._owned == []
    await provider.close()
