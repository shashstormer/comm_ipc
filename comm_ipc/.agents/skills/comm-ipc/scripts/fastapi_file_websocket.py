import asyncio
from fastapi import FastAPI
from comm_ipc.client import CommIPC
from comm_ipc.api import CommAPI
from comm_ipc.comm_data import CommData

app = FastAPI()
client = CommIPC(client_id="gateway")

async def main():
    await client.connect()
    
    # Open channel for the gateway
    chan = await client.open("media")
    
    # ----------------------------------------------------
    # REGISTER CORRESPONDING IPC EVENT HANDLERS
    # ----------------------------------------------------
    
    # RPC Event Handler for incoming WebSockets & fallback to publishing
    async def handle_realtime_stream(cd: CommData):
        print(f"[IPC] Received direct RPC from WebSocket: {cd.data}")
        # Broadcast the message back out as a notification to anyone subscribed
        await chan.publish("realtime_stream", {"echo": cd.data})
    
    await chan.add_event("realtime_stream", handle_realtime_stream)
    await chan.add_subscription("realtime_stream")

    # Streaming Handler for the file/video stream (Range Request support)
    async def video_file_stream(cd: CommData):
        # Simply yields a set of binary bytes
        yield b"Simulated video binary content stream payload over IPC"
        
    await chan.add_event("video_file", video_file_stream)

    # Dynamic file downloader event provider
    import os
    async def get_file_provider(cd: CommData):
        file_path = cd.data.get("file_path")
        if file_path and os.path.exists(file_path):
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield {"chunk": chunk}
                    
    await chan.add_event("get_file", get_file_provider)

    # Inbound file chunks handler for zero-copy upload
    async def incoming_file_chunks_handler(cd: CommData):
        chunk = cd.data["chunk"]
        filename = cd.data.get("filename") or "upload.bin"
        print(f"[IPC] Received file chunk of size {len(chunk)} for filename '{filename}'")
        
    await chan.add_event("incoming_file_chunks", incoming_file_chunks_handler)

    # Initialize CommAPI
    api = CommAPI(app, client)

    # 1. Add Bidirectional WebSocket
    api.add_websocket(path="/ws", channel=chan, event_name="realtime_stream")

    # 2. Add File & Video Streaming with Partial (Range) Support
    api.add_file_stream(path="/video", channel=chan, event_name="video_file")

    # 3. Add Safe Dynamic File Serving from a specific folder with custom extractor
    from fastapi import HTTPException
    def specific_folder_extractor(request):
        filename = request.path_params.get("filename")
        base_dir = os.path.abspath("./public")
        target_path = os.path.abspath(os.path.join(base_dir, filename))
        if not target_path.startswith(base_dir):
            raise HTTPException(status_code=400, detail="Forbidden")
        return {"file_path": target_path}

    api.add_file_stream(
        path="/files/{filename}",
        channel=chan,
        event_name="get_file",
        extractor=specific_folder_extractor
    )

    # 4. Handle Direct Zero-Copy Upload from FastAPI to IPC
    api.add_file_upload(
        path="/upload",
        channel=chan,
        event_name="incoming_file_chunks"
    )

    # 5. Add Two-Way Targeted RPC/Streaming Response over WebSocket
    # Outgoing: Sends data chunk directly back over that same WebSocket to the client.
    # Incoming: Receives a single targeted event request from the web client.
    api.add_rpc_websocket(
        path="/ws-rpc",
        channel=chan,
        event_name="video_file"
    )

    print("FastAPI Gateway initialized with WebSockets, Safe Video streaming, zero-copy uploads, and RPC-over-WS.")

if __name__ == "__main__":
    asyncio.run(main())
