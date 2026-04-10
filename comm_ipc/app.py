import asyncio
import uuid
import inspect
from typing import Callable, Optional, Type, Any, Dict, List
from pydantic import BaseModel

class CommIPCAppGroup:
    """Helper for load-balanced group decorators."""
    def __init__(self, app: 'CommIPCApp'):
        self.app = app

    def provide(self, event: str, parameters: Optional[Type[BaseModel]] = None, 
                returns: Optional[Type[BaseModel]] = None):
        """Decorator for registering a load-balanced group provider."""
        def decorator(handler):
            self.app._do_registration(event, handler, parameters, returns, is_group=True)
            return handler
        return decorator

class CommIPCApp:
    """
    A utility class to provide a clean decorator-based API for CommIPC.
    This avoids modifying the core CommIPC and CommIPCChannel classes.
    """
    def __init__(self, channel):
        self.channel = channel
        self.group = CommIPCAppGroup(self)

    def _do_registration(self, event_name: str, handler: Callable, 
                         parameters: Optional[Type[BaseModel]] = None,
                         returns: Optional[Type[BaseModel]] = None, 
                         is_group: bool = False):
        """Internal non-blocking registration logic."""
        # 1. Update local state directly
        is_stream = inspect.isasyncgenfunction(handler)
        param_schema = parameters.model_json_schema() if parameters else None
        return_schema = returns.model_json_schema() if returns else None
        
        full_event_name = event_name
        if is_group and hasattr(self.channel.group, '_get_event_name'):
             full_event_name = self.channel.group._get_event_name(event_name)

        self.channel.events[full_event_name] = {
            "call": handler,
            "parameters": parameters,
            "returns": returns,
            "is_stream": is_stream,
            "is_group": is_group,
            "param_schema": param_schema,
            "return_schema": return_schema
        }

        if full_event_name not in self.channel.listeners:
            self.channel.listeners[full_event_name] = []
        if handler not in self.channel.listeners[full_event_name]:
            self.channel.listeners[full_event_name].append(handler)

        # 2. Inform server (non-blocking)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.channel.parent.send_msg({
                "type": "register",
                "request_id": str(uuid.uuid4()),
                "client_id": self.channel.parent.client_id,
                "channel": self.channel.name,
                "is_provider": True,
                "event": full_event_name,
                "is_stream": is_stream,
                "is_group": is_group,
                "param_schema": param_schema,
                "return_schema": return_schema
            }))
        except RuntimeError:
            pass # Loop not running yet

    def provide(self, name: str, parameters: Optional[Type[BaseModel]] = None,
                returns: Optional[Type[BaseModel]] = None):
        """Decorator for registering an event provider."""
        def decorator(handler):
            self._do_registration(name, handler, parameters, returns, is_group=False)
            return handler
        return decorator

    def subscription(self, name: str, model: Optional[Type[BaseModel]] = None):
        """Decorator to declare a subscription (necessary for publishers)."""
        def decorator(func_or_class):
            try:
                loop = asyncio.get_running_loop()
                # We update local state then schedule server update
                return_schema = model.model_json_schema() if model else None
                self.channel.subscriptions[name] = {
                    "model": model,
                    "return_schema": return_schema
                }
                loop.create_task(self.channel.parent.add_subscription(self.channel.name, name, return_schema=return_schema))
            except RuntimeError:
                pass
            return func_or_class
        return decorator

    def on(self, event_name: str = None):
        """Decorator for registering a message listener and subscribing if event_name is provided."""
        def decorator(cb):
            self.channel.on_receive(cb, event_name)
            if event_name:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.channel.subscribe(event_name, cb))
                except RuntimeError:
                    pass
            return cb
        return decorator
