Integrations and extension points
=================================

Aeterna does not ship FastAPI, worker, secret-manager, or scheduler adapters.
The recipes below use public Aeterna interfaces; they are application patterns,
not bundled APIs.

FastAPI recipe
--------------

Let FastAPI own the event loop. Its lifespan hook builds, starts, and stops one
Aeterna application, while each request creates its own scope for request-scoped
services. The complete executable recipe, including installation and startup
commands, lives in :ref:`FastAPI integration <fastapi-integration>` so this
lifecycle contract has one maintained example. FastAPI is not an Aeterna
dependency.

Background workers
------------------

For an external worker runner, use embedding: build and start in the runner's
startup hook, use ``context.cancellation`` as its shutdown signal, and stop
the application during teardown. Alternatively, use a Aeterna
``HostedService`` when Aeterna owns the process.

Custom providers and clients
----------------------------

External systems integrate through ``ConfigurationProvider`` implementations
and DI factories. Keep provider names stable, return mappings, validate
secrets during binding or activation, and let Aeterna own a client only when
the registration's ``owns_instance`` policy matches that client's lifecycle.
