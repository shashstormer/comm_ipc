import asyncio
from comm_ipc.client import CommIPC

async def main():
    client = CommIPC(socket_path="/tmp/comm_ipc_demo.sock")
    await client.connect()
    
    channel = await client.open("stream_demo")

    print("\n--- Consuming Stream 'logs' ---")
    async for chunk in channel.stream("logs", {"count": 10}):
        print(f"Log Chunk: {chunk.data}")

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
