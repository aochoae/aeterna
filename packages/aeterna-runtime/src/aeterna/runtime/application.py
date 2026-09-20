# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Application composition, lifecycle, and hosted execution."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, TypeVar

from aeterna.config import Configuration, ConfigurationBuilder, ConfigurationProvider
from aeterna.di import ServiceCollection, ServiceLifetime, ServiceProvider

from .errors import (
    ApplicationCancellationError,
    HostedServiceError,
    InvalidStateError,
    ShutdownTimeoutError,
    StartupError,
)

# Library convention: emit nothing until the consuming application configures logging.
_logger = logging.getLogger("aeterna.runtime")
_logger.addHandler(logging.NullHandler())

T = TypeVar("T")
ServiceConfigurator = Callable[[ServiceCollection, Configuration], None | Awaitable[None]]
LifecycleCallback = Callable[["ApplicationContext"], None | Awaitable[None]]
ApplicationMain = Callable[["ApplicationContext"], T | Awaitable[T]]


class ApplicationState(Enum):
    """Lifecycle states of an application instance."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class CancellationToken:
    """Cooperative cancellation signal scoped to one application."""

    def __init__(self) -> None:
        """Create an uncanceled application-scoped signal."""
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested.

        :return: Whether the condition is true.
        :rtype: bool
        """
        return self._event.is_set()

    async def wait(self) -> None:
        """Wait until cancellation is requested.

        :return: None.
        :rtype: None
        """
        await self._event.wait()

    def cancel(self) -> None:
        """Request cancellation; repeated calls have no additional effect.

        :return: None.
        :rtype: None
        """
        self._event.set()


class HostedService(Protocol):
    """Protocol for a service with start, run, and stop lifecycle phases."""

    async def start(self, context: ApplicationContext) -> None:
        """Initialize the hosted service before its task is scheduled.

        :param context: Services, configuration, cancellation, and lifecycle state for the app.
        :return: None.
        :rtype: None
        """
        ...

    async def run(self, context: ApplicationContext) -> None:
        """Run the hosted service until cancellation or a failure.

        :param context: Services, configuration, cancellation, and lifecycle state for the app.
        :return: None.
        :rtype: None
        """
        ...

    async def stop(self, context: ApplicationContext) -> None:
        """Stop the hosted service during application shutdown.

        :param context: Services, configuration, cancellation, and lifecycle state for the app.
        :return: None.
        :rtype: None
        """
        ...


@dataclass(frozen=True, slots=True)
class LifecycleHook:
    """Pair of callbacks that run during startup and shutdown.

    :param start: Sync or async callback invoked while the application starts.
    :param stop: Sync or async callback invoked while the application stops.
    """

    start: LifecycleCallback
    stop: LifecycleCallback


class _StateTracker:
    def __init__(self) -> None:
        """Create a tracker initialized to the created lifecycle state."""
        self.value = ApplicationState.CREATED

    def set(self, state: ApplicationState) -> None:
        """Update the tracked lifecycle state.

        :param state: New lifecycle state to track.
        :return: None.
        :rtype: None
        """
        self.value = state


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    """Services and runtime state shared with application callbacks.

    :param services: Root service provider for the built application.
    :param configuration: Immutable configuration snapshot for the application.
    :param cancellation: Cooperative cancellation signal for application work.
    :param _state: Internal tracker that backs the public lifecycle state.
    """

    services: ServiceProvider
    configuration: Configuration
    cancellation: CancellationToken
    _state: _StateTracker

    @property
    def state(self) -> ApplicationState:
        """Return the current application lifecycle state.

        :return: The resulting state or resolution context.
        :rtype: ApplicationState
        """
        return self._state.value

    def _set_state(self, state: ApplicationState) -> None:
        """Update the tracked lifecycle state.

        :param state: New lifecycle state to track.
        :return: None.
        :rtype: None
        """
        previous = self._state.value
        self._state.set(state)
        _logger.debug("Application state %s -> %s", previous.value, state.value)


