import asyncio
import time
from comm_ipc.client import CommIPC

async def main():
    client = CommIPC(socket_path="/tmp/comm_ipc_demo.sock", verbose=True)
    await client.connect()
    
    channel = await client.open("pubsub_demo")
    
    print("--- Defining Subscription 'news' ---")
    await channel.add_subscription("news")

    print("Publisher is starting to broadcast every 2 seconds...")
    try:
        count = 0
        while True:
            msg = {"headline": f"Special Report #{count}", "time": time.ctime()}
            print(f"[PUBLISHER] Publishing: {msg}")
            await channel.publish("news", msg)
            count += 1
            await asyncio.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
