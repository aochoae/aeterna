# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

from __future__ import annotations

import asyncio
import logging

import pytest
from aeterna.config import Configuration, MappingProvider
from aeterna.di import ServiceCollection, ServiceLifetime
from aeterna.runtime import (
    ApplicationBuilder,
    ApplicationCancellationError,
    ApplicationContext,
    ApplicationState,
    CancellationToken,
    HostedServiceError,
    InvalidStateError,
    ShutdownTimeoutError,
)


@pytest.mark.asyncio
async def test_short_lived_embedded_application_and_bootstrap() -> None:
    class Greeting:
        def __init__(self, configuration: Configuration):
            self.value = configuration.require("greeting")

    builder = ApplicationBuilder().add_configuration(MappingProvider({"greeting": "hello"}))
    builder.configure_services(
        lambda services, _: services.add_type(Greeting, lifetime=ServiceLifetime.SINGLETON)
    )
    application = await builder.build()

    async def main(context: ApplicationContext) -> str:
        return (await context.services.get(Greeting)).value  # type: ignore[no-any-return]

    assert await application.run(main) == "hello"
    assert application.state is ApplicationState.STOPPED


@pytest.mark.asyncio
async def test_lifecycle_order() -> None:
    events: list[str] = []
    builder = ApplicationBuilder()

    async def first_start(_: ApplicationContext) -> None:
        events.append("first:start")

    async def first_stop(_: ApplicationContext) -> None:
        events.append("first:stop")

    async def second_start(_: ApplicationContext) -> None:
        events.append("second:start")

    async def second_stop(_: ApplicationContext) -> None:
        events.append("second:stop")

    builder.add_lifecycle_hook(first_start, first_stop)
    builder.add_lifecycle_hook(second_start, second_stop)
    application = await builder.build()
    await application.run(lambda _: None)
    assert events == ["first:start", "second:start", "second:stop", "first:stop"]


@pytest.mark.asyncio
async def test_partial_startup_cleanup() -> None:
    events: list[str] = []
    builder = ApplicationBuilder()

    async def started(_: ApplicationContext) -> None:
        events.append("start")

    async def stopped(_: ApplicationContext) -> None:
        events.append("stop")

    async def fail(_: ApplicationContext) -> None:
        raise RuntimeError("boom")

    builder.add_lifecycle_hook(started, stopped)
    builder.add_lifecycle_hook(fail, lambda _: None)
    application = await builder.build()
    with pytest.raises(Exception, match="startup failed"):
        await application.start()
    assert events == ["start", "stop"]
    assert application.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_use_shutdown_timeout_sets_value() -> None:
    application = await ApplicationBuilder().use_shutdown_timeout(10.0).build()
    assert application.shutdown_timeout == 10.0


def test_use_shutdown_timeout_non_positive_raises() -> None:
    builder = ApplicationBuilder()

    with pytest.raises(ValueError):
        builder.use_shutdown_timeout(0.0)

    with pytest.raises(ValueError):
        builder.use_shutdown_timeout(-1.0)


@pytest.mark.asyncio
async def test_builder_is_immutable_after_build() -> None:
    builder = ApplicationBuilder()
    await builder.build()
    with pytest.raises(InvalidStateError):
        builder.use_shutdown_timeout(5.0)


@pytest.mark.asyncio
async def test_async_service_configurator_is_awaited() -> None:
    configured = False

    async def configure(services: object, config: object) -> None:
        nonlocal configured
        configured = True

    await ApplicationBuilder().configure_services(configure).build()
    assert configured


@pytest.mark.asyncio
async def test_worker_completing_normally_raises_hosted_service_error() -> None:
    class QuickWorker:
        async def start(self, _: ApplicationContext) -> None:
            pass

        async def run(self, _: ApplicationContext) -> None:
            pass  # returns immediately without error

        async def stop(self, _: ApplicationContext) -> None:
            pass

    application = await ApplicationBuilder().add_hosted_service(QuickWorker).build()
    with pytest.raises(HostedServiceError) as caught:
        await application.run()
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_concurrent_stop_calls_are_idempotent() -> None:
    application = await ApplicationBuilder().build()
    await application.start()
    await asyncio.gather(application.stop(), application.stop())
    assert application.state is ApplicationState.STOPPED


