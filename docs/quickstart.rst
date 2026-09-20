Quickstart
==========

This application builds configuration, registers a service, and runs a
short-lived callback. ``Configuration`` and ``CancellationToken`` are also
registered automatically, so services can request them by type.

.. code-block:: python

   from dataclasses import dataclass

   from aeterna.config import Configuration, MappingProvider
   from aeterna.di import ServiceCollection, ServiceLifetime
   from aeterna.runtime import ApplicationBuilder, ApplicationContext, run

   @dataclass
   class Greeter:
       configuration: Configuration

       def greet(self, name: str) -> str:
           return f"{self.configuration.require('greeting:prefix')}, {name}!"

   def register(services: ServiceCollection, _: Configuration) -> None:
       services.add_type(Greeter, lifetime=ServiceLifetime.SINGLETON)

   async def main(context: ApplicationContext) -> str:
       message = (await context.services.get(Greeter)).greet("world")
       print(message)
       return message

   builder = ApplicationBuilder()
   builder.add_configuration(MappingProvider({"greeting": {"prefix": "Hello"}}))
   builder.configure_services(register)

   if __name__ == "__main__":
       run(builder, main)

Running the file prints ``Hello, world!``. ``ApplicationBuilder.build()``
loads providers, calls service configurators with the resulting immutable
snapshot, registers ``Configuration`` and ``CancellationToken``, and freezes
the composition. ``run`` then starts the application, invokes ``main``, and
stops it.

See :doc:`application-patterns` for variants that stay alive and
:doc:`embedding` when the event loop belongs to another application.
