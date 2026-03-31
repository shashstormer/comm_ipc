import asyncio
import unittest
import os
from tests.base import start_test_server, stop_test_server
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData

class TestRegistrationLock(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_reg_lock.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)

    async def asyncTearDown(self):
        if hasattr(self, 'server_task'):
            await stop_test_server(self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_registration_lock_and_cleanup(self):
        client_a = CommIPC(client_id="client_a", socket_path=self.socket_path)
        await client_a.connect()
        chan_a = await client_a.open("lock_chan")
        
        async def handler(cd: CommData):
            return "ok"
        
        await chan_a.add_event("ev1", call=handler)
        await asyncio.sleep(0.4)

        client_b = CommIPC(client_id="client_b", socket_path=self.socket_path)
        await client_b.connect()
        
        error_received = asyncio.Event()
        def on_error(err):
            if "Provider already exists" in str(err):
                error_received.set()
        client_b.on_error = on_error
        
        chan_b = await client_b.open("lock_chan")
        await chan_b.add_event("ev1", call=handler)
        
        try:
            await asyncio.wait_for(error_received.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            self.fail("Did not receive 'Provider already exists' error")
        self.assertTrue(error_received.is_set())

        await client_a.close()
        await asyncio.sleep(0.5)

        error_received.clear()
        
        await chan_b.add_event("ev1", call=handler)
        await asyncio.sleep(0.5)
        
        client_c = CommIPC(client_id="client_c", socket_path=self.socket_path)
        await client_c.connect()
        chan_c = await client_c.open("lock_chan")
        res = await chan_c.event("ev1", {})
        self.assertEqual(res.data, "ok")
        
        await client_b.close()
        await client_c.close()

if __name__ == "__main__":
    unittest.main()
