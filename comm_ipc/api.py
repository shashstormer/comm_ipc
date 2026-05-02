import asyncio
import json
from typing import Any, List, Optional, TYPE_CHECKING, Dict, Callable

try:
    from fastapi import FastAPI, Body, Request, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import StreamingResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    if TYPE_CHECKING:
        from fastapi import FastAPI, Body, Request, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.responses import StreamingResponse

from comm_ipc.channel import CommIPCChannel
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData

class CommAPI:
    def __init__(self, app: "FastAPI", client: CommIPC):
        if not HAS_FASTAPI:
            raise RuntimeError(
                "FastAPI is required to use CommAPI. "
                "Install it with: pip install 'comm-ipc[fastapi]'"
            )
        self.app = app
        self.client = client
        self.mounted_channels: List[str] = []
        self._dynamic_routes: Dict[str, Dict[str, Any]] = {} # path -> info
        self._old_openapi = self.app.openapi
        self.app.openapi = self._custom_openapi

    def _get_handler(self, channel: CommIPCChannel, event_name: str, is_stream: bool = False):
        async def rpc_handler(data: Any):
            try:
                info = channel.get_schema(event_name)
                if info:
                    param_schema = info.get("parameters") or info.get("param_schema")
                    if param_schema:
                        data = channel.validate_data(data, param_schema)

                res = await channel.event(event_name, data)
                if isinstance(res, CommData):
                    return res.data
                return res
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        async def stream_handler(data: Any):
            async def event_generator():
                try:
                    async for chunk in channel.stream(event_name, data):
                        if isinstance(chunk, CommData):
                            yield f"data: {json.dumps(chunk.data)}\n\n"
                        else:
                            yield f"data: {json.dumps(chunk)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        return stream_handler if is_stream else rpc_handler

    def add_event(self, channel: CommIPCChannel, event_name: str, path: str, method: str = "POST", tags: Optional[List[str]] = None):
        """Mounts a specific IPC event to a FastAPI route."""
        info = channel.get_schema(event_name)
        if not info:
             channel.explore()
             info = channel.get_schema(event_name)
        
        is_stream = False
        if info:
            is_stream = info.get("is_stream", False)
                
        param_model = None
        params_info = info.get("parameters") or info.get("param_schema")
        if info and params_info:
            if isinstance(params_info, dict) and "properties" in params_info:
                param_model = channel._create_model_from_schema(f"{event_name}Request", params_info)
            else:
                 param_model = Any

        response_model = None
        returns_info = info.get("returns") or info.get("return_schema")
        if info and returns_info and not is_stream:
             if isinstance(returns_info, dict) and "properties" in returns_info:
                 response_model = channel._create_model_from_schema(f"{event_name}Response", returns_info)

        handler = self._get_handler(channel, event_name, is_stream)
        
        self._dynamic_routes[path] = {
            "channel": channel,
            "event_name": event_name,
            "method": method,
            "tags": tags or [f"Channel: {channel.name}"],
            "is_stream": is_stream
        }

        if is_stream or method == "GET":
            async def wrapped_handler(request: Request):
                data = dict(request.query_params)
                return await handler(data)
        else:
            async def wrapped_handler(data: Any = Body(None)):
                return await handler(data)

        if is_stream:
            self.app.get(path, tags=tags)(wrapped_handler)
        else:
            self.app.api_route(path, methods=[method], tags=tags)(wrapped_handler)

    def _custom_openapi(self):
        if self.app.openapi_schema:
            return self.app.openapi_schema

        openapi_schema = self._old_openapi()
        
        for path, info in self._dynamic_routes.items():
            chan = info["channel"]
            ev_name = info["event_name"]
            method = info["method"].lower()
            
            schema_info = chan.get_schema(ev_name)
            if not schema_info: continue

            if path in openapi_schema["paths"] and method in openapi_schema["paths"][path]:
                op = openapi_schema["paths"][path][method]
                
                params = schema_info.get("parameters") or schema_info.get("param_schema")
                if params and method != "get":
                    title = params.get("title", f"{ev_name}Request")
                    if "components" not in openapi_schema: openapi_schema["components"] = {}
                    if "schemas" not in openapi_schema["components"]: openapi_schema["components"]["schemas"] = {}
                    
                    openapi_schema["components"]["schemas"][title] = params
                    op["requestBody"] = {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{title}"}
                            }
                        }
                    }

                returns = schema_info.get("returns") or schema_info.get("return_schema")
                if returns and not info["is_stream"]:
                    title = returns.get("title", f"{ev_name}Response")
                    openapi_schema["components"]["schemas"][title] = returns
                    op["responses"]["200"] = {
                        "description": "Successful Response",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{title}"}
                            }
                        }
                    }

        self.app.openapi_schema = openapi_schema
        return openapi_schema

    def add_resource(self, channel: CommIPCChannel, path_template: str = "/{event}", tags: Optional[List[str]] = None, method: str = "POST"):
        """Mounts all discovered events of a channel based on a path template."""
        info = channel.explore()
        events = info.get("events", {})
        
        if not tags:
            tags = [f"Channel: {channel.name}"]

        for event_name in events:
            clean_event_path = event_name.replace(".", "/")
            path = path_template.replace("{event}", clean_event_path)
            self.add_event(channel, event_name, path, method=method, tags=tags)

        self.mounted_channels.append(channel.name)

    def add_subscription(self, channel: CommIPCChannel, sub_name: str, path: str, tags: Optional[List[str]] = None):
        """
        Exposes an IPC subscription as an SSE (Server-Sent Events) endpoint.
        """
        tags = tags or [f"Subscription: {channel.name}"]

        @self.app.get(path, tags=tags)
        async def sse_subscription(request: Request):
            limit = request.query_params.get("limit")
            limit = int(limit) if limit and limit.isdigit() else None

            async def event_generator():
                queue = asyncio.Queue(maxsize=100)
                async def callback(cd: CommData):
                    try:
                        queue.put_nowait(cd.data)
                    except asyncio.QueueFull:
                        pass

                await channel.subscribe(sub_name, callback)
                try:
                    count = 0
                    while True:
                        if limit is not None and count >= limit:
                            break
                        if await request.is_disconnected():
                            break
                        try:
                            data = await asyncio.wait_for(queue.get(), timeout=2.0)
                            yield f"data: {json.dumps(data)}\n\n"
                            count += 1
                        except asyncio.TimeoutError:
                            yield ": keep-alive\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                finally:
                    await channel.unsubscribe(sub_name)

            return StreamingResponse(event_generator(), media_type="text/event-stream")

    def add_file_stream(self, path: str, channel: CommIPCChannel, event_name: str, extractor: Optional[Callable[[Request], Dict[str, Any]]] = None, tags: Optional[List[str]] = None):
        """
        Exposes an IPC streaming event as a file/video streaming endpoint with full support for the
        Range header (Partial Content). Supports dynamic path parameters with an optional custom extractor.
        """
        tags = tags or [f"File: {channel.name}"]

        @self.app.get(path, tags=tags)
        async def file_stream_route(request: Request):
            range_header = request.headers.get("range")
            
            async def event_generator():
                try:
                    start_pos = 0
                    end_pos = None
                    if range_header and range_header.startswith("bytes="):
                        parts = range_header.split("=")[1].split("-")
                        if parts[0]:
                            start_pos = int(parts[0])
                        if len(parts) > 1 and parts[1]:
                            end_pos = int(parts[1])

                    req_data = {}
                    if extractor:
                        if asyncio.iscoroutinefunction(extractor):
                            extracted = await extractor(request)
                        else:
                            extracted = extractor(request)
                        req_data.update(dict(extracted))
                    else:
                        req_data.update(dict(request.path_params))
                        req_data.update(dict(request.query_params))

                    req_data.update({"start": start_pos, "end": end_pos})

                    current_offset = 0
                    async for chunk_msg in channel.stream(event_name, req_data):
                        chunk = chunk_msg.data
                        if isinstance(chunk, dict) and "chunk" in chunk:
                            chunk = chunk["chunk"]
                        
                        if isinstance(chunk, str):
                            import base64
                            try:
                                chunk = base64.b64decode(chunk)
                            except:
                                chunk = chunk.encode("utf-8")

                        if not isinstance(chunk, bytes):
                            chunk = str(chunk).encode("utf-8")

                        if current_offset + len(chunk) <= start_pos:
                            current_offset += len(chunk)
                            continue

                        if current_offset < start_pos:
                            offset_in_chunk = start_pos - current_offset
                            chunk = chunk[offset_in_chunk:]
                            current_offset = start_pos

                        if end_pos is not None and current_offset + len(chunk) > end_pos:
                            limit_in_chunk = end_pos - current_offset + 1
                            chunk = chunk[:limit_in_chunk]
                            yield chunk
                            break

                        yield chunk
                        current_offset += len(chunk)

                except Exception:
                    pass

            headers = {}
            status_code = 200
            if range_header:
                status_code = 206
                headers["Accept-Ranges"] = "bytes"
                headers["Content-Range"] = f"bytes {range_header.split('=')[1]}/*"
            
            return StreamingResponse(event_generator(), status_code=status_code, headers=headers, media_type="application/octet-stream")

    def add_websocket(self, path: str, channel: CommIPCChannel, event_name: str, tags: Optional[List[str]] = None):
        """
        Creates full bidirectional WebSocket proxying between WebSocket connections and IPC channel.
        """
        tags = tags or [f"WebSocket: {channel.name}"]

        @self.app.websocket(path)
        async def ws_endpoint(websocket: WebSocket):
            await websocket.accept()
            queue = asyncio.Queue()

            async def ipc_callback(cd: CommData):
                try:
                    queue.put_nowait(cd.data)
                except asyncio.QueueFull:
                    pass

            await channel.subscribe(event_name, ipc_callback)

            async def ws_to_ipc():
                try:
                    while True:
                        msg_str = await websocket.receive_text()
                        try:
                            data = json.loads(msg_str)
                        except:
                            data = msg_str
                        await channel.event(event_name, data)
                except WebSocketDisconnect:
                    pass
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

            async def ipc_to_ws():
                try:
                    while True:
                        data = await queue.get()
                        if isinstance(data, (dict, list)):
                            await websocket.send_text(json.dumps(data))
                        else:
                            await websocket.send_text(str(data))
                except WebSocketDisconnect:
                    pass
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

            ws_task = asyncio.create_task(ws_to_ipc())
            ipc_task = asyncio.create_task(ipc_to_ws())

            try:
                await asyncio.gather(ws_task, ipc_task)
            except asyncio.CancelledError:
                pass
            finally:
                ws_task.cancel()
                ipc_task.cancel()
                await channel.unsubscribe(event_name)

    def add_file_upload(self, path: str, channel: CommIPCChannel, event_name: str, tags: Optional[List[str]] = None):
        """
        Exposes an endpoint to receive file uploads from clients and streams chunks
        directly into an IPC event listener to avoid double writes.
        """
        tags = tags or [f"Upload: {channel.name}"]

        @self.app.post(path, tags=tags)
        async def file_upload_route(request: Request):
            filename = (
                request.headers.get("x-file-name") or
                request.headers.get("x-filename") or
                request.headers.get("file-name") or
                request.headers.get("filename") or
                request.query_params.get("filename") or
                request.query_params.get("file_name")
            )
            async for chunk in request.stream():
                await channel.send(event_name, {"chunk": chunk, "filename": filename})
            return {"status": "uploaded", "filename": filename}


