Embedding Aeterna
=================

Use embedding when another framework owns the event loop, process signals, or
the server. Build and manage the Aeterna application inside that framework's
lifecycle. The host should build the application once, start it before
accepting requests, await ``Application.wait()`` while hosted services run,
and stop it during shutdown:

.. code-block:: python

   import asyncio

   from aeterna.runtime import ApplicationBuilder, ApplicationContext


   class Worker:
       async def start(self, _: ApplicationContext) -> None:
           pass

       async def run(self, context: ApplicationContext) -> None:
           await context.cancellation.wait()

       async def stop(self, _: ApplicationContext) -> None:
           pass

   builder = ApplicationBuilder()
   builder.add_hosted_service(Worker)

   async def run_inside_existing_app() -> None:
       application = await builder.build()
       await application.start()
       try:
           await application.wait()
       finally:
           await application.stop()


   if __name__ == "__main__":
       asyncio.run(run_inside_existing_app())

The caller owns the loop, so it must arrange signal handling and decide when
to stop the application. Aeterna still owns registered service resources and
lifecycle callbacks. Do not call ``runtime.run`` from an already running
event loop.

.. mermaid::

   sequenceDiagram
       participant Host as External host (FastAPI, gRPC, worker)
       participant Builder as ApplicationBuilder
       participant App as Application
       participant Provider as ServiceProvider
       participant Scope as ServiceScope

       Host->>Builder: await build() during host startup
       Builder-->>Host: Application
       Host->>App: await start()
       Host->>App: await wait() while hosted services run
       Note over Host,App: Host owns the event loop, signals, and server
       Host->>Provider: create_scope() for one request, RPC, or job
       Provider-->>Scope: explicit scope
       Host->>Scope: resolve scoped application service
       Scope-->>Host: close at unit-of-work end
       Host->>App: await stop() during host shutdown
       App->>Provider: close root-owned resources

The examples below use the same small application: a configuration-backed
``GreetingService`` is scoped to one request, while its immutable
``Configuration`` snapshot is shared by the application. The service is
resolved through an explicit scope instead of being constructed directly by
the transport framework.

.. _fastapi-integration:

FastAPI integration
-------------------

FastAPI's lifespan context is the right place to start and stop Aeterna. Each
request creates a ``ServiceScope`` so that scoped services are isolated and
closed when the request finishes.

Save this as ``fastapi_app.py``:

.. code-block:: python

   from contextlib import asynccontextmanager

   from fastapi import FastAPI, Request

   from aeterna.config import Configuration, MappingProvider
   from aeterna.di import ServiceCollection, ServiceLifetime
   from aeterna.runtime import ApplicationBuilder


   class GreetingService:
       def __init__(self, configuration: Configuration) -> None:
           self._prefix = str(configuration.require("greeting:prefix"))

       async def greet(self, name: str) -> dict[str, str]:
           return {"message": f"{self._prefix}, {name}!"}


   def configure_services(services: ServiceCollection, _: Configuration) -> None:
       services.add_type(GreetingService, lifetime=ServiceLifetime.SCOPED)


   builder = ApplicationBuilder()
   builder.add_configuration(MappingProvider({"greeting": {"prefix": "Hello"}}))
   builder.configure_services(configure_services)


   @asynccontextmanager
   async def lifespan(app: FastAPI):
       application = await builder.build()
       await application.start()
       app.state.aeterna = application
       try:
           yield
       finally:
           await application.stop()


   app = FastAPI(lifespan=lifespan)


   @app.get("/greet/{name}")
   async def greet(name: str, request: Request) -> dict[str, str]:
       application = request.app.state.aeterna
       async with application.context.services.create_scope() as scope:
           service = await scope.get(GreetingService)
           return await service.greet(name)

The example assumes an application project has Aeterna and the transport
dependencies installed. With ``uv``, install them with:

.. code-block:: console

   $ uv add aeterna-runtime fastapi uvicorn

When working from this repository, ``uv sync --locked`` supplies the local
Aeterna workspace packages; add ``fastapi`` and ``uvicorn`` to the application
environment if they are not already present. Start the example with:

.. code-block:: console

   $ uv run uvicorn fastapi_app:app --reload
   $ curl http://127.0.0.1:8000/greet/Ada
   {"message":"Hello, Ada!"}

Uvicorn owns the process and event loop. Its startup invokes the FastAPI
lifespan, which builds the configuration snapshot, validates the DI graph,
and starts Aeterna. Its shutdown invokes the ``finally`` block, which requests
cancellation, runs lifecycle cleanup, closes owned resources, and is safe to
call exactly once. Do not rebuild the application or reuse a request scope
for multiple requests.

