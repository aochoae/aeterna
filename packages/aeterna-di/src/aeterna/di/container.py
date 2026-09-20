# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Explicit, annotation-driven dependency injection."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol, TypeVar, get_type_hints

from .errors import (
    ActivationError,
    AmbiguousRegistrationError,
    CaptiveDependencyError,
    CircularDependencyError,
    MissingRegistrationError,
    RegistrationError,
    ScopeClosedError,
    ServiceCancellationError,
)

T = TypeVar("T")
Factory = Callable[["ServiceResolver"], object | Awaitable[object]]
_MISSING = object()


class ServiceLifetime(Enum):
    """Lifetime policy used when resolving a registered service."""

    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


class ServiceResolver(Protocol):
    """Protocol for resolving services from a provider or scope."""

    async def get(self, key: type[T]) -> T:
        """Resolve a required registered service.

        :param key: Service type used as the registration key.
        :return: The converted or resolved value.
        :rtype: T
        """
        ...

    async def try_get(self, key: type[T]) -> T | None:
        """Resolve an optional registered service.

        :param key: Service type used as the registration key.
        :return: The result, or `None` when unavailable.
        :rtype: T | None
        """
        ...


@dataclass(frozen=True, slots=True)
class ServiceDescriptor:
    """Immutable description of how one service is activated and owned.

    :param key: Type clients use to resolve the service.
    :param lifetime: Reuse policy for activated instances.
    :param implementation: Optional concrete type activated from constructor dependencies.
    :param factory: Optional sync or async callable used to activate the service.
    :param instance: Optional already-created singleton instance.
    :param owns_instance: Whether the provider or scope closes the activated value. Ownership
        is opt-in: a service is closed only when this is requested explicitly.
    :param dependencies: Constructor service types required by ``implementation``.
    """

    key: type[object]
    lifetime: ServiceLifetime
    implementation: type[object] | None = None
    factory: Factory | None = None
    instance: object = _MISSING
    owns_instance: bool = False
    dependencies: tuple[type[object], ...] = ()


@dataclass(frozen=True, slots=True)
class _ResolutionContext:
    path: tuple[type[object], ...] = ()
    singleton_graph: bool = False

    def enter(self, key: type[object], lifetime: ServiceLifetime) -> _ResolutionContext:
        """Extend the resolution path and retain singleton-graph state.

        :param key: Service type about to be resolved.
        :param lifetime: Lifetime associated with ``key``.
        :return: The resulting state or resolution context.
        :rtype: _ResolutionContext
        """
        if key in self.path:
            index = self.path.index(key)
            raise CircularDependencyError((*self.path[index:], key))
        return _ResolutionContext(
            (*self.path, key), self.singleton_graph or lifetime is ServiceLifetime.SINGLETON
        )


