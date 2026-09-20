Aeterna
========

Aeterna is an async-first Python framework for building applications with
layered configuration, explicit dependency injection, and predictable lifecycle
management. It supports Python 3.12 and later.

Aeterna draws inspiration from the composition patterns of .NET—especially in
configuration, dependency injection, and application hosting—but implements them
in Python with async-first primitives, explicit ownership boundaries, and clear
shutdown semantics.

Use only the layers your application needs. ``aeterna-config`` and
``aeterna-di`` are independent core packages. ``aeterna-config-yaml`` adds the
optional YAML provider, and ``aeterna-runtime`` composes configuration and DI
into an application host.

Why Aeterna
-----------

Aeterna is a good fit when you want:

* Explicit service ownership instead of hidden global state
* Typed, layered configuration with recursive merging and immutable snapshots
* Lifecycle-aware dependency resolution with singleton, scoped, and transient
  lifetimes
* Controlled startup and shutdown ordering for hosted services and application
  hooks
* A modular architecture that lets you adopt only the layers your application
  needs

It is less suitable for projects that want framework magic, implicit runtime
behavior, or a single monolithic application shell with hidden composition
rules.

.. toctree::
   :maxdepth: 2
   :caption: Guides

   installation
   quickstart
   architecture
   configuration
   dependency-injection
   lifecycle
   application-patterns
   embedding
   hosting
   integrations

.. toctree::
   :maxdepth: 2
   :caption: API reference

   api/configuration
   api/di
   api/runtime
   api/yaml
   api/errors

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