gRPC integration (pseudocode)
-----------------------------

gRPC uses the same composition and scope rules. The transport adapter resolves
the application service inside each unary RPC, while ``grpc.aio`` owns the
network server and its event loop. First define the contract in
``greeting.proto``:

.. code-block:: protobuf

   syntax = "proto3";

   package greeting;

   service Greeter {
     rpc Greet (GreetRequest) returns (GreetReply);
   }

   message GreetRequest {
     string name = 1;
   }

   message GreetReply {
     string message = 1;
   }

Generate the Python modules, then save the following as ``grpc_server.py``.
The generated ``greeting_pb2`` and ``greeting_pb2_grpc`` imports are shown in
their usual ``grpcio-tools`` form; the signal and deployment setup is left to
the surrounding service runner, hence the pseudocode label.

.. code-block:: python

   import asyncio

   import grpc

   import greeting_pb2
   import greeting_pb2_grpc
   from aeterna.config import Configuration, MappingProvider
   from aeterna.di import ServiceCollection, ServiceLifetime
   from aeterna.runtime import Application, ApplicationBuilder


   class GreetingService:
       def __init__(self, configuration: Configuration) -> None:
           self._prefix = str(configuration.require("greeting:prefix"))

       async def greet(self, name: str) -> str:
           return f"{self._prefix}, {name}!"


   def configure_services(services: ServiceCollection, _: Configuration) -> None:
       services.add_type(GreetingService, lifetime=ServiceLifetime.SCOPED)


   class GreeterEndpoint(greeting_pb2_grpc.GreeterServicer):
       def __init__(self, application: Application) -> None:
           self._application = application

       async def Greet(self, request, context):  # noqa: N802 - generated RPC name
           async with self._application.context.services.create_scope() as scope:
               service = await scope.get(GreetingService)
               message = await service.greet(request.name)
           return greeting_pb2.GreetReply(message=message)


   async def serve() -> None:
       builder = ApplicationBuilder()
       builder.add_configuration(MappingProvider({"greeting": {"prefix": "Hello"}}))
       builder.configure_services(configure_services)

       application = await builder.build()
       server = grpc.aio.server()
       greeting_pb2_grpc.add_GreeterServicer_to_server(
           GreeterEndpoint(application), server
       )
       server.add_insecure_port("[::]:50051")

       await application.start()
       tasks: list[asyncio.Task[object]] = []
       try:
           await server.start()
           application_wait = asyncio.create_task(application.wait())
           server_wait = asyncio.create_task(server.wait_for_termination())
           tasks.extend((application_wait, server_wait))
           done, _ = await asyncio.wait(
               set(tasks),
               return_when=asyncio.FIRST_COMPLETED,
           )
           if application_wait in done:
               await application_wait
       finally:
           for task in tasks:
               if not task.done():
                   task.cancel()
           await asyncio.gather(*tasks, return_exceptions=True)
           await server.stop(grace=10)
           await application.stop()


   if __name__ == "__main__":
       asyncio.run(serve())

Install the runtime and gRPC packages in the application project:

.. code-block:: console

   $ uv add aeterna-runtime grpcio grpcio-tools
   $ uv run python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. greeting.proto

Run the server with ``uv run python grpc_server.py``. A gRPC client such as
``grpcurl`` can call it after startup:

.. code-block:: console

   $ grpcurl -plaintext -d '{"name":"Ada"}' \
       127.0.0.1:50051 greeting.Greeter/Greet
   {
     "message": "Hello, Ada!"
   }

The ``server.start()`` and ``server.wait_for_termination()`` calls represent
the gRPC host's normal serving phase. In production, connect SIGINT/SIGTERM
or the runner's shutdown callback to the gRPC server's graceful stop path;
the ``finally`` block must stop gRPC before stopping Aeterna so no new RPCs
arrive while the provider is closing. For streaming RPCs, use the same rule:
create one scope for the RPC lifetime and close it when the stream ends.

Choosing a transport
--------------------

Use FastAPI when the boundary is HTTP/JSON, browser or public-client
compatibility, OpenAPI documentation, or a broad HTTP middleware ecosystem.
Use gRPC when services are primarily internal, clients can use generated
protobuf types, and efficient binary transport, strict contracts, or
streaming matter. The choice affects only the adapter and server lifecycle;
the Aeterna builder, application lifecycle, configuration, and explicit DI
scopes remain the same.
