import asyncio
import os
import unittest
import json
from fastapi import FastAPI, WebSocket
from httpx import AsyncClient, ASGITransport
from pydantic import BaseModel

from comm_ipc import CommIPC, CommIPCServer, CommAPI, CommData
from tests.base import start_test_server, stop_test_server

class TestGatewayExhaustive(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_gateway_ex.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)
        
        self.app = FastAPI()
        self.gateway_client = CommIPC(client_id="gateway", socket_path=self.socket_path)
        await self.gateway_client.connect()
        self.api = CommAPI(self.app, self.gateway_client)
        
        # Provider
        self.provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        await self.provider.connect()
        self.chan = await self.provider.open("gateway_test")

    async def asyncTearDown(self):
        await self.provider.close()
        await self.gateway_client.close()
        await stop_test_server(self.server, self.server_task)
        if os.path.exists(self.socket_path):
            try: os.remove(self.socket_path)
            except: pass

    async def test_sse_5_messages(self):
        """Test SSE stream with exactly 5 messages."""
        async def ticker(cd: CommData):
            for i in range(5):
                yield {"count": i}
                await asyncio.sleep(0.05)
                
        await self.chan.add_event("ticker", ticker)
        
        api_chan = await self.gateway_client.open("gateway_test")
        self.api.add_event(api_chan, "ticker", "/ticker")
        
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            results = []
            async with ac.stream("GET", "/ticker") as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        results.append(json.loads(line[6:]))
                        if len(results) == 5: break
            
            self.assertEqual(len(results), 5)
            self.assertEqual(results[0]["count"], 0)
            self.assertEqual(results[4]["count"], 4)

    async def test_http_methods(self):
        """Test various HTTP methods."""
        async def echo(cd): return cd.data
        await self.chan.add_event("echo", echo)
        api_chan = await self.gateway_client.open("gateway_test")
        self.api.add_event(api_chan, "echo", "/get", method="GET")
        self.api.add_event(api_chan, "echo", "/post", method="POST")
        self.api.add_event(api_chan, "echo", "/delete", method="DELETE")
        
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            r1 = await ac.get("/get", params={"x": 1})
            self.assertEqual(r1.json()["x"], "1")
            
            r2 = await ac.post("/post", json={"x": 2})
            self.assertEqual(r2.json()["x"], 2)
            
            r3 = await ac.request("DELETE", "/delete", json={"x": 3})
            self.assertEqual(r3.json()["x"], 3)

    async def test_schema_dynamics_advanced(self):
        """Test that the API handles schema evolution perfectly."""
        async def handler_v1(cd): return {"v": 1, "res": cd.data["a"] + 1}
        await self.chan.add_event("dyn", handler_v1)
        
        api_chan = await self.gateway_client.open("gateway_test")
        self.api.add_event(api_chan, "dyn", "/dyn")
        
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            # 1. Call V1
            resp = await ac.post("/dyn", json={"a": 10})
            self.assertEqual(resp.json()["v"], 1)
            
            # 2. Change Provider Logic and Schema
            async def handler_v2(cd): return {"v": 2, "res": f"Hello {cd.data['name']}"}
            # Manually update the event on the same channel
            await self.chan.add_event("dyn", handler_v2)
            # Give a moment for metadata propagation
            await asyncio.sleep(0.2)
            
            # 3. Call V2 - Gateway should adapt immediately!
            resp = await ac.post("/dyn", json={"name": "Alice"})
            self.assertEqual(resp.json()["v"], 2)
            self.assertEqual(resp.json()["res"], "Hello Alice")

if __name__ == "__main__":
    unittest.main()
