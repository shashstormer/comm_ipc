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
    
    # Initialize CommAPI
    api = CommAPI(app, client)

    # 1. Add Bidirectional WebSocket
    # Outgoing: To send to client, any channel subscriber triggers direct text/JSON message.
    # Incoming: Client sends JSON text to be passed to IPC.
    api.add_websocket(path="/ws", channel=chan, event_name="realtime_stream")

    # 2. Add File & Video Streaming with Partial (Range) Support
    api.add_file_stream(path="/video", channel=chan, event_name="video_file")

    # 3. Add Safe Dynamic File Serving from a specific folder with custom extractor
    import os
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

    print("FastAPI Gateway initialized with WebSockets, Safe Video streaming, and zero-copy uploads.")

if __name__ == "__main__":
    asyncio.run(main())
