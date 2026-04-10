import asyncio
from comm_ipc.client import CommIPC

async def add_handler(cd):
    print(f"[RPC PROVIDER] Handling add: {cd.data}")
    return {"result": cd.data["a"] + cd.data["b"]}

async def main():
    client = CommIPC(socket_path="/tmp/comm_ipc_demo.sock", verbose=True)
    await client.connect()
    
    channel = await client.open("rpc_demo")
    
    print("--- Registering Standard RPC Handler ---")
    await channel.add_event("add", add_handler)

    print("RPC provider is running. Press Ctrl+C to exit.")
    try:
        await client.wait_till_end()
    finally:
        await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
