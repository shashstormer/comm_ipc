import asyncio
from comm_ipc.client import CommIPC

async def log_streamer(cd):
    print(f"[STREAM PROVIDER] Starting log stream for {cd.data.get('count', 5)} items...")
    for i in range(cd.data.get('count', 5)):
        await asyncio.sleep(0.3)
        yield {"log_id": i, "entry": "System operational", "severity": "DEBUG"}

async def main():
    client = CommIPC(socket_path="/tmp/comm_ipc_demo.sock", verbose=True)
    await client.connect()
    
    channel = await client.open("stream_demo")
    
    print("--- Registering Stream Handler ---")
    await channel.add_stream("logs", log_streamer)

    print("Stream provider is running. Press Ctrl+C to exit.")
    try:
        await client.wait_till_end()
    finally:
        await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
