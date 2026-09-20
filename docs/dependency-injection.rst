Dependency injection
====================

Use a mutable ``ServiceCollection`` to describe services, then build an
immutable ``ServiceProvider`` to resolve them asynchronously. Service keys are
types.

Registration
------------

Register constructor-activated classes, factories, or existing instances. The
following registrations use each form:

.. code-block:: python

   from aeterna.di import ServiceCollection, ServiceLifetime, ServiceResolver

   class Database:
       pass

   class Handler:
       def __init__(self, database: Database) -> None:
           self.database = database

   class Cache:
       pass

   class Clock:
       pass

   async def create_cache(_: ServiceResolver) -> Cache:
       return Cache()

   services = ServiceCollection()
   services.add_type(Database, lifetime=ServiceLifetime.SINGLETON)
   services.add_type(Handler, lifetime=ServiceLifetime.SCOPED)
   services.add_factory(Cache, create_cache, lifetime=ServiceLifetime.SINGLETON)
   services.add_instance(Clock, Clock(), owns_instance=False)

``add_type`` reads constructor annotations. Required parameters without a type
annotation and unsupported annotations are registration errors. A factory
receives a ``ServiceResolver`` and may return its service directly or as an
awaitable.

Lifetimes and scopes
--------------------

``SINGLETON`` is shared by the root provider. ``SCOPED`` is shared within one
explicit ``ServiceScope``. ``TRANSIENT`` is activated for every resolution.
Scoped services cannot be resolved from the root provider. A singleton graph
cannot capture a scoped service; attempting to do so raises
``CaptiveDependencyError``.

.. code-block:: python

   async with services.build_provider() as provider:
       async with provider.create_scope() as scope:
           handler = await scope.get(Handler)

.. mermaid::

   flowchart TB
       Collection[Mutable ServiceCollection<br/>type, factory, or instance descriptors]
       Collection -->|build_provider validates registrations| Provider[ServiceProvider<br/>root ownership boundary]
       Provider -->|get singleton| SingletonCache[Singleton cache<br/>one instance per provider]
       Provider -->|create_scope| Scope[ServiceScope<br/>explicit ownership boundary]
       Scope -->|get scoped| ScopedCache[Scoped cache<br/>one instance per scope]
       Provider -->|get transient| RootTransient[Fresh transient activation]
       Scope -->|get transient| ScopedTransient[Fresh transient activation]
       SingletonCache --> ProviderOwned[Owned singleton resources]
       ScopedCache --> ScopeOwned[Owned scoped resources]
       RootTransient --> CallerOwned[Caller closes the transient]
       ScopedTransient --> CallerOwned
       ScopeOwned -->|scope close: reverse acquisition order| ScopeClosed[Scoped resources closed]
       ProviderOwned -->|provider close: reverse acquisition order| ProviderClosed[Root resources closed]

The collection and provider are intentionally explicit. Use ``try_get`` for
optional registrations. ``get`` raises ``MissingRegistrationError`` when a key
is not registered.

Validation and ownership
------------------------

Building a provider validates duplicate registrations and constructor
dependencies. Circular graphs report their resolution path, including cycles
spread across two concurrently resolving tasks.

Ownership is opt-in. A registration is closed by the container only when it is
made with ``owns_instance=True``; otherwise the caller keeps responsibility for
the object's lifetime. An owned service that provides an async or synchronous
context-manager method, ``aclose``, or ``close`` is entered when it is activated
and closed in reverse acquisition order when its boundary closes.

.. code-block:: python

   services.add_factory(Database, make_database,
                        lifetime=ServiceLifetime.SINGLETON, owns_instance=True)

The owner follows the lifetime: owned singletons belong to the provider, and
owned scoped services belong to the scope that resolved them.

Closing a provider or scope stops new resolutions, waits for resolutions already
in progress, then closes owned resources. Closed boundaries release their
instance caches and cleanup callbacks. Cancellation of the task awaiting
``close()`` is reported only after cleanup completes.

If a resource itself raises ``asyncio.CancelledError`` while closing, Aeterna
continues cleanup and reports ``ServiceCancellationError`` inside an
``ExceptionGroup``. Framework cleanup failures therefore remain ordinary
``Exception`` instances.

Transient services are never owned. Nothing tells the container when a caller has
finished with a transient, so tracking one would retain every instance ever
resolved until its boundary closed. Registering a transient with
``owns_instance=True`` is rejected by ``build_provider()`` rather than silently
ignored; register the service as scoped, or close it in the caller.

Factories and validation
------------------------

A factory resolves its own dependencies, so the collection cannot infer them the
way it inspects a constructor. Declaring them opts the registration into the same
build-time validation that constructor graphs receive:

.. code-block:: python

   services.add_factory(Handler, make_handler, dependencies=(Clock,))

Declared dependencies are validated, not injected — the factory still resolves
them through the resolver it is handed. Omitting them is supported and defers
missing-registration failures to the first resolution.

Stereotype conventions
----------------------

Aeterna does not provide stereotype classes or decorators. A useful application
convention is a configuration-backed singleton for immutable settings and
clients, scoped services for request or job state, transient services for cheap
operations, and singleton hosted services for long-running loops. These are
conventions expressed with ``ServiceLifetime`` and registration methods, not
extra framework APIs.
