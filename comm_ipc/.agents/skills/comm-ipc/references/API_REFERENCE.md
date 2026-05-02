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
- **`upload_file(file_path, remote_event)`**: Reads a file in chunks and streams it over to the remote IPC event.
- **`download_file(event_name, dest_path)`**: Streams a remote IPC event directly to disk.
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
- **`add_event(channel, event_name, path, method, tags)`**: Expose a specific event at `path`.
- **`add_resource(channel, path_template, tags, method)`**: Expose all discovered events on a channel.
- **`add_subscription(channel, sub_name, path, tags)`**: Expose any topic as a live SSE stream.
- **`add_file_stream(path, channel, event_name, tags)`**: Expose a specific IPC stream as a file/video stream supporting range headers.
- **`add_websocket(path, channel, event_name, tags)`**: Expose any topic as a two-way bidirectional WebSocket.
- **`add_file_upload(path, channel, event_name, tags)`**: Stream an incoming FastAPI request directly into the IPC event listener (Zero Copy/Single-Write).

## `CommData`
The structured message envelope.
- **Fields**: `sender_id`, `server_id`, `channel`, `event`, `data`, `timestamp`, `metadata`, `request_id`, `target_id`, `path`, `is_stream`, `is_final`, `signature`, `origin_server_id`, `sub_name`.

## `CommIPCBridge`
Federation layer to connect two independent CommIPC Hubs.
- **Constructor**: `CommIPCBridge(bridge_id="bridge-net", socket_path1=None, socket_path2=None, ssl_context1=None, ssl_context2=None, allowed_channels=None)`
- **`connect(target1_params, target2_params)`**: Connects both sides of the bridge and automatically begins synchronizing the `allowed_channels`.
- **`stop()`**: Closes bridge connections.

## Examples

### Bidirectional WebSocket Proxy Example
```python
# To expose a bidirectional WebSocket using FastAPI Gateway
api_chan = await client.open("video_chat")
api.add_websocket("/ws", api_chan, "live_stream")
```

### High-Performance File Upload & Download Example
```python
# Provider side
await channel.add_event("file_download", download_handler)

# Consumer side - downloading the file
await channel.download_file("file_download", "/path/to/save.mp4")
```

### Video and File Streaming with Range Headers over FastAPI Example
```python
# Create route that exposes the 'video_feed' streaming IPC event
api_chan = await client.open("media")
api.add_file_stream("/stream/video", api_chan, "video_feed")
```

### Serving Files from a Specific Folder Securely Example with Extractor
```python
import os
from fastapi import HTTPException

def specific_folder_extractor(request):
    filename = request.path_params.get("filename")
    base_dir = os.path.abspath("./public")
    target_path = os.path.abspath(os.path.join(base_dir, filename))
    
    # Securely verify that the file is strictly within the public folder
    if not target_path.startswith(base_dir):
        raise HTTPException(status_code=400, detail="Forbidden")
        
    return {"file_path": target_path}

api_chan = await client.open("files")
api.add_file_stream(
    path="/files/{filename}",
    channel=api_chan,
    event_name="get_file",
    extractor=specific_folder_extractor
)
```

### Direct Streaming User File Uploads over FastAPI to IPC Example (Zero Copy/No Double Write)
```python
from fastapi import UploadFile

@app.post("/upload")
async def upload_file_to_ipc(file: UploadFile):
    # Zero-copy/single-write: Read from file and stream chunks directly to the IPC channel
    chunk_size = 65536
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        # Send binary chunk directly over the IPC channel
        await api_chan.send("incoming_file_chunk", {"chunk": chunk})

    return {"filename": file.filename, "status": "streamed directly to IPC"}
```

### Native add_file_upload on CommAPI Example (Zero-Copy)
```python
# To natively expose a file upload endpoint that streams directly over IPC
api.add_file_upload(
    path="/upload",
    channel=api_chan,
    event_name="incoming_file_chunks"
)
```

### IPC-Side Receiver for Incoming Uploaded Chunks
On the receiver side of the IPC network, add an event listener to append incoming chunks directly to disk:
```python
import os
from comm_ipc.comm_data import CommData

async def save_file_chunks(cd: CommData):
    chunk = cd.data["chunk"]
    filename = cd.data.get("filename") or "default_file.bin"
    
    # Ensure secure and sanitized path
    safe_name = os.path.basename(filename)
    os.makedirs("./uploads", exist_ok=True)
    
    with open(f"./uploads/{safe_name}", "ab") as f:
        f.write(chunk)

# Register the event listener on the worker/provider channel
await chan.add_event("incoming_file_chunks", save_file_chunks)
```

#### Note on Browser Uploads
When uploading a file from the browser using standard JavaScript, attach the filename to the request headers or query parameters to be zero-copy/single-write:
```javascript
fetch('/upload?filename=' + encodeURIComponent(file.name), {
  method: 'POST',
  body: file // Streams raw file blob
});
```
