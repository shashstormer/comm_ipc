"""
CommIPC Client Streaming Skill

This skill demonstrates how to handle streaming data in CommIPC.
It involves registering an async generator as a stream provider,
and consuming it using the `stream()` async iterator.
"""

import asyncio

try:
    from comm_ipc import CommIPC, CommData
except ImportError:
    pass

async def run_stream_demo():
    """
    Demonstrates an async stream provider and consumer.
    """
    client = CommIPC(verbose=True)
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
            await asyncio.sleep(0.1)
            
        print("[Provider] Stream finished")

    # 2. Register the stream
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

    # 4. Clean up
    await client.close()

if __name__ == "__main__":
    # Note: A server must be running at /tmp/comm_ipc.sock for this to work
    asyncio.run(run_stream_demo())
