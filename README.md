# CommIPC: Asynchronous IPC for Linux

## Installation

```bash
pip install comm-ipc
```

## Why CommIPC?

CommIPC bridges the gap between simple Unix sockets and complex message brokers like RabbitMQ. It gives you Type-Safe, Asynchronous communication with the ease of a local function call.

---

## Quick Start

This script demonstrates a basic server and client interaction in a single file.

```python
import asyncio
from comm_ipc.server import CommIPCServer
from comm_ipc.client import CommIPC

async def main():
    # Start server
    server = CommIPCServer(socket_path="/tmp/quickstart.sock")
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1)  # Wait for server to start

    # Start client
    client = CommIPC(socket_path="/tmp/quickstart.sock")
    await client.connect()
    
    channel = await client.open("demo")

    # Register an event
    async def hello_handler(cd):
        return {"msg": f"Hello, {cd.data['name']}"}
    
    await channel.add_event("hello", hello_handler)

    # Call the event
    res = await channel.event("hello", {"name": "World"})
    print(res.data["msg"])

    # Shutdown
    await client.close()
    await server.stop()
    server_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Connectivity and Transport

CommIPC supports several transport layers:
- **Local**: Unix Domain Sockets.
- **Remote**: TCP connections.
- **Secure**: SSL/TLS encryption for TCP.

### Initialization

```python
from comm_ipc.server import CommIPCServer
from comm_ipc.client import CommIPC

# Server setup
server = CommIPCServer(socket_path="/tmp/comm_ipc.sock")
await server.run()

