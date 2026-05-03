"""
CommIPC WebSocket Input + Stream Response Example Skill

This script demonstrates Pattern 18: WebSocket SSE with Initial User Input/Payload.
A client establishes a single WebSocket connection, transmits its initial parameters, 
and the server invokes an IPC stream to continuously relay response data chunks 
back over that same WebSocket.
"""

import asyncio
import os
import json
from fastapi import FastAPI

from comm_ipc import CommIPC, CommData
from comm_ipc.api import CommAPI
from comm_ipc.server import CommIPCServer

class MockWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent_messages = []
        self.to_receive = asyncio.Queue()

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        return await self.to_receive.get()

    async def send_text(self, text):
        self.sent_messages.append(text)

async def run_ws_input_stream_demo():
    socket_path = "/tmp/comm_ipc_ws_rpc.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)
        
    # 1. Start a local server in the background
    server = CommIPCServer(socket_path=socket_path)
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1) # Wait for server
    
    # 2. Connect client and open a channel
    client = CommIPC(socket_path=socket_path, verbose=False)
    await client.connect()
    chan = await client.open("market_data")
    
    # 3. Register a stream provider on the IPC channel that takes the initial payload
    async def ticker_stream(cd: CommData):
        symbol = cd.data.get("symbol", "UNKNOWN")
        limit = cd.data.get("limit", 3)
        print(f"[IPC Provider] Processing stream for symbol: {symbol}, limit: {limit}")
        for i in range(limit):
            yield {"symbol": symbol, "update_index": i, "price": 100 + i * 1.5}
            await asyncio.sleep(0.01)

    # Add the streaming event
    await chan.add_stream("ticker", ticker_stream)
    print("IPC stream provider 'ticker' successfully registered.")

    # 4. Create a FastAPI Gateway using CommAPI
    app = FastAPI()
    api = CommAPI(app, client)

    # Map the WebSocket to the targeted ticker event
    api.add_rpc_websocket(path="/ws-rpc", channel=chan, event_name="ticker")
    print("FastAPI Gateway initialized with RPC WebSocket.")

    # Get the WebSocket route endpoint directly
    route = [r for r in app.routes if r.path == "/ws-rpc"][0]
    ws_endpoint = route.endpoint

    # 5. Connect and simulate the WebSocket client
    mock_ws = MockWebSocket()
    ws_task = asyncio.create_task(ws_endpoint(mock_ws))
    await asyncio.sleep(0.1)

    # Send initial request parameters as JSON text
    initial_payload = {"symbol": "BTC-USD", "limit": 4}
    print(f"\n[WebSocket Client] Sending initial request payload: {initial_payload}")
    await mock_ws.to_receive.put(json.dumps(initial_payload))

    # Wait for the stream chunks to process
    await asyncio.sleep(0.5)

    print("\n[WebSocket Client] Received streamed response chunks:")
    for msg in mock_ws.sent_messages:
        print(f" -> {msg}")

    # 6. Clean up
    ws_task.cancel()
    await client.close()
    await server.stop()
    print("\nDemo completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_ws_input_stream_demo())
