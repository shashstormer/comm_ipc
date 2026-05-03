import asyncio
import sys
import argparse
import json
from typing import Optional, Any

from comm_ipc.server import CommIPCServer
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData
from comm_ipc.config import SOCKET_PATH

def parse_data(data_str: Optional[str]) -> Any:
    if not data_str:
        return {}
    try:
        return json.loads(data_str)
    except Exception:
        return data_str

async def handle_server(args):
    print(f"Starting server with socket_path={args.socket_path or SOCKET_PATH}")
    server = CommIPCServer(
        socket_path=args.socket_path or SOCKET_PATH,
        connection_secret=args.connection_secret,
        verbose=args.verbose
    )
    try:
        await server.run(host=args.host, port=args.port)
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
        print("Server stopped.")

async def handle_call(args):
    client = CommIPC(
        socket_path=args.socket_path or SOCKET_PATH,
        connection_secret=args.connection_secret,
        verbose=args.verbose
    )
    try:
        await client.connect(host=args.host, port=args.port)
        chan = await client.open(args.channel)
        data = parse_data(args.data)
        print(f"Invoking event {args.event} on channel {args.channel}...")
        res = await chan.event(args.event, data)
        print("Response received:")
        print(json.dumps(res.data, indent=2))
    except Exception as e:
        print(f"Error calling event: {e}", file=sys.stderr)
    finally:
        await client.close()

async def handle_publish(args):
    client = CommIPC(
        socket_path=args.socket_path or SOCKET_PATH,
        connection_secret=args.connection_secret,
        verbose=args.verbose
    )
    try:
        await client.connect(host=args.host, port=args.port)
        chan = await client.open(args.channel)
        data = parse_data(args.data)
        print(f"Publishing to topic {args.topic} on channel {args.channel}...")
        await chan.publish(args.topic, data)
        print("Published successfully.")
    except Exception as e:
        print(f"Error publishing: {e}", file=sys.stderr)
    finally:
        await client.close()

async def handle_subscribe(args):
    client = CommIPC(
        socket_path=args.socket_path or SOCKET_PATH,
        connection_secret=args.connection_secret,
        verbose=args.verbose
    )
    try:
        await client.connect(host=args.host, port=args.port)
        chan = await client.open(args.channel)

        async def sub_callback(cd: CommData):
            print(f"[Topic '{args.topic}' Notification] Received data:", flush=True)
            print(json.dumps(cd.data, indent=2), flush=True)

        await chan.subscribe(args.topic, sub_callback)
        print(f"Subscribed to topic '{args.topic}'. Listening for events. Press Ctrl+C to stop...", flush=True)
        
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("\nSubscription stopped.")
    except Exception as e:
        print(f"Error subscribing: {e}", file=sys.stderr)
    finally:
        await client.close()

async def handle_explore(args):
    client = CommIPC(
        socket_path=args.socket_path or SOCKET_PATH,
        connection_secret=args.connection_secret,
        verbose=args.verbose
    )
    try:
        await client.connect(host=args.host, port=args.port)
        chan = await client.open(args.channel)
        print(f"Exploring capabilities of channel {args.channel}...")
        meta = chan.explore()
        print(json.dumps(meta, indent=2))
    except Exception as e:
        print(f"Error exploring channel: {e}", file=sys.stderr)
    finally:
        await client.close()

async def handle_members(args):
    client = CommIPC(
        socket_path=args.socket_path or SOCKET_PATH,
        connection_secret=args.connection_secret,
        verbose=args.verbose
    )
    try:
        await client.connect(host=args.host, port=args.port)
        chan = await client.open(args.channel)
        print(f"Fetching members for channel {args.channel}...")
        res = await chan.list_members()
        print(json.dumps(res.data, indent=2))
    except Exception as e:
        print(f"Error getting channel members: {e}", file=sys.stderr)
    finally:
        await client.close()

