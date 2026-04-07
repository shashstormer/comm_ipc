import asyncio
import os

import pytest

from comm_ipc.client import CommIPC
from tests.base import start_test_server, stop_test_server

SOCKET_PATH = "/tmp/test_reserved_names.sock"

@pytest.mark.asyncio
async def test_client_reserved_channel():
    """Verify that the client rejects opening reserved channel names."""
    client = CommIPC(socket_path=SOCKET_PATH)
    
    with pytest.raises(ValueError, match="Channel name 'subscription' is reserved"):
        await client.open("subscription")

@pytest.mark.asyncio
async def test_client_reserved_event_prefix():
    """Verify that the client rejects registering events with reserved prefixes."""
    client = CommIPC(socket_path=SOCKET_PATH)
    from comm_ipc.channel import CommIPCChannel
    chan = CommIPCChannel("test", client)
    
    async def handler(cd):
        return cd.data
    
    with pytest.raises(ValueError, match="is reserved"):
        await chan.add_event("subscription.test", handler)

@pytest.mark.asyncio
async def test_server_reserved_channel_enforcement():
    """Verify that the server rejects reserved channel names even if requested manually."""
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
        
    server, server_task = await start_test_server(socket_path=SOCKET_PATH)
    
    client = CommIPC(socket_path=SOCKET_PATH)
    await client.connect()
    
    rid = "test_rid_1"
    fut = asyncio.get_running_loop().create_future()
    client.pending_calls[rid] = fut
    
    # Manually forge a request to bypass client-side checks
    await client.send_msg({
        "type": "add_subscription",
        "channel": "subscription",
        "sub_name": "test_sub",
        "request_id": rid
    })
    
    with pytest.raises(Exception, match="reserved"):
        await fut
        
    await client.close()
    await stop_test_server(server, server_task)

@pytest.mark.asyncio
async def test_server_reserved_event_enforcement():
    """Verify that the server rejects reserved event prefixes even if requested manually."""
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
        
    server, server_task = await start_test_server(socket_path=SOCKET_PATH)
    
    client = CommIPC(socket_path=SOCKET_PATH)
    await client.connect()
    
    rid = "test_rid_2"
    fut = asyncio.get_running_loop().create_future()
    client.pending_calls[rid] = fut
    
    # Manually forge a register request to bypass client-side checks
    await client.send_msg({
        "type": "add_subscription",
        "channel": "any_channel",
        "sub_name": "subscription.is_reserved",
        "request_id": rid
    })
    
    with pytest.raises(Exception, match="reserved"):
        await fut
        
    await client.close()
    await stop_test_server(server, server_task)
