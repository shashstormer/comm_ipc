import asyncio
import hashlib
import hmac
import inspect
import struct
import uuid
from typing import Dict, Any, Optional, Callable, Literal

import msgpack
from pydantic import BaseModel

from comm_ipc import security
from comm_ipc.channel import CommIPCChannel
from comm_ipc.comm_data import CommData
from comm_ipc.config import SOCKET_PATH, DEFAULT_IDLE_TIMEOUT, DEFAULT_DATA_TIMEOUT, DEFAULT_HEARTBEAT_INTERVAL


class CommIPC:
    def __init__(self, client_id: str = None, socket_path: str = SOCKET_PATH, on_error: Optional[Callable[[Exception], Any]] = None, 
                 ssl_context=None, connection_secret: str = None, auto_reconnect: bool = True, reconnect_max_tries: int = 0,
                 idle_timeout: float = DEFAULT_IDLE_TIMEOUT, data_timeout: float = DEFAULT_DATA_TIMEOUT,
                 heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
                 return_type: Literal["dict", "model"] = "dict",
                 mode: str = "client",
                 verbose: bool = False):
        self.client_id = client_id or f"cli-{uuid.uuid4().hex[:8]}"
        self.socket_path = socket_path
        self.on_error = on_error
        self.ssl_context = ssl_context
        self.connection_secret = connection_secret
        self.auto_reconnect = auto_reconnect
        self.reconnect_max_tries = reconnect_max_tries
        self.verbose = verbose
        self.idle_timeout = idle_timeout
        self.data_timeout = data_timeout
        self.heartbeat_interval = heartbeat_interval
        self.return_type = return_type
        self.mode = mode
        self._is_closing = False
        self._reconnect_count = 0
        self.server_id: Optional[str] = None
        self.channels: Dict[str, 'CommIPCChannel'] = {}
        self.active_streams: Dict[str, asyncio.Queue] = {}
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.pending_calls: Dict[str, asyncio.Future] = {}
        self._loop_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._ready = asyncio.Event()
        self.on_msg: Optional[Callable[[Dict], Any]] = None
        self.on_metadata: Optional[Callable[[Dict], Any]] = None
        self._host = None
        self._port = None
        self._send_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
    
    def _log(self, message: str):
        if self.verbose:
            print(f"[CLIENT {self.client_id}] {message}")

    async def connect(self, host: str = None, port: int = None, ssl_context=None, connection_secret: str = None):
        async with self._connect_lock:
            await self._connect_unlocked(host, port, ssl_context, connection_secret)

    async def _connect_unlocked(self, host: str = None, port: int = None, ssl_context=None, connection_secret: str = None):
        if connection_secret:
            self.connection_secret = connection_secret
            
        self._host = host or self._host
        self._port = port or self._port

        if self.writer:
            return

        ctx = ssl_context or self.ssl_context
        if self._host and self._port:
            self.reader, self.writer = await asyncio.open_connection(self._host, self._port, ssl=ctx)
        else:
            self.reader, self.writer = await asyncio.open_unix_connection(self.socket_path)

        self._log("Connecting to server...")
        try:
            async with self._send_lock:
                await self._send_to_socket_unlocked({"type": "identify", "client_id": self.client_id, "mode": self.mode})

            try:
                len_data = await asyncio.wait_for(self.reader.readexactly(4), timeout=self.idle_timeout)
                length = struct.unpack(">I", len_data)[0]
                data = await asyncio.wait_for(self.reader.readexactly(length), timeout=self.data_timeout)
                resp = msgpack.unpackb(data, raw=False)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                raise ConnectionError("Timeout or connection lost during identification")

            if resp.get("type") == "conn_challenge":
                if not self.connection_secret:
                    raise Exception("Server required connection secret but none provided")
                challenge = resp.get("challenge")
                secret_hash = security.hash_secret(self.connection_secret)
                proof = security.compute_signature(secret_hash.encode(), {"challenge": challenge})
                async with self._send_lock:
                    await self._send_to_socket_unlocked({"type": "conn_proof", "proof": proof})
                
                len_data = await self.reader.readexactly(4)
                length = struct.unpack(">I", len_data)[0]
                data = await self.reader.readexactly(length)
                resp = msgpack.unpackb(data, raw=False)

            if resp.get("type") == "identified":
                self.client_id = resp.get("client_id")
                self.server_id = resp.get("server_id")
                self._log(f"Identified by server {self.server_id}")
            elif resp.get("type") == "error":
                raise Exception(f"Connection failed: {resp.get('message')}")
        except Exception:
            if self.writer:
                try:
                    self.writer.close()
                    await asyncio.wait_for(self.writer.wait_closed(), timeout=1.0)
                except:
                    pass
                self.writer = None
            self.reader = None
            raise

        self._loop_task = asyncio.create_task(self._listen_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        self._ready.set()

    async def _listen_loop(self):
        try:
            while True:
                try:
                    len_data = await asyncio.wait_for(self.reader.readexactly(4), timeout=self.idle_timeout)
                    if not len_data: break
                    length = struct.unpack(">I", len_data)[0]
                    data = await asyncio.wait_for(self.reader.readexactly(length), timeout=self.data_timeout)
                    msg = msgpack.unpackb(data, raw=False)
                    asyncio.create_task(self._handle_message(msg))
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        except Exception as e:
            if self.on_error:
                await self.on_error(e)
        finally:
            self._ready.clear()
            for rid, fut in list(self.pending_calls.items()):
                if not fut.done():
                    fut.set_exception(ConnectionResetError("Connection lost before response was received"))
            self.pending_calls.clear()
            if self.writer:
                self.writer.close()
                self.writer = None
            self.reader = None

            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            if self.auto_reconnect and not self._is_closing:
                 asyncio.create_task(self._reconnect())

    async def _reconnect(self):
        delay = 1
        while self.auto_reconnect:
            if 0 < self.reconnect_max_tries <= self._reconnect_count:
                self._log("Max reconnection attempts reached.")
                await self.close()
                break
            
            try:
                self._reconnect_count += 1
                await asyncio.sleep(delay)
                await self.connect()
                await self._restore_state()
                self._reconnect_count = 0
                break
            except Exception as e:
                if "Authentication failed" in str(e) or "Invalid channel password" in str(e):
                    self._log("Critical auth failure, stopping reconnection.")
                    break
                delay = min(delay * 2, 60)

    async def _heartbeat(self):
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                if self.writer:
                    await self.send_msg({"type": "ping"})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._log(f"Heartbeat failed: {e}")

    async def _restore_state(self):
        for chan in list(self.channels.values()):
            await self.send_msg({
                "type": "register",
                "client_id": self.client_id,
                "channel": chan.name
            })
            for name, info in chan.events.items():
                await self.send_msg({
                    "type": "register",
                    "client_id": self.client_id,
                    "channel": chan.name,
                    "is_provider": True,
                    "event": name,
                    "is_stream": info.get("is_stream", False),
                    "param_schema": info.get("param_schema"),
                    "return_schema": info.get("return_schema")
                })
            if hasattr(chan, 'subscriptions'):
                for sub_name, sinfo in chan.subscriptions.items():
                    await self.send_msg({
                        "type": "add_subscription",
                        "client_id": self.client_id,
                        "channel": chan.name,
                        "sub_name": sub_name,
                        "schema": sinfo.get("param_schema")
                    })

    async def _handle_message(self, msg: Dict):
        if self.on_msg:
            asyncio.create_task(self.on_msg(msg))
        mtype = msg.get("type")
        if mtype == "response":
            rid = msg.get("request_id")
            if rid in self.active_streams:
                await self.active_streams[rid].put(msg)
            elif rid in self.pending_calls:
                fut = self.pending_calls.pop(rid)
                if "error" in msg:
                    fut.set_exception(Exception(msg["error"]))
                else:
                    try:
                        cd = CommData.from_dict(msg)
                        fut.set_result(cd)
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

                async def handle():
                    i_cd = CommData.from_dict(msg)
                    try:
                        hinfo = chan.events.get(ev)
                        h = hinfo["call"] if hinfo else None
                        if h:
                            if inspect.isasyncgenfunction(h):
                                i_cd.data = chan.validate_data(i_cd.data, hinfo["parameters"])
                                async for chunk in h(i_cd):
                                    resp = CommData(
                                        sender_id=self.client_id,
                                        server_id=self.server_id or "",
                                        channel=chan_name,
                                        event=ev,
                                        data=chunk,
                                        request_id=rid,
                                        target_id=i_cd.sender_id,
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
                                    target_id=i_cd.sender_id,
                                    is_stream=True,
                                    is_final=True
                                 )
                                final_dict = final.to_dict()
                                final_dict["type"] = "response"
                                await self.send_msg(final_dict)
                            else:
                                res = await chan.handle_call(i_cd)
                                await self.send_msg({
                                    "type": "response",
                                    "request_id": rid,
                                    "target_id": i_cd.sender_id,
                                    "data": res
                                })
                    except Exception as i_e:
                        if self.on_error:
                            await self.on_error(i_e)
                        
                        target_id = msg.get("sender_id") or (i_cd.sender_id if 'i_cd' in locals() else None)
                        await self.send_msg({
                            "type": "response",
                            "request_id": rid,
                            "target_id": target_id,
                            "error": str(i_e)
                        })

                asyncio.create_task(handle())

        elif mtype == "channel_sync":
            chan_name = msg.get("channel")
            if chan_name in self.channels:
                chan = self.channels[chan_name]
                events = msg.get("events", {})
                subs = msg.get("subscriptions", {})
                for name, info in events.items():
                    chan.remote_schemas[name] = info
                for name, info in subs.items():
                    chan.remote_schemas[name] = info

        elif mtype == "metadata_update":
            chan_name = msg.get("channel")
            if chan_name in self.channels:
                chan = self.channels[chan_name]
                name = msg.get("name")
                stype = msg.get("stype")
                if name and stype != "membership":
                    chan.remote_schemas[name] = {
                        "owner": msg.get("owner"),
                        "param_schema": msg.get("param_schema"),
                        "return_schema": msg.get("return_schema"),
                        "stype": stype
                    }
            if self.on_metadata:
                if inspect.iscoroutinefunction(self.on_metadata) or inspect.iscoroutine(self.on_metadata):
                     asyncio.create_task(self.on_metadata(msg))
                else:
                     res = self.on_metadata(msg)
                     if inspect.iscoroutine(res):
                         asyncio.create_task(res)

        elif mtype in ("broadcast", "send", "receive"):
            chan_name = msg.get("channel")
            if chan_name in self.channels:
                chan = self.channels[chan_name]
                try:
                    cd = CommData.from_dict(msg)
                    await chan.handle_receive(cd)
                except Exception as e:
                    if self.on_error:
                        await self.on_error(e)

        elif mtype == "auth_challenge":
            chan_name = msg.get("channel")
            challenge = msg.get("challenge")
            challenge_id = msg.get("challenge_id")
            rid = msg.get("request_id")
            
            if chan_name in self.channels:
                chan = self.channels[chan_name]
                if chan.password:
                    proof = hmac.new(
                        chan.password.encode(),
                        challenge.encode(),
                        hashlib.sha256
                    ).hexdigest()
                    
                    await self.send_msg({
                        "type": "register",
                        "request_id": rid,
                        "client_id": self.client_id,
                        "channel": chan_name,
                        "proof": proof,
                        "challenge_id": challenge_id
                    })
                else:
                    if rid in self.pending_calls:
                        fut = self.pending_calls.pop(rid)
                        fut.set_exception(Exception(f"Channel {chan_name} requires authentication, but no password was provided."))

        elif mtype == "error":
            mtext = msg.get('message', 'Unknown server error')
            rid = msg.get('request_id')
            if rid and rid in self.pending_calls:
                fut = self.pending_calls.pop(rid)
                if not fut.done():
                    fut.set_exception(Exception(mtext))
            
            if self.on_error:
                err = Exception(mtext)
                await self.on_error(err)

    async def add_subscription(self, chan: str, sub_name: str, return_schema: Optional[Dict] = None):
        if not self._ready.is_set():
            await self.connect()
        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending_calls[rid] = fut
        
        await self.send_msg({
            "type": "add_subscription",
            "channel": chan,
            "sub_name": sub_name,
            "return_schema": return_schema,
            "request_id": rid
        })
        return await fut

    async def remove_subscription(self, chan: str, sub_name: str):
        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending_calls[rid] = fut
        await self.send_msg({
            "type": "remove_subscription",
            "channel": chan,
            "sub_name": sub_name,
            "request_id": rid
        })
        return await fut

    async def subscribe(self, chan: str, sub_name: str, callback: Callable):
        if not self._ready.is_set():
            await self.connect()
        
        if chan not in self.channels:
            await self.open(chan)
        
        self.channels[chan].on_receive(callback, f"subscription.{sub_name}.data")
        
        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending_calls[rid] = fut
        await self.send_msg({
            "type": "subscribe",
            "channel": chan,
            "sub_name": sub_name,
            "request_id": rid
        })
        return await fut

    async def unsubscribe(self, chan: str, sub_name: str):
        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending_calls[rid] = fut
        await self.send_msg({
            "type": "unsubscribe",
            "channel": chan,
            "sub_name": sub_name,
            "request_id": rid
        })
        return await fut

    async def publish(self, chan: str, sub_name: str, data: Any):
        if isinstance(data, BaseModel):
            data = data.model_dump()
        await self.send_msg({
            "type": "publish",
            "channel": chan,
            "sub_name": sub_name,
            "data": data
        })

    async def list_members(self, chan: str):
        if not self._ready.is_set():
            await self.connect()
        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending_calls[rid] = fut
        await self.send_msg({
            "type": "list_members",
            "channel": chan,
            "request_id": rid
        })
        return await fut

    async def send_msg(self, msg: Dict):
        if "data" in msg and isinstance(msg["data"], BaseModel):
            msg["data"] = msg["data"].model_dump()
        async with self._send_lock:
            if not self.writer:
                pass
        
        if not self.writer:
            await self.connect()
            
        async with self._send_lock:
            await self._send_to_socket_unlocked(msg)

    async def _send_to_socket_unlocked(self, msg: Dict):
        try:
            data = msgpack.packb(msg, use_bin_type=True)
            length = struct.pack(">I", len(data))
            self.writer.write(length + data)
            await self.writer.drain()
        except Exception as e:
            if self.on_error:
                await self.on_error(e)
            
            rid = msg.get("request_id")
            if rid and rid in self.pending_calls:
                fut = self.pending_calls.pop(rid)
                if not fut.done():
                    fut.set_exception(e)

    async def open(self, chan: str, password: str = None) -> CommIPCChannel:
        if chan in ["subscription"]:
             raise ValueError(f"Channel name '{chan}' is reserved")

        if not self._ready.is_set():
            await self.connect()
             
        if chan not in self.channels:
            channel = CommIPCChannel(chan, self, password=password)
            self.channels[chan] = channel
        else:
            channel = self.channels[chan]
            channel.password = password

        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending_calls[rid] = fut

        await self.send_msg({
            "type": "register",
            "request_id": rid,
            "client_id": self.client_id,
            "channel": chan,
            "is_provider": False
        })
        
        try:
            resp = await asyncio.wait_for(fut, timeout=10.0)
            if password and not resp.data.get("authenticated"):
                 self._log(f"Rejecting unprotected channel {chan}")
                 if chan in self.channels: del self.channels[chan]
                 raise Exception(f"Channel {chan} is unprotected, but a password was provided.")
        except asyncio.TimeoutError:
            if chan in self.channels: del self.channels[chan]
            raise Exception(f"Registration for channel {chan} timed out")

        return self.channels[chan]

    async def set_password(self, chan: str, password: str):
        if not self._ready.is_set():
            await self.connect()
        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending_calls[rid] = fut
        
        await self.send_msg({
            "type": "set_password",
            "channel": chan,
            "password": password,
            "request_id": rid
        })
        
        resp = await fut
        if chan in self.channels:
            self.channels[chan].password = password
        return resp

    async def call(self, chan: str, ev: str, data: Any) -> Any:
        if not self._ready.is_set():
            await self.connect()
        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending_calls[rid] = fut
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
        self.active_streams[rid] = asyncio.Queue(maxsize=1000)
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
                if resp.get("data") is not None:
                    yield CommData.from_dict(resp)
                if resp.get("is_final"):
                    break
        finally:
            if rid in self.active_streams:
                del self.active_streams[rid]

    async def wait_till_end(self):
        """
        Wait until the client is closed or reconnection attempts are exhausted.
        This provides a clean way to keep a script running while the client processes messages.
        If the outer task is cancelled (e.g. via Ctrl+C in asyncio.run), this will 
        automatically call close() and return cleanly.
        """
        try:
            while not self._is_closing:
                if self._loop_task:
                    if self._loop_task.done():
                        await asyncio.sleep(0.5)
                        continue
                    try:
                        await asyncio.shield(self._loop_task)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        if not self.auto_reconnect:
                            await self.close()
                            break
                        await asyncio.sleep(1.0)
                else:
                    if self._is_closing:
                        break
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            await self.close()

    async def close(self):
        self._is_closing = True
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, asyncio.IncompleteReadError):
                pass
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self.writer:
            try:
                self.writer.close()
                await asyncio.wait_for(self.writer.wait_closed(), timeout=1.0)
            except Exception as e:
                if self.on_error:
                    await self.on_error(e)
