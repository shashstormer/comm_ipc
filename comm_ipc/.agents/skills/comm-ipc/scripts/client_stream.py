"""
CommIPC Client Streaming Skill

This skill demonstrates how to handle streaming data in CommIPC.
It involves registering an async generator as a stream provider,
and consuming it using the `stream()` async iterator.
"""

import asyncio
from comm_ipc import CommIPC, CommData
from comm_ipc.server import CommIPCServer
import os

async def run_stream_demo():
    """
    Spins up a local server in the background, registers an async stream provider, and consumes it.
    """
    socket_path = "/tmp/comm_ipc_stream.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)
        
    # Start server in background
    server = CommIPCServer(socket_path=socket_path)
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1) # Wait for server
    
    # Initialize client
    client = CommIPC(socket_path=socket_path, verbose=False)
    await client.connect()
    channel = await client.open("streams_channel")

    # 1. Create a Stream Provider (must be an async generator)
    async def count_up(cd: CommData):
        limit = cd.data.get("limit", 5)
        print(f"[Provider] Starting stream up to {limit}")
        for i in range(limit):
            # Yield chunks of data
            yield {"count": i}
            # Simulate some work or delay
            await asyncio.sleep(0.01)
            
        print("[Provider] Stream finished")

    # 2. Register the stream
    # Alternative: use channel.add_event(name, count_up) directly. 
    # Because count_up uses yield, the system automatically detects it's an async generator function.
    await channel.add_stream("counter", count_up)
    print("Stream provider 'counter' registered.")

    # 3. Consume the stream
    print("Calling stream 'counter'...")
    try:
        # stream() returns an async iterator
        async for chunk in channel.stream("counter", {"limit": 3}):
            print(f"[Consumer] Received chunk: {chunk.data['count']}")
    except Exception as e:
        print(f"[Consumer] Stream error: {e}")

    # To keep the script running indefinitely as a dedicated streaming node:
    # await client.wait_till_end()

    # 4. Clean up
    await client.close()
    await server.stop()
    print("Streaming Demo completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_stream_demo())