class ServiceCollection:
    """Mutable registration builder that produces an immutable provider."""

    def __init__(self) -> None:
        """Create an empty registration collection."""
        self._descriptors: list[ServiceDescriptor] = []
        self._built = False

    def add_instance(
        self, key: type[T], instance: T, *, owns_instance: bool = False
    ) -> ServiceCollection:
        """Register an existing instance as a singleton.

        :param key: Type clients use to resolve ``instance``.
        :param instance: Already-created object to return for every resolution.
        :param owns_instance: Whether the provider should close the instance when it closes.
        :return: This service collection.
        :rtype: ServiceCollection
        """
        return self._add(
            ServiceDescriptor(
                key, ServiceLifetime.SINGLETON, instance=instance, owns_instance=owns_instance
            )
        )

    def add_type(
        self,
        key: type[T],
        implementation: type[T] | None = None,
        *,
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT,
        owns_instance: bool = False,
    ) -> ServiceCollection:
        """Register a class activated from its constructor dependencies.

        :param key: Type clients use to resolve the registered service.
        :param implementation: Concrete class to construct; defaults to ``key``.
        :param lifetime: Reuse policy for constructed instances.
        :param owns_instance: Whether the provider or scope closes the constructed service.
        :return: This service collection.
        :rtype: ServiceCollection
        """
        implementation = implementation or key
        dependencies = _constructor_dependencies(implementation)
        return self._add(
            ServiceDescriptor(
                key,
                lifetime,
                implementation=implementation,
                owns_instance=owns_instance,
                dependencies=dependencies,
            )
        )

    def add_factory(
        self,
        key: type[T],
        factory: Callable[[ServiceResolver], T | Awaitable[T]],
        *,
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT,
        owns_instance: bool = False,
        dependencies: Sequence[type[object]] = (),
    ) -> ServiceCollection:
        """Register a synchronous or asynchronous factory.

        A factory resolves its own dependencies, so the collection cannot infer them the
        way it inspects a constructor. Declaring them through ``dependencies`` opts the
        registration into the same build-time validation that constructor graphs receive;
        omitting them defers every failure to the first resolution.

        :param key: Type clients use to resolve the factory result.
        :param factory: Callable that receives a resolver and returns or awaits the service.
        :param lifetime: Reuse policy for factory results.
        :param owns_instance: Whether the provider or scope closes the factory result.
        :param dependencies: Service types the factory resolves, validated at build time.
        :return: This service collection.
        :rtype: ServiceCollection
        """
        return self._add(
            ServiceDescriptor(
                key,
                lifetime,
                factory=factory,
                owns_instance=owns_instance,
                dependencies=tuple(dependencies),
            )
        )

    def add_async_factory(
        self,
        key: type[T],
        factory: Callable[[ServiceResolver], Awaitable[T]],
        *,
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT,
        owns_instance: bool = False,
        dependencies: Sequence[type[object]] = (),
    ) -> ServiceCollection:
        """Register an asynchronous factory.

        :param key: Type clients use to resolve the factory result.
        :param factory: Awaitable factory that receives a service resolver.
        :param lifetime: Reuse policy for factory results.
        :param owns_instance: Whether the provider or scope closes the factory result.
        :param dependencies: Service types the factory resolves, validated at build time.
        :return: This service collection.
        :rtype: ServiceCollection
        """
        return self.add_factory(
            key,
            factory,
            lifetime=lifetime,
            owns_instance=owns_instance,
            dependencies=dependencies,
        )

    def replace(self, descriptor: ServiceDescriptor) -> ServiceCollection:
        """Replace the registration for a service key.

        :param descriptor: New descriptor whose key identifies the registration to replace.
        :return: This service collection.
        :rtype: ServiceCollection
        """
        self._ensure_mutable()
        self._descriptors = [item for item in self._descriptors if item.key is not descriptor.key]
        self._descriptors.append(descriptor)
        return self

    def build_provider(self) -> ServiceProvider:
        """Validate registrations and create an immutable service provider.

        :return: The service provider.
        :rtype: ServiceProvider
        """
        self._ensure_mutable()
        descriptors: dict[type[object], ServiceDescriptor] = {}
        for descriptor in self._descriptors:
            if descriptor.key in descriptors:
                raise AmbiguousRegistrationError(descriptor.key)
            descriptors[descriptor.key] = descriptor
        for descriptor in descriptors.values():
            if descriptor.owns_instance and descriptor.lifetime is ServiceLifetime.TRANSIENT:
                # Honouring this would mean retaining every instance ever resolved, since
                # nothing tells the container when a caller has finished with a transient.
                raise RegistrationError(
                    f"Transient service {descriptor.key!r} cannot be owned by the container; "
                    "register it as scoped or close it in the caller"
                )
            for dependency in descriptor.dependencies:
                if dependency not in descriptors:
                    raise MissingRegistrationError(dependency, (descriptor.key, dependency))
        self._built = True
        return ServiceProvider(descriptors)

    def _add(self, descriptor: ServiceDescriptor) -> ServiceCollection:
        """Append a descriptor while the collection remains mutable.

        :param descriptor: Service registration to append.
        :return: This service collection.
        :rtype: ServiceCollection
        """
        self._ensure_mutable()
        self._descriptors.append(descriptor)
        return self

    def _ensure_mutable(self) -> None:
        """Raise when registration changes are attempted after provider construction.

        :return: None.
        :rtype: None
        """
        if self._built:
            raise RegistrationError("ServiceCollection is immutable after build_provider()")


