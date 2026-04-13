import asyncio
import os
import unittest

from pydantic import BaseModel
from comm_ipc.client import CommIPC
from tests.base import start_test_server, stop_test_server


class TestStreamIPC(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_stream.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)

    async def asyncTearDown(self):
        await stop_test_server(self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_basic_streaming(self):
        provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        chan_p = await provider.open("streaming")

        class CountParams(BaseModel):
            n: int

        async def count_to(cd):
            n = cd.data["n"]
            for i in range(1, n + 1):
                yield i
                await asyncio.sleep(0.01)

        await chan_p.add_stream("count", call=count_to, parameters=CountParams)

        consumer = CommIPC(client_id="consumer", socket_path=self.socket_path)
        chan_c = await consumer.open("streaming")

        try:
            results = []
            async for chunk in chan_c.stream("count", {"n": 5}):
                results.append(chunk.data)
            self.assertEqual(results, [1, 2, 3, 4, 5])
        finally:
            await asyncio.gather(provider.close(), consumer.close(), return_exceptions=True)

    async def test_stream_error(self):
        provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        chan_p = await provider.open("errors")

        async def fail_stream(_):
            yield "first"
            raise ValueError("oops")

        await chan_p.add_stream("fail", call=fail_stream)

        consumer = CommIPC(client_id="consumer", socket_path=self.socket_path)
        chan_c = await consumer.open("errors")

        try:
            results = []
            with self.assertRaises(Exception) as cm:
                async for chunk in chan_c.stream("fail", {}):
                    results.append(chunk.data)

            self.assertEqual(results, ["first"])
            self.assertIn("oops", str(cm.exception))
        finally:
            await asyncio.gather(provider.close(), consumer.close(), return_exceptions=True)

    async def test_bridge_streaming(self):
        from comm_ipc.bridge import CommIPCBridge
        socket_a = "/tmp/test_stream_a.sock"
        socket_b = "/tmp/test_stream_b.sock"
        task_a = None
        task_b = None
        bridge = None
        p_a = None
        c_b = None

        try:
            srv_a, task_a = await start_test_server(server_id="server-a", socket_path=socket_a)
            srv_b, task_b = await start_test_server(server_id="server-b", socket_path=socket_b)

            bridge = CommIPCBridge(bridge_id="bridge-ab", socket_path1=socket_a, socket_path2=socket_b, 
                                   allowed_channels=["cross_stream"])
            await bridge.connect({}, {})

            p_a = CommIPC(client_id="p-a", socket_path=socket_a)
            ch_a = await p_a.open("cross_stream")

            async def gen(_):
                yield "part1"
                yield "part2"

            await ch_a.add_stream("get_parts", call=gen)
            await asyncio.sleep(0.5)

            c_b = CommIPC(client_id="c-b", socket_path=socket_b)
            ch_b = await c_b.open("cross_stream")

            results = []
            async for chunk in ch_b.stream("get_parts", {}):
                results.append(chunk.data)
            self.assertEqual(results, ["part1", "part2"])
        finally:
            await asyncio.gather(
                p_a.close() if p_a else asyncio.sleep(0),
                c_b.close() if c_b else asyncio.sleep(0),
                bridge.stop() if bridge else asyncio.sleep(0),
                stop_test_server(task_a) if task_a else asyncio.sleep(0),
                stop_test_server(task_b) if task_b else asyncio.sleep(0),
                return_exceptions=True
            )
            for p in [socket_a, socket_b]:
                if os.path.exists(p): os.remove(p)


if __name__ == "__main__":
    unittest.main()
