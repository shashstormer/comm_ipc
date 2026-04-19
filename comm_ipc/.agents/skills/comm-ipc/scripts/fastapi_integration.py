"""
CommIPC FastAPI Integration Skill (Updated for 0.1.8)

This skill demonstrates how to bridge CommIPC with FastAPI, exposing IPC events
as dynamic, runtime-resilient REST or SSE (Server-Sent Events) endpoints.
"""

import asyncio
from contextlib import asynccontextmanager

# Assumes fastapi and uvicorn are installed
try:
    from fastapi import FastAPI
    from comm_ipc import CommIPC
    from comm_ipc.api import CommAPI
except ImportError:
    pass

# Initialize CommIPC client
client = CommIPC(verbose=True)

# Define FastAPI lifespan to manage CommIPC connection
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect CommIPC client
    print("Connecting CommIPC client...")
    try:
        await client.connect()
    except Exception as e:
        print(f"CommIPC connection failed: {e}. (Is the CommIPC server running?)")
    
    yield
    
    # Shutdown: Disconnect CommIPC client
    print("Closing CommIPC client...")
    await client.close()

# Initialize FastAPI app
app = FastAPI(lifespan=lifespan)

# Setup CommAPI bridge
comm_api = CommAPI(app, client)

async def setup_routes():
    # 1. Open channels first (CommAPI now takes channel objects for dynamic schema resolution)
    math_chan = await client.open("math_engine")
    stream_chan = await client.open("streams")
    pubsub_chan = await client.open("alerts")

    # 2. Expose a specific event explicitly
    # This will dynamically validate against the latest schema on math_engine
    comm_api.add_event(
        channel=math_chan,
        event_name="add",
        path="/api/math/add",
        method="POST",
        tags=["Math"]
    )

    # 3. Expose a grouped event
    # You explicitly define the manual URL path for every event
    comm_api.add_event(
        channel=math_chan,
        event_name="workers.mult",
        path="/api/math/mult",
        method="POST",
        tags=["Math"]
    )

    # 4. Expose a streaming event (automatically mapped to SSE)
    comm_api.add_event(
        channel=stream_chan,
        event_name="counter",
        path="/api/stream/counter",
        method="GET",
        tags=["Streams"]
    )

    # 5. Expose an IPC Subscription as an SSE stream
    # This bridges any IPC 'publish' message to the web client
    comm_api.add_subscription(
        channel=pubsub_chan,
        sub_name="system",
        path="/api/alerts/system",
        tags=["Alerts"]
    )

    # 6. Mount all discovered events on a channel
    comm_api.add_resource(
        channel=math_chan,
        path_template="/api/engine/{event}",
        tags=["Auto Engine"],
        method="POST"
    )

# Since setup_routes is async and needs an active client, 
# you'd typically call this inside lifespan or a separate startup task.
# Here we just show the definitions.

@app.get("/")
def read_root():
    return {"message": "FastAPI + CommIPC Gateway (v0.1.8) is running."}

if __name__ == "__main__":
    import uvicorn
    # Make sure a CommIPC Server is running, e.g. python -m comm_ipc.server
    print("Run this server using: uvicorn fastapi_integration:app --reload")