class _ResolverBase:
    def __init__(self, root: ServiceProvider, scope: ServiceScope | None) -> None:
        """Initialize a resolver associated with a provider and optional scope.

        :param root: Root provider that owns registrations and singleton services.
        :param scope: Scope that owns scoped services, if resolution is scoped.
        """
        self._root = root
        self._scope = scope

    async def get(self, key: type[T]) -> T:
        """Resolve a required service by type.

        :param key: Type used as the service registration key.
        :return: The converted or resolved value.
        :rtype: T
        """
        self._root._begin_resolution()
        scope_started = False
        try:
            if self._scope is not None:
                self._scope._begin_resolution()
                scope_started = True
            return await self._root._resolve(  # type: ignore[return-value]
                key, self._scope, _ResolutionContext()
            )
        finally:
            if scope_started:
                self._scope._end_resolution()  # type: ignore[union-attr]
            self._root._end_resolution()

    async def try_get(self, key: type[T]) -> T | None:
        """Resolve a service or return ``None`` when it is not registered.

        :param key: Type used as the service registration key.
        :return: The result, or `None` when unavailable.
        :rtype: T | None
        """
        if key not in self._root._descriptors:
            return None
        return await self.get(key)


class ServiceProvider(_ResolverBase):
    """Immutable root provider and singleton ownership boundary."""

    def __init__(self, descriptors: dict[type[object], ServiceDescriptor]) -> None:
        """Create a provider from validated service descriptors.

        :param descriptors: Mapping of registration keys to immutable descriptors.
        """
        self._descriptors = MappingProxyType(dict(descriptors))
        self._singletons: dict[type[object], object] = {}
        self._locks: dict[type[object], asyncio.Lock] = {}
        self._owned: list[Callable[[], Awaitable[None] | None]] = []
        self._close_lock = asyncio.Lock()
        self._closing = False
        self._closed = False
        self._active_resolutions = 0
        self._resolution_tasks: dict[asyncio.Task[Any], int] = {}
        self._resolutions_drained = asyncio.Event()
        self._resolutions_drained.set()
        # Wait-for graph for singleton activation, used to turn what would otherwise be a
        # silent cross-task deadlock into CircularDependencyError. `_activating` maps a
        # key to the task building it; `_waiting` maps a task to the key it is blocked on.
        self._activating: dict[type[object], asyncio.Task[Any]] = {}
        self._waiting: dict[asyncio.Task[Any], type[object]] = {}
        super().__init__(self, None)

    def create_scope(self) -> ServiceScope:
        """Create an explicit scope for scoped services.

        :return: The new service scope.
        :rtype: ServiceScope
        """
        self._ensure_open()
        return ServiceScope(self)

    async def close(self) -> None:
        """Close owned singleton resources in reverse acquisition order.

        :return: None.
        :rtype: None
        """
        if self._is_resolving_in_current_task():
            raise ScopeClosedError("ServiceProvider cannot close during service resolution")
        cancelled = await _finish_uninterrupted(self._close_core())
        if cancelled:
            raise asyncio.CancelledError

    async def _close_core(self) -> None:
        """Wait for active resolutions and close the provider exactly once."""
        if self._closed:
            return
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            await self._resolutions_drained.wait()
            try:
                await _close_all(self._owned)
            finally:
                self._owned.clear()
                self._singletons.clear()
                self._locks.clear()
                self._activating.clear()
                self._waiting.clear()
                self._closed = True
                self._closing = False

    async def __aenter__(self) -> ServiceProvider:
        """Return this open provider for asynchronous context management.

        :return: The service provider.
        :rtype: ServiceProvider
        """
        self._ensure_open()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Close the provider when leaving an asynchronous context.

        :param _: Exception details supplied by the asynchronous context protocol and ignored here.
        :return: None.
        :rtype: None
        """
        await self.close()

    async def _resolve(
        self, key: type[object], scope: ServiceScope | None, context: _ResolutionContext
    ) -> object:
        """Resolve one service according to its descriptor and lifetime.

        :param key: Registration key to resolve.
        :param scope: Active scope for scoped or transient resolution, if any.
        :param context: Dependency path and singleton-graph state for this resolution.
        :return: The resulting value.
        :rtype: object
        """
        descriptor = self._descriptors.get(key)
        if descriptor is None:
            raise MissingRegistrationError(key, (*context.path, key))
        entered = context.enter(key, descriptor.lifetime)
        if descriptor.lifetime is ServiceLifetime.SCOPED:
            if entered.singleton_graph:
                raise CaptiveDependencyError(key, entered.path)
            if scope is None:
                raise ScopeClosedError(f"Scoped service {key!r} requires an explicit ServiceScope")
            return await scope._resolve_scoped(descriptor, entered)
        if descriptor.lifetime is ServiceLifetime.SINGLETON:
            return await self._resolve_singleton(key, descriptor, entered)
        return await self._activate(descriptor, scope, entered)

    async def _resolve_singleton(
        self, key: type[object], descriptor: ServiceDescriptor, context: _ResolutionContext
    ) -> object:
        """Resolve a singleton, activating it at most once across concurrent callers.

        :param key: Registration key to resolve.
        :param descriptor: Registration describing how to activate the singleton.
        :param context: Dependency path and singleton-graph state for this resolution.
        :return: The resulting value.
        :rtype: object
        """
        if key in self._singletons:
            return self._singletons[key]
        task = asyncio.current_task()
        if task is not None:
            cycle = self._cross_task_cycle(key, task)
            if cycle is not None:
                raise CircularDependencyError(cycle)
        lock = self._locks.setdefault(key, asyncio.Lock())
        if task is not None:
            self._waiting[task] = key
        try:
            await lock.acquire()
        finally:
            if task is not None:
                self._waiting.pop(task, None)
        try:
            if key not in self._singletons:
                if task is not None:
                    self._activating[key] = task
                try:
                    self._singletons[key] = await self._activate(descriptor, None, context)
                finally:
                    self._activating.pop(key, None)
            return self._singletons[key]
        finally:
            lock.release()

    def _cross_task_cycle(
        self, key: type[object], task: asyncio.Task[Any]
    ) -> tuple[type[object], ...] | None:
        """Return the cycle that would deadlock if ``task`` blocked on ``key``.

        Cycle detection in :class:`_ResolutionContext` only sees one resolution path, so a
        cycle spread across two concurrent tasks escapes it. Each task would hold one
        singleton lock while awaiting the other's, and both would wait forever. Walking
        the wait-for graph first converts that hang into a diagnosable error.

        :param key: Singleton key the caller is about to block on.
        :param task: Task that would block.
        :return: The cycle of service keys, or ``None`` when blocking is safe.
        :rtype: tuple[type[object], ...] | None
        """
        chain: list[type[object]] = [key]
        current = key
        while True:
            owner = self._activating.get(current)
            if owner is None:
                return None
            if owner is task:
                return (*chain, key)
            blocked_on = self._waiting.get(owner)
            if blocked_on is None or blocked_on in chain:
                return None
            chain.append(blocked_on)
            current = blocked_on

    async def _activate(
        self,
        descriptor: ServiceDescriptor,
        scope: ServiceScope | None,
        context: _ResolutionContext,
    ) -> object:
        """Activate a descriptor and track an owned result when required.

        :param descriptor: Registration that specifies how to create the service.
        :param scope: Active scope that should own a scoped result, if any.
        :param context: Dependency path passed to factories and nested resolutions.
        :return: The resulting value.
        :rtype: object
        """
        resolver = _ContextResolver(self, scope, context)
        try:
            if descriptor.instance is not _MISSING:
                value = descriptor.instance
            elif descriptor.implementation is not None:
                arguments = [await resolver.get(item) for item in descriptor.dependencies]
                value = descriptor.implementation(*arguments)
            elif descriptor.factory is not None:
                value = descriptor.factory(resolver)
                if inspect.isawaitable(value):
                    value = await value
            else:  # pragma: no cover - descriptors are constructed by the public builder
                raise RegistrationError(f"Registration for {descriptor.key!r} has no activator")
            owner = self._ownership_boundary(descriptor, scope)
            if owner is not None:
                value = await _enter_and_track(value, owner._owned)
            return value
        except (MissingRegistrationError, CircularDependencyError, CaptiveDependencyError):
            raise
        except Exception as error:
            raise ActivationError(descriptor.key, context.path, error) from error

    def _ownership_boundary(
        self, descriptor: ServiceDescriptor, scope: ServiceScope | None
    ) -> ServiceProvider | ServiceScope | None:
        """Return the boundary responsible for closing an activated service.

        Transient services are never owned. A container cannot know when a caller has
        finished with a transient, so tracking one would retain every instance ever
        resolved for the lifetime of its boundary. Callers close transients themselves,
        or register the service as scoped when a boundary should close it for them.

        :param descriptor: Registration describing the activated service.
        :param scope: Active scope for this resolution, if any.
        :return: The owning boundary, or ``None`` when the caller retains ownership.
        :rtype: ServiceProvider | ServiceScope | None
        """
        if not descriptor.owns_instance:
            return None
        if descriptor.lifetime is ServiceLifetime.TRANSIENT:  # pragma: no cover
            # build_provider() rejects this combination, so it is unreachable through the
            # public API. Kept as the enforcement point: this is what actually prevents the
            # unbounded retention, and the build-time check exists to give a better error.
            return None
        if descriptor.lifetime is ServiceLifetime.SINGLETON:
            return self
        return scope

    def _ensure_open(self) -> None:
        """Raise when resolution is attempted after provider shutdown.

        :return: None.
        :rtype: None
        """
        if self._closing or self._closed:
            state = "closing" if self._closing else "closed"
            raise ScopeClosedError(f"ServiceProvider is {state}")

    def _begin_resolution(self) -> None:
        """Register a public resolution before activation begins."""
        self._ensure_open()
        self._active_resolutions += 1
        self._resolutions_drained.clear()
        task = asyncio.current_task()
        if task is not None:
            self._resolution_tasks[task] = self._resolution_tasks.get(task, 0) + 1

    def _end_resolution(self) -> None:
        """Release a public resolution slot and wake a waiting close operation."""
        task = asyncio.current_task()
        if task is not None:
            remaining = self._resolution_tasks.get(task, 0) - 1
            if remaining > 0:
                self._resolution_tasks[task] = remaining
            else:
                self._resolution_tasks.pop(task, None)
        self._active_resolutions -= 1
        if self._active_resolutions == 0:
            self._resolutions_drained.set()

    def _is_resolving_in_current_task(self) -> bool:
        """Return whether the current task owns an active public resolution."""
        task = asyncio.current_task()
        return task is not None and task in self._resolution_tasks


class ServiceScope(_ResolverBase):
    """Explicit scoped-service and resource ownership boundary."""

    def __init__(self, root: ServiceProvider) -> None:
        """Create a scope owned by a root provider.

        :param root: Provider that supplies registrations and singleton services.
        """
        self._scoped: dict[type[object], object] = {}
        self._locks: dict[type[object], asyncio.Lock] = {}
        self._owned: list[Callable[[], Awaitable[None] | None]] = []
        self._close_lock = asyncio.Lock()
        self._closing = False
        self._closed = False
        self._active_resolutions = 0
        self._resolution_tasks: dict[asyncio.Task[Any], int] = {}
        self._resolutions_drained = asyncio.Event()
        self._resolutions_drained.set()
        super().__init__(root, self)

    async def _resolve_scoped(
        self, descriptor: ServiceDescriptor, context: _ResolutionContext
    ) -> object:
        """Resolve or create a scoped service within this scope.

        :param descriptor: Scoped registration to resolve.
        :param context: Dependency path and singleton-graph state for the resolution.
        :return: The resulting value.
        :rtype: object
        """
        self._ensure_open()
        if descriptor.key in self._scoped:
            return self._scoped[descriptor.key]
        lock = self._locks.setdefault(descriptor.key, asyncio.Lock())
        async with lock:
            if descriptor.key not in self._scoped:
                self._scoped[descriptor.key] = await self._root._activate(descriptor, self, context)
            return self._scoped[descriptor.key]

    async def close(self) -> None:
        """Close owned scoped resources in reverse acquisition order.

        :return: None.
        :rtype: None
        """
        if self._is_resolving_in_current_task():
            raise ScopeClosedError("ServiceScope cannot close during service resolution")
        cancelled = await _finish_uninterrupted(self._close_core())
        if cancelled:
            raise asyncio.CancelledError

    async def _close_core(self) -> None:
        """Wait for active resolutions and close the scope exactly once."""
        if self._closed:
            return
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            await self._resolutions_drained.wait()
            try:
                await _close_all(self._owned)
            finally:
                self._owned.clear()
                self._scoped.clear()
                self._locks.clear()
                self._closed = True
                self._closing = False

    async def __aenter__(self) -> ServiceScope:
        """Return this open scope for asynchronous context management.

        :return: The new service scope.
        :rtype: ServiceScope
        """
        self._ensure_open()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Close the scope when leaving an asynchronous context.

        :param _: Exception details supplied by the asynchronous context protocol and ignored here.
        :return: None.
        :rtype: None
        """
        await self.close()

    def _ensure_open(self) -> None:
        """Raise when resolution is attempted after scope shutdown.

        :return: None.
        :rtype: None
        """
        if self._closing or self._closed:
            state = "closing" if self._closing else "closed"
            raise ScopeClosedError(f"ServiceScope is {state}")

    def _begin_resolution(self) -> None:
        """Register a public resolution before scoped activation begins."""
        self._ensure_open()
        self._active_resolutions += 1
        self._resolutions_drained.clear()
        task = asyncio.current_task()
        if task is not None:
            self._resolution_tasks[task] = self._resolution_tasks.get(task, 0) + 1

    def _end_resolution(self) -> None:
        """Release a public resolution slot and wake a waiting close operation."""
        task = asyncio.current_task()
        if task is not None:
            remaining = self._resolution_tasks.get(task, 0) - 1
            if remaining > 0:
                self._resolution_tasks[task] = remaining
            else:
                self._resolution_tasks.pop(task, None)
        self._active_resolutions -= 1
        if self._active_resolutions == 0:
            self._resolutions_drained.set()

    def _is_resolving_in_current_task(self) -> bool:
        """Return whether the current task owns an active public resolution."""
        task = asyncio.current_task()
        return task is not None and task in self._resolution_tasks


