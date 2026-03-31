import asyncio
from typing import Dict, Any, List

from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData


class CommIPCBridge:
    def __init__(self, bridge_id: str = None, socket_path1: str = None, socket_path2: str = None):
        self.bridge_id = bridge_id or "bridge-net"
        self.c1 = CommIPC(client_id=f"{self.bridge_id}-c1", socket_path=socket_path1)
        self.c2 = CommIPC(client_id=f"{self.bridge_id}-c2", socket_path=socket_path2)
        self.registrations: Dict[str, set] = {"c1": set(), "c2": set()}
        self.synced_channels: Dict[str, set] = {"c1": set(), "c2": set()}
        self.running = False

    async def connect(self, target1_params: Dict, target2_params: Dict):
        await asyncio.gather(
            self.c1.connect(host=target1_params.get("host"), port=target1_params.get("port")),
            self.c2.connect(host=target2_params.get("host"), port=target2_params.get("port"))
        )

        await self.c1.open("__comm_ipc_system")
        await self.c2.open("__comm_ipc_system")

        async def h1(d): await self._handle_system_event(d, src="c1", dest="c2")

        async def h2(d): await self._handle_system_event(d, src="c2", dest="c1")

        self.c1.channels["__comm_ipc_system"].on_receive(h1)
        self.c2.channels["__comm_ipc_system"].on_receive(h2)

        self.running = True

    async def _handle_system_event(self, comm_data: CommData, src: str, dest: str):
        if comm_data.event != "new_registration":
            return

        reg = comm_data.data
        if reg.get("client_id").startswith(self.bridge_id):
            return

        dest_client = getattr(self, dest)
        src_client = getattr(self, src)

        channel_name = reg["channel"]
        event_name = reg.get("event")
        is_provider = reg.get("is_provider")
        is_stream = reg.get("is_stream", False)
        password = reg.get("password")
        reg_key = f"{channel_name}:{event_name}:{is_provider}"
        if reg_key in self.registrations[dest]:
            return
        self.registrations[dest].add(reg_key)

        if is_provider and event_name:
            chan = await dest_client.open(channel_name, password=password)

            if is_stream:
                async def relay_stream_handler(cd: CommData):
                    async for chunk in src_client.stream(channel_name, event_name, cd.data):
                        yield chunk.data

                await chan.add_event(event_name, call=relay_stream_handler)
            else:
                async def relay_handler(cd: CommData):
                    res = await src_client.call(channel_name, event_name, cd.data)
                    return res.data

                await chan.add_event(event_name, call=relay_handler)

        elif not is_provider:
            if channel_name in self.synced_channels[dest]:
                return
            self.synced_channels[dest].add(channel_name)

            dest_chan = await dest_client.open(channel_name, password=password)

            async def relay_recv(d):
                await self._relay_receive(d, src_client=dest_client, dest_client=src_client)

            dest_chan.on_receive(relay_recv)

    @staticmethod
    async def _relay_receive(comm_data: CommData, src_client: CommIPC, dest_client: CommIPC):
        if dest_client.server_id in comm_data.path:
            return

        comm_data.path.append(src_client.server_id)

        payload = comm_data.to_dict()

        payload["type"] = "broadcast" if comm_data.request_id is None else "call"

        await dest_client.send_msg(payload)

    async def stop(self):
        self.running = False
        await self.c1.close()
        await self.c2.close()
