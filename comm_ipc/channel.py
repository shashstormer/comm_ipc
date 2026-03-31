import asyncio
import inspect
import time
import uuid
from typing import Callable, Dict, Any, List, Union, get_origin, get_args, Optional

from comm_ipc.comm_data import CommData
from comm_ipc import security


class CommIPCChannel:
    def __init__(self, name: str, parent: 'CommIPC', password: str = None):
        self.name = name
        self.parent = parent
        self._password = None
        self.message_key = None
        self.password = password
        self.events: Dict[str, Dict[str, Any]] = {}
        self.listeners: Dict[str, List[Callable]] = {}
        self.generic_listeners: List[Callable] = []

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
    def validate_data(data: Any, schema: Dict[str, Any]):
        if not schema:
            return
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for data, got {type(data)}")

        for key, expected_type in schema.items():
            if key not in data:
                if get_origin(expected_type) is Union and type(None) in get_args(expected_type):
                    continue
                raise ValueError(f"Missing required parameter: {key}")

            val = data[key]
            if val is None:
                if not (get_origin(expected_type) is Union and type(None) in get_args(expected_type)):
                    raise TypeError(f"Parameter {key} cannot be None")
                continue

            origin = get_origin(expected_type)
            if origin is Union:
                args = get_args(expected_type)
                if not any(isinstance(val, t) for t in args if t is not type(None)):
                    raise TypeError(f"Parameter {key} expected one of {args}, got {type(val)}")
            elif not isinstance(val, expected_type):
                raise TypeError(f"Parameter {key} expected {expected_type}, got {type(val)}")

    async def add_event(self, name: str, call: Callable, parameters: Dict = None, returns: Dict = None):
        is_stream = inspect.isasyncgenfunction(call)
        self.events[name] = {
            "call": call,
            "parameters": parameters,
            "returns": returns,
            "is_stream": is_stream
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
            "is_final": False
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
        self.validate_data(data, handler_info["parameters"])

        handler = handler_info["call"]
        if inspect.iscoroutinefunction(handler):
            result = await handler(comm_data)
        else:
            result = handler(comm_data)

        return result

    async def handle_receive(self, comm_data: CommData):
        if self.message_key:
            if not security.verify_signature(self.message_key, comm_data.to_dict(), comm_data.signature):
                if self.parent.verbose:
                    print(f"[SECURITY] Invalid signature on {self.name}, dropping message")
                return

        event_name = comm_data.event

        if event_name in self.listeners:
            for listener in self.listeners[event_name]:
                if inspect.iscoroutinefunction(listener):
                    await listener(comm_data)
                else:
                    listener(comm_data)

        for listener in self.generic_listeners:
            if inspect.iscoroutinefunction(listener):
                await listener(comm_data)
            else:
                listener(comm_data)


if __name__ == "__main__":
    from comm_ipc.client import CommIPC
