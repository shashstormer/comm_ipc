import asyncio
import unittest
import os
from tests.base import start_test_server, stop_test_server
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData

class TestTraceabilityIPC(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_trace.sock"
        self.server, self.server_task = await start_test_server(server_id="trace-srv", socket_path=self.socket_path)

    async def asyncTearDown(self):
        await stop_test_server(self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_trace_metadata(self):
        provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        ch_p = await provider.open("trace")
        
        received_data = []

        async def handler(comm_data: CommData):
            received_data.append(comm_data)
            return "ok"
            
        ch_p.on_receive(handler)
        
        consumer = CommIPC(client_id="consumer", socket_path=self.socket_path)
        ch_c = await consumer.open("trace")
        
        await ch_c.broadcast("ping", {"val": 1})
        await asyncio.sleep(0.2)
        
        self.assertEqual(len(received_data), 1)
        data = received_data[0]
        self.assertEqual(data.sender_id, "consumer")
        self.assertEqual(data.server_id, "trace-srv")
        self.assertIn("trace-srv", data.path)
        
        await provider.close()
        await consumer.close()

if __name__ == "__main__":
    unittest.main()
