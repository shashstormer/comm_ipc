import asyncio
import os
import unittest
from comm_ipc.server import CommIPCServer
from comm_ipc.client import CommIPC
from comm_ipc.bridge import CommIPCBridge

class TestFederatedDiscovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.s1_path = "/tmp/fed_s1.sock"
        self.s2_path = "/tmp/fed_s2.sock"
        
        self.server1 = CommIPCServer(server_id="S1", socket_path=self.s1_path)
        self.server2 = CommIPCServer(server_id="S2", socket_path=self.s2_path)
        
        self.t1 = asyncio.create_task(self.server1.run())
        self.t2 = asyncio.create_task(self.server2.run())
        await asyncio.sleep(0.2)

    async def asyncTearDown(self):
        await self.server1.stop()
        await self.server2.stop()
        self.t1.cancel()
        self.t2.cancel()
        if os.path.exists(self.s1_path): os.remove(self.s1_path)
        if os.path.exists(self.s2_path): os.remove(self.s2_path)

    async def test_federated_membership_and_routing(self):
        # 1. Connect a client to S1
        c1 = CommIPC(client_id="Client-A", socket_path=self.s1_path)
        await c1.connect()
        chan1 = await c1.open("test-chan")
        
        # 2. Setup a provider on S1
        async def hello(cd): return f"Hello from {cd.target_id} via S1"
        await chan1.add_event("greet", hello)
        
        # 3. Connect a bridge between S1 and S2
        bridge = CommIPCBridge(bridge_id="Bridge-1", socket_path1=self.s1_path, socket_path2=self.s2_path, allowed_channels=["test-chan"])
        await bridge.connect({}, {})
        await asyncio.sleep(0.5) # Wait for sync
        
        # 4. Connect a client to S2
        c2 = CommIPC(client_id="Client-B", socket_path=self.s2_path)
        await c2.connect()
        chan2 = await c2.open("test-chan")
        
        # 5. Verify Client-A is visible on S2 via Bridge
        members_resp = await chan2.list_members()
        member_ids = [m["id"] for m in members_resp.data["members"]]
        print(f"S2 Members: {member_ids}")
        self.assertIn("Client-A", member_ids)
        
        # 6. Verify RPC works cross-server
        res = await chan2.event("greet", {})
        print(f"RPC Result: {res.data}")
        self.assertIn("via S1", res.data)
        
        # 7. Broadcast test
        received = asyncio.Event()
        async def on_broadcast(cd):
            if cd.data == "ping":
                received.set()
        
        chan1.on_receive(on_broadcast)
        await asyncio.sleep(0.1)
        await chan2.broadcast("ping", "ping")
        
        try:
            await asyncio.wait_for(received.wait(), timeout=2.0)
            print("Broadcast relayed successfully!")
        except asyncio.TimeoutError:
            self.fail("Broadcast failed to relay through bridge")

        await c1.close()
        await c2.close()
        await bridge.stop()

if __name__ == "__main__":
    unittest.main()
