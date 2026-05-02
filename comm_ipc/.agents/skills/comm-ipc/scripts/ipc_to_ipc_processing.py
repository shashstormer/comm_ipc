import asyncio
import os
from comm_ipc.client import CommIPC
from comm_ipc.comm_data import CommData

async def main():
    # 1. Initialize Processor Node A (The File Processing Worker)
    processor = CommIPC(client_id="file_processor")
    await processor.connect()
    ch_processor = await processor.open("media_processing")

    # This node receives file chunks streamed over the IPC network
    received_chunks = []
    async def handle_uploaded_chunks(cd: CommData):
        chunk = cd.data["chunk"]
        is_final = cd.data["is_final"]
        received_chunks.append(chunk)
        
        if is_final:
            full_data = b"".join(received_chunks)
            print(f"[Worker] File completely uploaded over IPC. Received {len(full_data)} bytes.")
            print("[Worker] Processing file...")
            # For example, perform any audio/video transcoding, machine learning inference, etc.
            received_chunks.clear()

    await ch_processor.add_event("process_video_chunks", handle_uploaded_chunks)

    # 2. Initialize Node B (The Source/Producer Node)
    producer = CommIPC(client_id="file_producer")
    await producer.connect()
    ch_producer = await producer.open("media_processing")

    # Create a temporary source file to simulate the local file
    src_path = "/tmp/source_test.bin"
    with open(src_path, "wb") as f:
        f.write(b"Very large video content payload to be processed over IPC" * 50)

    # Stream file to Processor Node A via direct IPC chunked file transfer
    print("[Producer] Starting direct high-performance file transfer to processing node over IPC...")
    await ch_producer.upload_file(src_path, "process_video_chunks")

    print("[Producer] High-performance file processing transfer complete.")

    # Cleanup temporary file
    if os.path.exists(src_path):
        os.remove(src_path)

    await processor.close()
    await producer.close()

if __name__ == "__main__":
    asyncio.run(main())
