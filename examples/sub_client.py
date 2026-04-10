import asyncio
from comm_ipc.client import CommIPC

async def main():
    client = CommIPC(socket_path="/tmp/comm_ipc_demo.sock")
    await client.connect()
    
    channel = await client.open("pubsub_demo")

    print("--- Subscribing to 'news' ---")
    
    received_count = 0
    done = asyncio.Event()

    async def news_handler(cd):
        nonlocal received_count
        print(f"[SUBSCRIBER] Got News: {cd.data['headline']} (at {cd.data['time']})")
        received_count += 1
        if received_count >= 5:
            done.set()

    await channel.subscribe("news", news_handler)

    print("Subscriber will exit after 5 messages...")
    try:
        await asyncio.wait_for(done.wait(), timeout=15)
    except asyncio.TimeoutError:
        print("Subscriber timed out waiting for messages.")
    finally:
        await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
