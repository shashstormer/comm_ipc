import asyncio

from comm_ipc.server import CommIPCServer


async def start_test_server(server_id="test-srv", socket_path="/tmp/test_ipc.sock"):
    server = CommIPCServer(server_id=server_id, socket_path=socket_path)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1)
    return server, task

async def stop_test_server(arg1, arg2=None):
    if arg2 is None:
        server = None
        task = arg1
    else:
        server = arg1
        task = arg2

    if server and hasattr(server, 'stop'):
        await server.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
