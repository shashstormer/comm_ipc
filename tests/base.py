import asyncio
import os
import sys

from comm_ipc.server import CommIPCServer
from comm_ipc.client import CommIPC

async def start_test_server(server_id="test-srv", socket_path="/tmp/test_ipc.sock"):
    server = CommIPCServer(server_id=server_id, socket_path=socket_path)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1)
    return server, task

async def stop_test_server(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
