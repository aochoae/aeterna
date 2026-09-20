Framework-owned hosting
=======================

``aeterna.runtime.run`` builds an application, starts it, supervises its main
callback or hosted services, and stops it with ``asyncio.run``.
On platforms with asyncio signal-handler support, SIGINT and SIGTERM request
cooperative cancellation. Other environments still work; application code can
request cancellation directly.

.. mermaid::

   sequenceDiagram
       CLI->>Runtime: Start application
       Runtime->>EventLoop: Start event loop
       EventLoop->>Builder: Build application
       Builder-->>EventLoop: Return application
       EventLoop->>Application: Run application
       Application-->>EventLoop: Return result or error after shutdown
       EventLoop-->>Runtime: Close event loop
       Runtime-->>CLI: Return result or error

.. code-block:: python

   from aeterna.runtime import ApplicationBuilder, run

   builder = ApplicationBuilder().use_shutdown_timeout(10)
   run(builder)

Without a main callback or hosted service, ``run(builder)`` starts and stops
immediately. Add a hosted service for a long-running process. Standalone hosts
should use ``run``; embedded hosts should await ``build()``, ``start()``,
``wait()``, and ``stop()`` from their own event loop.

Pass a main callback for short-lived work:

.. code-block:: python

   from aeterna.runtime import ApplicationBuilder, ApplicationContext, run

   async def main(_: ApplicationContext) -> None:
       print("import complete")

   builder = ApplicationBuilder()
   run(builder, main)

``exit_code(error)`` maps successful completion to 0, cancellation and
keyboard interruption to 130, and other failures to 1. It is a helper for a
CLI entry point; ``run`` does not call it. Embedded applications should follow
their host's error-handling conventions instead.
