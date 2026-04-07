import asyncio
import os

import pytest
from pydantic import BaseModel

from comm_ipc.client import CommIPC
from tests.base import start_test_server, stop_test_server

SOCKET_PATH = "/tmp/test_readme.sock"

@pytest.mark.asyncio
async def test_readme_examples_verification():
    """Ensure that all code examples in README.md are functional."""
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
        
    server, server_task = await start_test_server(socket_path=SOCKET_PATH)
    
    # Client with automated model reception enabled
    client = CommIPC(socket_path=SOCKET_PATH, return_type="model")
    await client.connect()
    channel = await client.open("demo_chan")

    # Example 1: RPC (Request-Response)
    class MathParams(BaseModel):
        a: int
        b: int

    async def add_handler(cd):
        return {"result": cd.data.a + cd.data.b}

    await channel.add_event("add", add_handler, parameters=MathParams)
    
    res = await channel.event("add", MathParams(a=10, b=20))
    assert res.data["result"] == 30
    assert isinstance(res.data, dict) # handler returns a dict, so res.data is dict

    # Example 2: Pub/Sub
    class User(BaseModel):
        id: int
        name: str

    received = []
    async def on_data(cd):
        received.append(cd.data)

    await channel.add_subscription("news", model=User)
    await channel.subscribe("news", on_data)
    await asyncio.sleep(0.1)
    
    await channel.publish("news", User(id=1, name="Alice"))
    await asyncio.sleep(0.1)
    
    assert len(received) == 1
    assert received[0].name == "Alice"
    assert isinstance(received[0], BaseModel)

    # Example 3: Streaming
    async def count_up(cd):
        for i in range(cd.data["limit"]):
            yield i

    await channel.add_stream("counter", count_up)
    
    chunks = []
    async for chunk in channel.stream("counter", {"limit": 3}):
        chunks.append(chunk.data)
    
    assert chunks == [0, 1, 2]

    # Example 4: Listeners & Broadcast
    client2 = CommIPC(socket_path=SOCKET_PATH)
    await client2.connect()
    channel2 = await client2.open("demo_chan")
    
    broadcast_received = []
    async def on_update(cd):
        broadcast_received.append(cd.data)
    
    channel2.on_receive(on_update, "system_update")
    await asyncio.sleep(0.1)
    
    await channel.broadcast("system_update", {"status": "ok"})
    await asyncio.sleep(0.2)
    
    assert len(broadcast_received) == 1
    assert broadcast_received[0]["status"] == "ok"

    await client.close()
    await client2.close()
    await stop_test_server(server, server_task)
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
