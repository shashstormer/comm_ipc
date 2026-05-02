"""
CommIPC Bridge Federation Skill

This script demonstrates how to connect two separate CommIPC Hubs (Servers)
together using the CommIPCBridge. This allows clients on Server A to transparently
communicate with clients on Server B.
"""

import asyncio

try:
    from comm_ipc.server import CommIPCServer
    from comm_ipc.bridge import CommIPCBridge
    from comm_ipc.client import CommIPC
except ImportError:
    pass

async def run_federation_demo():
    # 1. Spin up two separate CommIPC servers
    print("Starting Hub A...")
    hub_a = CommIPCServer(server_id="hub_A", socket_path="/tmp/hub_A.sock")
    task_a = asyncio.create_task(hub_a.run())

    print("Starting Hub B...")
    hub_b = CommIPCServer(server_id="hub_B", socket_path="/tmp/hub_B.sock")
    task_b = asyncio.create_task(hub_b.run())
    
    await asyncio.sleep(0.5)

    # 2. Setup the Bridge between the two hubs
    print("Initializing Bridge...")
    # Pass socket paths and allowed_channels in the constructor
    bridge = CommIPCBridge(
        bridge_id="bridge_AB", 
        socket_path1="/tmp/hub_A.sock", 
        socket_path2="/tmp/hub_B.sock",
        allowed_channels=["federated_channel"]
    )
    
    # Connect the bridge (it acts as a client on both sides, routing traffic)
    await bridge.connect(target1_params={}, target2_params={})
    print("Bridge connected. Federation active.")

    # 3. Client on Hub A (Provider)
    client_a = CommIPC(client_id="provider_a", socket_path="/tmp/hub_A.sock")
    await client_a.connect()
    chan_a = await client_a.open("federated_channel")
    
    async def global_ping(cd):
        return {"msg": f"Hello from {cd.server_id}!"}
        
    await chan_a.add_event("ping", global_ping)

    # 4. Client on Hub B (Consumer)
    client_b = CommIPC(client_id="consumer_b", socket_path="/tmp/hub_B.sock")
    await client_b.connect()
    chan_b = await client_b.open("federated_channel")
    
    # Call the event. The bridge will route this from Hub B to Hub A seamlessly.
    print("Client B calling Provider on Hub A...")
    res = await chan_b.event("ping", {})
    print(f"Response received on Client B: {res.data}")

    # 5. Cleanup
    await client_b.close()
    await client_a.close()
    await bridge.stop()
    await hub_b.stop()
    await hub_a.stop()
    task_b.cancel()
    task_a.cancel()

if __name__ == "__main__":
    asyncio.run(run_federation_demo())
