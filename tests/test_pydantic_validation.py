import asyncio
import unittest
import os
from pydantic import BaseModel
from typing import Optional, List
from comm_ipc.client import CommIPC
from tests.base import start_test_server, stop_test_server


class User(BaseModel):
    id: int
    name: str
    tags: List[str] = []


class TestPydanticValidation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_pydantic.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)

    async def asyncTearDown(self):
        await stop_test_server(self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_event_pydantic_model(self):
        client = CommIPC(socket_path=self.socket_path)
        ch = await client.open("test")
        
        async def handler(cd):
            # cd.data should be a dict produced by Pydantic model_dump
            user = cd.data
            return {"msg": f"Hello {user['name']} ({user['id']})"}
            
        await ch.add_event("greet", call=handler, parameters=User, returns={"msg": str})
        
        # 1. Valid call
        print("Sending valid event...")
        res = await asyncio.wait_for(ch.event("greet", {"id": 1, "name": "Alice", "tags": ["admin"]}), timeout=2.0)
        print("Received response:", res.data)
        self.assertEqual(res.data, {"msg": "Hello Alice (1)"})
        
        # 2. Invalid call (missing tag) - validation error on caller side or provider side?
        # In our implementation, caller validates before sending (event method), 
        # and provider validates before handling (handle_call).
        with self.assertRaises(Exception):
            await ch.event("greet", {"id": "wrong", "name": "Alice"})
            
        await client.close()

    async def test_subscription_pydantic_validation(self):
        provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        p_ch = await provider.open("pubsub")
        
        # Register subscription with schema
        await p_ch.add_subscription("updates", parameters={"val": int, "meta": Optional[str]})
        
        subscriber = CommIPC(client_id="subscriber", socket_path=self.socket_path)
        s_ch = await subscriber.open("pubsub")
        
        received = asyncio.Queue()
        async def on_data(cd):
            await received.put(cd.data)
            
        await s_ch.subscribe("updates", on_data)
        
        # 1. Valid publish
        await p_ch.publish("updates", {"val": 100})
        data = await asyncio.wait_for(received.get(), timeout=1.0)
        self.assertEqual(data, {"val": 100, "meta": None}) # Pydantic adds None for optional fields if schema is a dict
        
        # 2. Invalid publish (should raise locally)
        with self.assertRaises(Exception):
            await p_ch.publish("updates", {"val": "not-an-int"})
            
        await provider.close()
        await subscriber.close()

if __name__ == "__main__":
    unittest.main()
