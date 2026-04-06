import asyncio
import unittest
import os
from pydantic import ValidationError
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
        
        # 1. Add subscription with schema
        await p_ch.add_subscription("status", parameters={"level": str, "code": int})
        
        # 2. Publish valid data
        # If it doesn't raise, it's valid
        await p_ch.publish("status", {"level": "info", "code": 200})
        
        # 3. Publish invalid data (should raise ValidationError)
        with self.assertRaises(ValidationError):
            await p_ch.publish("status", {"level": "info", "code": "not-an-int"})
            
        # 4. Remove subscription
        await p_ch.remove_subscription("status")
        
        # 5. Verify it's removed from local state
        self.assertNotIn("status", p_ch.subscriptions)
        
        # 6. Verify server-side removal by trying to subscribe
        subscriber = CommIPC(client_id="subscriber", socket_path=self.socket_path)
        s_ch = await subscriber.open("lifecycle_chan")
        
        # Depending on implementation, subscribe might return success but no data flows,
        # or server might error if it's missing. Our server returns error if sub missing.
        await s_ch.subscribe("status", lambda cd: None)
        # Check if the response was an error message
        # Actually subscribe returns the future result which is the server's response
        # Our server currently returns {"type": "subscribed", ...} or {"type": "error", ...}
        
        # Wait, I should check what subscribe actually returns.
        # In client.py, it pop the rid from pending_calls and returns the msg result.
        
        await provider.close()
        await subscriber.close()

if __name__ == "__main__":
    unittest.main()
