Application lifecycle
=====================

Application context
-------------------

``ApplicationContext`` gives callbacks the root service provider, immutable
configuration, and an application-scoped ``CancellationToken``.
``Configuration`` and ``CancellationToken`` are also registered in the
container. ``context.state`` exposes the current ``ApplicationState``.

States and order
----------------

The normal path is ``CREATED`` → ``STARTING`` → ``RUNNING`` → ``STOPPING`` →
``STOPPED``. A failure moves the application to ``FAILED``. Startup hooks run
in registration order, followed by hosted-service ``start`` methods. Hosted
service ``run`` methods are scheduled after startup.

.. mermaid::

   stateDiagram-v2
       [*] --> CREATED
       CREATED --> STARTING: start()
       STARTING --> RUNNING: hooks and services start successfully
       STARTING --> FAILED: startup failure
       RUNNING --> STOPPING: cancellation or normal completion
       RUNNING --> FAILED: main callback or hosted task failure
       STOPPING --> STOPPED: cleanup succeeds
       STOPPING --> FAILED: cleanup failure or timeout
       FAILED --> FAILED: stop() performs remaining cleanup

.. mermaid::

   sequenceDiagram
       participant App as Application
       participant Hooks as Lifecycle hooks
       participant Services as Hosted services
       participant Tasks as run() tasks
       participant Provider as ServiceProvider

       App->>Hooks: start callbacks (registration order)
       App->>Services: resolve and start (registration order)
       App->>Tasks: schedule each service run()
       Note over Tasks: runs until cancellation or failure
       App->>Services: stop (reverse start order)
       App->>Hooks: stop callbacks (reverse registration order)
       App->>Tasks: wait for tasks within shutdown timeout
       App->>Provider: close owned root resources

Shutdown requests cancellation, stops hosted services in reverse start order,
runs lifecycle hook stop callbacks in reverse registration order, waits for
running tasks, and closes the service provider. ``stop`` is idempotent.

``Application.run()`` combines build, start, supervision, and shutdown for a
standalone host. An embedded host owns the event loop and uses
``await application.start()``, ``await application.wait()`` while hosted
services run, and ``await application.stop()`` during shutdown.

Hooks and hosted services
-------------------------

Hooks are start and stop callback pairs. Each callback may be synchronous or
asynchronous and receives the application context:

.. code-block:: python

   from aeterna.runtime import ApplicationBuilder, ApplicationContext

   builder = ApplicationBuilder()

   async def on_start(context: ApplicationContext) -> None:
       print("starting")

   async def on_stop(_: ApplicationContext) -> None:
       print("stopping")

   builder.add_lifecycle_hook(on_start, on_stop)

A hosted service implements async ``start(context)``, ``run(context)``, and
``stop(context)``. ``add_hosted_service`` registers its type as a singleton.
Its ``run`` method must wait for cancellation or raise an error; returning
normally is also treated as an unexpected stop.

.. code-block:: python

   from aeterna.runtime import ApplicationContext

   class Worker:
       async def start(self, _: ApplicationContext) -> None:
           pass

       async def run(self, context: ApplicationContext) -> None:
           await context.cancellation.wait()

       async def stop(self, _: ApplicationContext) -> None:
           pass

   builder.add_hosted_service(Worker)

An embedded host starts the application in its own event loop, waits for hosted
services, and stops the application during shutdown:

.. code-block:: python

   import asyncio

   async def embedded_host() -> None:
       application = await builder.build()
       await application.start()
       try:
           await application.wait()
       finally:
           await application.stop()


   if __name__ == "__main__":
       asyncio.run(embedded_host())

When a hosted task ends before cancellation, ``HostedServiceError`` cancels
the application and surfaces the failure. Hosted tasks remain supervised while
an asynchronous main callback is running; a hosted-service failure cancels that
callback before shutdown begins.

Embedded hosts that call ``Application.start()`` should await
``Application.wait()`` while their server or worker loop is running. ``wait``
returns after cooperative cancellation is requested and raises
``HostedServiceError`` after cleaning up when a hosted task stops unexpectedly.
The embedding host remains responsible for calling ``Application.stop()`` during
its shutdown path.

Cancellation and failure
------------------------

Long-running code should await ``context.cancellation.wait()`` or check
``context.cancellation.is_cancelled``. Startup failures clean up hooks and
services that have already started. Shutdown is bounded by the configured
timeout (30 seconds by default); exceeding it produces ``ShutdownTimeoutError``
inside the raised exception group, naming the hosted services that were still
running. Cleanup failures are preserved in exception groups where appropriate.

``run`` also survives cancellation of the task running it, which is how an
embedding host usually shuts an application down. Shutdown still completes, and
the ``CancelledError`` is re-raised afterwards so the supervising code observes
the cancellation it requested. The shutdown timeout continues to apply, so a
hung service cannot defer termination indefinitely.

The same completion guarantee applies when an embedded host directly awaits
``stop()``: cancellation is reported after shutdown completes. Cancellation
during ``start()`` cleans hooks and services that already started and closes the
provider before re-raising ``CancelledError``.

If cleanup also fails after cancellation, Aeterna raises an ``ExceptionGroup``
containing the cleanup failure and an ``ApplicationCancellationError``. This keeps framework
failures within the normal ``Exception`` hierarchy while preserving the reason
the lifecycle operation did not complete normally.

Logging
-------

The runtime logs to ``aeterna.runtime`` through a ``NullHandler``, so it emits
nothing until the application configures logging:

.. code-block:: python

   import logging

   logging.basicConfig(level=logging.INFO)

* ``DEBUG`` — each lifecycle state transition.
* ``INFO`` — hook and hosted-service start and stop, with elapsed durations.
* ``WARNING`` — the hosted services still running when the shutdown deadline
  expired.
* ``ERROR`` — hook, service, and provider close failures.

The warning and ``ShutdownTimeoutError`` both name the services that failed to
stop before the deadline.