class ApplicationBuilder:
    """Composes configuration, services, hooks, and hosted services."""

    def __init__(self) -> None:
        """Create an application builder with empty configuration and services."""
        self.configuration = ConfigurationBuilder()
        self.services = ServiceCollection()
        self._configurators: list[ServiceConfigurator] = []
        self._hooks: list[LifecycleHook] = []
        self._hosted_keys: list[type[object]] = []
        self._shutdown_timeout = 30.0
        self._built = False

    def add_configuration(self, provider: ConfigurationProvider) -> ApplicationBuilder:
        """Add a configuration provider to the application pipeline.

        :param provider: Source loaded with the application's other configuration providers.
        :return: This application builder.
        :rtype: ApplicationBuilder
        """
        self._ensure_mutable()
        self.configuration.add(provider)
        return self

    def configure_services(self, callback: ServiceConfigurator) -> ApplicationBuilder:
        """Add a callback that registers services after configuration loads.

        :param callback: Sync or async function that receives services and built configuration.
        :return: This application builder.
        :rtype: ApplicationBuilder
        """
        self._ensure_mutable()
        self._configurators.append(callback)
        return self

    def add_lifecycle_hook(
        self, start: LifecycleCallback, stop: LifecycleCallback
    ) -> ApplicationBuilder:
        """Add a lifecycle hook invoked during startup and shutdown.

        :param start: Sync or async callback invoked during startup in registration order.
        :param stop: Sync or async callback invoked during shutdown in reverse registration order.
        :return: This application builder.
        :rtype: ApplicationBuilder
        """
        self._ensure_mutable()
        self._hooks.append(LifecycleHook(start, stop))
        return self

    def add_hosted_service(self, service_type: type[HostedService]) -> ApplicationBuilder:
        """Register a singleton hosted service for the application lifetime.

        :param service_type: Hosted-service implementation to construct and run as a singleton.
        :return: This application builder.
        :rtype: ApplicationBuilder
        """
        self._ensure_mutable()
        self.services.add_type(service_type, service_type, lifetime=ServiceLifetime.SINGLETON)
        self._hosted_keys.append(service_type)
        return self

    def use_shutdown_timeout(self, seconds: float) -> ApplicationBuilder:
        """Set the maximum time allowed for graceful shutdown.

        :param seconds: Positive number of seconds allowed for lifecycle cleanup and task
            completion.
        :return: This application builder.
        :rtype: ApplicationBuilder
        """
        self._ensure_mutable()
        if seconds <= 0:
            raise ValueError("Shutdown timeout must be positive")
        self._shutdown_timeout = seconds
        return self

    async def build(self) -> Application:
        """Build an application and freeze this builder's configuration.

        :return: The built application.
        :rtype: Application
        """
        self._ensure_mutable()
        configuration = await self.configuration.build()
        for callback in self._configurators:
            result = callback(self.services, configuration)
            if inspect.isawaitable(result):
                await result
        cancellation = CancellationToken()
        self.services.add_instance(Configuration, configuration)
        self.services.add_instance(CancellationToken, cancellation)
        provider = self.services.build_provider()
        tracker = _StateTracker()
        context = ApplicationContext(provider, configuration, cancellation, tracker)
        self._built = True
        return Application(
            context,
            tuple(self._hooks),
            tuple(self._hosted_keys),
            self._shutdown_timeout,
        )

    def _ensure_mutable(self) -> None:
        """Raise when composition changes are attempted after application construction.

        :return: None.
        :rtype: None
        """
        if self._built:
            raise InvalidStateError("ApplicationBuilder is immutable after build()")


