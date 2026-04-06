import asyncio
import unittest
import os
from comm_ipc.client import CommIPC
from tests.base import start_test_server, stop_test_server


class TestPubSubNotifications(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket_path = "/tmp/test_pubsub_notif.sock"
        self.server, self.server_task = await start_test_server(socket_path=self.socket_path)

    async def asyncTearDown(self):
        await stop_test_server(self.server, self.server_task)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    async def test_first_last_subscriber_notifications(self):
        provider = CommIPC(client_id="provider", socket_path=self.socket_path)
        p_ch = await provider.open("notif_chan")

        first_notified = asyncio.Event()
        last_notified = asyncio.Event()

        async def on_first(_):
            first_notified.set()

        async def on_last(_):
            last_notified.set()

        p_ch.on_receive(on_first, event_name="subscription.updates.first")
        p_ch.on_receive(on_last, event_name="subscription.updates.last")

        await p_ch.add_subscription("updates")

        sub1 = CommIPC(client_id="sub1", socket_path=self.socket_path)

        async def sub1_cb(_):
            pass

        await sub1.connect()
        await sub1.subscribe("notif_chan", "updates", sub1_cb)

        await asyncio.wait_for(first_notified.wait(), timeout=2.0)
        self.assertTrue(first_notified.is_set())

        sub2 = CommIPC(client_id="sub2", socket_path=self.socket_path)

        async def sub2_cb(_):
            pass

        await sub2.connect()
        await sub2.subscribe("notif_chan", "updates", sub2_cb)

        await sub1.unsubscribe("notif_chan", "updates")
        await asyncio.sleep(0.1)
        self.assertFalse(last_notified.is_set())

        await sub2.unsubscribe("notif_chan", "updates")
        await asyncio.wait_for(last_notified.wait(), timeout=2.0)
        self.assertTrue(last_notified.is_set())

        await provider.close()
        await sub1.close()
        await sub2.close()


if __name__ == "__main__":
    unittest.main()
