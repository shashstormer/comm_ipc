import asyncio
import os
import unittest
from typing import List

from pydantic import BaseModel

from comm_ipc.client import CommIPC
from tests.base import start_test_server, stop_test_server


class NestedModel(BaseModel):
    name: str
    data: bytes

class ComplexModel(BaseModel):
    id: int
    items: List[NestedModel]

class FailResponse(BaseModel):
    res: str

class TestPydanticAdvanced(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_pydantic_adv.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)

    async def asyncTearDown(self):
        await stop_test_server(self.server, self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_complex_models_and_binary(self):
        provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        ch_p = await provider.open("adv")
        
        async def handler(cd):
            items = cd.data['items']
            if items[0]['data'] == b"\x00\x01\x02":
                return {"status": "ok", "len": len(items)}
            return {"status": "fail"}
            
        await ch_p.add_event("process", call=handler, parameters=ComplexModel)
        
        caller = CommIPC(client_id="caller", socket_path=self.socket_path)
        ch_c = await caller.open("adv")
        
        data = {
            "id": 123,
            "items": [{"name": "bin", "data": b"\x00\x01\x02"}]
        }
        res = await asyncio.wait_for(ch_c.event("process", data), timeout=2.0)
        self.assertEqual(res.data["status"], "ok")
        
        async def fail_handler(_):
            return {"res": 123}
            
        await ch_p.add_event("fail", call=fail_handler, returns=FailResponse)
        
        with self.assertRaises(Exception) as cm:
            await ch_c.event("fail", {})
            
        err_msg = str(cm.exception)
        self.assertTrue("validation error" in err_msg.lower() or "Input should be a valid string" in err_msg)
        
        await provider.close()
        await caller.close()

if __name__ == "__main__":
    unittest.main()
