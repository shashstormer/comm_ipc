import asyncio
import json
import struct
import uuid
import inspect
from typing import Dict, Any, Optional, Callable

from comm_ipc.channel import CommIPCChannel
from comm_ipc.config import SOCKET_PATH
from comm_ipc.comm_data import CommData


class CommIPC:
    def __init__(self, client_id: str = None, socket_path: str = SOCKET_PATH, on_error: Optional[Callable[[Exception], Any]] = None):
        self.client_id = client_id or f"cli-{uuid.uuid4().hex[:8]}"
        self.socket_path = socket_path
        self.on_error = on_error
        self.server_id: Optional[str] = None
        self.channels: Dict[str, CommIPCChannel] = {}
        self.active_streams: Dict[str, asyncio.Queue] = {}
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._pending_calls: Dict[str, asyncio.Future] = {}
        self._loop_task: Optional[asyncio.Task] = None
        self._ready = asyncio.Event()
        self.on_msg: Optional[Callable[[Dict], Any]] = None

    async def connect(self, host: str = None, port: int = None):
        if self.writer:
            return

        if host and port:
            self.reader, self.writer = await asyncio.open_connection(host, port)
        else:
            self.reader, self.writer = await asyncio.open_unix_connection(self.socket_path)

        await self.send_msg({"type": "identify", "client_id": self.client_id})

        len_data = await self.reader.readexactly(4)
        length = struct.unpack(">I", len_data)[0]
        data = await self.reader.readexactly(length)
        resp = json.loads(data.decode())

        if resp.get("type") == "identified":
            self.client_id = resp.get("client_id")
            self.server_id = resp.get("server_id")
        elif resp.get("type") == "error":
            raise Exception(f"Connection failed: {resp.get('message')}")

        self._loop_task = asyncio.create_task(self._listen_loop())
        self._ready.set()

    async def _listen_loop(self):
        try:
            while True:
                len_data = await self.reader.readexactly(4)
                if not len_data: break
                length = struct.unpack(">I", len_data)[0]
                data = await self.reader.readexactly(length)
                msg = json.loads(data.decode())
                asyncio.create_task(self._handle_message(msg))
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        except Exception as e:
            if self.on_error:
                if asyncio.iscoroutinefunction(self.on_error):
                    await self.on_error(e)
                else:
                    self.on_error(e)
        finally:
            self._ready.clear()
            for rid, fut in self._pending_calls.items():
                if not fut.done():
                    fut.set_exception(ConnectionResetError("Connection lost before response was received"))
            self._pending_calls.clear()
            if self.writer:
                self.writer.close()

    async def _handle_message(self, msg: Dict):
        if self.on_msg:
            if asyncio.iscoroutinefunction(self.on_msg):
                asyncio.create_task(self.on_msg(msg))
            else:
                self.on_msg(msg)
        mtype = msg.get("type")
        if mtype == "response":
            rid = msg.get("request_id")
            if rid in self.active_streams:
                await self.active_streams[rid].put(msg)
            elif rid in self._pending_calls:
                fut = self._pending_calls.pop(rid)
                if "error" in msg:
                    fut.set_exception(Exception(msg["error"]))
                else:
                    try:
                        fut.set_result(CommData.from_dict(msg))
                    except Exception as e:
                        fut.set_exception(e)
            else:
                if rid in self.active_streams:
                    pass

        elif mtype == "call":
            chan_name = msg.get("channel")
            if chan_name in self.channels:
                chan = self.channels[chan_name]
                rid = msg.get("request_id")
                ev = msg.get("event")
                cd = CommData.from_dict(msg)

                async def handle():
                    try:
                        hinfo = chan.events.get(ev)
                        h = hinfo["call"] if hinfo else None
                        if h:
                            cd = CommData.from_dict(msg)
                            if inspect.isasyncgenfunction(h):
                                async for chunk in h(cd):
                                    resp = CommData(
                                        sender_id=self.client_id,
                                        server_id=self.server_id or "",
                                        channel=chan_name,
                                        event=ev,
                                        data=chunk,
                                        request_id=rid,
                                        target_id=cd.sender_id,
                                        is_stream=True,
                                        is_final=False
                                    )
                                    resp_dict = resp.to_dict()
                                    resp_dict["type"] = "response"
                                    await self.send_msg(resp_dict)

                                final = CommData(
                                    sender_id=self.client_id,
                                    server_id=self.server_id or "",
                                    channel=chan_name,
                                    event=ev,
                                    data=None,
                                    request_id=rid,
                                    target_id=cd.sender_id,
                                    is_stream=True,
                                    is_final=True
                                 )
                                final_dict = final.to_dict()
                                final_dict["type"] = "response"
                                await self.send_msg(final_dict)
                            else:
                                res = await chan.handle_call(cd)
                                await self.send_msg({
                                    "type": "response",
                                    "request_id": rid,
                                    "target_id": cd.sender_id,
                                    "data": res
                                })
                    except Exception as e:
                        if self.on_error:
                            if inspect.iscoroutinefunction(self.on_error):
                                await self.on_error(e)
                            else:
                                self.on_error(e)
                        await self.send_msg({
                            "type": "response",
                            "request_id": rid,
                            "target_id": cd.sender_id,
                            "error": str(e)
                        })

                asyncio.create_task(handle())

        elif mtype in ("broadcast", "send", "receive"):
            chan_name = msg.get("channel")
            if chan_name in self.channels:
                chan = self.channels[chan_name]
                cd = CommData.from_dict(msg)
                await chan.handle_receive(cd)

        elif mtype == "error":
            mtext = msg.get('message', 'Unknown server error')
            if self.on_error:
                err = Exception(mtext)
                if asyncio.iscoroutinefunction(self.on_error):
                    await self.on_error(err)
                else:
                    self.on_error(err)

    async def send_msg(self, msg: Dict):
        if not self.writer:
            await self.connect()
        try:
            data = json.dumps(msg).encode()
            length = struct.pack(">I", len(data))
            self.writer.write(length + data)
            await self.writer.drain()
        except Exception as e:
            if self.on_error:
                if asyncio.iscoroutinefunction(self.on_error):
                    await self.on_error(e)
                else:
                    self.on_error(e)

    async def open(self, chan: str, password: str = None) -> CommIPCChannel:
        if not self._ready.is_set():
            await self.connect()
        if chan not in self.channels:
            channel = CommIPCChannel(chan, self, password=password)
            self.channels[chan] = channel
        else:
            channel = self.channels[chan]
            channel.password = password

        await self.send_msg({
            "type": "register",
            "client_id": self.client_id,
            "channel": chan,
            "password": password,
            "is_provider": False
        })
        return self.channels[chan]

    async def call(self, chan: str, ev: str, data: Any) -> Any:
        if not self._ready.is_set():
            await self.connect()
        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self._pending_calls[rid] = fut
        await self.send_msg({
            "type": "call",
            "channel": chan,
            "event": ev,
            "data": data,
            "request_id": rid,
            "sender_id": self.client_id,
            "server_id": self.server_id
        })
        return await fut

    async def stream(self, chan: str, ev: str, data: Any):
        if not self._ready.is_set():
            await self.connect()
        rid = str(uuid.uuid4())
        self.active_streams[rid] = asyncio.Queue()
        await self.send_msg({
            "type": "call",
            "channel": chan,
            "event": ev,
            "data": data,
            "request_id": rid,
            "sender_id": self.client_id,
            "server_id": self.server_id
        })
        try:
            while True:
                resp = await self.active_streams[rid].get()
                if resp.get("error"):
                    raise Exception(resp["error"])
                if resp.get("is_final"):
                    break
                yield CommData.from_dict(resp)
        finally:
            if rid in self.active_streams:
                del self.active_streams[rid]

    async def close(self):
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, asyncio.IncompleteReadError):
                pass
        if self.writer:
            try:
                self.writer.close()
                await asyncio.wait_for(self.writer.wait_closed(), timeout=1.0)
            except Exception as e:
                if self.on_error:
                    if asyncio.iscoroutinefunction(self.on_error):
                        await self.on_error(e)
                    else:
                        self.on_error(e)
