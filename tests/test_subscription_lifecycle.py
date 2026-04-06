import unittest
import os
import unittest

from pydantic import BaseModel, ValidationError

from comm_ipc.client import CommIPC
from tests.base import start_test_server, stop_test_server


class TestSubscriptionLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_sub_lifecycle.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)

    async def asyncTearDown(self):
        await stop_test_server(self.server, self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_add_remove_and_validation(self):
        provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        p_ch = await provider.open("lifecycle_chan")
        
        class StatusModel(BaseModel):
            level: str
            code: int

        await p_ch.add_subscription("status", parameters=StatusModel)
        
        await p_ch.publish("status", {"level": "info", "code": 200})
        
        with self.assertRaises(ValidationError):
            await p_ch.publish("status", {"level": "info", "code": "not-an-int"})
            
        await p_ch.remove_subscription("status")
        
        self.assertNotIn("status", p_ch.subscriptions)
        
        subscriber = CommIPC(client_id="subscriber", socket_path=self.socket_path)
        s_ch = await subscriber.open("lifecycle_chan")
        
        await s_ch.subscribe("status", lambda cd: None)
        
        await provider.close()
        await subscriber.close()

if __name__ == "__main__":
    unittest.main()
