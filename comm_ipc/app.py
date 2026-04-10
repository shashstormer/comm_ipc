import asyncio
import uuid
import inspect
from typing import Callable, Optional, Type, Any, Dict, List
from pydantic import BaseModel

class CommIPCAppGroup:
    """Helper for load-balanced group decorators."""
    def __init__(self, app: 'CommIPCApp', name: Optional[str] = None):
        self.app = app
        self.name = name

    def __call__(self, name: str) -> 'CommIPCAppGroup':
        """Returns a new CommIPCAppGroup with the specified name."""
        return CommIPCAppGroup(self.app, name)

    def provide(self, event: str, parameters: Optional[Type[BaseModel]] = None, 
                returns: Optional[Type[BaseModel]] = None):
        """Decorator for registering a load-balanced group provider."""
        def decorator(handler):
            if self.app.channel:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.app._apply_provide(event, handler, parameters, returns, is_group=True, group_name=self.name))
                except RuntimeError:
                    self.app._provides.append((event, handler, parameters, returns, True, self.name))
            else:
                self.app._provides.append((event, handler, parameters, returns, True, self.name))
            return handler
        return decorator

class CommIPCApp:
    """
    A utility class to provide a decoupled decorator-based API for CommIPC.
    Supports deferred registration (FastAPI-style).
    """
    def __init__(self, channel: Optional[Any] = None):
        self.channel = channel
        self.group = CommIPCAppGroup(self)
        self._provides = [] # List[tuple]
        self._ons = []      # List[tuple]
        self._subs = []     # List[tuple]
        
        if channel:
            # If channel is provided in init, try to register immediately
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.register(channel))
            except RuntimeError:
                pass # Will need manual register() call later or when loop starts

    async def register(self, channel: Any):
        """Bind the app to a channel and register all buffered decorators."""
        self.channel = channel
        
        # Apply buffered providers
        for event, handler, params, returns, is_group, group_name in self._provides:
            await self._apply_provide(event, handler, params, returns, is_group, group_name)
        self._provides = []

        # Apply buffered listeners
        for event_name, cb in self._ons:
            await self._apply_on(event_name, cb)
        self._ons = []

        # Apply buffered subscriptions
        for name, model in self._subs:
            await self._apply_sub(name, model)
        self._subs = []

    async def _apply_provide(self, event_name: str, handler: Callable, 
                           parameters: Optional[Type[BaseModel]] = None,
                           returns: Optional[Type[BaseModel]] = None, 
                           is_group: bool = False,
                           group_name: Optional[str] = None):
        """The actual async registration logic."""
        if not self.channel:
            return

        is_stream = inspect.isasyncgenfunction(handler)
        
        full_event_name = event_name
        if is_group:
             grp = self.channel.group
             if group_name:
                 grp = grp(group_name)
             full_event_name = grp._get_event_name(event_name)

        # Register on the channel
        await self.channel.add_event(
            full_event_name, 
            handler, 
            parameters=parameters, 
            returns=returns, 
            is_group=is_group
        )

    async def _apply_on(self, event_name: Optional[str], cb: Callable):
        if not self.channel:
            return
        
        self.channel.on_receive(cb, event_name)
        if event_name:
            await self.channel.subscribe(event_name, cb)

    async def _apply_sub(self, name: str, model: Optional[Type[BaseModel]]):
        if not self.channel:
            return
        await self.channel.add_subscription(name, model=model)

    def provide(self, name: str, parameters: Optional[Type[BaseModel]] = None,
                returns: Optional[Type[BaseModel]] = None):
        """Decorator for registering an event provider."""
        def decorator(handler):
            if self.channel:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._apply_provide(name, handler, parameters, returns))
                except RuntimeError:
                    self._provides.append((name, handler, parameters, returns, False, None))
            else:
                self._provides.append((name, handler, parameters, returns, False, None))
            return handler
        return decorator

    def subscription(self, name: str, model: Optional[Type[BaseModel]] = None):
        """Decorator to declare a subscription."""
        def decorator(func_or_class):
            if self.channel:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._apply_sub(name, model))
                except RuntimeError:
                    self._subs.append((name, model))
            else:
                self._subs.append((name, model))
            return func_or_class
        return decorator

    def on(self, event_name: str = None):
        """Decorator for registering a listener."""
        def decorator(cb):
            if self.channel:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._apply_on(event_name, cb))
                except RuntimeError:
                    self._ons.append((event_name, cb))
            else:
                self._ons.append((event_name, cb))
            return cb
        return decorator
