import asyncio
import json
import os
import pytest
import uuid
from comm_ipc.client import CommIPC
from comm_ipc.server import CommIPCServer

@pytest.mark.asyncio
async def test_high_concurrency_identification_race():
    """
    Test that triggering multiple concurrent send_msg calls on a new client
    doesn't corrupt the identification handshake.
    """
    socket_path = f"/tmp/test_concurrency_{uuid.uuid4().hex}.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)
        
    server = CommIPCServer(verbose=False)
    server_task = asyncio.create_task(server.run(socket_path=socket_path))
    await asyncio.sleep(0.1)

    client = CommIPC(socket_path=socket_path, verbose=False)
    
    num_concurrent = 50
    
    async def task(i):
        chan = await client.open("test_chan")
        await chan.broadcast("event", {"data": i})
        return True

    results = await asyncio.gather(*(task(i) for i in range(num_concurrent)), return_exceptions=True)
    
    for r in results:
        if isinstance(r, Exception):
            pytest.fail(f"Concurrent task failed: {r}")
    
    assert len(results) == num_concurrent
    
    await client.close()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
    
    if os.path.exists(socket_path):
        os.remove(socket_path)

@pytest.mark.asyncio
async def test_concurrent_server_writes():
    """
    Test that the server can handle multiple concurrent tasks sending to the same client
    without corrupting the byte stream.
    """
    socket_path = f"/tmp/test_srv_concurrency_{uuid.uuid4().hex}.sock"
    server = CommIPCServer(verbose=False)
    server_task = asyncio.create_task(server.run(socket_path=socket_path))
    await asyncio.sleep(0.1)

    client = CommIPC(socket_path=socket_path, verbose=False)
    await client.connect()
    
    received_messages = []
    
    async def on_msg(msg):
        if msg.get("type") in ("broadcast", "receive", "send"):
             received_messages.append(msg)
             
    client.on_msg = on_msg
    chan = await client.open("test_chan")
    
    async def provider_handler(data):
        for i in range(100):
            await server._handle_broadcast("system", {
                "type": "broadcast",
                "channel": "test_chan",
                "event": "stress",
                "data": i
            })
        return "ok"

    await chan.add_event("stress_trigger", provider_handler)
    
    await chan.event("stress_trigger", {})
    
    for _ in range(50):
        if len(received_messages) >= 100:
            break
        await asyncio.sleep(0.1)
        
    assert len(received_messages) >= 100
    
    await client.close()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
    
    if os.path.exists(socket_path):
        os.remove(socket_path)
