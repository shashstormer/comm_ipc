import json
from typing import Any, List, Optional

from fastapi import FastAPI, Body, Request, HTTPException
from fastapi.responses import StreamingResponse

from comm_ipc.channel import CommIPCChannel
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData


class CommAPI:
    def __init__(self, app: FastAPI, client: CommIPC):
        self.app = app
        self.client = client
        self.mounted_channels: List[str] = []

    def _get_handler(self, channel: CommIPCChannel, event_name: str, is_stream: bool = False):
        async def rpc_handler(data: Any):
            try:
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
        
        if is_stream or method == "GET":
            if param_model and param_model is not Any:
                from fastapi import Depends
                async def wrapped_handler(request: Request, data: param_model = Depends()):
                    return await handler(data)
            else:
                async def wrapped_handler(request: Request):
                    data = dict(request.query_params)
                    return await handler(data)
        else:
            if param_model and param_model is not Any:
                async def wrapped_handler(data: param_model = Body(...)):
                    return await handler(data)
            else:
                async def wrapped_handler(data: Any = Body(None)):
                    return await handler(data)

        if is_stream:
            self.app.get(path, tags=tags)(wrapped_handler)
        else:
            self.app.api_route(path, methods=[method], tags=tags, response_model=response_model)(wrapped_handler)

    def add_resource(self, channel: CommIPCChannel, path_template: str = "/{event}", tags: Optional[List[str]] = None, method: str = "POST"):
        """Mounts all discovered events of a channel based on a path template."""
        info = channel.explore()
        events = info.get("events", {})
        
        if not tags:
            tags = [f"Channel: {channel.name}"]

        for event_name in events:
            path = path_template.replace("{event}", event_name)
            self.add_event(channel, event_name, path, method=method, tags=tags)

        self.mounted_channels.append(channel.name)