@pytest.mark.asyncio
async def test_lifecycle_hook_stop_failure_is_collected() -> None:
    async def start(_: ApplicationContext) -> None:
        pass

    async def failing_stop(_: ApplicationContext) -> None:
        raise RuntimeError("stop failed")

    builder = ApplicationBuilder()
    builder.add_lifecycle_hook(start, failing_stop)
    application = await builder.build()
    await application.start()
    with pytest.raises(ExceptionGroup) as caught:
        await application.stop()
    inner = caught.value.exceptions[0]
    assert isinstance(inner, ExceptionGroup)
    assert any("stop failed" in str(e) for e in inner.exceptions)
    assert application.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_shutdown_timeout_exceeded_raises() -> None:
    class RunThenHangWorker:
        started = asyncio.Event()

        async def start(self, _: ApplicationContext) -> None:
            self.started.set()

        async def run(self, ctx: ApplicationContext) -> None:
            await ctx.cancellation.wait()
            await asyncio.sleep(100)  # hang after cancellation signal so the task stays alive

        async def stop(self, _: ApplicationContext) -> None:
            pass

    builder = ApplicationBuilder().use_shutdown_timeout(0.05)
    builder.add_hosted_service(RunThenHangWorker)
    application = await builder.build()
    running = asyncio.create_task(application.run())
    await asyncio.wait_for(RunThenHangWorker.started.wait(), timeout=1.0)
    application.context.cancellation.cancel()
    with pytest.raises(ExceptionGroup) as caught:
        await running
    assert any(isinstance(e, ShutdownTimeoutError) for e in caught.value.exceptions)
    assert application.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_service_close_failure_collected_during_stop() -> None:
    class FailingResource:
        async def aclose(self) -> None:
            raise RuntimeError("close failed")

    def configure(services: ServiceCollection, _: Configuration) -> None:
        services.add_factory(
            FailingResource,
            lambda _: FailingResource(),
            lifetime=ServiceLifetime.SINGLETON,
            owns_instance=True,
        )

    builder = ApplicationBuilder().configure_services(configure)
    application = await builder.build()
    await application.context.services.get(FailingResource)
    with pytest.raises(ExceptionGroup) as caught:
        await application.run()
    inner = caught.value.exceptions[0]
    assert isinstance(inner, ExceptionGroup)
    assert any("close failed" in str(e) for e in inner.exceptions)


@pytest.mark.asyncio
async def test_execution_and_shutdown_both_fail_raises_exception_group() -> None:
    class FailingStopWorker:
        async def start(self, _: ApplicationContext) -> None:
            pass

        async def run(self, _: ApplicationContext) -> None:
            raise RuntimeError("run failed")

        async def stop(self, _: ApplicationContext) -> None:
            raise RuntimeError("stop failed")

    application = await ApplicationBuilder().add_hosted_service(FailingStopWorker).build()
    with pytest.raises(ExceptionGroup) as caught:
        await application.run()
    messages = [str(e) for e in caught.value.exceptions]
    assert any("run failed" in m for m in messages)


@pytest.mark.asyncio
async def test_start_when_not_in_created_state_raises() -> None:
    application = await ApplicationBuilder().build()
    await application.run()
    with pytest.raises(InvalidStateError):
        await application.start()


@pytest.mark.asyncio
async def test_startup_and_close_both_fail_raises_exception_group() -> None:
    class FailingOnClose:
        async def aclose(self) -> None:
            raise RuntimeError("close failed")

    async def resolve_resource(ctx: ApplicationContext) -> None:
        await ctx.services.get(FailingOnClose)

    async def failing_start(_: ApplicationContext) -> None:
        raise RuntimeError("startup failed")

    def configure(services: ServiceCollection, _: Configuration) -> None:
        services.add_factory(
            FailingOnClose,
            lambda _: FailingOnClose(),
            lifetime=ServiceLifetime.SINGLETON,
            owns_instance=True,
        )

    builder = ApplicationBuilder().configure_services(configure)
    builder.add_lifecycle_hook(resolve_resource, lambda _: None)
    builder.add_lifecycle_hook(failing_start, lambda _: None)
    application = await builder.build()
    with pytest.raises(ExceptionGroup) as caught:
        await application.start()
    messages = [str(e) for e in caught.value.exceptions]
    assert any("startup failed" in m for m in messages)


@pytest.mark.asyncio
async def test_concurrent_stop_calls_inner_idempotent_check() -> None:
    async def on_start(_: ApplicationContext) -> None:
        pass

    async def on_stop(_: ApplicationContext) -> None:
        await asyncio.sleep(0)

    builder = ApplicationBuilder()
    builder.add_lifecycle_hook(on_start, on_stop)
    application = await builder.build()
    await application.start()
    await asyncio.gather(application.stop(), application.stop())
    assert application.state is ApplicationState.STOPPED


