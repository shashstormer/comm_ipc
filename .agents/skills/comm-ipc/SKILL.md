---
name: comm-ipc
description: Instructions and guidelines for building asynchronous, type-safe IPC (Inter-Process Communication) applications using the CommIPC library. Use this skill whenever setting up a CommIPC server, client, or FastAPI integration.
license: LGPL-3.0
compatibility: Requires python >= 3.8 and comm-ipc installed.
metadata:
  version: "1.0"
  target: "comm-ipc"
---

# CommIPC Skill

CommIPC is a powerful Python library that bridges the gap between simple Unix sockets and complex message brokers. It provides asynchronous, type-safe, and load-balanced communication via IPC.

When building applications using `comm_ipc`, strictly follow the patterns and architectural guidelines outlined in this document.

## System Architecture

CommIPC uses a central Hub/Server to route messages between clients. It does not use a direct peer-to-peer connection.
1. **Server (`CommIPCServer`)**: Acts as a central router.
2. **Clients (`CommIPC`)**: Connect to the server, join channels, and provide/consume events, streams, or pub/sub messages.
3. **Gateway (`CommAPI`)**: Optional FastAPI bridge to expose IPC endpoints as REST/SSE endpoints.

## Step-by-Step Instructions

### 1. Starting the Server
Before any clients can communicate, you must spin up a `CommIPCServer`. It manages connections, security handshakes, and event routing.
- Refer to [`scripts/server_setup.py`](scripts/server_setup.py) for the standard way to configure load balancing (`lb_policy`) and error handling (`error_policy`).

### 2. Standard RPC (Request-Response)
To perform RPC calls, clients connect to the server and open a channel.
- **Provider**: Registers an event handler using `add_event`.
- **Consumer**: Calls the event using `event`.
- Both sides should use Pydantic models for validation by passing `return_type="model"` in the `CommIPC` client initialization and `parameters=MyModel` in the provider registration.
- Refer to [`scripts/client_rpc.py`](scripts/client_rpc.py) for a complete example.

### 3. Using the App Decorator API (Recommended)
For complex clients or modular design, use the `CommIPCApp` decorator API to bind multiple providers, streams, and groups to a single app object, which is then registered to a channel.
- Register standard RPCs: `@app.provide("event_name", parameters=MyModel)`
- Register Load-Balanced Groups: `@app.group("workers").provide("mult")` *(Note: This internally registers the event as `"workers.mult"`)*
- Register Stream Providers: `@app.provide("stream_name")` (automatically detected if the handler is an async generator)
- Refer to [`scripts/app_decorator_api.py`](scripts/app_decorator_api.py).

### 4. Publisher / Subscriber Pattern
For fan-out notifications or uncoupled event listeners:
- **Declarative Approach (App API)**: Use `@app.subscription("name", model=MyModel)` to define the schema, then `@app.on("name")` to listen.
- **Manual Approach**: Define the subscription using `add_subscription(name, model=MyModel)` to register the schema with the server, then `subscribe(name, callback)`.
- Publish events using `publish(name, MyModel(data=...))`.
- Refer to [`scripts/client_pubsub.py`](scripts/client_pubsub.py).

### 5. Data Streaming
For long-running tasks or large data transfers, use streaming.
- **Provider**: Create an asynchronous generator function (`async def func(): yield chunk`) and register it using `add_stream`.
- **Consumer**: Read using the async iterator `async for chunk in channel.stream(...)`.
- Refer to [`scripts/client_stream.py`](scripts/client_stream.py).

### 6. FastAPI Integration
When exposing CommIPC capabilities over the network:
- Initialize a `FastAPI` app.
- Create a `CommAPI(app, client)` bridge instance.
- Explicitly expose endpoints using `comm_api.add_event()` (for REST) or `comm_api.add_resource()`. Streaming IPC endpoints automatically become Server-Sent Events (SSE).
- **Group Routing**: When exposing a grouped event via `CommAPI`, you must use the full internal name format: `"{group_name}.{event_name}"` (e.g., `comm_api.add_event(..., event_name="workers.mult", ...)`).
- Refer to [`scripts/fastapi_integration.py`](scripts/fastapi_integration.py).

### 7. Advanced Usage (Federation & Monitoring)
For complex multi-hub networks or observability:
- **Bridge Federation**: Connect two separate CommIPC Hubs using `CommIPCBridge`. This transparently routes calls between them. Refer to [`scripts/bridge_federation.py`](scripts/bridge_federation.py).
- **System Monitoring**: Listen to internal read-only system channels (`__comm_ipc_logs`, `__comm_ipc_errors`, `__comm_ipc_system`) for audit logging and diagnostics. Refer to [`scripts/system_monitor.py`](scripts/system_monitor.py).

## Technical References
For deep technical lookups and network design:
- [API Reference](references/API_REFERENCE.md): Detailed method signatures for all core classes.
- [Architecture Diagrams](references/ARCHITECTURE.md): Mermaid visualizations of standard Hub, Gateway, and Federated topologies.
- [Architectural Patterns](references/PATTERNS.md): How to implement 14 distinct distributed systems architectures (Scatter-Gather, CQRS, Saga, etc.) using CommIPC.

## Common Edge Cases & Best Practices
- **Explicit Defaults (CRITICAL)**: Many advanced features are *disabled* by default for maximum performance. You **MUST** manually override the defaults if you want them:
  - Pydantic validation is off by default. You must pass `return_type="model"` to `CommIPC()` to enable it (default is `"dict"`).
  - Server errors are silently ignored by default. You must pass `error_policy="broadcast"` to `CommIPCServer()` to log errors to the system channel (default is `"ignore"`).
  - Load balancing for groups defaults to `"least-active"` (not round-robin).
  - Channels terminate when the owner disconnects (`channel_policy="terminate"`).
- **Reconnection**: Ensure clients are initialized with `auto_reconnect=True` (this *is* the default). On disconnection, CommIPC will automatically attempt to restore the link, re-open channels, and re-register all endpoints/handlers.
- **Data Object**: Remember that callbacks and providers receive a `CommData` object (`cd`). To access the payload, use `cd.data`. The payload will already be parsed into the expected Pydantic model if configured correctly.
- **Passwords**: If you are using channel passwords, ensure `channel.set_password()` is executed by the first member (owner), and subsequent members provide it in `client.open(chan, password=...)`.
