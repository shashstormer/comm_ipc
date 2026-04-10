import asyncio
import uuid
from typing import Any, Optional, Type, Callable
from pydantic import BaseModel

class CommIPCGroup:
    def __init__(self, channel: 'CommIPCChannel', name: Optional[str] = None):
        self.channel = channel
        self.name = name

    def __call__(self, name: str) -> 'CommIPCGroup':
        """Returns a new CommIPCGroup with the specified name."""
        return CommIPCGroup(self.channel, name)

    def _get_event_name(self, event: str) -> str:
        if self.name:
            return f"{self.name}.{event}"
        return event

    async def provide(self, event: str, handler: Callable, parameters: Optional[Type[BaseModel]] = None, 
                      returns: Optional[Type[BaseModel]] = None):
        """Registers a group provider for an event on the channel."""
        full_name = self._get_event_name(event)
        return await self.channel.add_event(full_name, handler, parameters, returns, is_group=True)

    async def get(self, event: str, data: Any) -> Any:
        """Calls an event on the group (load balanced)."""
        full_name = self._get_event_name(event)
        return await self.channel.event(full_name, data)

    async def stream(self, event: str, data: Any):
        """Streams from an event on the group (load balanced)."""
        full_name = self._get_event_name(event)
        async for chunk in self.channel.stream(full_name, data):
            yield chunk
