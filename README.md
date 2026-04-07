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
- `channel_policy` (str): Behavior on owner disconnect (e.g., `"terminate"`).
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
- `await add_event(name, call, parameters, returns)`: Register an RPC handler.
- `await add_stream(name, call, parameters)`: Register a stream handler.
- `await event(event_name, data)`: Call a remote RPC event.
- `stream(event_name, data)`: Collect a remote stream.
- `await broadcast(event_name, data)`: Send to all channel members.
- `await send(event_name, data)`: Send to a provider without a response.
- `await add_subscription(sub_name, parameters)`: Register a channel subscription.
- `await remove_subscription(sub_name)`: Remove a channel subscription.
- `await subscribe(sub_name, callback)`: Channel-level subscription.
- `await unsubscribe(sub_name)`: Channel-level unsubscription.
- `await publish(sub_name, data)`: Channel-level publishing. Accepts dict or `BaseModel`.
- `on_receive(call, event_name)`: Attach a listener for specific or all messages.
- `explore()`: List discovered events and subscriptions.
- `get_schema(name)`: Get the Pydantic schema for an endpoint.

---

## Code Examples

### Request-Response (RPC)

```python
from pydantic import BaseModel
from comm_ipc.client import CommIPC

class MathParams(BaseModel):
    a: int
    b: int

# Provider
async def add_handler(cd):
    assert isinstance(cd.data, MathParams)
    return {"result": cd.data.a + cd.data.b}

# Consumer
client = CommIPC(return_type="model") # Enables automated model reception
channel = await client.open("math")
await channel.add_event("add", add_handler, parameters=MathParams)

res = await channel.event("add", MathParams(a=10, b=20))
print(f"Result: {res.data['result']}") # cd.data is automatically a model instance
```

### Publisher-Subscriber

```python
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str

# Publisher
await channel.add_subscription("news", model=User)
await channel.publish("news", User(id=1, name="Alice"))

# Subscriber
async def on_data(cd):
    # cd.data is automatically an instance of User (local or dynamic)
    print(f"Got user: {cd.data.name}") 

await channel.subscribe("news", on_data)
```

### Streaming

```python
# Provider
async def count_up(cd):
    for i in range(cd.data["limit"]):
        yield i

await channel.add_stream("counter", count_up)

# Consumer
async for chunk in channel.stream("counter", {"limit": 5}):
    print(chunk.data)
```

### Messaging and Listeners

```python
# Send: Directed message to a provider (no response)
await channel.send("log", {"level": "info", "msg": "event started"})

# Broadcast: Message to every client in the channel
await channel.broadcast("system_update", {"status": "maintenance"})

# Listen: specific event
async def on_update(cd):
    print(f"Update: {cd.data}")

channel.on_receive(on_update, "system_update")

# Listen: generic channel observer
async def on_any(cd):
    print(f"Channel {cd.channel} got {cd.event}")

channel.on_receive(on_any)
```

### Security and Passwords

```python
# Set password (owner)
channel = await client.open("secure")
await client.set_password("secure", "password123")

# Open with password (client)
channel = await client.open("secure", password="password123")
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

## Resilience

Clients recover state automatically if `auto_reconnect` is `True`. On reconnection, the client:
1. Re-identifies with the same ID.
2. Re-opens and authenticates active channels.
3. Re-registers all handlers and endpoints.

## License
Licensed under the LGPLv3 License.