# Client setup
client = CommIPC(socket_path="/tmp/comm_ipc.sock")
await client.connect()
```

---

## System Reference: CommIPCServer

CommIPCServer manages routing and security handshakes.

### Constructor: `CommIPCServer`
- `server_id` (str): Unique server ID.
- `socket_path` (str): Path to the Unix socket. Default: `/tmp/comm_ipc.sock`.
- `error_policy` (str): Behavior on exceptions (`"ignore"`, `"raise"`, `"broadcast"`).
- `connection_secret` (str): Secret for HMAC-SHA256 handshakes.
- `system_passwords` (Dict[str, str]): Pre-set channel passwords.
- `channel_policy` (str): Behavior on owner disconnect. 
  - `"terminate"`: Close the channel (default).
  - `"promote"`: Promote the next earliest member to owner.
- `lb_policy` (str): Load balancing policy for group events.
  - `"least-active"`: Send to provider with fewest pending calls (default).
  - `"round-robin"`: Cycle through providers sequentially.
- `idle_timeout` (float): Header read timeout. Default: `60.0`.
- `data_timeout` (float): Body read timeout. Default: `60.0`.
- `verbose` (bool): log output.

### Methods
- `await run(socket_path, host, port, ssl_context)`: Start the server on a socket or TCP address.
- `await stop()`: Close all links and stop the server.

---

## System Reference: CommIPC (Client)

CommIPC is the main client interface.

### Constructor: `CommIPC`
- `client_id` (str): Unique client ID.
- `socket_path` (str): Path to the Unix socket.
- `on_error` (Callable): Callback for errors.
- `ssl_context`: SSL context for TCP.
- `connection_secret` (str): Handshake secret.
- `auto_reconnect` (bool): Automatic reconnection. Default: `True`.
- `reconnect_max_tries` (int): Retry limit. `0` means unlimited.
- `idle_timeout` (float): Header read timeout.
- `data_timeout` (float): Body read timeout.
- `heartbeat_interval` (float): Ping frequency. Default: `30.0`.
- `return_type` (str): Data format (`"dict"` or `"model"`). Default: `"dict"`.
- `verbose` (bool): Log output.

### Methods
- `await connect(host, port, ssl_context, connection_secret)`: Establish a link.
- `await open(chan, password)`: Open a channel and return a `CommIPCChannel`.
- `await set_password(chan, password)`: Set a channel password (owner only).
- `await call(chan, ev, data)`: Perform a request-response call.
- `stream(chan, ev, data)`: Async iterator for data streams.
- `await add_subscription(chan, sub_name, parameters)`: Register a subscription endpoint.
- `await remove_subscription(chan, sub_name)`: Remove a subscription.
- `await subscribe(chan, sub_name, callback)`: Receive data from a stream.
- `await unsubscribe(chan, sub_name)`: Stop receiving data.
- `await publish(chan, sub_name, data)`: Send data to subscribers. Accepts dict or `BaseModel`.
- `await wait_till_end()`: Wait until the connection terminates.
- `await close()`: Disconnect from the server.
- `on_msg`: Callback for all incoming messages.

---

## System Reference: CommIPCChannel

`CommIPCChannel` objects handle channel-specific interactions.

### Methods
- `await add_event(name, call, parameters, returns, is_group)`: Register an RPC handler. If `is_group` is True, it registers as a load-balanced provider.
- `await add_stream(name, call, parameters)`: Register a stream handler (automatically detects async generators).
- `await event(event_name, data)`: Call a remote RPC event.
- `stream(event_name, data)`: Collect a remote stream.
- `await broadcast(event_name, data)`: Send to all channel members.
- `await send(event_name, data)`: Send to a provider without a response.
- `await add_subscription(sub_name, model)`: Register a channel subscription schema.
- `await remove_subscription(sub_name)`: Remove a channel subscription.
- `await subscribe(sub_name, callback)`: Channel-level subscription.
- `await unsubscribe(sub_name)`: Channel-level unsubscription.
- `await publish(sub_name, data)`: Channel-level publishing. Accepts dict or `BaseModel`.
- `on_receive(call, event_name)`: Attach a listener for specific or all messages.
- `explore()`: List discovered events and subscriptions.
- `get_schema(name)`: Get the Pydantic schema for an endpoint.

---

## System Reference: CommIPCApp

`CommIPCApp` provides a declarative, decorator-based interface for `CommIPCChannel`.

### Constructor: `CommIPCApp`
- `channel` (`CommIPCChannel`, optional): The open channel instance to wrap. If provided, registration happens immediately.

### Methods
- **`await app.register(channel)`**: 
  Binds the app to a channel and registers all buffered handlers/listeners. This is the recommended way to initialize a top-level `CommIPCApp`.

### Decorators
- **`@app.provide(name, parameters, returns)`**: 
  Registers an asynchronous handler as an event provider. Automatically detects if the handler is an async generator for streaming support.
- **`@app.on(event_name)`**: 
  Attaches a listener to the channel. If an `event_name` is provided, it also automatically handles the server-side `subscribe()` call.
- **`@app.group.provide(name, parameters, returns)`**: 
  Registers a load-balanced group event provider.
- **`@app.subscription(name, model)`**: 
  Declares a subscription schema. This is a non-blocking way to ensure the server is aware of the subscription metadata, which is required before calling `publish()`.
- **`app.group(name: str)`**:
  Returns a `CommIPCAppGroup` helper for the specified load-balanced group.

### CommIPCAppGroup Reference
- **`@group.provide(name, parameters, returns)`**:
  Registers an event provider within the group. Calls to this event will be load-balanced across all providers in the group.

---

## System Reference: CommIPCGroup

`CommIPCGroup` provides an interface for load-balanced event groups. It is accessed via `channel.group`.

### Methods
- **`__call__(name: str)`**:
  Returns a `CommIPCGroup` instance scoped to the specified group name.
- **`await provide(event, handler, parameters, returns)`**: 
  Registers a provider for an event within this group.
- **`await get(event, data)`**: 
  Calls an event within the group (load balanced).
- **`stream(event, data)`**: 
  Returns an async iterator for a grouped stream (load balanced).

---
### Example Usage (Decoupled API)
 
```python
from comm_ipc import CommIPCApp, CommIPC
from comm_ipc.comm_data import CommData
from pydantic import BaseModel
import asyncio

