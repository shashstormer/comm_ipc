import asyncio
import os
import unittest
import uuid

from comm_ipc.client import CommIPC
from comm_ipc.server import CommIPCServer

SOCKET_A = f"/tmp/test_adv_{uuid.uuid4().hex}.sock"

async def start_server(passwords=None, policy="terminate"):
    server = CommIPCServer(socket_path=SOCKET_A, system_passwords=passwords, channel_policy=policy)
    if os.path.exists(SOCKET_A): os.remove(SOCKET_A)
    
    srv = await asyncio.start_unix_server(server.handle_client, SOCKET_A)
    task = asyncio.create_task(srv.serve_forever())
    server.running = True
    
    for _ in range(10):
        if os.path.exists(SOCKET_A): break
        await asyncio.sleep(0.1)
        
    return server, task, srv

async def stop_server(server, task, srv):
    await server.close()
    srv.close()
    await srv.wait_closed()
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    if os.path.exists(SOCKET_A): os.remove(SOCKET_A)

class TestAdvancedMgmt(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = None
        self.server_task = None

    async def asyncTearDown(self):
        if self.server:
            await stop_server(self.server, self.server_task, self.srv)

    async def test_ownership_and_admin(self):
        self.server, self.server_task, self.srv = await start_server()
        
        c1 = CommIPC(client_id="owner", socket_path=SOCKET_A)
        c2 = CommIPC(client_id="other", socket_path=SOCKET_A)

        await c1.open("test-chan")
        await c2.open("test-chan")
        
        with self.assertRaises(Exception):
            await c2.set_password("test-chan", "secure")
            
        await c1.set_password("test-chan", "secure")
        await asyncio.sleep(0.1)
        self.assertEqual(self.server.channel_passwords.get("test-chan"), "secure")
        
        await c1.close()
        await c2.close()

    async def test_policy_terminate(self):
        self.server, self.server_task, self.srv = await start_server(policy="terminate")
        
        c1 = CommIPC(client_id="owner", socket_path=SOCKET_A)
        c2 = CommIPC(client_id="consumer", socket_path=SOCKET_A)
        
        await c1.open("test-chan")
        await c2.open("test-chan")
        
        self.assertIn("test-chan", self.server.channel_members)
        self.assertEqual(len(self.server.channel_members["test-chan"]), 2)
        
        await c1.close()
        await asyncio.sleep(0.2)
        
        self.assertNotIn("test-chan", self.server.channel_members)
        self.assertNotIn("test-chan", self.server.channels)
        
        await c2.close()

    async def test_policy_promote(self):
        self.server, self.server_task, self.srv = await start_server(policy="promote")
        
        c1 = CommIPC(client_id="owner", socket_path=SOCKET_A)
        c2 = CommIPC(client_id="second", socket_path=SOCKET_A)
        
        await c1.open("test-chan")
        await c2.open("test-chan")
        
        self.assertEqual(self.server.channel_members["test-chan"][0], "owner")
        
        await c1.close()
        await asyncio.sleep(0.1)
        
        self.assertEqual(self.server.channel_members["test-chan"][0], "second")
        
        await c2.close()

    async def test_auto_reconnect(self):
        self.server, self.server_task, self.srv = await start_server()
        
        c1 = CommIPC(client_id="reconnector", socket_path=SOCKET_A, auto_reconnect=True)
        ch = await c1.open("sticky-chan")
        
        received = []
        ch.on_receive(lambda data: received.append(data.data), "ping")
        
        await stop_server(self.server, self.server_task, self.srv)
        self.server = None
        await asyncio.sleep(0.5)
        
        self.server, self.server_task, self.srv = await start_server()
        await asyncio.sleep(1.5)
        
        c2 = CommIPC(client_id="sender", socket_path=SOCKET_A)
        ch2 = await c2.open("sticky-chan")
        await ch2.broadcast("ping", "hello")
        
        await asyncio.sleep(0.2)
        self.assertIn("hello", received)
        
        await c1.close()
        await c2.close()

    async def test_insecure_channel_rejection(self):
        self.server, self.server_task, self.srv = await start_server()
        
        c1 = CommIPC(client_id="secure-client", socket_path=SOCKET_A)
        
        with self.assertRaises(Exception) as cm:
            await c1.open("open-chan", password="expected-protected")
        self.assertIn("is unprotected", str(cm.exception))
        
        await c1.close()

    async def test_system_channel_protection(self):
        self.server, self.server_task, self.srv = await start_server(passwords={"__comm_ipc_system": "sys-pass"})
        
        c1 = CommIPC(client_id="unauth", socket_path=SOCKET_A)
        
        with self.assertRaises(Exception) as cm:
            await c1.open("__comm_ipc_system")
        self.assertIn("requires authentication", str(cm.exception)) 
        
        c2 = CommIPC(client_id="auth", socket_path=SOCKET_A)
        ch_sys = await c2.open("__comm_ipc_system", password="sys-pass")
        self.assertIsNotNone(ch_sys)
        
        await c1.close()
        await c2.close()

if __name__ == "__main__":
    unittest.main()
