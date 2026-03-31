import asyncio
import unittest
import os
from typing import Union, Optional, List
from tests.base import start_test_server, stop_test_server
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData
from comm_ipc.bridge import CommIPCBridge

class TestCoverageEdge(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_edge.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)
        self.server.error_policy = "broadcast"

    async def asyncTearDown(self):
        await stop_test_server(self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_validation_edge_cases(self):
        client = CommIPC(socket_path=self.socket_path)
        ch = await client.open("edge")
        
        async def handler(cd: CommData):
            a = cd.data.get("a")
            b = cd.data.get("b")
            return f"{a}-{b}"
            
        await ch.add_event("test", call=handler, parameters={"a": Union[int, str], "b": Optional[int]})
        
        res1 = await ch.event("test", {"a": 1, "b": 2})
        self.assertEqual(res1.data, "1-2")
        res2 = await ch.event("test", {"a": "hi"})
        self.assertEqual(res2.data, "hi-None")
        
        with self.assertRaises(Exception):
            await ch.event("test", {"a": 1.5})
        with self.assertRaises(Exception):
            await ch.event("test", {}) 
        with self.assertRaises(Exception):
            await ch.event("test", {"a": 1, "b": "wrong"})
            
        await client.close()

    async def test_tcp_and_reconnect(self):
        srv, srv_task = await start_test_server(server_id="tcp-srv", socket_path="/tmp/unused.sock")
        tcp_task = asyncio.create_task(srv.run(host="127.0.0.1", port=9999))
        await asyncio.sleep(0.1)
        
        c = CommIPC()
        await c.connect(host="127.0.0.1", port=9999)
        self.assertEqual(c.server_id, "tcp-srv")
        
        await c.connect(host="127.0.0.1", port=9999) 
        
        await c.close()
        tcp_task.cancel()
        await stop_test_server(srv_task)

    async def test_bridge_loop_prevention(self):
        b = CommIPCBridge("b1", self.socket_path, self.socket_path)
        b.c2.server_id = "target-srv"
        d = CommData("s", "srv", "ch", "ev", {}, path=["target-srv"])
        await b._relay_receive(d, b.c1, b.c2)

    async def test_client_error_reporting(self):
        client = CommIPC(socket_path=self.socket_path)
        await client.connect()
        with self.assertRaises(Exception):
            await client.call("unknown_chan", "ev", {})
        await client.close()

    async def test_server_branch_logic(self):
        c1 = CommIPC(client_id="fixed-id", socket_path=self.socket_path)
        await c1.connect()
        
        c2 = CommIPC(client_id="fixed-id", socket_path=self.socket_path)
        with self.assertRaises(Exception):
            await c2.connect()
            
        ch1 = await c1.open("chan1")
        await ch1.add_event("ev1", call=lambda cd: "ok")
        
        c3 = CommIPC(client_id="p3", socket_path=self.socket_path)
        ch3 = await c3.open("chan1")
        await ch3.add_event("ev1", call=lambda cd: "fail")
        
        await c1.close()
        await c3.close()

    async def test_more_coverage(self):
        client = CommIPC(socket_path=self.socket_path)
        ch = await client.open("more")
        
        with self.assertRaises(Exception):
             await ch.handle_call(CommData(sender_id="s", server_id="srv", channel="more", event="bad", data={}))
             
        await client.open("more", password="new")
        self.assertEqual(ch.password, "new")
        
        err_received = asyncio.Event()
        client.on_error = lambda e: err_received.set()
        client.writer.close()
        try:
            await client.send_msg({"msg": 1})
        except:
            pass
        await asyncio.sleep(0.1)
        self.assertTrue(err_received.is_set())
        
        await client.close()