# 1. Define App at top level (FastAPI-style)
app = CommIPCApp()

# 2. Define a data model
class MathParams(BaseModel):
    a: int
    b: int

# 3. Register a provider
@app.provide("add", parameters=MathParams)
async def add(cd: CommData):
    return cd.data.a + cd.data.b

# 4. Register a streaming provider (detected automatically)
@app.provide("counter")
async def count_up(cd: CommData):
    for i in range(5):
        yield {"count": i}

# 5. Register a group provider
@app.group("workers").provide("mult")
async def mult(cd: CommData):
    return cd.data["a"] * cd.data["b"]

# 6. Listen to subscriptions
@app.on("updates")
async def handle_update(cd: CommData):
    print(f"System Status: {cd.data['status']}")

async def main():
    client = CommIPC(socket_path="/tmp/comm_ipc.sock")
    await client.connect()
    chan = await client.open("math")
    
    # 7. Bind and register all handlers
    await app.register(chan)
    
    await client.wait_till_end()

if __name__ == "__main__":
    asyncio.run(main())
```
 
---
 
### Load Balancing (Event Groups)
 
When multiple providers register for the same event, it creates a conflict unless **Groups** are used. By grouping providers, the server automatically load-balances calls (using a `least-active` or `round-robin` policy).
 
#### Standard API
 
```python
# Provider A
await channel.group("workers").add_event("process", handle_a)
 
# Provider B
await channel.group("workers").add_event("process", handle_b)
 
# Consumer
res = await channel.group("workers").event("process", data)
```
 
#### Decorator API
 
```python
# Create a named group decorator
workers = app.group("workers")
 
@workers.provide("process")
async def handle(cd):
    ...
```
 
---
 
## Code Examples

### Request-Response (RPC)

```python
import asyncio
from pydantic import BaseModel
from comm_ipc import CommIPC, CommData

class MathParams(BaseModel):
    a: int
    b: int

async def main():
    # 1. Setup client with model support
    client = CommIPC(return_type="model") 
    await client.connect()
    channel = await client.open("math_engine")

    # 2. Register a provider
    async def add_handler(cd: CommData):
        # cd.data is automatically a MathParams instance
        return {"result": cd.data.a + cd.data.b}
    
    await channel.add_event("add", add_handler, parameters=MathParams)

    # 3. Call the provider
    res = await channel.event("add", MathParams(a=10, b=20))
    print(f"Result: {res.data['result']}") 

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Publisher-Subscriber

```python
import asyncio
from pydantic import BaseModel
from comm_ipc import CommIPC

class User(BaseModel):
    id: int
    name: str

async def main():
    client = CommIPC(return_type="model")
    await client.connect()
    channel = await client.open("social")

    # 1. Declare and Subscribe
    async def on_user(cd):
        # cd.data is automatically an instance of User
        print(f"New user joined: {cd.data.name}") 

    await channel.subscribe("join_events", on_user)

    # 2. Publish
    # Note: add_subscription is required before publishing to register the schema
    await channel.add_subscription("join_events", model=User)
    await channel.publish("join_events", User(id=1, name="Alice"))
    
    await asyncio.sleep(0.5) # Give it time to arrive
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Streaming

```python
import asyncio
from comm_ipc import CommIPC

async def main():
    client = CommIPC()
    await client.connect()
    channel = await client.open("streams")

    # 1. Provider (Async Generator)
    async def count_up(cd):
        for i in range(cd.data["limit"]):
            yield {"count": i}

    await channel.add_stream("counter", count_up)

    # 2. Consumer
    async for chunk in channel.stream("counter", {"limit": 5}):
        print(f"Received: {chunk.data['count']}")

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Messaging and Listeners

