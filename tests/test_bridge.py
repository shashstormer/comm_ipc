import asyncio
import unittest
import os
from tests.base import start_test_server, stop_test_server
from pydantic import BaseModel
from comm_ipc.client import CommIPC
from comm_ipc.bridge import CommIPCBridge
from comm_ipc.comm_data import CommData


class TestBridgeIPC(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_a = "/tmp/test_bridge_a.sock"
        self.socket_b = "/tmp/test_bridge_b.sock"
        self.srv_a, self.task_a = await start_test_server(server_id="server-a", socket_path=self.socket_a)
        self.srv_b, self.task_b = await start_test_server(server_id="server-b", socket_path=self.socket_b)

        self.bridge = CommIPCBridge(bridge_id="bridge-ab", socket_path1=self.socket_a, socket_path2=self.socket_b, 
                                   allowed_channels=["cross", "sys", "ch"])
        await self.bridge.connect({}, {})

    async def asyncTearDown(self):
        await self.bridge.stop()
        await stop_test_server(self.task_a)
        await stop_test_server(self.task_b)
        for p in [self.socket_a, self.socket_b]:
            if os.path.exists(p):
                os.remove(p)

    async def test_bridge_edge_cases(self):
        d1 = {
            "channel": "sys",
            "stype": "event",
            "name": "ping",
            "owner": "s",
            "is_local": True
        }
        await self.bridge._process_metadata(d1, self.bridge.c1, self.bridge.c2, "c1", "c2")

        c1 = CommIPC(client_id="s1", socket_path=self.socket_a)
        c2 = CommIPC(client_id="s2", socket_path=self.socket_b)
        d2 = CommData(sender_id="s1", server_id="srv1", channel="ch", event="ev", data={}, path=["server-b"])
        await self.bridge._relay_receive(d2, src_client=c1, dest_client=c2)
        await c1.close()
        await c2.close()

    async def test_bridge_rpc_and_broadcast(self):
        p_a = CommIPC(client_id="provider-a", socket_path=self.socket_a)
        ch_a = await asyncio.wait_for(p_a.open("cross"), timeout=2.0)

        class GreetParams(BaseModel):
            name: str

        async def greet_call(cd): return f"Hello {cd.data['name']}"

        await ch_a.add_event("greet", call=greet_call, parameters=GreetParams)

        await asyncio.sleep(0.5)

        c_b = CommIPC(client_id="consumer-b", socket_path=self.socket_b)
        ch_b = await asyncio.wait_for(c_b.open("cross"), timeout=2.0)

        res = await asyncio.wait_for(ch_b.event("greet", {"name": "Bridge"}), timeout=2.0)
        self.assertEqual(res.data, "Hello Bridge")

        received = asyncio.Event()

        async def shout_handler(_):
            received.set()

        ch_b.on_receive(shout_handler, event_name="shout")

        await asyncio.sleep(0.1)
        await ch_a.broadcast("shout", {"msg": "yo"})

        await asyncio.wait_for(received.wait(), timeout=2.0)
        self.assertTrue(received.is_set())

        await p_a.close()
        await c_b.close()


if __name__ == "__main__":
    unittest.main()
