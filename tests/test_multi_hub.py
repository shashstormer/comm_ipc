import asyncio
import os
import unittest
from comm_ipc.server import CommIPCServer
from comm_ipc.client import CommIPC
from comm_ipc.bridge import CommIPCBridge

class TestMultiHubRouting(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p1 = "/tmp/hop_s1.sock"
        self.p2 = "/tmp/hop_s2.sock"
        self.p3 = "/tmp/hop_s3.sock"
        
        self.s1 = CommIPCServer(server_id="S1", socket_path=self.p1)
        self.s2 = CommIPCServer(server_id="S2", socket_path=self.p2)
        self.s3 = CommIPCServer(server_id="S3", socket_path=self.p3)
        
        self.t1 = asyncio.create_task(self.s1.run())
        self.t2 = asyncio.create_task(self.s2.run())
        self.t3 = asyncio.create_task(self.s3.run())
        await asyncio.sleep(0.2)

    async def asyncTearDown(self):
        await asyncio.gather(self.s1.stop(), self.s2.stop(), self.s3.stop())
        for t in [self.t1, self.t2, self.t3]: t.cancel()
        for p in [self.p1, self.p2, self.p3]:
            if os.path.exists(p): os.remove(p)

    async def test_three_hop_rpc_and_broadcast(self):
        c_a = CommIPC(client_id="Client-A", socket_path=self.p1)
        await c_a.connect()
        ch_a = await c_a.open("hop-chan")
        
        async def hello_from_s1(cd):
            return "Hello from Hub 1"
        await ch_a.add_event("greet", hello_from_s1)
        
        b1 = CommIPCBridge(bridge_id="B1", socket_path1=self.p1, socket_path2=self.p2, allowed_channels=["hop-chan"])
        b2 = CommIPCBridge(bridge_id="B2", socket_path1=self.p2, socket_path2=self.p3, allowed_channels=["hop-chan"])
        
        await b1.connect({}, {})
        await b2.connect({}, {})
        await asyncio.sleep(1.0)

        c_c = CommIPC(client_id="Client-C", socket_path=self.p3)
        await c_c.connect()
        ch_c = await c_c.open("hop-chan")
        
        members_resp = await ch_c.list_members()
        member_ids = [m["id"] for m in members_resp.data["members"]]
        print(f"S3 Members: {member_ids}")
        
        try:
            res = await asyncio.wait_for(ch_c.event("greet", {}), timeout=3.0)
            print(f"Transitive RPC Result: {res.data}")
            self.assertEqual(res.data, "Hello from Hub 1")
        except asyncio.TimeoutError:
            self.fail("Transitive RPC (S3->S2->S1) timed out")
        except Exception as e:
            self.fail(f"Transitive RPC failed: {e}")
            
        received = asyncio.Event()
        async def on_hop_msg(cd):
            if cd.data == "ping":
                received.set()
        
        ch_c.on_receive(on_hop_msg)
        await asyncio.sleep(0.1)
        await ch_a.broadcast("hop-msg", "ping")
        
        try:
            await asyncio.wait_for(received.wait(), timeout=3.0)
            print("Transitive Broadcast succeeded!")
        except asyncio.TimeoutError:
            self.fail("Transitive Broadcast (S1->S2->S3) timed out")

        await c_a.close()
        await c_c.close()
        await b1.stop()
        await b2.stop()

    async def test_circular_routing(self):
        # Topology: Hub S1 - Hub S2 - Hub S3 - Hub S1 (Loop)
        
        # 1. Setup Client-A on S1
        c_a = CommIPC(client_id="Client-A", socket_path=self.p1)
        await c_a.connect()
        await c_a.open("loop-chan")
        
        # 2. Start Bridges forming a ring: B1(S1-S2), B2(S2-S3), B3(S3-S1)
        b1 = CommIPCBridge(bridge_id="B1", socket_path1=self.p1, socket_path2=self.p2, allowed_channels=["loop-chan"])
        b2 = CommIPCBridge(bridge_id="B2", socket_path1=self.p2, socket_path2=self.p3, allowed_channels=["loop-chan"])
        b3 = CommIPCBridge(bridge_id="B3", socket_path1=self.p3, socket_path2=self.p1, allowed_channels=["loop-chan"])
        
        await asyncio.gather(b1.connect({}, {}), b2.connect({}, {}), b3.connect({}, {}))
        await asyncio.sleep(1.0) # Let the paths propagate
        
        # 3. Connect Client-C to S3
        c_c = CommIPC(client_id="Client-C", socket_path=self.p3)
        await c_c.connect()
        ch_c = await c_c.open("loop-chan")
        
        # 4. Check Client-A from S3
        # Path 1: S1 -> B1 -> S2 -> B2 -> S3 (Path: [S1, S2])
        # Path 2: S1 -> B3 -> S3 (Path: [S1]) 
        # S3 should prefer Path 2 (shortest)
        members_resp = await ch_c.list_members()
        members = members_resp.data["members"]
        client_a = next(m for m in members if m["id"] == "Client-A")
        
        print(f"Client-A routing on S3: {client_a}")
        self.assertEqual(len(client_a["path"]), 1, "Should prefer shortest path (1 hop)")
        self.assertEqual(client_a["path"], [self.s1.server_id])
        
        # 5. Verify no infinite "ghost" members if Client-A disappears
        await c_a.close()
        await asyncio.sleep(1.0)
        
        members_resp = await ch_c.list_members()
        member_ids = [m["id"] for m in members_resp.data["members"]]
        print(f"Members on S3 after Client-A disconnect: {member_ids}")
        self.assertNotIn("Client-A", member_ids, "Client-A should be purged even in circular topology")
        
        await b1.stop()
        await b2.stop()
        await b3.stop()
        await c_c.close()

if __name__ == "__main__":
    unittest.main()
