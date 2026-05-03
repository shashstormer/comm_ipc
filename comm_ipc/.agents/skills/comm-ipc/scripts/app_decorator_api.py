"""
CommIPC App Decorator API Skill

This skill demonstrates the modern, decoupled "FastAPI-style" decorator API using `CommIPCApp`.
It covers RPC providers, stream providers, load-balanced groups, and event listeners.
"""

import asyncio
from pydantic import BaseModel

try:
    from comm_ipc import CommIPC, CommData, CommIPCApp
except ImportError:
    pass

# 1. Instantiate the App at the top level
app = CommIPCApp()

# Pydantic model for validation
class MathParams(BaseModel):
    a: int
    b: int

# 2. Register an RPC provider
@app.provide("add", parameters=MathParams)
async def add(cd: CommData):
    """Simple RPC handler validated by Pydantic."""
    return {"result": cd.data.a + cd.data.b}

# 3. Register a streaming provider (automatically detected as async generator)
@app.provide("counter")
async def count_up(cd: CommData):
    """Stream handler."""
    for i in range(5):
        yield {"count": i}

# 4. Register a Load-Balanced Group provider
# Providers in a group share the load (e.g. round-robin or least-active)
workers = app.group("workers")

@workers.provide("mult")
async def mult(cd: CommData):
    """Grouped RPC handler. (Internally registered as 'workers.mult')"""
    return {"result": cd.data["a"] * cd.data["b"]}

class UpdateModel(BaseModel):
    info: str

# 5. Declare a Subscription Schema
# This registers the subscription with the server
@app.subscription("system_updates", model=UpdateModel)
def _declare_updates(): pass

# 6. Listen to Subscriptions / Events
@app.on("system_updates")
async def handle_update(cd: CommData):
    """Event listener."""
    print(f"[Listener] Update received: {cd.data}")

async def run_decorator_demo():
    """
    Spins up a local server in the background, connects the client, and binds the app to a channel.
    """
    from comm_ipc.server import CommIPCServer
    import os
    
    # 1. Start a local server in the background
    socket_path = "/tmp/comm_ipc_decorator.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)
    server = CommIPCServer(socket_path=socket_path)
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1) # Wait for server
    
    client = CommIPC(socket_path=socket_path, return_type="model", verbose=False)
    await client.connect()
    
    # Open the channel
    channel = await client.open("app_channel")
    
    # 6. Bind the application to the channel. 
    # This automatically registers all @app.provide and @app.on handlers
    await app.register(channel)
    print("CommIPCApp registered on 'app_channel'.")
    
    # Demonstration: calling the handlers
    
    # Call standard RPC
    res = await channel.event("add", MathParams(a=5, b=7))
    print(f"Add Result: {res.data['result']}")
    
    # Call Group RPC (Using the App helper automatically formats the name)
    res_group = await channel.group("workers").get("mult", {"a": 4, "b": 5})
    # If calling natively without the helper: await channel.event("workers.mult", ...)
    print(f"Mult (Group) Result: {res_group.data['result']}")
    
    # Call Stream
    async for chunk in channel.stream("counter", {}):
        print(f"Stream Chunk: {chunk.data['count']}")
        
    await client.close()
    await server.stop()
    print("Demo completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_decorator_demo())
