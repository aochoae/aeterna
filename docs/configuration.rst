Configuration
=============

Configuration loads asynchronous providers into one immutable snapshot. The
core package provides ``MappingProvider`` and ``EnvironmentProvider``.
``YamlProvider`` is available from the optional ``aeterna-config-yaml``
package.

Layering and precedence
-----------------------

Providers load in the order they are added. A later provider has higher
precedence:

* mappings merge recursively when both values are mappings;
* a later scalar, list, or tuple replaces the earlier value;
* ``None`` is a value, so it overrides an earlier value; and
* ``Configuration.source(path)`` returns the provider that last supplied a
  value.

.. mermaid::

    sequenceDiagram
          participant First as Earlier provider
          participant Later as Later provider
          participant Builder as ConfigurationBuilder
          participant Snapshot as Configuration snapshot
          participant Consumer as Application code

          First->>Builder: async load() -> mapping
          Builder->>Builder: copy and validate values
          Later->>Builder: async load() -> overlay mapping
          Builder->>Builder: recursively merge mappings
          Builder->>Builder: replace scalar, list, and tuple values
          Builder->>Builder: record final value provenance and freeze tree
          Builder->>Snapshot: build()
          Consumer->>Snapshot: get(), section(), source(), or bind()

.. code-block:: python

   from aeterna.config import ConfigurationBuilder
   from aeterna.config_yaml import YamlProvider

   builder = ConfigurationBuilder()
   builder.add(YamlProvider("settings.yaml"))
   builder.add_environment(prefix="AETERNA_")
   configuration = await builder.build()

For example, a ``settings.yaml`` value of ``server: {port: 8000}`` is
overridden by ``AETERNA_SERVER__PORT=8080``. The resulting value is the string
``"8080"`` until it is bound to a type.

Environment variables
---------------------

``EnvironmentProvider`` can filter variables by an exact prefix. The default
delimiter, ``__``, turns the remaining name into nested path segments. For
example, ``AETERNA_DATABASE__PORT=5432`` with ``prefix="AETERNA_"`` becomes
``database:port``. By default, path segments are normalized to lower case;
values remain strings until binding.

Use ``case_sensitive=True`` to retain the original case, or select a different
delimiter for another environment convention. Empty path segments and
normalized collisions raise ``MergeError``.

YAML files
----------

``YamlProvider`` reads one YAML mapping document asynchronously with PyYAML.
An empty file produces an empty mapping. A sequence root, multiple documents,
or duplicate keys is invalid. Malformed YAML and file I/O failures become a
sanitized ``ProviderError``; invalid YAML structure that can be described
safely raises ``MergeError``.

Custom and secret providers
---------------------------

Implement the public provider protocol. Give each provider a stable name and
return a mapping:

.. code-block:: python

   import os
   from collections.abc import Mapping

   from aeterna.config import ConfigurationBuilder

   class SecretProvider:
       name = "secret-store"

       async def load(self) -> Mapping[str, object]:
           return {"database": {"password": os.environ["DATABASE_PASSWORD"]}}

   builder = ConfigurationBuilder()
   builder.add(SecretProvider())

Do not log secrets or include them in exceptions. Unexpected provider
exceptions become ``ProviderError`` containing only the provider name. A
provider may raise a sanitized ``MergeError`` when it can safely describe bad
data.

Reading and binding
-------------------

Use colon-delimited paths with ``get``, ``require``, and ``contains``. Use
``section`` to create a view rooted at a mapping, and ``source`` to inspect
provenance. ``as_mapping`` returns an immutable mapping; lists and tuples are
frozen as tuples.

``bind`` converts values to annotated Python types. It supports dataclasses,
``Enum``, ``bool``, ``str``, ``int``, ``float``, unions, sequences,
dictionaries, and ``Any``. Dataclass binding rejects unknown fields and reports
precise paths through ``BindingError``.

Binding errors identify the path and requested type, but deliberately omit the
rejected value and underlying conversion error because configuration values may
contain secrets. The built-in binder is intentionally narrow: it supports
homogeneous sequences and concrete ``dict`` targets, but not heterogeneous
tuples, ``Literal``, arbitrary ``Mapping`` implementations, or application-
specific scalar conversions. Convert those types in application code or bind
to an intermediate dataclass first.

.. code-block:: python

   from dataclasses import dataclass

   @dataclass
   class Settings:
       port: int
       debug: bool = False

   settings = configuration.bind(Settings, "server")

With ``{"server": {"port": "8080", "debug": "true"}}``, this produces
``Settings(port=8080, debug=True)``. Binding is strict: an unknown dataclass
field or an invalid conversion raises ``BindingError`` with its configuration
path.

The diagram's merge step happens once during ``build()``. The resulting
snapshot is immutable, so later reads and bindings never reload a provider.

API details are in :doc:`api/configuration`.