```python
import asyncio
from comm_ipc import CommIPC

async def main():
    client = CommIPC()
    await client.connect()
    channel = await client.open("monitor")

    async def on_event(cd):
        print(f"Message from {cd.sender_id}: {cd.data}")

    # Listen for specific event
    channel.on_receive(on_event, "alert")
    
    # Broadcast to everyone
    await channel.broadcast("alert", {"msg": "System going down!"})
    
    # Send directed message (no response expected)
    await channel.send("alert", {"msg": "Individual warning"})

    await asyncio.sleep(0.1)
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Security and Passwords

```python
import asyncio
from comm_ipc import CommIPC

async def main():
    client = CommIPC()
    await client.connect()

    # 1. Open and set password (Owner)
    channel = await client.open("secure_vault")
    await client.set_password("secure_vault", "secret123")
    
    # 2. Open with password (Member)
    # This would typically be in a separate process
    client2 = CommIPC(client_id="guest")
    await client2.connect()
    try:
        chan2 = await client2.open("secure_vault", password="secret123")
        print("Successfully accessed vault!")
    except Exception as e:
        print(f"Access denied: {e}")

    await client2.close()
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## System Reference: CommData (Message Object)

`CommData` models all messages and metadata.

### Fields
- `sender_id` (str): Sender identifier.
- `server_id` (str): Routing server identifier.
- `channel` (str): Channel name.
- `event` (str): Event name or subscription ID.
- `data` (Any): Message content.
- `timestamp` (int): Creation timestamp.
- `metadata` (Dict): Additional data.
- `request_id` (str): Correlation ID for calls.
- `target_id` (str): Recipient identifier.
- `path` (List[str]): Chain of routing servers.
- `is_stream` (bool): Stream flag.
- `is_final` (bool): End-of-stream flag.
- `signature` (str): Message integrity signature.
- `origin_server_id` (str): First server in the chain.
- `sub_name` (str): Subscription identifier.

---

## System Reference: CommIPCBridge

`CommIPCBridge` synchronizes two separate hubs.

### Constructor: `CommIPCBridge`
- `bridge_id` (str): Bridge identifier.
- `socket_path1`, `socket_path2` (str): Local socket paths.
- `ssl_context1`, `ssl_context2`: SSL contexts.
- `allowed_channels` (List[str]): List of channels to sync. Default: all.

### Methods
- `await connect(target1_params, target2_params)`: Connect two targets.
- `await stop()`: Stop the bridge.

```python
from comm_ipc.bridge import CommIPCBridge

bridge = CommIPCBridge(bridge_id="bridge-1")
await bridge.connect(
    target1_params={"socket_path": "/tmp/s1.sock"},
    target2_params={"socket_path": "/tmp/s2.sock"}
)
```

---

## System Reference: System Channels

The server provides read-only channels for monitoring:
- `__comm_ipc_logs`: Server log broadcast.
- `__comm_ipc_errors`: Global error broadcast.
- `__comm_ipc_system`: System event broadcast (e.g., `new_registration`).

## Running Examples & Demos

The repository includes a comprehensive `examples/` directory demonstrating various communication patterns.

### Quick Start: All Demos
To run the full integration suite and verify your installation:
```bash
chmod +x examples/run_demos.sh
./examples/run_demos.sh
```

### Manual Examples
You can run individual examples by starting the server first:
1. **Start Server**: `python examples/server.py`
2. **Start Provider**: `python examples/rpc_prov.py`
3. **Run Client**: `python examples/rpc_client.py`

Other examples include:
- `decorator_prov.py` / `decorator_client.py`: Modern decoupled API.
- `pub_prov.py` / `sub_client.py`: Publish/Subscribe pattern.
- `stream_prov.py` / `stream_client.py`: Async streaming.
- `decoupled_demo.py`: "FastAPI-style" top-level application structure.

## Resilience

Clients recover state automatically if `auto_reconnect` is `True`. On reconnection, the client:
1. Re-identifies with the same ID.
2. Re-opens and authenticates active channels.
3. Re-registers all handlers and endpoints.

## License
Licensed under the LGPLv3 License.
