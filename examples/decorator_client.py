import asyncio
from comm_ipc.client import CommIPC

async def main():
    # Use return_type="model" for automated Pydantic model conversion
    client = CommIPC(socket_path="/tmp/comm_ipc_demo.sock", return_type="model")
    await client.connect()
    
    channel = await client.open("demo_app")

    print("\n--- Testing @app.provide('add') ---")
    res = await channel.event("add", {"a": 10, "b": 25})
    print(f"Add Result: {res.data['result']}")

    print("\n--- Testing @app.provide('time_stream') ---")
    async for chunk in channel.stream("time_stream", {}):
        print(f"Stream Chunk: {chunk.data}")

    print("\n--- Testing @app.on('system_events') via publish ---")
    await channel.publish("system_events", {"type": "info", "msg": "Hello from Client!"})
    
    # Wait a bit for the listener to receive
    await asyncio.sleep(1)

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
