import asyncio
from typing import Any, Dict
from pydantic import BaseModel
from comm_ipc import CommIPC, CommData
from comm_ipc.server import CommIPCServer
import os

# Define a Pydantic model for request validation
class MathParams(BaseModel):
    a: int
    b: int

async def run_rpc_provider_and_consumer():
    """
    Spins up a server in the background, connects the client, registers a provider and calls it.
    """
    socket_path = "/tmp/comm_ipc_rpc.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)
        
    server = CommIPCServer(socket_path=socket_path)
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1) # Wait for server
    
    # Initialize client
    client = CommIPC(
        client_id="demo_client",
        socket_path=socket_path,
        return_type="model",
        auto_reconnect=True,
        verbose=False
    )
    
    await client.connect()
    
    # 1. Open a channel. If it doesn't exist, it will be created.
    channel = await client.open("math_engine")

    # 2. Register an RPC provider
    async def add_handler(cd: CommData):
        # Because we registered with parameters=MathParams, cd.data is guaranteed to be a MathParams instance
        params: MathParams = cd.data
        return {"result": params.a + params.b}
    
    # Register the event on the channel
    await channel.add_event(
        name="add", 
        call=add_handler, 
        parameters=MathParams
    )
    
    print("Provider registered. Calling the event...")

    # 3. Call the event from the same client
    try:
        res: CommData = await channel.event("add", MathParams(a=10, b=20))
        print(f"RPC Call Result: {res.data['result']}")
    except Exception as e:
        print(f"RPC Call Failed: {e}")
        
    await client.close()
    await server.stop()
    print("RPC Demo completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_rpc_provider_and_consumer())
