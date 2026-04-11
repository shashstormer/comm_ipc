import asyncio
import os
import unittest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from pydantic import BaseModel
import json

from comm_ipc import CommIPC, CommIPCServer, CommAPI, CommData
from tests.base import start_test_server, stop_test_server

class TestFastAPIAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_fastapi_api.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)
        
        # Setup provider
        self.provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        await self.provider.connect()
        self.math_chan = await self.provider.open("math")
        
        # Setup FastAPI
        self.app = FastAPI()
        self.gateway_client = CommIPC(client_id="gateway", socket_path=self.socket_path)
        await self.gateway_client.connect()
        self.api = CommAPI(self.app, self.gateway_client)

    async def asyncTearDown(self):
        await self.gateway_client.close()
        await self.provider.close()
        await stop_test_server(self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_basic_rpc(self):
        # 1. Register event on provider
        class AddParams(BaseModel):
            a: int
            b: int
        
        async def add_h(cd: CommData):
            return cd.data["a"] + cd.data["b"]
            
        await self.math_chan.add_event("add", add_h, parameters=AddParams)
        
        # 2. Expose on API
        api_chan = await self.gateway_client.open("math")
        self.api.add_event(api_chan, "add", "/add")
        
        # 3. Test via Client
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            resp = await ac.post("/add", json={"a": 10, "b": 20})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), 30)

    async def test_get_params_casting(self):
        # 1. Register event on provider
        class QueryParams(BaseModel):
            val: int
        
        async def check_h(cd: CommData):
            return {"received": cd.data["val"], "type": str(type(cd.data["val"]))}
            
        await self.math_chan.add_event("check", check_h, parameters=QueryParams)
        
        # 2. Expose on API as GET
        api_chan = await self.gateway_client.open("math")
        self.api.add_event(api_chan, "check", "/check", method="GET")
        
        # 3. Test via Client (pass as query string)
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            resp = await ac.get("/check", params={"val": "123"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            # Verify it was cast to int
            self.assertEqual(data["received"], 123)
            self.assertIn("int", data["type"])

    async def test_streaming_sse(self):
        # 1. Register streaming event
        async def ticker(cd: CommData):
            for i in range(3):
                yield {"count": i}
                
        await self.math_chan.add_event("ticker", ticker)
        
        # 2. Expose on API
        api_chan = await self.gateway_client.open("math")
        self.api.add_event(api_chan, "ticker", "/ticker")
        
        # 3. Test Stream
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            results = []
            async with ac.stream("GET", "/ticker") as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        results.append(json.loads(line[6:]))
            
            self.assertEqual(len(results), 3)
            self.assertEqual(results[0], {"count": 0})
            self.assertEqual(results[2], {"count": 2})

    async def test_resource_mapping_templates(self):
        # 1. Register multiple events
        async def ev1(cd): return "one"
        async def ev2(cd): return "two"
        await self.math_chan.add_event("ev1", ev1)
        await self.math_chan.add_event("ev2", ev2)
        
        # 2. Add resource with template
        api_chan = await self.gateway_client.open("math")
        self.api.add_resource(api_chan, path_template="/v1/{event}")
        
        # 3. Test routes
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            r1 = await ac.post("/v1/ev1")
            r2 = await ac.post("/v1/ev2")
            self.assertEqual(r1.json(), "one")
            self.assertEqual(r2.json(), "two")

    async def test_api_error_handling(self):
        # 1. Register failing event
        async def fail_h(cd):
            raise ValueError("intentional fail")
            
        await self.math_chan.add_event("fail", fail_h)
        
        # 2. Expose
        api_chan = await self.gateway_client.open("math")
        self.api.add_event(api_chan, "fail", "/fail")
        
        # 3. Test
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            resp = await ac.post("/fail")
            self.assertEqual(resp.status_code, 500)
            self.assertIn("intentional fail", resp.json()["detail"])

if __name__ == "__main__":
    unittest.main()
