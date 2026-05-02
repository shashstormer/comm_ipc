import asyncio
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData

async def main():
    # 1. Connect first client (provider)
    provider = CommIPC(client_id="provider")
    await provider.connect()
    ch_provider = await provider.open("files")

    # 2. Add an event to download a file from a remote event (Provider side)
    async def file_sender(cd: CommData):
        with open("/path/to/source_file.mp4", "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                yield {"chunk": chunk}

    await ch_provider.add_event("download_video", file_sender)

    # 3. Add an event to receive file chunks from a FastAPI upload route
    import os
    async def file_chunks_receiver(cd: CommData):
        chunk = cd.data["chunk"]
        filename = cd.data.get("filename") or "default_file.bin"
        os.makedirs("./uploads", exist_ok=True)
        with open(os.path.join("./uploads", os.path.basename(filename)), "ab") as f:
            f.write(chunk)

    await ch_provider.add_event("incoming_file_chunks", file_chunks_receiver)

    # 2. Connect second client (consumer)
    consumer = CommIPC(client_id="consumer")
    await consumer.connect()
    ch_consumer = await consumer.open("files")

    # High performance chunked file download over IPC
    await ch_consumer.download_file(
        event_name="download_video",
        dest_path="/path/to/downloaded_file.mp4"
    )

    print("File transfer complete.")
    await provider.close()
    await consumer.close()

if __name__ == "__main__":
    asyncio.run(main())