@pytest.mark.asyncio
async def test_worker_cancellation_and_idempotent_stop() -> None:
    class Worker:
        started = asyncio.Event()
        stopped = 0

        async def start(self, _: ApplicationContext) -> None:
            self.started.set()

        async def run(self, context: ApplicationContext) -> None:
            await context.cancellation.wait()

        async def stop(self, _: ApplicationContext) -> None:
            self.stopped += 1

    application = await ApplicationBuilder().add_hosted_service(Worker).build()
    running = asyncio.create_task(application.run())
    worker = await application.context.services.get(Worker)
    await worker.started.wait()
    application.context.cancellation.cancel()
    await running
    assert worker.stopped == 1
    await application.stop()
    assert worker.stopped == 1
    assert application.state is ApplicationState.STOPPED


@pytest.mark.asyncio
async def test_hosted_failure_cancels_and_surfaces() -> None:
    class FailingWorker:
        async def start(self, _: ApplicationContext) -> None:
            pass

        async def run(self, _: ApplicationContext) -> None:
            raise RuntimeError("worker failed")

        async def stop(self, _: ApplicationContext) -> None:
            pass

    application = await ApplicationBuilder().add_hosted_service(FailingWorker).build()
    with pytest.raises(HostedServiceError, match="worker failed"):
        await application.run()
    assert application.context.cancellation.is_cancelled
    assert application.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_embedded_wait_surfaces_hosted_failure_and_cleans_up() -> None:
    stopped = False

    class FailingWorker:
        async def start(self, _: ApplicationContext) -> None:
            pass

        async def run(self, _: ApplicationContext) -> None:
            raise RuntimeError("embedded worker failed")

        async def stop(self, _: ApplicationContext) -> None:
            nonlocal stopped
            stopped = True

    application = await ApplicationBuilder().add_hosted_service(FailingWorker).build()
    await application.start()

    with pytest.raises(HostedServiceError, match="embedded worker failed"):
        await application.wait()

    assert stopped
    assert application.context.cancellation.is_cancelled
    assert application.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_embedded_wait_returns_on_cancellation() -> None:
    class Worker:
        async def start(self, _: ApplicationContext) -> None:
            pass

        async def run(self, context: ApplicationContext) -> None:
            await context.cancellation.wait()

        async def stop(self, _: ApplicationContext) -> None:
            pass

    application = await ApplicationBuilder().add_hosted_service(Worker).build()
    await application.start()
    waiting = asyncio.create_task(application.wait())
    application.context.cancellation.cancel()
    await waiting
    assert application.state is ApplicationState.RUNNING
    await application.stop()
    assert application.state is ApplicationState.STOPPED


@pytest.mark.asyncio
async def test_context_services_include_configuration_and_cancellation() -> None:
    application = await ApplicationBuilder().build()
    await application.start()
    assert (
        await application.context.services.get(Configuration) is application.context.configuration
    )
    assert (
        await application.context.services.get(CancellationToken)
        is application.context.cancellation
    )
    await application.stop()


@pytest.mark.asyncio
async def test_invalid_transitions_and_multiple_isolated_apps() -> None:
    first = await ApplicationBuilder().build()
    second = await ApplicationBuilder().build()
    with pytest.raises(InvalidStateError):
        await first.stop()
    await asyncio.gather(first.run(lambda _: 1), second.run(lambda _: 2))
    assert first.context.services is not second.context.services


@pytest.mark.asyncio
async def test_shutdown_timeout_logs_the_offending_services(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class HangingWorker:
        started = asyncio.Event()

        async def start(self, _: ApplicationContext) -> None:
            self.started.set()

        async def run(self, ctx: ApplicationContext) -> None:
            await ctx.cancellation.wait()
            await asyncio.sleep(100)

        async def stop(self, _: ApplicationContext) -> None:
            pass

    builder = ApplicationBuilder().use_shutdown_timeout(0.05)
    builder.add_hosted_service(HangingWorker)
    application = await builder.build()

    running = asyncio.create_task(application.run())
    await asyncio.wait_for(HangingWorker.started.wait(), timeout=1.0)
    with caplog.at_level(logging.WARNING, logger="aeterna.runtime"):
        application.context.cancellation.cancel()
        with pytest.raises(ExceptionGroup) as caught:
            await running

    # An operator must be able to tell *which* service hung, from both the log and
    # the error, not just that shutdown exceeded its deadline.
    assert "HangingWorker" in caplog.text
    timeouts = [e for e in caught.value.exceptions if isinstance(e, ShutdownTimeoutError)]
    assert timeouts
    assert "HangingWorker" in str(timeouts[0])


@pytest.mark.asyncio
async def test_library_emits_nothing_without_handler_configuration() -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    # Attach to the root logger: anything propagating past an unconfigured library
    # logger would land here. A NullHandler on "aeterna.runtime" is not enough on its
    # own -- the level must also leave INFO/DEBUG unemitted by default.
    root = logging.getLogger()
    handler = Capture()
    root.addHandler(handler)
    previous = root.level
    root.setLevel(logging.WARNING)
    try:
        application = await ApplicationBuilder().build()
        await application.run(lambda _: None)
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)

    assert [record.getMessage() for record in records] == []


