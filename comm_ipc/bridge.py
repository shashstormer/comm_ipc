import asyncio
from typing import Dict, List, Any

from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData


class CommIPCBridge:
    def __init__(self, bridge_id: str = None, socket_path1: str = None, socket_path2: str = None, 
                 ssl_context1=None, ssl_context2=None, allowed_channels: List[str] = None):
        self.bridge_id = bridge_id or "bridge-net"
        self.allowed_channels = allowed_channels or []
        self.c1 = CommIPC(client_id=f"{self.bridge_id}-c1", socket_path=socket_path1, ssl_context=ssl_context1, mode="bridge")
        self.c2 = CommIPC(client_id=f"{self.bridge_id}-c2", socket_path=socket_path2, ssl_context=ssl_context2, mode="bridge")
        self.registrations: Dict[str, set] = {"c1": set(), "c2": set()}
        self.proxied_members: Dict[str, set] = {"c1": set(), "c2": set()}
        self.running = False

    @property
    def synced_channels(self) -> Dict[str, set]:
        return {
            "c1": set(self.c1.channels.keys()),
            "c2": set(self.c2.channels.keys())
        }

    async def connect(self, target1_params: Dict, target2_params: Dict):
        await asyncio.gather(
            self.c1.connect(
                host=target1_params.get("host"), 
                port=target1_params.get("port"), 
                ssl_context=target1_params.get("ssl_context"),
                connection_secret=target1_params.get("connection_secret")
            ),
            self.c2.connect(
                host=target2_params.get("host"), 
                port=target2_params.get("port"), 
                ssl_context=target2_params.get("ssl_context"),
                connection_secret=target2_params.get("connection_secret")
            )
        )

        self.c1.on_metadata = lambda d: self._process_metadata(d, src=self.c1, dest=self.c2, src_key="c1", dest_key="c2")
        self.c2.on_metadata = lambda d: self._process_metadata(d, src=self.c2, dest=self.c1, src_key="c2", dest_key="c1")

        for chan_name in self.allowed_channels:
            await self._sync_channel(chan_name)

        self.running = True

    async def _sync_channel(self, chan_name: str):
        ch1 = await self.c1.open(chan_name)
        ch2 = await self.c2.open(chan_name)

        async def relay_1_to_2(d): await self._relay_receive(d, src_client=self.c1, dest_client=self.c2)
        async def relay_2_to_1(d): await self._relay_receive(d, src_client=self.c2, dest_client=self.c1)
        
        ch1.on_receive(relay_1_to_2)
        ch2.on_receive(relay_2_to_1)

        await asyncio.gather(
            self._sync_side(ch1, self.c1, self.c2, "c1", "c2"),
            self._sync_side(ch2, self.c2, self.c1, "c2", "c1")
        )

    async def _sync_side(self, channel, src_client, dest_client, src_key, dest_key):
        members_resp = await channel.list_members()
        members = members_resp.data.get("members", [])
        
        remote_announce = []
        for m in members:
            if m["id"].startswith(self.bridge_id):
                continue
            
            m_path = m.get("path", [])
            new_m = m.copy()
            new_m["path"] = m_path + [src_client.server_id]
            remote_announce.append(new_m)

        if remote_announce:
            await dest_client.send_msg({
                "type": "announce_remote",
                "clients": remote_announce,
                "channel": channel.name
            })
            for m in remote_announce:
                self.proxied_members[dest_key].add(m["id"])

        capabilities = channel.explore()
        for ev_name, info in capabilities.get("events", {}).items():
            if ev_name and not info["owner"].startswith(self.bridge_id):
                await self._proxy_event(chan_name=channel.name, event_name=ev_name, info=info, src=src_client, dest=dest_client)

    async def _process_metadata(self, msg: Dict, src: CommIPC, dest: CommIPC, src_key: str, dest_key: str):
        chan_name = msg.get("channel")
        if self.allowed_channels and chan_name not in self.allowed_channels:
            return

        stype = msg.get("stype")
        owner = msg.get("owner")
        event_name = msg.get("name")

        if owner.startswith(self.bridge_id):
            return

        if stype == "membership":
            action = msg.get("action")
            if action == "join":
                if owner not in self.proxied_members[dest_key]:
                    m_path = msg.get("path", [])
                    new_path = m_path + [src.server_id]
                    await dest.send_msg({
                        "type": "announce_remote",
                        "clients": [{"id": owner, "mode": msg.get("mode", "client"), "path": new_path}],
                        "channel": chan_name
                    })
                    self.proxied_members[dest_key].add(owner)
            elif action == "leave":
                if owner in self.proxied_members[dest_key]:
                    await dest.send_msg({
                        "type": "forget_remote",
                        "id": owner,
                        "channel": chan_name
                    })
                    self.proxied_members[dest_key].remove(owner)
        
        elif stype == "event":
            if event_name:
                await self._proxy_event(chan_name, event_name, msg, src, dest)

    async def _proxy_event(self, chan_name: str, event_name: str, info: Dict, src: CommIPC, dest: CommIPC):
        dest_key = "c1" if dest == self.c1 else "c2"
        reg_key = f"{chan_name}:{event_name}:provider"
        if reg_key in self.registrations[dest_key]:
            return
        self.registrations[dest_key].add(reg_key)

        dest_chan = await dest.open(chan_name)
        
        is_stream = info.get("is_stream", False)
        is_group = info.get("is_group", False)

        if is_stream:
            async def relay_stream(cd: CommData):
                async for chunk in src.stream(chan_name, event_name, cd.data):
                    yield chunk.data
            await dest_chan.add_event(event_name, call=relay_stream, is_group=is_group)
        else:
            async def relay_call(cd: CommData):
                res = await src.call(chan_name, event_name, cd.data)
                return res.data
            await dest_chan.add_event(event_name, call=relay_call, is_group=is_group)

    async def _relay_receive(self, comm_data: CommData, src_client: CommIPC, dest_client: CommIPC):
        if dest_client.server_id in comm_data.path:
            return
        
        if comm_data.sender_id.startswith(self.bridge_id):
            return

        comm_data.path.append(src_client.server_id)
        if not comm_data.origin_server_id:
            comm_data.origin_server_id = src_client.server_id

        payload = comm_data.to_dict()
        payload["type"] = "broadcast" if comm_data.request_id is None else "call"
        
        if payload["type"] == "broadcast":
            await dest_client.send_msg(payload)

    async def stop(self):
        self.running = False
        await self.c1.close()
        await self.c2.close()