class _ContextResolver(_ResolverBase):
    def __init__(
        self, root: ServiceProvider, scope: ServiceScope | None, context: _ResolutionContext
    ) -> None:
        """Create a resolver that preserves an in-progress dependency path.

        :param root: Root provider that owns the registrations.
        :param scope: Active scope for this resolution, if any.
        :param context: Resolution context to preserve for nested dependencies.
        """
        super().__init__(root, scope)
        self._context = context

    async def get(self, key: type[T]) -> T:
        """Resolve a dependency while preserving the current resolution context.

        :param key: Type used as the dependency registration key.
        :return: The converted or resolved value.
        :rtype: T
        """
        return await self._root._resolve(key, self._scope, self._context)  # type: ignore[return-value]


def _constructor_dependencies(implementation: type[object]) -> tuple[type[object], ...]:
    """Inspect required constructor parameters for resolvable service types.

    :param implementation: Concrete class whose constructor dependencies are inspected.
    :return: The constructor dependency types.
    :rtype: tuple[type[object], ...]
    """
    try:
        signature = inspect.signature(implementation.__init__)
        hints = get_type_hints(implementation.__init__)
    except (TypeError, NameError) as error:
        raise RegistrationError(f"Cannot inspect {implementation!r}: {error}") from error
    dependencies: list[type[object]] = []
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "cls"}:
            continue
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            continue
        annotation = hints.get(parameter.name, parameter.annotation)
        if annotation is inspect.Parameter.empty:
            if parameter.default is not inspect.Parameter.empty:
                continue
            raise RegistrationError(
                f"Constructor parameter {implementation.__qualname__}.{parameter.name} "
                "requires a resolvable type annotation"
            )
        if not isinstance(annotation, type):
            raise RegistrationError(
                f"Unsupported annotation {annotation!r} on "
                f"{implementation.__qualname__}.{parameter.name}"
            )
        dependencies.append(annotation)
    return tuple(dependencies)