@pytest.mark.asyncio
async def test_lifecycle_logging_names_hooks_and_services(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Worker:
        async def start(self, _: ApplicationContext) -> None:
            pass

        async def run(self, ctx: ApplicationContext) -> None:
            await ctx.cancellation.wait()

        async def stop(self, _: ApplicationContext) -> None:
            pass

    async def on_start(_: ApplicationContext) -> None:
        pass

    async def on_stop(_: ApplicationContext) -> None:
        pass

    builder = ApplicationBuilder().add_hosted_service(Worker)
    builder.add_lifecycle_hook(on_start, on_stop)
    application = await builder.build()

    with caplog.at_level(logging.DEBUG, logger="aeterna.runtime"):
        await application.run(lambda _: None)

    assert any(
        "Started hosted service" in r.getMessage() and "Worker" in r.getMessage()
        for r in caplog.records
    )
    assert any(
        "Stopped hosted service" in r.getMessage() and "Worker" in r.getMessage()
        for r in caplog.records
    )
    assert any("on_start" in record.getMessage() for record in caplog.records)
    assert any("on_stop" in record.getMessage() for record in caplog.records)
    assert "running -> stopping" in caplog.text


@pytest.mark.asyncio
async def test_context_exposes_state_without_a_public_mutator() -> None:
    application = await ApplicationBuilder().build()
    context = application.context
    assert context.state is ApplicationState.CREATED
    # Every hook, hosted service and main callback holds this context. A public
    # mutator would let any of them corrupt the lifecycle state machine.
    assert not hasattr(context, "set_state")
    await application.run(lambda _: None)
    assert context.state is ApplicationState.STOPPED


@pytest.mark.asyncio
async def test_external_cancellation_still_runs_graceful_shutdown() -> None:
    events: list[str] = []

    class Worker:
        started = asyncio.Event()

        async def start(self, _: ApplicationContext) -> None:
            events.append("service:start")
            self.started.set()

        async def run(self, context: ApplicationContext) -> None:
            await context.cancellation.wait()

        async def stop(self, _: ApplicationContext) -> None:
            await asyncio.sleep(0.05)
            events.append("service:stop")

    async def hook_start(_: ApplicationContext) -> None:
        events.append("hook:start")

    async def hook_stop(_: ApplicationContext) -> None:
        events.append("hook:stop")

    builder = ApplicationBuilder().add_hosted_service(Worker)
    builder.add_lifecycle_hook(hook_start, hook_stop)
    application = await builder.build()

    running = asyncio.create_task(application.run())
    worker = await application.context.services.get(Worker)
    await asyncio.wait_for(worker.started.wait(), timeout=1.0)

    # A supervisor asks the application to stop, then escalates while shutdown is
    # still in flight. Absorbing only the first cancellation is not enough: the
    # pre-fix code lost every cleanup step and never closed the provider.
    running.cancel()
    await asyncio.sleep(0)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert events == ["hook:start", "service:start", "service:stop", "hook:stop"]
    assert application.context.services._closed


@pytest.mark.asyncio
async def test_cancellation_arriving_during_a_successful_shutdown_is_reported() -> None:
    stopped = asyncio.Event()

    async def on_start(_: ApplicationContext) -> None:
        pass

    async def slow_stop(_: ApplicationContext) -> None:
        stopped.set()
        await asyncio.sleep(0.05)

    builder = ApplicationBuilder()
    builder.add_lifecycle_hook(on_start, slow_stop)
    application = await builder.build()

    # main() succeeds, so there is no primary error; cancellation then arrives while
    # shutdown is already under way. The cancellation must not be swallowed just
    # because the application itself did not fail.
    running = asyncio.create_task(application.run(lambda _: "done"))
    await asyncio.wait_for(stopped.wait(), timeout=1.0)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert application.state is ApplicationState.STOPPED


@pytest.mark.asyncio
async def test_external_cancellation_respects_shutdown_timeout() -> None:
    class HangingWorker:
        started = asyncio.Event()

        async def start(self, _: ApplicationContext) -> None:
            self.started.set()

        async def run(self, context: ApplicationContext) -> None:
            await context.cancellation.wait()
            await asyncio.sleep(100)

        async def stop(self, _: ApplicationContext) -> None:
            pass

    builder = ApplicationBuilder().use_shutdown_timeout(0.05)
    builder.add_hosted_service(HangingWorker)
    application = await builder.build()

    running = asyncio.create_task(application.run())
    worker = await application.context.services.get(HangingWorker)
    await asyncio.wait_for(worker.started.wait(), timeout=1.0)

    running.cancel()
    # Absorbing cancellation must not make shutdown unbounded: the deadline still applies.
    with pytest.raises((asyncio.CancelledError, ExceptionGroup)):
        await asyncio.wait_for(running, timeout=2.0)
    assert application.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_hosted_failure_interrupts_running_main_callback() -> None:
    main_cancelled = asyncio.Event()

    class FailingWorker:
        async def start(self, _: ApplicationContext) -> None:
            pass

        async def run(self, _: ApplicationContext) -> None:
            await asyncio.sleep(0)
            raise RuntimeError("worker failed while main was running")

        async def stop(self, _: ApplicationContext) -> None:
            pass

    async def main(_: ApplicationContext) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            main_cancelled.set()

    application = await ApplicationBuilder().add_hosted_service(FailingWorker).build()
    with pytest.raises(HostedServiceError, match="worker failed while main was running"):
        await application.run(main)

    assert main_cancelled.is_set()
    assert application.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_cancellation_during_start_cleans_partial_startup() -> None:
    events: list[str] = []
    blocking_start_entered = asyncio.Event()

    async def first_start(_: ApplicationContext) -> None:
        events.append("first:start")

    async def first_stop(_: ApplicationContext) -> None:
        events.append("first:stop")

    async def blocking_start(_: ApplicationContext) -> None:
        blocking_start_entered.set()
        await asyncio.Event().wait()

    builder = ApplicationBuilder()
    builder.add_lifecycle_hook(first_start, first_stop)
    builder.add_lifecycle_hook(blocking_start, lambda _: None)
    application = await builder.build()

    starting = asyncio.create_task(application.start())
    await blocking_start_entered.wait()
    starting.cancel()

    with pytest.raises(asyncio.CancelledError):
        await starting
    assert events == ["first:start", "first:stop"]
    assert application.context.services._closed
    assert application.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_startup_cleanup_failure_after_cancellation_uses_framework_error() -> None:
    blocking_start_entered = asyncio.Event()

    async def first_start(_: ApplicationContext) -> None:
        pass

    async def failing_stop(_: ApplicationContext) -> None:
        raise RuntimeError("cleanup failed")

    async def blocking_start(_: ApplicationContext) -> None:
        blocking_start_entered.set()
        await asyncio.Event().wait()

    builder = ApplicationBuilder()
    builder.add_lifecycle_hook(first_start, failing_stop)
    builder.add_lifecycle_hook(blocking_start, lambda _: None)
    application = await builder.build()

    starting = asyncio.create_task(application.start())
    await blocking_start_entered.wait()
    starting.cancel()

    with pytest.raises(ExceptionGroup) as caught:
        await starting
    assert any(isinstance(error, ApplicationCancellationError) for error in caught.value.exceptions)
    assert any("cleanup failed" in str(error) for error in caught.value.exceptions)


@pytest.mark.asyncio
async def test_direct_stop_completes_before_reporting_caller_cancellation() -> None:
    stop_started = asyncio.Event()
    stop_release = asyncio.Event()

    async def on_start(_: ApplicationContext) -> None:
        pass

    async def on_stop(_: ApplicationContext) -> None:
        stop_started.set()
        await stop_release.wait()

    builder = ApplicationBuilder().add_lifecycle_hook(on_start, on_stop)
    application = await builder.build()
    await application.start()

    stopping = asyncio.create_task(application.stop())
    await stop_started.wait()
    stopping.cancel()
    stopping.cancel()
    stop_release.set()

    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert application.context.services._closed
    assert application.state is ApplicationState.STOPPED