class Application:
    """A built application that runs inside the caller's event loop."""

    def __init__(
        self,
        context: ApplicationContext,
        hooks: Sequence[LifecycleHook],
        hosted_keys: Sequence[type[object]],
        shutdown_timeout: float,
    ) -> None:
        """Create a built application with its immutable composition state.

        :param context: Shared services, configuration, cancellation, and lifecycle state.
        :param hooks: Lifecycle hooks to invoke around hosted services.
        :param hosted_keys: Registration keys for hosted services to start.
        :param shutdown_timeout: Maximum graceful-shutdown duration in seconds.
        :return: None.
        :rtype: None
        """
        self.context = context
        self._hooks = tuple(hooks)
        self._hosted_keys = tuple(hosted_keys)
        self._shutdown_timeout = shutdown_timeout
        self._started_hooks: list[LifecycleHook] = []
        self._started_services: list[HostedService] = []
        self._tasks: dict[asyncio.Task[None], HostedService] = {}
        self._stop_lock = asyncio.Lock()
        self._stop_complete = asyncio.Event()

    @property
    def state(self) -> ApplicationState:
        """Return the current application lifecycle state.

        :return: The resulting state or resolution context.
        :rtype: ApplicationState
        """
        return self.context.state

    @property
    def shutdown_timeout(self) -> float:
        """Return the maximum graceful-shutdown duration in seconds.

        :return: The configured shutdown deadline.
        :rtype: float
        """
        return self._shutdown_timeout

    async def start(self) -> None:
        """Start hooks and hosted services, then schedule hosted service tasks.

        :return: None.
        :rtype: None
        """
        if self.state is not ApplicationState.CREATED:
            raise InvalidStateError(f"Cannot start application in state {self.state.value}")
        self.context._set_state(ApplicationState.STARTING)
        try:
            await self._start_hooks()
            await self._start_services()
            self.context._set_state(ApplicationState.RUNNING)
            self._schedule_hosted_services()
        except asyncio.CancelledError:
            await self._handle_cancelled_startup()
            raise
        except Exception as error:
            await self._handle_startup_failure(error)

    async def run(self, main: ApplicationMain[T] | None = None) -> T | None:
        """Start, execute the optional main callback, and stop the application.

        :param main: Optional sync or async callback to execute while the application is running.
        :return: The result, or `None` when unavailable.
        :rtype: T | None
        """
        await self.start()
        primary_error: Exception | None = None
        cancelled = False
        result: T | None = None
        try:
            result = await self._execute_main(main)
        except asyncio.CancelledError:
            cancelled = True
            self.context._set_state(ApplicationState.FAILED)
        except Exception as error:
            primary_error = error
            self.context._set_state(ApplicationState.FAILED)
        finally:
            cancelled = await self._stop_after_run(primary_error, cancelled) or cancelled
        if cancelled:
            raise asyncio.CancelledError
        if primary_error is not None:
            raise primary_error
        return result

    async def wait(self) -> None:
        """Wait for cancellation or an unexpected hosted-service completion.

        This is the supervision operation for embedded hosts that call
        :meth:`start` and own the surrounding server or event loop. Normal
        cancellation returns so the host can call :meth:`stop`; a hosted-service
        failure is cleaned up before its error is re-raised.

        :return: None after cooperative cancellation is requested.
        :rtype: None
        :raises HostedServiceError: When a hosted service stops unexpectedly.
        """
        if self.state is not ApplicationState.RUNNING:
            raise InvalidStateError(f"Cannot wait for application in state {self.state.value}")
        try:
            await self._supervise(None)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.context._set_state(ApplicationState.FAILED)
            await self._stop_after_run(error, False)
            raise

    async def _stop_uninterrupted(self) -> bool:
        """Run shutdown to completion even while the awaiting task is being cancelled.

        ``asyncio.CancelledError`` does not inherit from :class:`Exception`, so external
        cancellation—a supervising task group, a framework lifespan teardown—would
        otherwise abort the first ``await`` of shutdown and skip hook, hosted-service,
        and resource cleanup entirely. Shutdown runs as its own task here, and repeated
        cancellation is absorbed until it finishes. :meth:`stop` still applies the
        shutdown deadline internally, so a hung service cannot defer termination
        indefinitely.

        :return: Whether cancellation was absorbed while shutting down.
        :rtype: bool
        """
        _, cancelled = await _await_uninterrupted(self._stop_core())
        return cancelled

    async def stop(self) -> None:
        """Request cancellation and stop the application exactly once.

        :return: None.
        :rtype: None
        """
        _, cancelled = await _await_uninterrupted(self._stop_core())
        if cancelled:
            raise asyncio.CancelledError

    async def _stop_core(self) -> None:
        """Perform the application shutdown state transition and cleanup."""
        if self._stop_complete.is_set():
            return
        async with self._stop_lock:
            if self._stop_complete.is_set():
                return
            if self.state is ApplicationState.CREATED:
                raise InvalidStateError("Cannot stop an application that has not started")
            was_failed = self.state is ApplicationState.FAILED
            if not was_failed:
                self.context._set_state(ApplicationState.STOPPING)
            self.context.cancellation.cancel()
            errors = await self._shutdown_started_components()
            provider_error = await self._close_service_provider()
            if provider_error is not None:
                errors.append(provider_error)
            self._complete_stop(was_failed, errors)

    async def _supervise(self, main: Awaitable[T] | None) -> T | None:
        """Monitor main work, hosted services, and cancellation together."""
        main_task = asyncio.ensure_future(main) if main is not None else None
        cancellation_wait = asyncio.create_task(self.context.cancellation.wait())
        waiters: set[asyncio.Future[Any]] = {*self._tasks, cancellation_wait}
        if main_task is not None:
            waiters.add(main_task)
        try:
            done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            if cancellation_wait in done:
                await _cancel_main_task(main_task)
                return None

            completed = next((task for task in self._tasks if task in done), None)
            if completed is not None:
                await _cancel_main_task(main_task)
                self._raise_for_completed_service(completed)
            return _main_task_result(main_task)
        finally:
            await _finish_supervision(cancellation_wait, main_task)

    async def _start_hooks(self) -> None:
        """Start lifecycle hooks in registration order."""
        for hook in self._hooks:
            started_at = time.perf_counter()
            await _invoke(hook.start, self.context)
            self._started_hooks.append(hook)
            _logger.info(
                "Started lifecycle hook %s in %.3fs",
                _describe(hook.start),
                time.perf_counter() - started_at,
            )

    async def _start_services(self) -> None:
        """Resolve and start hosted services in registration order."""
        for key in self._hosted_keys:
            service = await self.context.services.get(key)
            started_at = time.perf_counter()
            await service.start(self.context)  # type: ignore[attr-defined]
            self._started_services.append(service)  # type: ignore[arg-type]
            _logger.info(
                "Started hosted service %s in %.3fs",
                type(service).__qualname__,
                time.perf_counter() - started_at,
            )

    def _schedule_hosted_services(self) -> None:
        """Schedule the run task for each started hosted service."""
        for service in self._started_services:
            task = asyncio.create_task(service.run(self.context))
            self._tasks[task] = service

    async def _handle_cancelled_startup(self) -> None:
        """Clean up a cancelled startup and re-raise its cancellation outcome."""
        self.context._set_state(ApplicationState.FAILED)
        cleanup_error, interrupted = await _await_uninterrupted(self._cleanup_after_start_failure())
        if cleanup_error is not None:
            errors: list[Exception] = [ApplicationCancellationError(), cleanup_error]
            if interrupted:
                errors.append(ApplicationCancellationError())
            raise ExceptionGroup("Application startup cleanup failed", errors) from None
        if interrupted:
            raise ApplicationCancellationError(
                "Startup was cancelled again during cleanup"
            ) from None

    async def _handle_startup_failure(self, error: Exception) -> None:
        """Clean up a failed startup and preserve its primary failure."""
        self.context._set_state(ApplicationState.FAILED)
        cleanup_error, interrupted = await _await_uninterrupted(self._cleanup_after_start_failure())
        secondary: list[Exception] = []
        if cleanup_error is not None:
            secondary.append(cleanup_error)
        if interrupted:
            secondary.append(ApplicationCancellationError())
        if secondary:
            raise ExceptionGroup(
                "Application startup and cleanup failed", [error, *secondary]
            ) from error
        raise StartupError(error) from error

    async def _execute_main(self, main: ApplicationMain[T] | None) -> T | None:
        """Execute main work or supervise hosted services until cancellation."""
        if main is None:
            if self._tasks:
                await self._supervise(None)
            return None
        value = main(self.context)
        if inspect.isawaitable(value):
            return await self._supervise(value)
        return value

    async def _stop_after_run(self, primary_error: Exception | None, cancelled: bool) -> bool:
        """Stop after execution and combine a shutdown failure with prior failures."""
        try:
            return await self._stop_uninterrupted()
        except Exception as stop_error:
            errors = _execution_errors(primary_error, cancelled, stop_error)
            if len(errors) > 1:
                raise ExceptionGroup(
                    "Application execution and shutdown failed", errors
                ) from stop_error
            raise

    async def _shutdown_started_components(self) -> list[Exception]:
        """Stop started components within the configured graceful-shutdown deadline."""
        errors: list[Exception] = []
        try:
            async with asyncio.timeout(self._shutdown_timeout):
                cleanup_error = await self._cleanup_started()
                if cleanup_error is not None:
                    errors.append(cleanup_error)
                await self._await_hosted_tasks()
        except TimeoutError:
            errors.append(await self._cancel_stalled_tasks())
        return errors

    async def _await_hosted_tasks(self) -> None:
        """Wait for hosted service tasks without cancelling them."""
        if not self._tasks:
            return
        # asyncio.wait, not gather: a cancelled gather cancels its children, which would
        # leave every task done() and make the timeout handler unable to report the hang.
        await asyncio.wait(self._tasks)
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _cancel_stalled_tasks(self) -> ShutdownTimeoutError:
        """Cancel timed-out hosted tasks and return an actionable timeout error."""
        stalled = sorted(
            type(service).__qualname__ for task, service in self._tasks.items() if not task.done()
        )
        _logger.warning(
            "Shutdown exceeded %gs; cancelling hosted services still running: %s",
            self._shutdown_timeout,
            ", ".join(stalled) or "none",
        )
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        detail = f" while waiting for {', '.join(stalled)}" if stalled else ""
        return ShutdownTimeoutError(f"Shutdown exceeded {self._shutdown_timeout:g} seconds{detail}")

    async def _close_service_provider(self) -> Exception | None:
        """Close the service provider and return a failure without interrupting cleanup."""
        try:
            await self.context.services.close()
        except Exception as error:
            _logger.exception("Failed to close service provider")
            return error
        return None

    def _complete_stop(self, was_failed: bool, errors: list[Exception]) -> None:
        """Record the terminal state and surface accumulated shutdown failures."""
        self.context._set_state(
            ApplicationState.FAILED if was_failed or errors else ApplicationState.STOPPED
        )
        self._stop_complete.set()
        if errors:
            raise ExceptionGroup("Application shutdown failed", errors)

    def _raise_for_completed_service(self, task: asyncio.Task[None]) -> None:
        """Raise the hosted-service result as the appropriate framework error."""
        service = self._tasks[task]
        if task.cancelled():
            raise HostedServiceError(service)
        try:
            task.result()
        except Exception as error:
            raise HostedServiceError(service, error) from error
        raise HostedServiceError(service)

    async def _cleanup_after_start_failure(self) -> Exception | None:
        """Clean partially started components and close their service provider."""
        errors: list[Exception] = []
        cleanup_error = await self._cleanup_started()
        if cleanup_error is not None:
            errors.append(cleanup_error)
        try:
            await self.context.services.close()
        except asyncio.CancelledError:
            errors.append(ApplicationCancellationError("Service provider cleanup was cancelled"))
        except Exception as error:
            errors.append(error)
        if errors:
            return ExceptionGroup("Application startup cleanup failed", errors)
        return None

    async def _cleanup_started(self) -> Exception | None:
        """Stop started services and hooks in reverse order, preserving cleanup failures.

        :return: The result, or `None` when unavailable.
        :rtype: Exception | None
        """
        errors: list[Exception] = []
        for service in reversed(self._started_services):
            name = type(service).__qualname__
            stopped_at = time.perf_counter()
            try:
                await service.stop(self.context)
            except asyncio.CancelledError:
                cancellation_error = ApplicationCancellationError(
                    f"Hosted service {name} stop was cancelled"
                )
                _logger.error("Hosted service %s failed to stop: %s", name, cancellation_error)
                errors.append(cancellation_error)
            except Exception as error:
                _logger.exception("Hosted service %s failed to stop", name)
                errors.append(error)
            else:
                _logger.info(
                    "Stopped hosted service %s in %.3fs", name, time.perf_counter() - stopped_at
                )
        self._started_services.clear()
        for hook in reversed(self._started_hooks):
            name = _describe(hook.stop)
            stopped_at = time.perf_counter()
            try:
                await _invoke(hook.stop, self.context)
            except asyncio.CancelledError:
                cancellation_error = ApplicationCancellationError(
                    f"Lifecycle hook {name} stop was cancelled"
                )
                _logger.error("Lifecycle hook %s failed to stop: %s", name, cancellation_error)
                errors.append(cancellation_error)
            except Exception as error:
                _logger.exception("Lifecycle hook %s failed to stop", name)
                errors.append(error)
            else:
                _logger.info(
                    "Stopped lifecycle hook %s in %.3fs", name, time.perf_counter() - stopped_at
                )
        self._started_hooks.clear()
        if errors:
            return ExceptionGroup("Lifecycle cleanup failed", errors)
        return None


