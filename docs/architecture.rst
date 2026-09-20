Architecture
============

Package boundaries
------------------

Aeterna keeps its package boundaries small and explicit:

.. mermaid::

   flowchart TB
       subgraph Core[Independent core packages]
           Config[aeterna-config<br/>providers, merging, binding]
           DI[aeterna-di<br/>registration, resolution, scopes]
       end

       YAML[aeterna-config-yaml<br/>optional PyYAML adapter]
       Runtime[aeterna-runtime<br/>composition, lifecycle, hosting]
       App[Application code]

       YAML -->|depends on| Config
       Runtime -->|depends on| Config
       Runtime -->|depends on| DI
       App -->|uses the public aeterna namespace| Config
       App -->|uses the public aeterna namespace| DI
       App -->|typically composes through| Runtime

``aeterna-config`` and ``aeterna-di`` do not depend on another Aeterna
package. The YAML adapter depends on configuration; the runtime depends on
both core packages. Each distribution contributes a focused subpackage to the
shared ``aeterna`` namespace: ``aeterna.config``, ``aeterna.di``,
``aeterna.config_yaml``, or ``aeterna.runtime``. Keep adapters and
application-specific integrations out of the core packages.

Composition flow
----------------

.. mermaid::

   flowchart LR
       Providers[Configuration providers] --> ConfigBuilder[ConfigurationBuilder]
       ConfigBuilder --> Snapshot[Immutable Configuration snapshot]
       Snapshot --> Configurators[Service configurators]
       Registrations[Service registrations<br/>and hosted-service types] --> Services[ServiceCollection]
       Configurators --> Services
       Snapshot -->|registered as Configuration| Services
       Token[Application CancellationToken] -->|registered during build| Services
       Services --> Provider[Immutable ServiceProvider]
       Provider --> Context[ApplicationContext]
       Snapshot --> Context
       Token --> Context
       Hooks[Lifecycle hooks] --> Application[Application]
       Provider --> Application
       Context --> Application
       Application --> Execution[start → run or wait → cancellation → stop]

``ApplicationBuilder.build()`` loads configuration before invoking service
configurators, so registrations can depend on the completed snapshot. It then
adds ``Configuration`` and ``CancellationToken`` to the collection, validates
the service graph, and returns an ``Application`` with an immutable provider,
context, hooks, and hosted-service registrations.

Design principles
-----------------

* Providers are asynchronous, so an implementation can perform I/O without
  blocking the event loop.
* Configuration is a snapshot. Merging happens during build; reads do not
  reload sources.
* Registration is mutable only until ``build_provider()`` or application build.
* Resolution is explicit and annotation-driven; there is no global container.
* Resource ownership follows the provider or scope that activated the service.
* Runtime lifecycle is usable both as a framework-owned host and inside a
  caller-owned event loop.
