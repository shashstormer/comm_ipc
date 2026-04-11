import asyncio
import time
import multiprocessing
from benchmark.utils import BenchmarkRunner, calculate_stats, uvloop
from comm_ipc.client import CommIPC

def _run_stream_provider_proc(socket_path, ready_event):
    if uvloop:
        uvloop.install()

    async def run():
        client = CommIPC(socket_path=socket_path, verbose=False)
        await client.connect()
        chan = await client.open("bench_stream")

        async def stream_handler(cd):
            count = cd.data.get("count", 100)
            for i in range(count):
                yield {"chunk": i}

        await chan.add_stream("data_stream", stream_handler)
        ready_event.set()
        await client.wait_till_end()

    asyncio.run(run())

# Since the previous helper was generic, we might need a custom one for streaming
# or update utils.py. Let's just define it here for now.

async def run_stream_benchmark(num_chunks=50000):
    runner = BenchmarkRunner()
    await runner.start_server()
    
    # Custom provider for streaming
    ready_event = multiprocessing.Event()
    proc = multiprocessing.Process(
        target=_run_stream_provider_proc,
        args=(runner.socket_path, ready_event)
    )
    proc.start()
    runner.child_procs.append(proc)
    
    while not ready_event.is_set():
        await asyncio.sleep(0.1)

    # Consumer
    cons_client = await runner.get_client()
    chan_cons = await cons_client.open("bench_stream")
    
    # Warmup
    async for _ in chan_cons.stream("data_stream", {"count": 10}):
        pass
    
    print(f"Running Streaming benchmark ({num_chunks} chunks)...")
    start = time.perf_counter()
    
    received = 0
    async for chunk in chan_cons.stream("data_stream", {"count": num_chunks}):
        received += 1
        
    total_time = time.perf_counter() - start
    throughput = received / total_time
    
    await cons_client.close()
    await runner.stop_all()
    
    return {
        "throughput": throughput
    }

if __name__ == "__main__":
    from benchmark.utils import uvloop
    results = asyncio.run(run_stream_benchmark(num_chunks=10000))
    print(f"\nThroughput: {results['throughput']:.2f} chunks/sec")
