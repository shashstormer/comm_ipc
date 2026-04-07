import asyncio
import inspect
import time
import uuid
from typing import Callable, Dict, Any, List, Optional, Type

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
        self._generated_models: Dict[str, Type[BaseModel]] = {}

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

    def _create_model_from_schema(self, name: str, schema: Dict[str, Any], root_defs: Dict[str, Any] = None) -> Type[BaseModel]:
        defs = root_defs or schema.get("$defs", {})
        
        if name in self._generated_models:
            return self._generated_models[name]
            
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        fields = {}
        for prop_name, prop_info in properties.items():
            if "$ref" in prop_info:
                ref_path = prop_info["$ref"]
                if ref_path.startswith("#/$defs/"):
                    ref_key = ref_path.split("/")[-1]
                    prop_info = defs.get(ref_key, {})
                elif ref_path.startswith("#/"):
                    pass
            
            prop_type = Any
            ptype = prop_info.get("type")
            
            if ptype == "string": prop_type = str
            elif ptype == "integer": prop_type = int
            elif ptype == "number": prop_type = float
            elif ptype == "boolean": prop_type = bool
            elif ptype == "array": 
                items = prop_info.get("items", {})
                if "$ref" in items:
                    ref_key = items["$ref"].split("/")[-1]
                    items = defs.get(ref_key, {})
                
                if items.get("type") == "object":
                    inner_name = items.get("title", f"{prop_name}Item")
                    prop_type = List[self._create_model_from_schema(inner_name, items, defs)]
                else:
                    prop_type = List[Any]
            elif ptype == "object":
                if "properties" in prop_info:
                    inner_name = prop_info.get("title", prop_name.capitalize())
                    prop_type = self._create_model_from_schema(inner_name, prop_info, defs)
                else:
                    prop_type = Dict[str, Any]
            
            if prop_name in required:
                fields[prop_name] = (prop_type, ...)
            else:
                fields[prop_name] = (Optional[prop_type], None)
                
        model = create_model(schema.get("title", f"Dynamic{name}"), **fields)
        self._generated_models[name] = model
        return model

    def validate_data(self, data: Any, schema: Any) -> Any:
        if schema is None or data is None:
            return data

        if isinstance(schema, type) and issubclass(schema, BaseModel):
            validated = schema.model_validate(data)
            if self.parent.return_type == "model":
                return validated
            return validated.model_dump()

        if isinstance(schema, dict) and self.parent.return_type == "model":
            title = schema.get("title", "DynamicModel")
            cls = self._create_model_from_schema(title, schema)
            return cls.model_validate(data)

        return data

    async def add_event(self, name: str, call: Callable, parameters: Optional[Type[BaseModel]] = None,
                        returns: Optional[Type[BaseModel]] = None):
        is_stream = inspect.isasyncgenfunction(call)

        param_schema = parameters.model_json_schema() if parameters else None
        return_schema = returns.model_json_schema() if returns else None

        if name.startswith("subscription."):
            raise ValueError(f"Event name '{name}' is reserved (cannot start with 'subscription.')")

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
            "is_stream": is_stream,
            "param_schema": param_schema,
            "return_schema": return_schema
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
        if isinstance(data, BaseModel):
            msg["data"] = data.model_dump()
        if self.message_key:
            msg["signature"] = security.compute_signature(self.message_key, msg)
        return msg

    async def event(self, event_name: str, data: Any) -> Any:
        rid = str(uuid.uuid4())
        msg = await self._create_message("call", event_name, data, rid)

        fut = asyncio.get_running_loop().create_future()
        self.parent.pending_calls[rid] = fut
        await self.parent.send_msg(msg)
        res = await fut
        if self.parent.return_type == "model":
            schema_info = self.events.get(event_name) or self.remote_schemas.get(event_name)
            if schema_info:
                schema = schema_info.get("returns") or schema_info.get("return_schema")
                if schema:
                    res.data = self.validate_data(res.data, schema)
        return res

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
                    
                    if self.parent.return_type == "model":
                        schema_info = self.events.get(event_name) or self.remote_schemas.get(event_name)
                        if schema_info:
                            schema = schema_info.get("returns") or schema_info.get("return_schema")
                            if schema:
                                 cd.data = self.validate_data(cd.data, schema)
                    yield cd
                if resp.get("is_final"):
                    break
        finally:
            if rid in self.parent.active_streams:
                del self.parent.active_streams[rid]

    async def add_stream(self, name: str, call: Callable, parameters: Optional[Type[BaseModel]] = None):
        await self.add_event(name, call, parameters=parameters)

    async def broadcast(self, event_name: str, data: Any):
        msg = await self._create_message("broadcast", event_name, data)
        await self.parent.send_msg(msg)

    async def send(self, event_name: str, data: Any):
        msg = await self._create_message("send", event_name, data)
        await self.parent.send_msg(msg)

    async def add_subscription(self, sub_name: str, model: Optional[Type[BaseModel]] = None):
        return_schema = model.model_json_schema() if model else None
        self.subscriptions[sub_name] = {
            "model": model,
            "return_schema": return_schema 
        }
        return await self.parent.add_subscription(self.name, sub_name, return_schema=return_schema)

    async def remove_subscription(self, sub_name: str):
        self.subscriptions.pop(sub_name, None)
        return await self.parent.remove_subscription(self.name, sub_name)

    async def subscribe(self, sub_name: str, callback: Callable):
        return await self.parent.subscribe(self.name, sub_name, callback)

    async def unsubscribe(self, sub_name: str):
        return await self.parent.unsubscribe(self.name, sub_name)

    async def publish(self, sub_name: str, data: Any):
        if sub_name in self.subscriptions:
            data = self.validate_data(data, self.subscriptions[sub_name].get("model"))
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
        validated_result = self.validate_data(result, handler_info["returns"])
        return validated_result

    def explore(self) -> Dict[str, Any]:
        """Provides a consolidated view of all discovered events and subscriptions in this channel."""
        all_info = {
            "events": {},
            "subscriptions": {}
        }

        for name, info in self.events.items():
            all_info["events"][name] = {
                "owner": self.parent.client_id,
                "is_stream": info["is_stream"],
                "parameters": info["param_schema"],
                "returns": info["return_schema"]
            }

        for name, info in self.subscriptions.items():
            all_info["subscriptions"][name] = {
                "owner": self.parent.client_id,
                "returns": info["return_schema"]
            }

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
                "returns": self.subscriptions[name]["return_schema"]
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
        
        if self.parent.return_type == "model":
            logical_name = event_name
            if event_name.startswith("subscription.") and event_name.endswith(".data"):
                logical_name = event_name.split(".")[1]
            
            schema_info = self.subscriptions.get(logical_name) or self.remote_schemas.get(logical_name)
            if schema_info:
                if logical_name in self.subscriptions:
                     schema = schema_info.get("model") or schema_info.get("return_schema")
                else:
                     schema = schema_info.get("parameters") or schema_info.get("param_schema")
                
                if schema:
                    comm_data.data = self.validate_data(comm_data.data, schema)

        if event_name in self.listeners:
            for listener in self.listeners[event_name]:
                await listener(comm_data)

        for listener in self.generic_listeners:
            await listener(comm_data)


if __name__ == "__main__":
    from comm_ipc.client import CommIPC
