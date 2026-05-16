from typing import Dict, Optional, Any
from comm_ipc.client import CommIPC

class ChannelManager:
    """
    Singleton class to manage channels for easier access in other modules
    """
    _instance = None
    _initialized = False
    channels: Dict[str, Any] = {}

    def __new__(cls, client: Optional[CommIPC] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, client: Optional[CommIPC] = None):
        if not self.__class__._initialized:
            self.client: Optional[CommIPC] = client
            self.__class__._initialized = True

    async def get_channel(self, channel_name: str):
        await self.add_channel(channel_name)
        return self.channels.get(channel_name)

    async def add_channel(self, channel_name: str):
        if channel_name in self.channels:
            return
        
        if not self.client:
             raise ValueError("ChannelManager requires a valid CommIPC client to open channels.")
             
        channel = await self.client.open(channel_name)
        self.channels[channel_name] = channel
