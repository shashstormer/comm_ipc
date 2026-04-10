import asyncio
import pytest
import os
from tests.base import start_test_server, stop_test_server
from pydantic import BaseModel
from comm_ipc.client import CommIPC
from comm_ipc.app import CommIPCApp
from comm_ipc.comm_data import CommData


@pytest.mark.asyncio
async def test_app_decorators():
    """Test that CommIPCApp decorators correctly register handlers via the core API."""
    socket_path = "/tmp/test_app_pytest_v2.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)

    server, server_task = await start_test_server(socket_path=socket_path)

    try:
        ipc = CommIPC(socket_path=socket_path)
        chan = await ipc.open("math")
        app = CommIPCApp(chan)

        @app.provide("add")
        async def add(cd: CommData):
            return cd.data["a"] + cd.data["b"]

        @app.subscription("notify")
        class NotifyModel(BaseModel):
            msg: str

        received = []

        @app.on("notify")
        async def on_notify(cd: CommData):
            received.append(True)

        @app.group.provide("mult")
        async def mult(cd: CommData):
            return cd.data["a"] * cd.data["b"]

        await asyncio.sleep(0.5)

        res = await ipc.call("math", "add", {"a": 10, "b": 20})
        assert res.data == 30

        res = await ipc.call("math", "mult", {"a": 5, "b": 6})
        assert res.data == 30

        await ipc.publish("math", "notify", {"msg": "hello"})
        await asyncio.sleep(0.2)
        assert len(received) == 1

        await ipc.close()
    finally:
        await stop_test_server(server, server_task)
        if os.path.exists(socket_path):
            os.remove(socket_path)
