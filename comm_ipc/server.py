import asyncio
import hashlib
import hmac
import msgpack
import os
import secrets
import string
import struct
import uuid
import time
from typing import Dict, Any, List, Set

from comm_ipc.config import SOCKET_PATH, DEFAULT_IDLE_TIMEOUT, DEFAULT_DATA_TIMEOUT
from comm_ipc import security


class CommIPCServer:
    def __init__(self, server_id: str = None, socket_path: str = SOCKET_PATH,
                 error_policy: str = "ignore", connection_secret: str = None,
                 system_passwords: Dict[str, str] = None, channel_policy: str = "terminate",
                 idle_timeout: float = DEFAULT_IDLE_TIMEOUT, data_timeout: float = DEFAULT_DATA_TIMEOUT,
                 verbose: bool = False):
        self.running = None
        self.server_id = server_id or f"srv-{uuid.uuid4().hex[:8]}"
        self.socket_path = socket_path
        self.clients: Dict[str, asyncio.StreamWriter] = {}
        self.active_writers: Set[asyncio.StreamWriter] = set()
        self.channels: Dict[str, List[str]] = {}
        self.channel_passwords: Dict[str, str] = system_passwords or {}
        self.channel_members: Dict[str, List[str]] = {}
        self.channel_policy = channel_policy
        self.verbose = verbose
        self.providers: Dict[str, Dict[str, str]] = {}
        self.error_policy = error_policy
        self._reporting_error = False
        self.auth_challenges: Dict[str, Dict[str, Any]] = {}
        self.connection_secret_hash = security.hash_secret(connection_secret) if connection_secret else None
        self.unauthenticated_clients: Set[asyncio.StreamWriter] = set()
        self.idle_timeout = idle_timeout
        self.data_timeout = data_timeout
        self._cleanup_task = None
        self._writer_locks: Dict[asyncio.StreamWriter, asyncio.Lock] = {}
        self.subscribers: Dict[str, Dict[str, Set[str]]] = {}
        self.sub_owners: Dict[str, Dict[str, str]] = {}
        self.sub_params: Dict[str, Dict[str, Any]] = {}
        self.event_schemas: Dict[str, Dict[str, Any]] = {}

    def _log(self, message: str, level: str = "info", client_id: str = None):
        log_msg = f"[SERVER {self.server_id}] {message}"
        if self.verbose:
            print(log_msg)

        asyncio.create_task(self._system_broadcast("__comm_ipc_logs", {
            "type": "receive",
            "channel": "__comm_ipc_logs",
            "event": "server_log",
            "data": {"message": message, "level": level, "client_id": client_id, "server_id": self.server_id}
        }))

    async def _prune_challenges(self):
        while True:
            await asyncio.sleep(60)
            now = time.time()
            expired = [cid for cid, data in self.auth_challenges.items() if now - data["timestamp"] > 300]
            for cid in expired:
                del self.auth_challenges[cid]
                if cid in self.clients:
                    try:
                        self.clients[cid].close()
                    except:
                        pass
                    del self.clients[cid]

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.active_writers.add(writer)
        client_id = None
        try:
            len_data = await reader.readexactly(4)
            length = struct.unpack(">I", len_data)[0]
            data = await reader.readexactly(length)
            ident = msgpack.unpackb(data, raw=False)

            if ident.get("type") == "identify":
                proposed_id = ident.get("client_id")
                if proposed_id in self.clients:
                    await self._send_to_writer(writer,
                                               {"type": "error", "message": f"Client ID {proposed_id} already in use"})
                    writer.close()
                    return
                client_id = proposed_id

                if self.connection_secret_hash:
                    challenge = security.generate_challenge()
                    self.auth_challenges[client_id] = {
                        "conn_challenge": challenge,
                        "timestamp": int(time.time()),
                        "authenticated": False
                    }
                    await self._send_to_writer(writer, {
                        "type": "conn_challenge",
                        "challenge": challenge,
                        "server_id": self.server_id
                    })

                    try:
                        len_data = await asyncio.wait_for(reader.readexactly(4), timeout=10.0)
                        length = struct.unpack(">I", len_data)[0]
                        data = await reader.readexactly(length)
                        resp = msgpack.unpackb(data, raw=False)

                        if resp.get("type") == "conn_proof":
                            proof = resp.get("proof")
                            expected = security.compute_signature(self.connection_secret_hash.encode(),
                                                                  {"challenge": challenge})

                            if hmac.compare_digest(expected, proof):
                                self.auth_challenges[client_id]["authenticated"] = True
                                await self._send_to_writer(writer, {"type": "identified", "client_id": client_id,
                                                                    "server_id": self.server_id})
                            else:
                                await self._send_to_writer(writer,
                                                           {"type": "error", "message": "Authentication failed"})
                                await writer.drain()
                                writer.close()
                                return
                        else:
                            writer.close()
                            return
                    except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                        writer.close()
                        return
                else:
                    if not self._reporting_error:
                        await self._send_to_writer(writer, {"type": "identified", "client_id": client_id,
                                                            "server_id": self.server_id})

                    self._log(f"Client {client_id} identified", client_id=client_id)
                self.clients[client_id] = writer

            while True:
                try:
                    len_data = await asyncio.wait_for(reader.readexactly(4), timeout=self.idle_timeout)
                    if not len_data: break
                    length = struct.unpack(">I", len_data)[0]
                    data = await asyncio.wait_for(reader.readexactly(length), timeout=self.data_timeout)
                    msg = msgpack.unpackb(data, raw=False)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                if msg.get("type") == "ping":
                    await self._send_to_writer(writer, {"type": "pong"})
                    continue

                if self.connection_secret_hash:
                    if not self.auth_challenges.get(client_id, {}).get("authenticated"):
                        await self._send_to_writer(writer, {"type": "error", "message": "Not authenticated"})
                        writer.close()
                        return

                await self.process_message(client_id, msg)

        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            await self._report_error(e, client_id)
        finally:
            if client_id:
                for channel in list(self.channel_members.keys()):
                    if client_id in self.channel_members[channel]:
                        is_owner = (self.channel_members[channel][0] == client_id)
                        self.channel_members[channel].remove(client_id)

                        if is_owner and self.channel_policy == "terminate" and self.channel_members[channel]:
                            for other_id in list(self.channel_members[channel]):
                                if other_id in self.clients:
                                    await self._send_to_client(other_id, {"type": "error",
                                                                          "message": "Channel owner disconnected, channel terminated"})
                                    if channel in self.channels and other_id in self.channels[channel]:
                                        self.channels[channel].remove(other_id)
                                    if channel in self.providers:
                                        evs = [ev for ev, pid in self.providers[channel].items() if pid == other_id]
                                        for ev in evs: del self.providers[channel][ev]
                            self.channel_members[channel] = []

                        if not self.channel_members[channel]:
                            if channel in self.channel_passwords and not channel.startswith("__comm_ipc"):
                                del self.channel_passwords[channel]
                            del self.channel_members[channel]

                if client_id in self.clients:
                    del self.clients[client_id]
                for channel in list(self.channels.keys()):
                    if client_id in self.channels[channel]:
                        self.channels[channel].remove(client_id)
                        if not self.channels[channel]:
                            del self.channels[channel]
                for channel in list(self.providers.keys()):
                    for event in list(self.providers[channel].keys()):
                        if self.providers[channel][event] == client_id:
                            del self.providers[channel][event]
                    if not self.providers[channel]:
                        del self.providers[channel]

                for channel in list(self.sub_owners.keys()):
                    for sub_name in list(self.sub_owners[channel].keys()):
                        if self.sub_owners[channel][sub_name] == client_id:
                            await self._remove_subscription(channel, sub_name)
                    if not self.sub_owners.get(channel):
                        self.sub_owners.pop(channel, None)

                for channel in list(self.subscribers.keys()):
                    for sub_name in list(self.subscribers[channel].keys()):
                        if client_id in self.subscribers[channel][sub_name]:
                            await self._unsubscribe(client_id, channel, sub_name)
                    if not self.subscribers.get(channel):
                        self.subscribers.pop(channel, None)

            if writer in self.active_writers:
                self.active_writers.remove(writer)

            if writer in self._writer_locks:
                del self._writer_locks[writer]

            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except Exception as e:
                await self._report_error(e, client_id)

    async def process_message(self, client_id: str, msg: Dict):
        mtype = msg.get("type")
        if mtype == "register":
            await self._handle_register(client_id, msg.get("reg", msg))
        elif mtype == "call":
            await self._handle_call(client_id, msg)
        elif mtype == "response":
            await self._handle_response(client_id, msg)
        elif mtype == "broadcast":
            await self._handle_broadcast(client_id, msg)
        elif mtype == "send":
            await self._handle_send(client_id, msg)
        elif mtype == "set_password":
            await self._handle_set_password(client_id, msg)
        elif mtype == "add_subscription":
            await self._handle_add_subscription(client_id, msg)
        elif mtype == "remove_subscription":
            await self._handle_remove_subscription(client_id, msg)
        elif mtype == "subscribe":
            await self._handle_subscribe(client_id, msg)
        elif mtype == "unsubscribe":
            await self._handle_unsubscribe(client_id, msg)
        elif mtype == "publish":
            await self._handle_publish(client_id, msg)

    async def _handle_register(self, client_id: str, reg: Dict):
        chan_name = reg.get("channel")
        is_provider = reg.get("is_provider", False)
        event = reg.get("event")
        is_stream = reg.get("is_stream", False)

        if chan_name in self.channel_passwords:
            proof = reg.get("proof")
            challenge_id = reg.get("challenge_id")

            if not proof:
                challenge = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
                challenge_id = str(uuid.uuid4())

                if client_id not in self.auth_challenges:
                    self.auth_challenges[client_id] = {}
                self.auth_challenges[client_id][challenge_id] = {
                    "challenge": challenge,
                    "reg": reg,
                    "timestamp": int(time.time())
                }

                await self._send_to_client(client_id, {
                    "type": "auth_challenge",
                    "channel": chan_name,
                    "challenge": challenge,
                    "challenge_id": challenge_id,
                    "request_id": reg.get("request_id")
                })
                return

            if client_id not in self.auth_challenges or challenge_id not in self.auth_challenges[client_id]:
                await self._send_to_client(client_id, {
                    "type": "response",
                    "request_id": reg.get("request_id"),
                    "error": "Invalid or expired challenge"
                })
                await self._report_error(Exception("Invalid or expired challenge"), client_id)
                return

            challenge_data = self.auth_challenges[client_id].pop(challenge_id)
            if time.time() - challenge_data["timestamp"] > 60:
                await self._send_to_client(client_id, {
                    "type": "response",
                    "request_id": reg.get("request_id"),
                    "error": "Challenge expired"
                })
                await self._report_error(Exception("Challenge expired"), client_id)
                return

            expected_proof = hmac.new(
                self.channel_passwords[chan_name].encode(),
                challenge_data["challenge"].encode(),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(expected_proof, proof):
                await self._send_to_client(client_id, {
                    "type": "response",
                    "request_id": reg.get("request_id"),
                    "error": "Invalid channel password"
                })
                await self._report_error(Exception("Invalid channel password"), client_id)
                return

            original_reg = challenge_data["reg"]
            reg = original_reg
            is_provider = reg.get("is_provider", False)
            event = reg.get("event")
            is_stream = reg.get("is_stream", False)

        if chan_name not in self.channel_members:
            self.channel_members[chan_name] = []
        if client_id not in self.channel_members[chan_name]:
            self.channel_members[chan_name].append(client_id)

        if is_provider:
            if not event:
                await self._send_to_client(client_id, {
                    "type": "response",
                    "request_id": reg.get("request_id"),
                    "error": "Event name required for provider registration"
                })
                return
            if chan_name in self.providers and event in self.providers[chan_name]:
                existing_provider = self.providers[chan_name][event]
                if existing_provider != client_id:
                    err_msg = f"Provider already exists for {chan_name}:{event} (by {existing_provider})"
                    await self._send_to_client(client_id, {
                        "type": "response",
                        "request_id": reg.get("request_id"),
                        "channel": chan_name,
                        "event": event,
                        "error": err_msg
                    })
                    await self._report_error(Exception(err_msg), client_id)
                    return

            if chan_name not in self.providers:
                self.providers[chan_name] = {}
            self.providers[chan_name][event] = client_id

            if chan_name not in self.event_schemas:
                self.event_schemas[chan_name] = {}
            self.event_schemas[chan_name][event] = {
                "param_schema": reg.get("param_schema"),
                "return_schema": reg.get("return_schema")
            }

            await self._broadcast_to_channel(chan_name, {
                "type": "metadata_update",
                "channel": chan_name,
                "name": event,
                "stype": "event",
                "owner": client_id,
                "param_schema": reg.get("param_schema"),
                "return_schema": reg.get("return_schema")
            }, exclude_client=client_id)
        else:
            is_stream = False
            if chan_name not in self.channels:
                self.channels[chan_name] = []
            if client_id not in self.channels[chan_name]:
                self.channels[chan_name].append(client_id)

            events = {}
            if chan_name in self.providers:
                for ev, pid in self.providers[chan_name].items():
                    schemas = self.event_schemas.get(chan_name, {}).get(ev, {})
                    events[ev] = {
                        "owner": pid,
                        "param_schema": schemas.get("param_schema"),
                        "return_schema": schemas.get("return_schema"),
                        "stype": "event"
                    }

            subs = {}
            if chan_name in self.sub_owners:
                for sn, pid in self.sub_owners[chan_name].items():
                    subs[sn] = {
                        "owner": pid,
                        "param_schema": self.sub_params.get(chan_name, {}).get(sn),
                        "stype": "subscription"
                    }

            await self._send_to_client(client_id, {
                "type": "channel_sync",
                "channel": chan_name,
                "events": events,
                "subscriptions": subs
            })

        await self._system_broadcast("__comm_ipc_system", {
            "type": "receive",
            "channel": "__comm_ipc_system",
            "event": "new_registration",
            "data": {
                "channel": chan_name,
                "event": event,
                "is_provider": is_provider,
                "is_stream": is_stream,
                "client_id": client_id
            }
        })

        await self._send_to_client(client_id, {
            "type": "response",
            "request_id": reg.get("request_id"),
            "channel": chan_name,
            "event": event,
            "data": {
                "channel": chan_name,
                "event": event,
                "authenticated": (chan_name in self.channel_passwords)
            }
        })

    async def _handle_set_password(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        pwd = msg.get("password")
        rid = msg.get("request_id")

        if chan in self.channel_members and self.channel_members[chan][0] != client_id:
            if rid:
                await self._send_to_client(client_id, {
                    "type": "response",
                    "request_id": rid,
                    "error": "Only the channel owner can set or change the password"
                })
            await self._report_error(Exception("Only the channel owner can set or change the password"), client_id)
            return

        if chan not in self.channel_members:
            self.channel_members[chan] = [client_id]

        old_pwd = self.channel_passwords.get(chan)
        if pwd != old_pwd:
            self._log(f"Channel {chan} password set/changed", client_id=client_id)
            self.channel_passwords[chan] = pwd
            others = [cid for cid in self.channel_members.get(chan, []) if cid != client_id]
            for cid in others:
                if cid in self.clients:
                    await self._send_to_client(cid, {"type": "error",
                                                     "message": "Channel password changed, please reconnect"})
                    if chan in self.channels and cid in self.channels[chan]:
                        self.channels[chan].remove(cid)
                    if chan in self.providers:
                        events_to_remove = [ev for ev, pid in self.providers[chan].items() if pid == cid]
                        for ev in events_to_remove: del self.providers[chan][ev]

        if rid:
            await self._send_to_client(client_id, {
                "type": "response",
                "request_id": rid,
                "data": {"success": True}
            })

    async def _handle_call(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        event = msg.get("event")
        if not self._prepare_message(msg, client_id): return

        target_id = None
        if chan in self.providers and event in self.providers[chan]:
            target_id = self.providers[chan][event]

        if target_id:
            await self._send_to_client(target_id, msg)
        else:
            err_msg = f"No provider for {chan}:{event}"
            resp = {
                "type": "response",
                "request_id": msg.get("request_id"),
                "error": err_msg,
                "channel": chan,
                "event": event,
                "sender_id": "server",
                "server_id": self.server_id,
                "origin_server_id": self.server_id,
                "timestamp": int(time.time()),
                "target_id": None,
                "is_stream": False,
                "is_final": False
            }
            await self._send_to_client(client_id, resp)
            await self._report_error(Exception(err_msg), client_id)

    async def close(self):
        self.running = False
        for writer in list(self.active_writers):
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except:
                pass
        self.active_writers.clear()
        self._writer_locks.clear()

    async def _handle_response(self, client_id: str, msg: Dict):
        target_id = msg.get("target_id")
        if not self._prepare_message(msg, client_id):
            return
        if target_id:
            await self._send_to_client(target_id, msg)

    async def _handle_broadcast(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        if not self._prepare_message(msg, client_id):
            return
        if chan in self.channels:
            for tid in self.channels[chan]:
                if tid != client_id:
                    await self._send_to_client(tid, msg)

    async def _handle_send(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        event = msg.get("event")
        if not self._prepare_message(msg, client_id): return
        if chan in self.providers and event in self.providers[chan]:
            await self._send_to_client(self.providers[chan][event], msg)

    def _prepare_message(self, msg: Dict, client_id: str) -> bool:
        if self.server_id in msg.get("path", []):
            return False

        msg["sender_id"] = client_id
        if "timestamp" not in msg:
            msg["timestamp"] = int(time.time())
        if "origin_server_id" not in msg:
            msg["origin_server_id"] = self.server_id

        msg["path"] = msg.get("path", []) + [self.server_id]
        return True

    async def _system_broadcast(self, channel_name: str, msg: Any):
        if channel_name in self.channels:
            msg["sender_id"] = "system"
            msg["server_id"] = self.server_id
            for target_id in self.channels[channel_name]:
                if self.connection_secret_hash and not self.auth_challenges.get(target_id, {}).get("authenticated"):
                    continue
                await self._send_to_client(target_id, msg)

    async def _broadcast_to_channel(self, chan: str, msg: Dict, exclude_client: str = None):
        if chan in self.channels:
            for tid in self.channels[chan]:
                if tid != exclude_client:
                    await self._send_to_client(tid, msg)

    async def _send_to_client(self, client_id: str, msg: Dict):
        if client_id in self.clients:
            writer = self.clients[client_id]
            asyncio.create_task(self._send_to_writer(writer, msg))

    async def _send_to_writer(self, writer: asyncio.StreamWriter, msg: Any):
        if writer not in self._writer_locks:
            self._writer_locks[writer] = asyncio.Lock()

        lock = self._writer_locks[writer]
        async with lock:
            try:
                data = msgpack.packb(msg, use_bin_type=True)
                length = struct.pack(">I", len(data))
                writer.write(length + data)
                await writer.drain()
            except Exception as e:
                if not self._reporting_error:
                    await self._report_error(e)

    async def _report_error(self, e: Exception, client_id: str = None):
        if self._reporting_error:
            return
        self._reporting_error = True
        try:
            if self.error_policy == "raise":
                raise e
            elif self.error_policy == "broadcast":
                err_msg = {
                    "type": "receive",
                    "channel": "__comm_ipc_errors",
                    "event": "server_error",
                    "data": {
                        "error": str(e).split(":")[0],
                        "client_id": client_id,
                        "server_id": self.server_id
                    }
                }
                self._log(str(e).split(":")[0], level="error", client_id=client_id)
                await self._system_broadcast("__comm_ipc_errors", err_msg)

                if client_id and client_id in self.clients:
                    try:
                        await self._send_to_writer(self.clients[client_id], {
                            "type": "error",
                            "message": str(e).split(":")[0]
                        })
                        await self.clients[client_id].drain()
                    except Exception:
                        pass
        finally:
            self._reporting_error = False

    async def run(self, socket_path: str = None, host: str = None, port: int = None, ssl_context=None):
        if socket_path:
            self.socket_path = socket_path

        server = None
        try:
            if host and port:
                server = await asyncio.start_server(self.handle_client, host, port, ssl=ssl_context)
            else:
                if os.path.exists(self.socket_path):
                    os.remove(self.socket_path)
                server = await asyncio.start_unix_server(self.handle_client, self.socket_path)

            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            if server:
                server.close()
                for w in list(self.active_writers):
                    try:
                        w.close()
                        await asyncio.wait_for(w.wait_closed(), timeout=1.0)
                    except:
                        pass
                await asyncio.wait_for(server.wait_closed(), timeout=2.0)
            if self._cleanup_task:
                self._cleanup_task.cancel()

    async def _handle_add_subscription(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        sub_name = msg.get("sub_name")
        rid = msg.get("request_id")
        return_schema = msg.get("return_schema")

        if not chan or not sub_name:
            if rid:
                await self._send_to_client(client_id, {"type": "response", "request_id": rid,
                                                       "error": "channel and sub_name required"})
            return

        if chan in ["subscription"]:
             if rid:
                await self._send_to_client(client_id, {"type": "response", "request_id": rid,
                                                       "error": f"Channel name {chan} is reserved"})
             return

        if sub_name.startswith("subscription."):
             if rid:
                await self._send_to_client(client_id, {"type": "response", "request_id": rid,
                                                       "error": f"Subscription name {sub_name} is reserved"})
             return

        if chan not in self.sub_owners:
            self.sub_owners[chan] = {}

        if sub_name in self.sub_owners[chan] and self.sub_owners[chan][sub_name] != client_id:
            if rid:
                await self._send_to_client(client_id, {"type": "response", "request_id": rid,
                                                       "error": f"Subscription {sub_name} already owned by another client"})
            return

        self.sub_owners[chan][sub_name] = client_id

        if chan not in self.sub_params:
            self.sub_params[chan] = {}
        self.sub_params[chan][sub_name] = return_schema

        await self._broadcast_to_channel(chan, {
            "type": "metadata_update",
            "channel": chan,
            "name": sub_name,
            "stype": "subscription",
            "owner": client_id,
            "return_schema": return_schema
        }, exclude_client=client_id)

        self._log(f"Client {client_id} added subscription {sub_name} on channel {chan}", client_id=client_id)

        if rid:
            await self._send_to_client(client_id, {"type": "response", "request_id": rid, "data": {"success": True}})

    async def _handle_remove_subscription(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        sub_name = msg.get("sub_name")
        rid = msg.get("request_id")

        if chan in self.sub_owners and self.sub_owners[chan].get(sub_name) == client_id:
            await self._remove_subscription(chan, sub_name)
            if rid:
                await self._send_to_client(client_id,
                                           {"type": "response", "request_id": rid, "data": {"success": True}})
        else:
            if rid:
                await self._send_to_client(client_id, {"type": "response", "request_id": rid,
                                                       "error": "Not the owner or subscription does not exist"})

    async def _remove_subscription(self, chan: str, sub_name: str):
        if chan in self.sub_owners:
            self.sub_owners[chan].pop(sub_name, None)

        if chan in self.subscribers and sub_name in self.subscribers[chan]:
            self.subscribers[chan].pop(sub_name, None)

        self._log(f"Subscription {sub_name} on channel {chan} removed")

    async def _handle_subscribe(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        sub_name = msg.get("sub_name")
        rid = msg.get("request_id")

        if chan not in self.subscribers:
            self.subscribers[chan] = {}
        if sub_name not in self.subscribers[chan]:
            self.subscribers[chan][sub_name] = set()

        is_first = (len(self.subscribers[chan][sub_name]) == 0)
        self.subscribers[chan][sub_name].add(client_id)

        if is_first:
            owner_id = self.sub_owners.get(chan, {}).get(sub_name)
            if owner_id:
                await self._send_to_client(owner_id, {
                    "type": "receive",
                    "channel": chan,
                    "event": f"subscription.{sub_name}.first",
                    "data": {"sub_name": sub_name},
                    "timestamp": int(time.time())
                })

        if rid:
            await self._send_to_client(client_id, {"type": "response", "request_id": rid, "data": {"success": True}})

    async def _handle_unsubscribe(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        sub_name = msg.get("sub_name")
        rid = msg.get("request_id")
        await self._unsubscribe(client_id, chan, sub_name)
        if rid:
            await self._send_to_client(client_id, {"type": "response", "request_id": rid, "data": {"success": True}})

    async def _unsubscribe(self, client_id: str, chan: str, sub_name: str):
        if chan in self.subscribers and sub_name in self.subscribers[chan]:
            if client_id in self.subscribers[chan][sub_name]:
                self.subscribers[chan][sub_name].remove(client_id)
                if len(self.subscribers[chan][sub_name]) == 0:
                    owner_id = self.sub_owners.get(chan, {}).get(sub_name)
                    if owner_id:
                        await self._send_to_client(owner_id, {
                            "type": "receive",
                            "channel": chan,
                            "event": f"subscription.{sub_name}.last",
                            "data": {"sub_name": sub_name},
                            "timestamp": int(time.time())
                        })

    async def _handle_publish(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        sub_name = msg.get("sub_name")
        data = msg.get("data")

        if self.sub_owners.get(chan, {}).get(sub_name) != client_id:
            return

        if chan in self.subscribers and sub_name in self.subscribers[chan]:
            pub_msg = {
                "type": "receive",
                "channel": chan,
                "event": f"subscription.{sub_name}.data",
                "data": data,
                "sender_id": client_id,
                "server_id": self.server_id,
                "timestamp": int(time.time())
            }
            for sub_id in list(self.subscribers[chan][sub_name]):
                await self._send_to_client(sub_id, pub_msg)

    async def stop(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        for w in list(self.active_writers):
            try:
                w.close()
                await w.wait_closed()
            except:
                pass
        self.active_writers.clear()