def _describe(callback: LifecycleCallback) -> str:
    """Return a readable identity for a lifecycle callback.

    :param callback: Callback registered as a lifecycle hook.
    :return: The resulting string.
    :rtype: str
    """
    return getattr(callback, "__qualname__", None) or repr(callback)


async def _invoke(callback: LifecycleCallback, context: ApplicationContext) -> None:
    """Invoke a lifecycle callback and await it when necessary.

    :param callback: Sync or async lifecycle callback to execute.
    :param context: Application state supplied to the callback.
    :return: None.
    :rtype: None
    """
    result = callback(context)
    if inspect.isawaitable(result):
        await result


async def _cancel_main_task(main_task: asyncio.Task[Any] | None) -> None:
    """Cancel and collect a main task when supervision ends for another reason."""
    if main_task is None:
        return
    if not main_task.done():
        main_task.cancel()
    await asyncio.gather(main_task, return_exceptions=True)


async def _finish_supervision(
    cancellation_wait: asyncio.Task[None], main_task: asyncio.Task[Any] | None
) -> None:
    """Cancel supervision waiters that are no longer needed."""
    if not cancellation_wait.done():
        cancellation_wait.cancel()
    await asyncio.gather(cancellation_wait, return_exceptions=True)
    if main_task is not None and not main_task.done():
        main_task.cancel()
        await asyncio.gather(main_task, return_exceptions=True)


