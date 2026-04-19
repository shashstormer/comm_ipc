import asyncio
import json
from typing import Any, List, Optional, TYPE_CHECKING, Dict

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
            async def event_generator():
                queue = asyncio.Queue(maxsize=100)
                async def callback(cd: CommData):
                    try:
                        queue.put_nowait(cd.data)
                    except asyncio.QueueFull:
                        pass

                    await channel.subscribe(sub_name, callback)
                    try:
                        while True:
                            if await request.is_disconnected():
                                break
                            try:
                                data = await asyncio.wait_for(queue.get(), timeout=2.0)
                                yield f"data: {json.dumps(data)}\n\n"
                            except asyncio.TimeoutError:
                                yield ": keep-alive\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'error': str(e)})}\n\n"
                    finally:
                        await channel.unsubscribe(sub_name)

            return StreamingResponse(event_generator(), media_type="text/event-stream")


