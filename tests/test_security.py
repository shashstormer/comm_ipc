import asyncio
import unittest
import os
from tests.base import start_test_server, stop_test_server
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData

class TestSecurityIPC(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_security.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)
        self.server.error_policy = "broadcast"
        self.server.channel_passwords["secure"] = "1234"

    async def asyncTearDown(self):
        await stop_test_server(self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_auto_id(self):
        client = CommIPC(socket_path=self.socket_path)
        await client.connect()
        self.assertTrue(client.client_id.startswith("cli-"))
        await client.close()

    async def test_id_collision(self):
        c1 = CommIPC(client_id="same-id", socket_path=self.socket_path)
        await c1.connect()
        
        c2 = CommIPC(client_id="same-id", socket_path=self.socket_path)
        with self.assertRaises(Exception) as cm:
            try:
                await c2.connect()
            finally:
                await c2.close()
        self.assertIn("already in use", str(cm.exception))
        
        await c1.close()

    async def test_password_protection(self):
        c_bad = CommIPC(client_id="bad-actor", socket_path=self.socket_path)
        provider = CommIPC(client_id="admin", socket_path=self.socket_path)
        consumer = CommIPC(client_id="user", socket_path=self.socket_path)
        
        try:
            await c_bad.connect()
            with self.assertRaisesRegex(Exception, "Invalid channel password"):
                await c_bad.open("secure", password="wrong")
            
            await provider.connect()
            ch_admin = await provider.open("secure", password="1234")
            
            async def secret_call(_: CommData): return "done"
            await ch_admin.add_event("shutdown", call=secret_call)
            
            await consumer.connect()
            ch_user = await consumer.open("secure", password="1234")
            res = await ch_user.event("shutdown", {})
            self.assertEqual(res.data, "done")
        finally:
            await asyncio.gather(
                c_bad.close(),
                provider.close(),
                consumer.close(),
                return_exceptions=True
            )

    async def test_duplicate_listener(self):
        c1 = CommIPC(client_id="p1", socket_path=self.socket_path)
        ch1 = await c1.open("dup_chan")
        await ch1.add_event("event1", call=lambda _: "ok")
        
        c2 = CommIPC(client_id="p2", socket_path=self.socket_path)
        ch2 = await c2.open("dup_chan")
                                                                                                                            
                                                                                          
        with self.assertRaisesRegex(Exception, "Provider already exists"):
            await ch2.add_event("event1", call=lambda _: "fail")
        
        self.assertEqual(len(self.server.providers["dup_chan"]), 1)
        self.assertEqual(self.server.providers["dup_chan"]["event1"][0], "p1")
        
        await c1.close()
        await c2.close()

    async def test_unauthorized_password_set(self):
        c1 = CommIPC(client_id="owner", socket_path=self.socket_path)
        await c1.open("sec")
        await c1.set_password("sec", "p1")
        
        c2 = CommIPC(client_id="intruder", socket_path=self.socket_path)
        await c2.open("sec", password="p1")
        with self.assertRaisesRegex(Exception, "Only the channel owner"):
            await c2.set_password("sec", "p2")
        
        await c1.close()
        await c2.close()

if __name__ == "__main__":
    unittest.main()