def _main_task_result[T](main_task: asyncio.Task[T] | None) -> T | None:
    """Return the completed main-task result when one was supplied."""
    if main_task is None:  # pragma: no cover - a hosted task must have completed
        return None
    return main_task.result()


def _execution_errors(
    primary_error: Exception | None, cancelled: bool, stop_error: Exception
) -> list[Exception]:
    """Collect execution and shutdown failures in their established reporting order."""
    errors: list[Exception] = []
    if primary_error is not None:
        errors.append(primary_error)
    if cancelled:
        errors.append(ApplicationCancellationError())
    errors.append(stop_error)
    return errors


async def _await_uninterrupted[T](awaitable: Awaitable[T]) -> tuple[T, bool]:
    """Complete an operation despite caller cancellation.

    :param awaitable: Operation that must run to completion.
    :return: The operation result and whether caller cancellation was absorbed.
    :rtype: tuple[T, bool]
    """
    task = asyncio.ensure_future(awaitable)
    cancelled = False
    while True:
        try:
            return await asyncio.shield(task), cancelled
        except asyncio.CancelledError:
            cancelled = True
            if task.done():
                return task.result(), cancelled
        except Exception as error:
            if cancelled:
                raise ExceptionGroup(
                    "Operation failed after caller cancellation",
                    [ApplicationCancellationError(), error],
                ) from error
            raise
