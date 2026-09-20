Application patterns
====================

Short-lived applications
------------------------

CLI tools, jobs, migrations, and batch processes can use an application main
callback. Put argument parsing or the unit of work in the callback, resolve
services from the context, and return a result when it helps the caller.

.. code-block:: python

   from aeterna.di import ServiceLifetime
   from aeterna.runtime import ApplicationBuilder, ApplicationContext, run

   class ImportJob:
       async def run(self) -> int:
           return 0

   async def main(context: ApplicationContext) -> int:
       job = await context.services.get(ImportJob)
       return await job.run()

   builder = ApplicationBuilder()
   builder.services.add_type(ImportJob, lifetime=ServiceLifetime.TRANSIENT)
   exit_status = run(builder, main)

Long-running applications
-------------------------

APIs, workers, consumers, and schedulers map naturally to hosted services.
Implement ``run`` as a long-lived, cancellation-aware operation. Use
``use_shutdown_timeout`` when external work needs a different graceful-shutdown
deadline.

Migrations and batch work
-------------------------

Register database clients as singletons, a unit-of-work or transaction service
as scoped, and the migration or batch operation as transient or a main
callback. When processing multiple items, create one explicit scope per unit
of work so scoped state and resources are released between items.
