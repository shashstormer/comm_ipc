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
    
    # Example 1: RPC (Request-Response)
    channel = await client.open("math_engine")
    class MathParams(BaseModel):
        a: int
        b: int

    async def add_handler(cd):
        # cd.data is automatically a MathParams instance
        return {"result": cd.data.a + cd.data.b}

    await channel.add_event("add", add_handler, parameters=MathParams)
    
    res = await channel.event("add", MathParams(a=10, b=20))
    assert res.data["result"] == 30

    # Example 2: Pub/Sub
    channel_social = await client.open("social")
    class User(BaseModel):
        id: int
        name: str

    received = []
    async def on_user(cd):
        received.append(cd.data)

    await channel_social.subscribe("join_events", on_user)
    await channel_social.add_subscription("join_events", model=User)
    await asyncio.sleep(0.1)
    
    await channel_social.publish("join_events", User(id=1, name="Alice"))
    await asyncio.sleep(0.1)
    
    assert len(received) == 1
    assert received[0].name == "Alice"
    assert isinstance(received[0], BaseModel)

    # Example 3: Streaming
    channel_streams = await client.open("streams")
    async def count_up(cd):
        for i in range(cd.data["limit"]):
            yield {"count": i}

    await channel_streams.add_stream("counter", count_up)
    
    chunks = []
    async for chunk in channel_streams.stream("counter", {"limit": 3}):
        chunks.append(chunk.data["count"])
    
    assert chunks == [0, 1, 2]

    # Example 4: Listeners & Broadcast
    channel_monitor = await client.open("monitor")
    
    client2 = CommIPC(socket_path=SOCKET_PATH)
    await client2.connect()
    channel2 = await client2.open("monitor")
    
    broadcast_received = []
    async def on_event(cd):
        broadcast_received.append(cd.data)
    
    channel2.on_receive(on_event, "alert")
    await asyncio.sleep(0.1)
    
    await channel_monitor.broadcast("alert", {"msg": "ok"})
    await asyncio.sleep(0.2)
    
    assert len(broadcast_received) == 1
    assert broadcast_received[0]["msg"] == "ok"

    await client.close()
    await client2.close()
    await stop_test_server(server, server_task)
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
