from comm_ipc import CommIPCApp, CommIPC
from comm_ipc.comm_data import CommData
from pydantic import BaseModel
import asyncio
import os

# 1. Define App at top level (no channel yet!)
app = CommIPCApp()

# 2. Define a data model
class MathParams(BaseModel):
    a: int
    b: int

# 3. Register a provider via decorators
@app.provide("add", parameters=MathParams)
async def add(cd: CommData):
    print(f"[SERVER] Adding {cd.data.a} + {cd.data.b}")
    return cd.data.a + cd.data.b

# 4. Register a streaming provider
@app.provide("counter")
async def count_up(cd: CommData):
    print("[SERVER] Starting counter...")
    for i in range(5):
        yield {"count": i}

# 5. Register a group provider
@app.group("workers").provide("mult")
async def mult(cd: CommData):
    print(f"[SERVER] Multiplying in group: {cd.data}")
    return cd.data["a"] * cd.data["b"]

# 6. Declare and listen to subscriptions
@app.subscription("updates")
class UpdateModel(BaseModel):
    status: str

@app.on("updates")
async def handle_update(cd: CommData):
    print(f"[SERVER] Received System Status: {cd.data.status}")

async def run_client(socket_path):
    await asyncio.sleep(1) # Wait for server to register
    client = CommIPC(socket_path=socket_path)
    await client.connect()
    chan = await client.open("math")
    
    print("\n--- Testing 'add' ---")
    res = await chan.event("add", {"a": 10, "b": 20})
    print(f"Result: {res.data}")
    
    print("\n--- Testing 'counter' stream ---")
    async for chunk in chan.stream("counter", {}):
        print(f"Stream: {chunk.data}")
        
    print("\n--- Testing 'mult' group ---")
    res = await chan.group("workers").get("mult", {"a": 5, "b": 6})
    print(f"Group Result: {res.data}")

    print("\n--- Testing PubSub ---")
    await chan.publish("updates", {"status": "all systems green"})
    await asyncio.sleep(0.5)

    await client.close()

async def main():
    socket_path = "/tmp/comm_ipc_decoupled.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)
        
    from comm_ipc.server import CommIPCServer
    server = CommIPCServer(socket_path=socket_path)
    asyncio.create_task(server.run())
    
    # Wait for socket to be created
    for _ in range(10):
        if os.path.exists(socket_path):
            break
        await asyncio.sleep(0.1)
    
    # --- DECOUPLED ACTIVATION ---
    client = CommIPC(socket_path=socket_path, return_type="model")
    await client.connect()
    chan = await client.open("math")
    
    print("Activating App via app.register(chan)...")
    await app.register(chan)
    # ----------------------------

    # Run client test
    await run_client(socket_path)
    
    await server.stop()
    if os.path.exists(socket_path):
        os.remove(socket_path)

if __name__ == "__main__":
    asyncio.run(main())
