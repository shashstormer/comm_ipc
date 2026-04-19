"""
CommIPC System Monitor Skill

This script demonstrates how to subscribe to the internal system channels
provided by the CommIPCServer for observability, debugging, and audit logging.
"""

import asyncio

try:
    from comm_ipc import CommIPC, CommData
except ImportError:
    pass

async def run_monitor():
    """
    Connects to the server and listens to system diagnostic channels.
    """
    # Using verbose=True is another way to see logs, but this script
    # demonstrates programmatically capturing them.
    client = CommIPC(client_id="system_monitor", verbose=False)
    await client.connect()
    
    # The server provides three reserved read-only channels:
    # 1. __comm_ipc_logs: General routing and connection logs
    # 2. __comm_ipc_errors: Exceptions and warnings
    # 3. __comm_ipc_system: Topology changes (new clients, registrations)
    
    log_chan = await client.open("__comm_ipc_logs")
    err_chan = await client.open("__comm_ipc_errors")
    sys_chan = await client.open("__comm_ipc_system")

    # Generic listener callback
    def make_listener(prefix):
        async def _listen(cd: CommData):
            print(f"[{prefix}] {cd.data}")
        return _listen

    # Attach listeners. Note: we don't need to specify an event_name
    # when listening to a broadcast-only system channel.
    log_chan.on_receive(make_listener("LOG"))
    err_chan.on_receive(make_listener("ERROR"))
    sys_chan.on_receive(make_listener("SYSTEM"))

    print("System Monitor Active. Waiting for events...")
    
    # Keep the monitor alive
    try:
        await asyncio.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        await client.close()

if __name__ == "__main__":
    # Ensure a server is running at /tmp/comm_ipc.sock
    asyncio.run(run_monitor())
