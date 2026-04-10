import asyncio
import os
from comm_ipc.server import CommIPCServer

async def main():
    socket_path = "/tmp/comm_ipc_demo.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)
        
    print(f"Starting CommIPC Server on {socket_path}...")
    server = CommIPCServer(socket_path=socket_path, verbose=True)
    
    try:
        await server.run()
    except asyncio.CancelledError:
        print("Server shutting down...")
    finally:
        if os.path.exists(socket_path):
            os.remove(socket_path)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