async def _enter_and_track(
    value: object, callbacks: list[Callable[[], Awaitable[None] | None]]
) -> object:
    """Enter or register an owned resource and return its usable value.

    :param value: Activated service, possibly a context manager or closable resource.
    :param callbacks: Ownership callbacks to append in acquisition order.
    :return: The resulting value.
    :rtype: object
    """
    if hasattr(value, "__aenter__") and hasattr(value, "__aexit__"):
        manager = value
        entered = await manager.__aenter__()

        async def exit_async() -> None:
            """Exit the tracked asynchronous context manager.

            :return: None.
            :rtype: None
            """
            await manager.__aexit__(None, None, None)

        callbacks.append(exit_async)
        return entered
    if hasattr(value, "__enter__") and hasattr(value, "__exit__"):
        manager = value
        entered = manager.__enter__()

        def exit_sync() -> None:
            """Exit the tracked synchronous context manager.

            :return: None.
            :rtype: None
            """
            manager.__exit__(None, None, None)

        callbacks.append(exit_sync)
        return entered
    if hasattr(value, "aclose"):

        async def aclose() -> None:
            """Close the tracked resource through its asynchronous close method.

            :return: None.
            :rtype: None
            """
            await value.aclose()

        callbacks.append(aclose)
    elif hasattr(value, "close"):

        async def close() -> None:
            """Close the tracked resource and await an awaitable close result.

            :return: None.
            :rtype: None
            """
            result = value.close()
            if inspect.isawaitable(result):
                await result

        callbacks.append(close)
    return value


async def _close_all(callbacks: Sequence[Callable[[], Awaitable[None] | None]]) -> None:
    """Run ownership callbacks in reverse acquisition order.

    :param callbacks: Resource-closing callbacks ordered by acquisition.
    :return: None.
    :rtype: None
    """
    errors: list[Exception] = []
    for callback in reversed(callbacks):
        try:
            result = callback()
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            errors.append(ServiceCancellationError("Service cleanup was cancelled"))
        except Exception as error:
            errors.append(error)
    if errors:
        raise ExceptionGroup("One or more services failed to close", errors)


async def _finish_uninterrupted(awaitable: Awaitable[None]) -> bool:
    """Complete cleanup despite caller cancellation and report absorbed cancellation."""
    task = asyncio.ensure_future(awaitable)
    cancelled = False
    while True:
        try:
            await asyncio.shield(task)
            return cancelled
        except asyncio.CancelledError:
            cancelled = True
            if task.done():
                task.result()
                return cancelled
        except Exception as error:
            if cancelled:
                raise ExceptionGroup(
                    "Service cleanup failed after caller cancellation",
                    [ServiceCancellationError(), error],
                ) from error
            raise
