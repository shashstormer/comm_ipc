# CommIPC API Reference

This document serves as the technical reference for agents interacting with CommIPC.

## `CommIPCServer`
Central router for message parsing, security handshakes, and group routing.
- **Constructor**: `CommIPCServer(server_id=None, socket_path="/tmp/comm_ipc.sock", error_policy="ignore", connection_secret=None, system_passwords=None, channel_policy="terminate", lb_policy="least-active", idle_timeout=60.0, data_timeout=60.0, verbose=False)`
  - *Note on Defaults*: `error_policy` defaults to `"ignore"` (errors are not broadcasted). `lb_policy` defaults to `"least-active"`. `channel_policy` defaults to `"terminate"`.
- **`run(socket_path=None, host=None, port=None, ssl_context=None)`**: Starts the async listening task.
- **`stop()`**: Closes all active connections and terminates the server loop.

## `CommIPC`
The main client interface for communicating with the server.
- **Constructor**: `CommIPC(client_id=None, socket_path="/tmp/comm_ipc.sock", on_error=None, ssl_context=None, connection_secret=None, auto_reconnect=True, reconnect_max_tries=0, idle_timeout=0.0, data_timeout=0.0, heartbeat_interval=30.0, return_type="dict", verbose=False)`
  - *Note on Defaults*: `return_type` defaults to `"dict"`. You **must** set it to `"model"` to enable Pydantic validation. `auto_reconnect` is `True` by default.
- **`connect(host=None, port=None, ssl_context=None, connection_secret=None)`**: Establish connection.
- **`open(chan, password=None)` -> `CommIPCChannel`**: Opens a specific channel and returns a channel object.
- **`set_password(chan, password)`**: Set a channel password (owner only).
- **`wait_till_end()`**: Blocks until connection completely closes.
- **`close()`**: Graceful disconnect.

## `CommIPCChannel`
Returned by `client.open()`. Manages channel-specific RPCs and pub/sub.
- **`add_event(name, call, parameters=None, returns=None, is_group=False)`**: Register an RPC provider.
- **`add_stream(name, call, parameters=None)`**: Register a streaming async generator.
- **`event(event_name, data)` -> `CommData`**: Execute an RPC call.
- **`stream(event_name, data)` -> `AsyncIterator[CommData]`**: Iterate over a data stream.
- **`broadcast(event_name, data)`**: Fire-and-forget message to all channel members.
- **`send(event_name, data)`**: Directed fire-and-forget message.
- **`add_subscription(sub_name, model=None)`**: Declare a subscription schema.
- **`subscribe(sub_name, callback)`**: Listen to a topic.
- **`publish(sub_name, data)`**: Publish a message to subscribers.
- **`on_receive(call, event_name=None)`**: Generic message listener.
- **`explore()` -> `Dict`**: Consolidates all discovered events and subscriptions on this channel.
- **`get_schema(name)` -> `Dict`**: Returns the JSON schema for a specific event or subscription.

## `CommIPCApp` (Decorator API)
A declarative framework wrapper over `CommIPCChannel`.
- **Constructor**: `CommIPCApp(channel=None)`
- **`register(channel)`**: Binds and registers all buffered handlers to the channel.
- **`@provide(name, parameters=None, returns=None)`**: Decorator to register an RPC or stream.
- **`@subscription(name, model=None)`**: Decorator to declare a subscription schema.
- **`@on(event_name)`**: Decorator to listen to events/subscriptions.
- **`group(name)` -> `CommIPCGroup`**: Access a load-balanced group.
- **`@group(name).provide(event_name, ...)`**: Register a provider within a load-balanced group. *Important: The server registers this internally as `"{group_name}.{event_name}"`.*

## `CommAPI` (FastAPI Bridge)
Bridge to expose IPC networks as HTTP endpoints.
- **Constructor**: `CommAPI(app: FastAPI, client: CommIPC)`
- **`add_event(channel, event_name, path, method, tags)`**: Expose a specific event at `path`. If exposing a grouped event, `event_name` must be formatted as `"{group_name}.{event_name}"`.
- **`add_resource(channel, path_template, tags, method)`**: Expose all discovered events on a channel (e.g. `path_template="/api/{event}"`).

## `CommData`
The structured message envelope.
- **Fields**: `sender_id`, `server_id`, `channel`, `event`, `data`, `timestamp`, `metadata`, `request_id`, `target_id`, `path`, `is_stream`, `is_final`, `signature`, `origin_server_id`, `sub_name`.

## `CommIPCBridge`
Federation layer to connect two independent CommIPC Hubs.
- **Constructor**: `CommIPCBridge(bridge_id="bridge-net", socket_path1=None, socket_path2=None, ssl_context1=None, ssl_context2=None, allowed_channels=None)`
- **`connect(target1_params, target2_params)`**: Connects both sides of the bridge and automatically begins synchronizing the `allowed_channels`.
- **`stop()`**: Closes bridge connections.
