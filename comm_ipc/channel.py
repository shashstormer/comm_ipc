import asyncio
import inspect
import time
import uuid
from typing import Callable, Dict, Any, List, Union, get_origin, get_args, Optional, Type

from pydantic import BaseModel, create_model

from comm_ipc import security
from comm_ipc.comm_data import CommData


class CommIPCChannel:
    def __init__(self, name: str, parent: 'CommIPC', password: str = None):
        self.subscriptions: Dict[str, Dict[str, Any]] = {}
        self.name = name
        self.parent = parent
        self._password = None
        self.message_key = None
        self.password = password
        self.events: Dict[str, Dict[str, Any]] = {}
        self.listeners: Dict[str, List[Callable]] = {}
        self.generic_listeners: List[Callable] = []
        self.remote_schemas: Dict[str, Dict[str, Any]] = {}

    @property
    def password(self) -> Optional[str]:
        return self._password

    @password.setter
    def password(self, val: str):
        self._password = val
        if val:
            self.message_key = security.derive_key(val, self.name.encode())
        else:
            self.message_key = None

    @staticmethod
    def validate_data(data: Any, schema: Any) -> Any:
        if schema is None or data is None:
            return data

        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema.model_validate(data).model_dump()
        
        # Dict support removed. Only BaseModel is allowed for schemas.
        if isinstance(schema, dict):
            raise TypeError("Dictionary-based schemas are no longer supported. Please use a Pydantic BaseModel class.")

        return data

    async def add_event(self, name: str, call: Callable, parameters: Optional[Type[BaseModel]] = None, returns: Optional[Type[BaseModel]] = None):
        is_stream = inspect.isasyncgenfunction(call)
        
        param_schema = parameters.model_json_schema() if parameters else None
        return_schema = returns.model_json_schema() if returns else None
        
        self.events[name] = {
            "call": call,
            "parameters": parameters,
            "returns": returns,
            "is_stream": is_stream,
            "param_schema": param_schema,
            "return_schema": return_schema
        }
        
        if name not in self.listeners:
            self.listeners[name] = []
        if call not in self.listeners[name]:
            self.listeners[name].append(call)

        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.parent.pending_calls[rid] = fut

        await self.parent.send_msg({
            "type": "register",
            "request_id": rid,
            "client_id": self.parent.client_id,
            "channel": self.name,
            "is_provider": True,
            "event": name,
            "is_stream": is_stream
        })

        try:
            await asyncio.wait_for(fut, timeout=10.0)
        except asyncio.TimeoutError:
            raise Exception(f"Registration for event {self.name}:{name} timed out")

    async def _create_message(self, msg_type: str, event_name: str, data: Any, request_id: str = None) -> Dict:
        msg = {
            "type": msg_type,
            "channel": self.name,
            "event": event_name,
            "data": data,
            "sender_id": self.parent.client_id,
            "server_id": self.parent.server_id,
            "origin_server_id": self.parent.server_id,
            "timestamp": int(time.time()),
            "request_id": request_id,
            "target_id": None,
            "is_stream": False,
            "is_final": False,
            "sub_name": None
        }
        if self.message_key:
            msg["signature"] = security.compute_signature(self.message_key, msg)
        return msg

    async def event(self, event_name: str, data: Any) -> Any:
        rid = str(uuid.uuid4())
        msg = await self._create_message("call", event_name, data, rid)
        
        fut = asyncio.get_running_loop().create_future()
        self.parent.pending_calls[rid] = fut
        await self.parent.send_msg(msg)
        return await fut

    async def stream(self, event_name: str, data: Any):
        rid = str(uuid.uuid4())
        msg = await self._create_message("call", event_name, data, rid)
            
        self.parent.active_streams[rid] = asyncio.Queue(maxsize=1000)
        await self.parent.send_msg(msg)
        
        try:
            while True:
                resp = await self.parent.active_streams[rid].get()
                if resp.get("error"):
                    raise Exception(resp["error"])
                if resp.get("data") is not None:
                    cd = CommData.from_dict(resp)
                    if self.message_key:
                        if not security.verify_signature(self.message_key, cd.to_dict(), cd.signature):
                            raise ValueError(f"Invalid signature for channel {self.name}")
                    yield cd
                if resp.get("is_final"):
                    break
        finally:
            if rid in self.parent.active_streams:
                del self.parent.active_streams[rid]

    async def add_stream(self, name: str, call: Callable, parameters: Dict = None):
        await self.add_event(name, call, parameters)

    async def broadcast(self, event_name: str, data: Any):
        msg = await self._create_message("broadcast", event_name, data)
        await self.parent.send_msg(msg)

    async def send(self, event_name: str, data: Any):
        msg = await self._create_message("send", event_name, data)
        await self.parent.send_msg(msg)

    async def add_subscription(self, sub_name: str, parameters: Optional[Type[BaseModel]] = None):
        param_schema = parameters.model_json_schema() if parameters else None
        self.subscriptions[sub_name] = {
            "parameters": parameters,
            "param_schema": param_schema
        }
        return await self.parent.add_subscription(self.name, sub_name, parameters=parameters, schema=param_schema)

    async def remove_subscription(self, sub_name: str):
        self.subscriptions.pop(sub_name, None)
        return await self.parent.remove_subscription(self.name, sub_name)

    async def subscribe(self, sub_name: str, callback: Callable):
        return await self.parent.subscribe(self.name, sub_name, callback)

    async def unsubscribe(self, sub_name: str):
        return await self.parent.unsubscribe(self.name, sub_name)

    async def publish(self, sub_name: str, data: Any):
        if sub_name in self.subscriptions:
            data = self.validate_data(data, self.subscriptions[sub_name].get("parameters"))
        return await self.parent.publish(self.name, sub_name, data)

    def on_receive(self, call: Callable, event_name: str = None):
        if event_name:
            if event_name not in self.listeners:
                self.listeners[event_name] = []
            self.listeners[event_name].append(call)
        else:
            self.generic_listeners.append(call)

    async def handle_call(self, comm_data: CommData) -> Any:
        if self.message_key:
            if not security.verify_signature(self.message_key, comm_data.to_dict(), comm_data.signature):
                raise ValueError(f"Invalid signature for channel {self.name}")

        event_name = comm_data.event
        if event_name not in self.events:
            raise ValueError(f"Event {event_name} not found on channel {self.name}")

        handler_info = self.events[event_name]
        data = comm_data.data
        validated_params = self.validate_data(data, handler_info["parameters"])
        comm_data.data = validated_params

        handler = handler_info["call"]
        result = await handler(comm_data)
        def explore(self) -> Dict[str, Any]:
        """Provides a consolidated view of all discovered events and subscriptions in this channel."""
        # Mix local events (provided by this client) and remote events (discovered from server)
        all_info = {
            "events": {},
            "subscriptions": {}
        }
        
        # Local events
        for name, info in self.events.items():
            all_info["events"][name] = {
                "owner": self.parent.client_id,
                "is_stream": info["is_stream"],
                "parameters": info["param_schema"],
                "returns": info["return_schema"]
            }
            
        # Local subscriptions
        for name, info in self.subscriptions.items():
            all_info["subscriptions"][name] = {
                "owner": self.parent.client_id,
                "parameters": info["param_schema"]
            }
            
        # Remote info from server
        for name, info in self.remote_schemas.items():
            stype = info.get("type", "event")
            if stype == "event":
                if name not in all_info["events"]:
                    all_info["events"][name] = {
                        "owner": info.get("owner"),
                        "is_stream": info.get("is_stream", False),
                        "parameters": info.get("param_schema"),
                        "returns": info.get("return_schema")
                    }
            elif stype == "subscription":
                 if name not in all_info["subscriptions"]:
                    all_info["subscriptions"][name] = {
                        "owner": info.get("owner"),
                        "parameters": info.get("param_schema")
                    }
                    
        return all_info

    def get_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """Returns the full JSON schema for a specific event or subscription."""
        if name in self.events:
            return {
                "type": "event",
                "parameters": self.events[name]["param_schema"],
                "returns": self.events[name]["return_schema"]
            }
        if name in self.subscriptions:
            return {
                "type": "subscription",
                "parameters": self.subscriptions[name]["param_schema"]
            }
        if name in self.remote_schemas:
            return self.remote_schemas[name]
        return None

    async def handle_receive(self, comm_data: CommData):
        if self.message_key:
            if not security.verify_signature(self.message_key, comm_data.to_dict(), comm_data.signature):
                if self.parent.verbose:
                    print(f"[SECURITY] Invalid signature on {self.name}, dropping message")
                return

        event_name = comm_data.event

        if event_name in self.listeners:
            for listener in self.listeners[event_name]:
                await listener(comm_data)

        for listener in self.generic_listeners:
            await listener(comm_data)


if __name__ == "__main__":
    from comm_ipc.client import CommIPC
