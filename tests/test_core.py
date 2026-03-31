import asyncio
import unittest
import os
from typing import Union, Callable, Optional, Dict, Any
from tests.base import start_test_server, stop_test_server
from comm_ipc.client import CommIPC
from comm_ipc.server import CommIPCServer
from comm_ipc.channel import CommIPCChannel
from comm_ipc.comm_data import CommData

class TestCoreIPC(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_core.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)

    async def asyncTearDown(self):
        await stop_test_server(self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_rpc_call(self):
        provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        chan_p = await provider.open("math")
        async def add(cd: CommData): return cd.data["a"] + cd.data["b"]
        await chan_p.add_event("add", call=add, parameters={"a": int, "b": int})
        consumer = CommIPC(client_id="consumer", socket_path=self.socket_path)
        chan_c = await consumer.open("math")
        result = await chan_c.event("add", {"a": 5, "b": 10})
        self.assertEqual(result.data, 15)
        await provider.close()
        await consumer.close()

    async def test_broadcast(self):
        c1 = CommIPC(client_id="c1", socket_path=self.socket_path)
        c2 = CommIPC(client_id="c2", socket_path=self.socket_path)
        ch1 = await c1.open("events")
        ch2 = await c2.open("events")
        received = asyncio.Event()
        data_received = None
        async def on_event(cd: CommData):
            nonlocal data_received
            data_received = cd.data
            received.set()
        ch2.on_receive(on_event, event_name="alert")
        await asyncio.sleep(0.1)
        await ch1.broadcast("alert", {"msg": "fire!"})
        await asyncio.wait_for(received.wait(), timeout=1.0)
        self.assertEqual(data_received["msg"], "fire!")
        await c1.close()
        await c2.close()

    async def test_tcp_connectivity(self):
        tcp_server = CommIPCServer(error_policy="broadcast")
        tcp_task = asyncio.create_task(tcp_server.run(host="127.0.0.1", port=8890))
        await asyncio.sleep(0.5)
        client = CommIPC()
        await client.connect(host="127.0.0.1", port=8890)
        self.assertEqual(client.server_id, tcp_server.server_id)
        await client.close()
        tcp_task.cancel()
        try: await tcp_task
        except asyncio.CancelledError: pass

    async def test_validation_logic(self):
        chan = CommIPCChannel("test", None)
        schema = {"age": int, "opt": Union[int, None]}
        with self.assertRaises(TypeError): chan.validate_data("not-dict", schema)
        with self.assertRaises(ValueError): chan.validate_data({}, schema)
        with self.assertRaises(TypeError): chan.validate_data({"age": None}, schema)
        chan.validate_data({"age": 10, "opt": None}, schema)

    async def test_error_policies_and_callbacks(self):
        srv = CommIPCServer(error_policy="raise")
        with self.assertRaises(Exception): await srv._report_error(Exception("fail"))
        err_event = asyncio.Event()
        async def on_err(e): err_event.set()
        client = CommIPC(on_error=on_err, socket_path=self.socket_path)
        await client.connect()
        if client.writer: client.writer.close()
        await client.send_msg({"type": "ping"})
        await asyncio.wait_for(err_event.wait(), timeout=1.0)
        await client.close()

    async def test_generic_async_listener(self):
        c1 = CommIPC(socket_path=self.socket_path)
        await c1.connect()
        chan1 = await c1.open("gen")
        received = asyncio.Event()
        async def gen_handler(cd: CommData): received.set()
        chan1.on_receive(gen_handler)
        c2 = CommIPC(socket_path=self.socket_path)
        await c2.connect()
        chan2 = await c2.open("gen")
        await chan2.broadcast("any", {"x": 1})
        await asyncio.wait_for(received.wait(), timeout=1.0)
        received_sync = asyncio.Event()
        def sync_handler(cd: CommData): received_sync.set()
        chan1.on_receive(sync_handler)
        await chan2.broadcast("other", {"y": 2})
        await asyncio.wait_for(received_sync.wait(), timeout=1.0)
        await c1.close()
        await c2.close()

    async def test_server_send_type(self):
        client = CommIPC(socket_path=self.socket_path)
        await client.connect()
        p = CommIPC(client_id="p1", socket_path=self.socket_path)
        ch_p = await p.open("ch1")
        received = asyncio.Event()
        async def on_msg(cd: CommData):
            received.set()
        await ch_p.add_event("e1", call=on_msg)
        await asyncio.sleep(0.5)
        
        await client.send_msg({"type": "send", "channel": "ch1", "event": "e1", "data": {"hello": 1}})
        await asyncio.wait_for(received.wait(), timeout=3.0)
        
        await client.close()
        await p.close()

    async def test_error_broadcast_policy(self):
        srv = CommIPCServer(error_policy="broadcast", socket_path="/tmp/test_err.sock")
        task = asyncio.create_task(srv.run())
        await asyncio.sleep(0.2)
        client = CommIPC(socket_path="/tmp/test_err.sock")
        await client.connect()
        error_received = asyncio.Event()
        err_ch = await client.open("__comm_ipc_errors")
        def on_err(cd: CommData):
            error_received.set()
        err_ch.on_receive(on_err)
        await asyncio.sleep(0.2)
        print("[DEBUG] triggering server error")
        await srv._report_error(Exception("test-err"))
        await asyncio.wait_for(error_received.wait(), timeout=2.0)
        
        await client.close()
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        if os.path.exists("/tmp/test_err.sock"): os.remove("/tmp/test_err.sock")

    async def test_client_stream_connect(self):
        p = CommIPC(client_id="provider", socket_path=self.socket_path)
        ch_p = await p.open("ch_stream")
        async def h(cd: CommData):
            n = cd.data["n"]
            for i in range(n): yield i
        await ch_p.add_event("ev", call=h)

        client = CommIPC(socket_path=self.socket_path)
        results = []
        
        async def run_stream():
            async for chunk in client.stream("ch_stream", "ev", {"n": 5}):
                results.append(chunk.data)
        
        await asyncio.wait_for(run_stream(), timeout=2.0)
        self.assertEqual(results, [0, 1, 2, 3, 4])
        
        await p.close()
        await client.close()

if __name__ == "__main__":
    unittest.main()
