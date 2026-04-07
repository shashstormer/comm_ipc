import asyncio
import os
import pytest
from pydantic import BaseModel
from typing import List, Optional
from comm_ipc.client import CommIPC
from tests.base import start_test_server, stop_test_server

SOCKET_PATH = "/tmp/test_pydantic_dynamic.sock"


class Nested(BaseModel):
    id: int
    data: str


class Root(BaseModel):
    name: str
    items: List[Nested]
    single: Nested
    opt: Optional[int] = None


@pytest.mark.asyncio
async def test_dynamic_model_basic():
    """Verify that a subscriber can automatically receive a model instance from a schema."""
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    server, server_task = await start_test_server(socket_path=SOCKET_PATH)

    # Provider (has the class)
    p_client = CommIPC(socket_path=SOCKET_PATH)
    await p_client.connect()
    p_chan = await p_client.open("news")
    await p_chan.add_subscription("top", model=Nested)

    # Subscriber (return_type='model', but NO local class knowledge)
    s_client = CommIPC(socket_path=SOCKET_PATH, return_type="model")
    await s_client.connect()
    s_chan = await s_client.open("news")

    received = []

    async def on_data(cd):
        received.append(cd.data)

    await s_chan.subscribe("top", on_data)
    await asyncio.sleep(0.1)

    # Publish
    await p_chan.publish("top", Nested(id=101, data="dynamic info"))
    await asyncio.sleep(0.2)

    assert len(received) == 1
    data = received[0]
    assert isinstance(data, BaseModel)
    assert data.id == 101
    assert data.data == "dynamic info"

    await p_client.close()
    await s_client.close()
    await stop_test_server(server, server_task)


@pytest.mark.asyncio
async def test_dynamic_model_nested_refs():
    """Verify that deeply nested models with $ref and $defs are correctly generated."""
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    server, server_task = await start_test_server(socket_path=SOCKET_PATH)

    p_client = CommIPC(socket_path=SOCKET_PATH)
    await p_client.connect()
    p_chan = await p_client.open("nested_edge")

    async def nested_handler(cd):
        return cd.data

    await p_chan.add_event("process", nested_handler, parameters=Root, returns=Root)

    s_client = CommIPC(socket_path=SOCKET_PATH, return_type="model")
    await s_client.connect()
    s_chan = await s_client.open("nested_edge")

    payload = Root(
        name="root_test",
        items=[Nested(id=1, data="item1"), Nested(id=2, data="item2")],
        single=Nested(id=3, data="item3"),
        opt=None
    )

    res = await s_chan.event("process", payload)

    assert isinstance(res.data, BaseModel)
    assert res.data.name == "root_test"
    assert len(res.data.items) == 2
    assert res.data.items[0].id == 1
    assert res.data.items[1].data == "item2"
    assert res.data.single.id == 3
    assert res.data.opt is None

    await p_client.close()
    await s_client.close()
    await stop_test_server(server, server_task)


@pytest.mark.asyncio
async def test_model_return_type_parity():
    """Verify that return_type='dict' still works as a fallback."""
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    server, server_task = await start_test_server(socket_path=SOCKET_PATH)

    p_client = CommIPC(socket_path=SOCKET_PATH)
    await p_client.connect()
    p_chan = await p_client.open("parity")
    await p_chan.add_subscription("topic", model=Nested)

    s_client = CommIPC(socket_path=SOCKET_PATH, return_type="dict")
    await s_client.connect()
    s_chan = await s_client.open("parity")

    received = []

    async def on_data(cd):
        received.append(cd.data)

    await s_chan.subscribe("topic", on_data)
    await asyncio.sleep(0.1)

    await p_chan.publish("topic", Nested(id=1, data="dict mode"))
    await asyncio.sleep(0.2)

    assert len(received) == 1
    assert isinstance(received[0], dict)
    assert received[0]["id"] == 1

    await p_client.close()
    await s_client.close()
    await stop_test_server(server, server_task)
