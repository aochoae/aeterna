Installation
============

Requirements
------------

Aeterna supports Python 3.12 and later. The repository is a ``uv`` workspace
with four component packages and one convenience distribution designed for
modular, lifecycle-aware application composition:

* ``aeterna`` — metadata-only convenience distribution that installs all four
  component packages.
* ``aeterna-di`` — explicit asynchronous dependency injection with singleton,
  scoped, and transient lifetimes.
* ``aeterna-config`` — immutable layered configuration with recursive merging
  and typed binding.
* ``aeterna-config-yaml`` — optional YAML configuration support for mapping
  documents and validation.
* ``aeterna-runtime`` — application composition, lifecycle hooks, hosted
  services, and graceful shutdown.

Install from the workspace
--------------------------

From a checkout, create the locked development environment and run the test
suite:

.. code-block:: console

   $ uv sync --locked
   $ uv run pytest

An application can then import the public packages directly:

.. code-block:: python

   from aeterna.config import ConfigurationBuilder
   from aeterna.di import ServiceCollection
   from aeterna.runtime import ApplicationBuilder

Install packages individually
-----------------------------

Install only the packages an application needs. A hosted application normally
uses ``aeterna-runtime``; add ``aeterna-config-yaml`` only when it reads YAML.
YAML is an adapter, not a dependency of ``aeterna-config``.

Install the complete framework distribution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``aeterna`` distribution installs ``aeterna-config``,
``aeterna-config-yaml``, ``aeterna-di``, and ``aeterna-runtime``:

.. code-block:: console

   $ python -m pip install aeterna

The distribution contains no additional runtime module. Applications continue
to import from the public modules provided by the component packages.

Install with pip
~~~~~~~~~~~~~~~~

Install the runtime and optional YAML adapter into the active Python
environment:

.. code-block:: console

   $ python -m pip install aeterna-runtime aeterna-config-yaml

Install with uv
~~~~~~~~~~~~~~~

Add the runtime and optional YAML adapter to a ``uv`` project:

.. code-block:: console

   $ uv add aeterna-runtime aeterna-config-yaml

In both cases, the runtime installs its required configuration and DI packages.
Import only from the public ``aeterna`` modules, not package-internal modules.

Development commands
--------------------

.. code-block:: console

   $ uv run pytest
   $ uv run ruff check .
   $ uv run ruff format --check .
   $ uv run mypy
   $ uv run python -m sphinx -W --keep-going -b html docs docs/_build/html

The ``uv run mypy`` command checks the production packages configured in
``pyproject.toml``; the test suite is not included in its target.
