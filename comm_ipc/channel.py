import asyncio
import inspect
from typing import Callable, Dict, Any, List, Union, get_origin, get_args

from comm_ipc.comm_data import CommData


class CommIPCChannel:
    def __init__(self, name: str, parent: 'CommIPC', password: str = None):
        self.name = name
        self.parent = parent
        self.password = password
        self.events: Dict[str, Dict[str, Any]] = {}
        self.listeners: Dict[str, List[Callable]] = {}
        self.generic_listeners: List[Callable] = []

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

        await self.parent.send_msg({
            "type": "register",
            "client_id": self.parent.client_id,
            "channel": self.name,
            "password": self.password,
            "is_provider": True,
            "event": name,
            "is_stream": is_stream
        })

    async def event(self, event_name: str, data: Any) -> Any:
        return await self.parent.call(self.name, event_name, data)

    async def stream(self, event_name: str, data: Any):
        async for chunk in self.parent.stream(self.name, event_name, data):
            yield chunk

    async def add_stream(self, name: str, call: Callable, parameters: Dict = None):

        await self.add_event(name, call, parameters)

    async def broadcast(self, event_name: str, data: Any):
        await self.parent.send_msg({
            "type": "broadcast",
            "channel": self.name,
            "event": event_name,
            "data": data,
            "sender_id": self.parent.client_id,
            "server_id": self.parent.server_id
        })

    async def send(self, event_name: str, data: Any):
        await self.parent.send_msg({
            "type": "send",
            "channel": self.name,
            "event": event_name,
            "data": data,
            "sender_id": self.parent.client_id,
            "server_id": self.parent.server_id
        })

    def on_receive(self, call: Callable, event_name: str = None):
        if event_name:
            if event_name not in self.listeners:
                self.listeners[event_name] = []
            self.listeners[event_name].append(call)
        else:
            self.generic_listeners.append(call)

    async def handle_call(self, comm_data: CommData) -> Any:
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
        event_name = comm_data.event
        data = comm_data.data

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
