import asyncio
from comm_ipc.client import CommIPC

async def main():
    client = CommIPC(socket_path="/tmp/comm_ipc_demo.sock")
    await client.connect()
    
    channel = await client.open("rpc_demo")

    print("\n--- Calling RPC 'add' ---")
    res = await channel.event("add", {"a": 50, "b": 100})
    print(f"RPC Result: {res.data['result']}")

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
