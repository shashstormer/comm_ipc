"""
CommIPC FastAPI Integration Skill

This skill demonstrates how to bridge CommIPC with FastAPI, exposing IPC events
as REST or SSE (Server-Sent Events) endpoints using the `CommAPI` class.
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

# Note: This setup assumes there is another CommIPC client registered
# to the "math_engine" channel providing an "add" event.
# Once FastAPI starts, it will expose POST /api/math/add which
# will forward the request to the CommIPC network.

# Example 1: Expose a specific event explicitly
comm_api.add_event(
    channel="math_engine",
    event_name="add",
    path="/api/math/add",
    method="POST",
    tags=["Math"]
)

# Example 2: Expose a streaming event (automatically mapped to SSE)
comm_api.add_event(
    channel="streams",
    event_name="counter",
    path="/api/stream/counter",
    method="GET",
    tags=["Streams"]
)

# Example 3: Expose a grouped event
# If a provider used `@app.group("workers").provide("mult")`, the actual
# event name in the CommIPC system is "workers.mult".
comm_api.add_event(
    channel="math_engine",
    event_name="workers.mult",
    path="/api/math/mult",
    method="POST",
    tags=["Math"]
)

# Example 4: Mount all discovered events on a channel
# This will query the server for all registered endpoints on "public_services"
# and mount them under /api/services/{event}
comm_api.add_resource(
    channel="public_services",
    path_template="/api/services/{event}",
    tags=["Auto Services"],
    method="POST"
)

@app.get("/")
def read_root():
    return {"message": "FastAPI + CommIPC Gateway is running."}

if __name__ == "__main__":
    import uvicorn
    # Make sure a CommIPC Server is running, e.g. python -m comm_ipc.server
    print("Run this server using: uvicorn fastapi_integration:app --reload")
    # uvicorn.run(app, host="127.0.0.1", port=8000)
