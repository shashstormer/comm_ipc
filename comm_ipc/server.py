import asyncio
import json
import os
import struct
import uuid
import time
from typing import Dict, Any, List, Set

from comm_ipc.config import SOCKET_PATH


class CommIPCServer:
    def __init__(self, server_id: str = None, socket_path: str = SOCKET_PATH, error_policy: str = "ignore"):
        self.server_id = server_id or f"srv-{uuid.uuid4().hex[:8]}"
        self.socket_path = socket_path
        self.clients: Dict[str, asyncio.StreamWriter] = {}
        self.active_writers: Set[asyncio.StreamWriter] = set()
        self.channels: Dict[str, List[str]] = {}
        self.channel_passwords: Dict[str, str] = {}
        self.providers: Dict[str, Dict[str, str]] = {}
        self.error_policy = error_policy
        self._reporting_error = False
        self.auth_challenges: Dict[str, Dict[str, Any]] = {}

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.active_writers.add(writer)
        client_id = None
        try:
            len_data = await reader.readexactly(4)
            length = struct.unpack(">I", len_data)[0]
            data = await reader.readexactly(length)
            ident = json.loads(data.decode())

            if ident.get("type") == "identify":
                proposed_id = ident.get("client_id")
                if proposed_id in self.clients:
                    await self._send_to_writer(writer, {"type": "error", "message": f"Client ID {proposed_id} already in use"})
                    writer.close()
                    return
                client_id = proposed_id
                self.clients[client_id] = writer
                await self._send_to_writer(writer, {"type": "identified", "client_id": client_id, "server_id": self.server_id})

            while True:
                len_data = await reader.readexactly(4)
                if not len_data: break
                length = struct.unpack(">I", len_data)[0]
                data = await reader.readexactly(length)
                msg = json.loads(data.decode())
                await self.process_message(client_id, msg)

        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            await self._report_error(e, client_id)
        finally:
            if client_id:
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

            if writer in self.active_writers:
                self.active_writers.remove(writer)
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

    async def _handle_register(self, client_id: str, reg: Dict):
        chan_name = reg.get("channel")
        password = reg.get("password")
        is_provider = reg.get("is_provider", False)
        event = reg.get("event")

        if chan_name in self.channel_passwords:
            proof = reg.get("proof")
            challenge_id = reg.get("challenge_id")
            
            if not proof:
                import secrets
                import string
                challenge = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
                challenge_id = str(uuid.uuid4())
                
                if client_id not in self.auth_challenges:
                    self.auth_challenges[client_id] = {}
                self.auth_challenges[client_id][challenge_id] = {
                    "challenge": challenge,
                    "reg": reg,
                    "timestamp": time.time()
                }
                
                await self._send_to_client(client_id, {
                    "type": "auth_challenge",
                    "channel": chan_name,
                    "challenge": challenge,
                    "challenge_id": challenge_id
                })
                return

            # Verify proof
            if client_id not in self.auth_challenges or challenge_id not in self.auth_challenges[client_id]:
                await self._report_error(Exception("Invalid or expired challenge"), client_id)
                return
            
            challenge_data = self.auth_challenges[client_id].pop(challenge_id)
            if time.time() - challenge_data["timestamp"] > 60:
                await self._report_error(Exception("Challenge expired"), client_id)
                return
            
            import hmac
            import hashlib
            expected_proof = hmac.new(
                self.channel_passwords[chan_name].encode(),
                challenge_data["challenge"].encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(expected_proof, proof):
                await self._report_error(Exception("Invalid channel password"), client_id)
                return
            
            reg = challenge_data["reg"]
            chan_name = reg.get("channel")
            is_provider = reg.get("is_provider", False)
            event = reg.get("event")

        if is_provider:
            if not event: return
            if chan_name in self.providers and event in self.providers[chan_name]:
                existing_provider = self.providers[chan_name][event]
                if existing_provider != client_id:
                    err_msg = f"Provider already exists for {chan_name}:{event} (by {existing_provider})"
                    await self._send_to_client(client_id, {"type": "error", "message": err_msg})
                    await self._report_error(Exception(err_msg), client_id)
                    return
            
            if chan_name not in self.providers:
                self.providers[chan_name] = {}
            self.providers[chan_name][event] = client_id
        else:
            if chan_name not in self.channels:
                self.channels[chan_name] = []
            if client_id not in self.channels[chan_name]:
                self.channels[chan_name].append(client_id)

        await self._system_broadcast({
            "type": "receive",
            "channel": "__comm_ipc_system",
            "event": "new_registration",
            "data": reg
        })

    async def _handle_set_password(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        pwd = msg.get("password")
        if chan in self.channel_passwords:
            await self._report_error(Exception("Channel password already set"), client_id)
            return
        self.channel_passwords[chan] = pwd

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
                "server_id": self.server_id
            }
            await self._send_to_client(client_id, resp)
            await self._report_error(Exception(err_msg), client_id)

    async def _handle_response(self, client_id: str, msg: Dict):
        target_id = msg.get("target_id")
        rid = msg.get("request_id")
        if not self._prepare_message(msg, client_id): 
            return
        if target_id:
            await self._send_to_client(target_id, msg)

    async def _handle_broadcast(self, client_id: str, msg: Dict):
        chan = msg.get("channel")
        if not self._prepare_message(msg, client_id): return
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
        path = msg.get("path", [])
        if self.server_id in path:
            return False
        msg["sender_id"] = client_id
        msg["server_id"] = self.server_id
        msg["timestamp"] = time.time()
        msg["path"] = path + [self.server_id]
        return True

    async def _system_broadcast(self, msg: Any):
        if "__comm_ipc_system" in self.channels:
            msg["sender_id"] = "system"
            msg["server_id"] = self.server_id
            for target_id in self.channels["__comm_ipc_system"]:
                await self._send_to_client(target_id, msg)

    async def _send_to_client(self, client_id: str, msg: Any):
        writer = self.clients.get(client_id)
        if writer:
            await self._send_to_writer(writer, msg)

    async def _send_to_writer(self, writer: asyncio.StreamWriter, msg: Any):
        try:
            data = json.dumps(msg).encode()
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
                        "error": str(e),
                        "client_id": client_id,
                        "server_id": self.server_id
                    }
                }
                if "__comm_ipc_errors" in self.channels:
                    for tid in self.channels["__comm_ipc_errors"]:
                        await self._send_to_client(tid, err_msg)
                
                if client_id and client_id in self.clients:
                    try:
                        await self._send_to_writer(self.clients[client_id], {
                            "type": "error",
                            "message": str(e)
                        })
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
                    except:
                        pass
                await asyncio.wait_for(server.wait_closed(), timeout=2.0)
