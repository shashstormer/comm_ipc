import asyncio
import pytest
import time
from comm_ipc.server import CommIPCServer
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData

@pytest.mark.asyncio
async def test_group_load_balancing_least_active():
    socket_path = f"/tmp/comm_ipc_test_group_{int(time.time())}.sock"
    server = CommIPCServer(socket_path=socket_path, lb_policy="least-active")
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)

    client1 = CommIPC(socket_path=socket_path, client_id="provider1")
    client2 = CommIPC(socket_path=socket_path, client_id="provider2")
    consumer = CommIPC(socket_path=socket_path, client_id="consumer")

    results = []

    async def handler1(cd: CommData):
        results.append("p1")
        await asyncio.sleep(0.2) # Simulate work
        return "done1"

    async def handler2(cd: CommData):
        results.append("p2")
        await asyncio.sleep(0.2) # Simulate work
        return "done2"

    chan1 = await client1.open("test_group")
    await chan1.group.provide("work", handler1)

    chan2 = await client2.open("test_group")
    await chan2.group.provide("work", handler2)

    chan_cons = await consumer.open("test_group")
    g_cons = chan_cons.group

    # Send 4 calls concurrently
    tasks = [g_cons.get("work", {"i": i}) for i in range(4)]
    await asyncio.gather(*tasks)

    # With least-active, they should be distributed
    p1_count = results.count("p1")
    p2_count = results.count("p2")
    
    print(f"P1: {p1_count}, P2: {p2_count}")
    assert p1_count == 2
    assert p2_count == 2

    await client1.close()
    await client2.close()
    await consumer.close()
    await server.close()
    server_task.cancel()

@pytest.mark.asyncio
async def test_group_load_balancing_round_robin():
    socket_path = f"/tmp/comm_ipc_test_group_rr_{int(time.time())}.sock"
    server = CommIPCServer(socket_path=socket_path, lb_policy="round-robin")
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)

    client1 = CommIPC(socket_path=socket_path, client_id="provider1")
    client2 = CommIPC(socket_path=socket_path, client_id="provider2")
    consumer = CommIPC(socket_path=socket_path, client_id="consumer")

    results = []

    async def handler1(cd: CommData):
        results.append("p1")
        return "done1"

    async def handler2(cd: CommData):
        results.append("p2")
        return "done2"

    chan1 = await client1.open("test_group")
    await chan1.group.provide("work", handler1)
    
    chan2 = await client2.open("test_group")
    await chan2.group.provide("work", handler2)

    chan_cons = await consumer.open("test_group")
    g_cons = chan_cons.group

    # Send 4 calls sequentially
    for _ in range(4):
        await g_cons.get("work", {})

    print(f"Results: {results}")
    # Should be p1, p2, p1, p2
    assert results == ["p1", "p2", "p1", "p2"]

    await client1.close()
    await client2.close()
    await consumer.close()
    await server.close()
    server_task.cancel()

@pytest.mark.asyncio
async def test_exclusive_registration():
    socket_path = f"/tmp/comm_ipc_test_exclusive_{int(time.time())}.sock"
    server = CommIPCServer(socket_path=socket_path)
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)

    client1 = CommIPC(socket_path=socket_path, client_id="provider1")
    client2 = CommIPC(socket_path=socket_path, client_id="provider2")
    
    await client1.connect()
    await client2.connect()

    async def h1(cd): return 1
    async def h2(cd): return 2

    chan1 = await client1.open("test_chan")
    await chan1.add_event("work", h1)

    chan2 = await client2.open("test_chan")
    with pytest.raises(Exception, match="Provider already exists"):
        await chan2.add_event("work", h2)

    await client1.close()
    await client2.close()
    await server.close()
    server_task.cancel()

@pytest.mark.asyncio
async def test_group_with_password():
    socket_path = f"/tmp/comm_ipc_test_group_pwd_{int(time.time())}.sock"
    server = CommIPCServer(socket_path=socket_path)
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)

    client1 = CommIPC(socket_path=socket_path, client_id="provider")
    consumer = CommIPC(socket_path=socket_path, client_id="consumer")

    async def h(cd): return cd.data * 2

    # Provider opens and sets password
    chan1 = await client1.open("secured_group")
    await client1.set_password("secured_group", "secret_pwd")
    await chan1.group.provide("calc", h)

    # Consumer tries without password (should get identified as error or auth challenge)
    with pytest.raises(Exception):
        await consumer.open("secured_group")

    # Consumer with password
    chan_cons = await consumer.open("secured_group", password="secret_pwd")
    res = await chan_cons.group.get("calc", 21)
    assert res.data == 42

    await client1.close()
    await consumer.close()
    await server.close()
    server_task.cancel()

@pytest.mark.asyncio
async def test_named_subgroups():
    socket_path = f"/tmp/comm_ipc_test_named_sub_{int(time.time())}.sock"
    server = CommIPCServer(socket_path=socket_path)
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)

    client = CommIPC(socket_path=socket_path)
    consumer = CommIPC(socket_path=socket_path)

    async def h_sub1(cd): return "sub1"
    async def h_sub2(cd): return "sub2"

    chan = await client.open("multi_group")
    await chan.group("group1").provide("event", h_sub1)
    await chan.group("group2").provide("event", h_sub2)

    chan_cons = await consumer.open("multi_group")
    
    res1 = await chan_cons.group("group1").get("event", {})
    res2 = await chan_cons.group("group2").get("event", {})

    assert res1.data == "sub1"
    assert res2.data == "sub2"

    await client.close()
    await consumer.close()
    await server.close()
    server_task.cancel()

@pytest.mark.asyncio
async def test_group_streaming():
    socket_path = f"/tmp/comm_ipc_test_group_stream_{int(time.time())}.sock"
    server = CommIPCServer(socket_path=socket_path, lb_policy="round-robin")
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)

    client1 = CommIPC(socket_path=socket_path, client_id="provider1")
    client2 = CommIPC(socket_path=socket_path, client_id="provider2")
    consumer = CommIPC(socket_path=socket_path, client_id="consumer")

    async def gen1(cd):
        yield "p1-1"
        yield "p1-2"

    async def gen2(cd):
        yield "p2-1"
        yield "p2-2"

    chan1 = await client1.open("test_group")
    await chan1.group.provide("stream_work", gen1)
    
    chan2 = await client2.open("test_group")
    await chan2.group.provide("stream_work", gen2)

    chan_cons = await consumer.open("test_group")
    g_cons = chan_cons.group

    # First stream call
    results1 = []
    async for chunk in g_cons.stream("stream_work", {}):
        results1.append(chunk.data)
    
    # Second stream call
    results2 = []
    async for chunk in g_cons.stream("stream_work", {}):
        results2.append(chunk.data)

    print(f"Stream 1: {results1}")
    print(f"Stream 2: {results2}")
    
    assert results1 == ["p1-1", "p1-2"]
    assert results2 == ["p2-1", "p2-2"]

    await client1.close()
    await client2.close()
    await consumer.close()
    await server.close()
    server_task.cancel()