def main():
    parser = argparse.ArgumentParser(prog="comm-ipc", description="CLI interface for the CommIPC library")
    subparsers = parser.add_subparsers(dest="cmd", help="Subcommands", required=True)

    # Server subcommand
    srv_parser = subparsers.add_parser("server", help="Start a CommIPC Server locally")
    srv_parser.add_argument("--socket-path", help="Unix domain socket path to listen on")
    srv_parser.add_argument("--host", help="Host IP to bind to for TCP connections")
    srv_parser.add_argument("--port", type=int, help="Port to bind to for TCP connections")
    srv_parser.add_argument("--connection-secret", help="Secret key for verification during client handshake")
    srv_parser.add_argument("--verbose", action="store_true", help="Enable verbose log output")

    # Call subcommand
    call_parser = subparsers.add_parser("call", help="Invoke an RPC event on a channel")
    call_parser.add_argument("-c", "--channel", required=True, help="Channel name")
    call_parser.add_argument("-e", "--event", required=True, help="Event name to call")
    call_parser.add_argument("-d", "--data", help="JSON data payload string")
    call_parser.add_argument("--socket-path", help="Unix domain socket path")
    call_parser.add_argument("--host", help="Host IP for TCP connection")
    call_parser.add_argument("--port", type=int, help="Port for TCP connection")
    call_parser.add_argument("--connection-secret", help="Secret key for verification")
    call_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    # Publish subcommand
    pub_parser = subparsers.add_parser("publish", help="Publish a message to a pub/sub subscription")
    pub_parser.add_argument("-c", "--channel", required=True, help="Channel name")
    pub_parser.add_argument("-t", "--topic", required=True, help="Topic/Subscription name")
    pub_parser.add_argument("-d", "--data", help="JSON data payload string")
    pub_parser.add_argument("--socket-path", help="Unix domain socket path")
    pub_parser.add_argument("--host", help="Host IP for TCP connection")
    pub_parser.add_argument("--port", type=int, help="Port for TCP connection")
    pub_parser.add_argument("--connection-secret", help="Secret key")
    pub_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    # Subscribe subcommand
    sub_parser = subparsers.add_parser("subscribe", help="Listen to a pub/sub subscription")
    sub_parser.add_argument("-c", "--channel", required=True, help="Channel name")
    sub_parser.add_argument("-t", "--topic", required=True, help="Topic/Subscription name")
    sub_parser.add_argument("--socket-path", help="Unix domain socket path")
    sub_parser.add_argument("--host", help="Host IP for TCP connection")
    sub_parser.add_argument("--port", type=int, help="Port for TCP connection")
    sub_parser.add_argument("--connection-secret", help="Secret key")
    sub_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    # Explore subcommand
    explore_parser = subparsers.add_parser("explore", help="Explore channel events and metadata")
    explore_parser.add_argument("-c", "--channel", required=True, help="Channel name")
    explore_parser.add_argument("--socket-path", help="Unix domain socket path")
    explore_parser.add_argument("--host", help="Host IP for TCP connection")
    explore_parser.add_argument("--port", type=int, help="Port for TCP connection")
    explore_parser.add_argument("--connection-secret", help="Secret key")
    explore_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    # Members subcommand
    members_parser = subparsers.add_parser("members", help="List active channel members")
    members_parser.add_argument("-c", "--channel", required=True, help="Channel name")
    members_parser.add_argument("--socket-path", help="Unix domain socket path")
    members_parser.add_argument("--host", help="Host IP for TCP connection")
    members_parser.add_argument("--port", type=int, help="Port for TCP connection")
    members_parser.add_argument("--connection-secret", help="Secret key")
    members_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        if args.cmd == "server":
            loop.run_until_complete(handle_server(args))
        elif args.cmd == "call":
            loop.run_until_complete(handle_call(args))
        elif args.cmd == "publish":
            loop.run_until_complete(handle_publish(args))
        elif args.cmd == "subscribe":
            loop.run_until_complete(handle_subscribe(args))
        elif args.cmd == "explore":
            loop.run_until_complete(handle_explore(args))
        elif args.cmd == "members":
            loop.run_until_complete(handle_members(args))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
