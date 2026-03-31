import asyncio
import os
import unittest

from comm_ipc.bridge import CommIPCBridge
from comm_ipc.client import CommIPC
from comm_ipc.server import CommIPCServer
from tests.base import stop_test_server


class TestZeroTrust(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_zero_trust.sock"
        self.secret = "top-secret"
        self.server = CommIPCServer(server_id="secure-srv", socket_path=self.socket_path, connection_secret=self.secret)
        self.server_task = asyncio.create_task(self.server.run())
        await asyncio.sleep(0.1)

    async def asyncTearDown(self):
        await stop_test_server(self.server, self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_handshake_success(self):
        client = CommIPC(socket_path=self.socket_path, connection_secret=self.secret)
        await client.connect()
        self.assertTrue(client._ready.is_set())
        await client.close()

    async def test_handshake_failure(self):
        client = CommIPC(socket_path=self.socket_path, connection_secret="wrong-secret")
        with self.assertRaises(Exception) as cm:
            await client.connect()
        self.assertIn("Authentication failed", str(cm.exception))

    async def test_e2e_integrity(self):
        c1 = CommIPC(client_id="sender", socket_path=self.socket_path, connection_secret=self.secret)
        c2 = CommIPC(client_id="receiver", socket_path=self.socket_path, connection_secret=self.secret)
        
        ch1 = await c1.open("secure-chan", password="chan-password")
        ch2 = await c2.open("secure-chan", password="chan-password")
        
        received_event = asyncio.Event()
        received_data = None
        
        async def on_recv(cd):
            nonlocal received_data
            received_data = cd.data
            received_event.set()
            
        ch2.on_receive(on_recv)
        await asyncio.sleep(0.1)
        
        await ch1.broadcast("test-event", {"hello": "world"})
        await asyncio.wait_for(received_event.wait(), timeout=2.0)
        self.assertEqual(received_data, {"hello": "world"})
        
        await c1.close()
        await c2.close()

    async def test_signature_mismatch(self):
        c1 = CommIPC(client_id="sender", socket_path=self.socket_path, connection_secret=self.secret)
        c2 = CommIPC(client_id="receiver", socket_path=self.socket_path, connection_secret=self.secret)
        
        ch1 = await c1.open("secure-chan", password="chan-password")
        ch2 = await c2.open("secure-chan", password="wrong-password")
        
        received_event = asyncio.Event()
        
        async def on_recv(_):
            received_event.set()
            
        ch2.on_receive(on_recv)
        await asyncio.sleep(0.1)
        
        await ch1.broadcast("test-event", {"hello": "world"})
        try:
            await asyncio.wait_for(received_event.wait(), timeout=1.0)
            self.fail("Should not have received message with wrong signature")
        except asyncio.TimeoutError:
            pass # Success
            
        await c1.close()
        await c2.close()

    async def test_bridge_filtering(self):
        s1_path = "/tmp/s1.sock"
        s2_path = "/tmp/s2.sock"
        
        s1 = CommIPCServer(server_id="s1", socket_path=s1_path)
        s1_task = asyncio.create_task(s1.run())
        
        s2 = CommIPCServer(server_id="s2", socket_path=s2_path)
        s2_task = asyncio.create_task(s2.run())
        
        await asyncio.sleep(0.1)
        
        # Bridge only 'allowed' channel
        bridge = CommIPCBridge(socket_path1=s1_path, socket_path2=s2_path, allowed_channels=["allowed"])
        await bridge.connect({}, {})
        
        c1 = CommIPC(socket_path=s1_path)
        await c1.open("allowed")
        await c1.open("forbidden")
        c2 = CommIPC(socket_path=s2_path)
        await c2.open("allowed")
        await c2.open("forbidden")
        
        # Wait for sync
        await asyncio.sleep(0.2)
        
        # Check that 'allowed' is bridged
        self.assertIn("allowed", bridge.synced_channels["c1"])
        self.assertIn("allowed", bridge.synced_channels["c2"])
        
        # Check that 'forbidden' is NOT bridged
        self.assertNotIn("forbidden", bridge.synced_channels["c1"])
        
        await bridge.stop()
        await stop_test_server(s1, s1_task)
        await stop_test_server(s2, s2_task)
        if os.path.exists(s1_path): os.remove(s1_path)
        if os.path.exists(s2_path): os.remove(s2_path)

if __name__ == "__main__":
    unittest.main()
