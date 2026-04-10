import asyncio
from pydantic import BaseModel
from comm_ipc.client import CommIPC
from comm_ipc.app import CommIPCApp
from comm_ipc.comm_data import CommData

class MathParams(BaseModel):
    a: int
    b: int

async def main():
    client = CommIPC(socket_path="/tmp/comm_ipc_demo.sock", return_type="model", verbose=True)
    await client.connect()
    
    chan = await client.open("demo_app")
    app = CommIPCApp(chan)

    print("--- Defining Decorator Handlers ---")

    @app.provide("add", parameters=MathParams)
    async def add_handler(cd: CommData):
        print(f"[PROVIDER] Handling add: {cd.data}")
        return {"result": cd.data.a + cd.data.b}

    @app.provide("time_stream")
    async def time_stream(cd: CommData):
        print("[PROVIDER] Starting time stream...")
        for i in range(5):
            await asyncio.sleep(0.5)
            yield {"tick": i, "msg": "streaming data..."}

    @app.subscription("system_events")
    class EventModel(BaseModel):
        type: str
        msg: str

    @app.on("system_events")
    async def on_event(cd: CommData):
        print(f"[LISTENER] Received system event: {cd.data}")

    print("Decorator provider is running and registered at /tmp/comm_ipc_demo.sock.")
    print("Press Ctrl+C to exit.")
    
    try:
        await client.wait_till_end()
    finally:
        await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
