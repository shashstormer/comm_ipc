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

    async def test_subscription_sse(self):
        # 1. Add subscription on math channel
        api_chan = await self.gateway_client.open("math")
        await api_chan.add_subscription("test_sub")
        
        # Expose via CommAPI
        self.api.add_subscription(api_chan, "test_sub", "/sub")
        
        # Create a background task to publish data to this subscription
        async def background_publisher():
            await asyncio.sleep(0.1)
            await api_chan.publish("test_sub", {"message": "hello from sse!"})

        pub_task = asyncio.create_task(background_publisher())
        
        # 2. Test SSE stream
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            results = []
            async with ac.stream("GET", "/sub?limit=1") as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        results.append(json.loads(line[6:]))
                        break

        await pub_task
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], {"message": "hello from sse!"})

    async def test_add_file_stream_and_range(self):
        # 1. Register file stream handler on provider
        async def video_stream(cd: CommData):
            # Emit binary data or chunks
            yield b"abcdefghij" # 10 bytes

        await self.math_chan.add_event("video", video_stream)

        # 2. Add file stream route to API
        api_chan = await self.gateway_client.open("math")
        self.api.add_file_stream("/video", api_chan, "video")

        # 3. Request bytes via Range header
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            resp = await ac.get("/video", headers={"Range": "bytes=2-6"})
            self.assertEqual(resp.status_code, 206)
            self.assertEqual(resp.content, b"cdefg")
            self.assertEqual(resp.headers["Content-Range"], "bytes 2-6/*")

    async def test_bidirectional_websocket(self):
        class MockWebSocket:
            def __init__(self):
                self.accepted = False
                self.sent_messages = []
                self.to_receive = asyncio.Queue()

            async def accept(self):
                self.accepted = True

            async def receive_text(self):
                return await self.to_receive.get()

            async def send_text(self, text):
                self.sent_messages.append(text)

        # 1. Open math channel for WebSocket
        api_chan = await self.gateway_client.open("math")
        self.api.add_websocket("/ws", api_chan, "test_ws")

        # Get the ws_endpoint route directly from FastAPI
        route = [r for r in self.app.routes if r.path == "/ws"][0]
        ws_endpoint = route.endpoint

        # Provider adds event/sub for the WebSocket to send to
        async def ws_receiver(cd: CommData):
            await self.math_chan.publish("test_ws", cd.data)
        
        await self.math_chan.add_event("test_ws", ws_receiver)
        await self.math_chan.add_subscription("test_ws")

        # 2. Instantiate MockWebSocket and start the endpoint
        mock_ws = MockWebSocket()
        ws_task = asyncio.create_task(ws_endpoint(mock_ws))

        # Give it a moment to initialize
        await asyncio.sleep(0.1)

        # Send text to it!
        await mock_ws.to_receive.put(json.dumps({"test": "it works"}))

        # Wait up to 1 second for sent message to arrive back
        start_time = asyncio.get_event_loop().time()
        while not mock_ws.sent_messages and (asyncio.get_event_loop().time() - start_time < 1.0):
            await asyncio.sleep(0.05)

        # Cancel the task
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass

        self.assertTrue(mock_ws.accepted)
        self.assertEqual(len(mock_ws.sent_messages), 1)
        self.assertIn("it works", mock_ws.sent_messages[0])

    async def test_chunked_file_sharing(self):
        # 1. Create a temporary source file
        src_path = "/tmp/test_src.bin"
        dest_path = "/tmp/test_dest.bin"
        with open(src_path, "wb") as f:
            f.write(b"Hello from the file transfer system")

        # Provider registers chunk stream event
        async def stream_file(cd: CommData):
            with open(src_path, "rb") as f:
                while True:
                    chunk = f.read(10)
                    if not chunk: break
                    yield {"chunk": chunk}

        await self.math_chan.add_event("file_stream", stream_file)

        # Download using the channel directly
        api_chan = await self.gateway_client.open("math")
        await api_chan.download_file("file_stream", dest_path)

        # Check content match
        with open(dest_path, "rb") as f:
            self.assertEqual(f.read(), b"Hello from the file transfer system")

        # Cleanup
        for p in [src_path, dest_path]:
            if os.path.exists(p): os.remove(p)

    async def test_add_file_upload(self):
        # 1. Register listener for upload on the provider side
        received_chunks = []
        received_filenames = []
        async def upload_listener(cd: CommData):
            received_chunks.append(cd.data["chunk"])
            received_filenames.append(cd.data["filename"])
        await self.math_chan.add_event("upload", upload_listener)

        # 2. Expose upload endpoint on the API
        api_chan = await self.gateway_client.open("math")
        self.api.add_file_upload("/upload", api_chan, "upload")

        # 3. Test HTTP POST upload
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as ac:
            resp = await ac.post("/upload", content=b"fastapi to ipc upload works!", headers={"X-Filename": "upload_test.txt"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["status"], "uploaded")
            self.assertEqual(resp.json()["filename"], "upload_test.txt")

        # Wait a moment for chunks to be processed
        await asyncio.sleep(0.1)
        self.assertTrue(len(received_chunks) > 0)
        self.assertEqual(b"".join(received_chunks), b"fastapi to ipc upload works!")
        self.assertEqual(received_filenames[0], "upload_test.txt")

if __name__ == "__main__":
    unittest.main()
