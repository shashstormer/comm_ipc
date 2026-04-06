import asyncio
import unittest
import os
from comm_ipc.client import CommIPC
from tests.base import start_test_server, stop_test_server

class TestStrictAsync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_strict_async.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)

    async def asyncTearDown(self):
        await stop_test_server(self.server, self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_sync_callback_failure(self):
        provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        ch_p = await provider.open("strict")
        
        def sync_handler(_):
            return "fail"
        await ch_p.add_event("call_sync", call=sync_handler)
        
        caller = CommIPC(client_id="caller", socket_path=self.socket_path)
        ch_c = await caller.open("strict")
        
        with self.assertRaises(Exception) as cm:
            await ch_c.event("call_sync", {})
            
        err_msg = str(cm.exception)
        self.assertIn("can't be used in 'await' expression", err_msg)
        
        err_event = asyncio.Event()
        async def on_err(e): 
            if "can't be used in 'await' expression" in str(e):
                err_event.set()
            
        subscriber = CommIPC(client_id="sub", socket_path=self.socket_path, on_error=on_err)
        s_ch = await subscriber.open("strict")
        
        def sync_on_msg(_):
            pass
        await s_ch.subscribe("topic", sync_on_msg)
        
        await ch_p.add_subscription("topic")
        await asyncio.sleep(0.1)
        await ch_p.publish("topic", "ping")
        
        await asyncio.wait_for(err_event.wait(), timeout=2.0)
        self.assertTrue(err_event.is_set())
        
        await provider.close()
        await caller.close()
        await subscriber.close()

if __name__ == "__main__":
    unittest.main()
