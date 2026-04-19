"""
CommIPC Client RPC Skill

This skill demonstrates how to create a CommIPC client, connect to a server, open a channel,
register an RPC (Request-Response) handler with Pydantic validation, and call it.
"""

import asyncio
from typing import Any, Dict
from pydantic import BaseModel

# Assumes comm_ipc is installed or available in the path
try:
    from comm_ipc import CommIPC, CommData
except ImportError:
    pass

# Define a Pydantic model for request validation
class MathParams(BaseModel):
    a: int
    b: int

async def create_client(socket_path: str = "/tmp/comm_ipc.sock", client_id: str = "demo_client") -> CommIPC:
    """
    Creates and connects a CommIPC client.
    """
    # Initialize client, specify return_type="model" for Pydantic support
    client = CommIPC(
        client_id=client_id,
        socket_path=socket_path,
        return_type="model", # Required for Pydantic support (Default is "dict")
        auto_reconnect=True, # Automatically reconnect on failure (This is the default)
        verbose=True
    )
    
    # Establish connection to the server
    await client.connect()
    return client

async def run_rpc_provider_and_consumer():
    """
    Demonstrates setting up a provider and calling it.
    """
    client = await create_client()
    
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

    # 3. Call the event from the same client (or a different one)
    # The event call routes through the server back to the provider
    try:
        res: CommData = await channel.event("add", MathParams(a=10, b=20))
        print(f"RPC Call Result: {res.data['result']}")
    except Exception as e:
        print(f"RPC Call Failed: {e}")
        
    # 4. Clean up
    # Note: If this script were purely a provider intended to run forever, 
    # you would replace client.close() with: await client.wait_till_end()
    await client.close()

if __name__ == "__main__":
    # Note: A server must be running at /tmp/comm_ipc.sock for this to work
    asyncio.run(run_rpc_provider_and_consumer())
