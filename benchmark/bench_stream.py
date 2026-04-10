import asyncio
import time
from benchmark.utils import BenchmarkRunner

async def run_stream_benchmark(num_chunks=5000):
    runner = BenchmarkRunner()
    await runner.start_server()
    
    # Provider
    prov_client = await runner.get_client()
    chan_prov = await prov_client.open("bench_stream")
    
    async def stream_handler(cd):
        for i in range(num_chunks):
            yield {"idx": i}
            
    await chan_prov.add_stream("data", stream_handler)
    
    # Consumer
    cons_client = await runner.get_client()
    chan_cons = await cons_client.open("bench_stream")
    
    print(f"Running Streaming benchmark ({num_chunks} chunks)...")
    start = time.perf_counter()
    count = 0
    async for chunk in chan_cons.stream("data", {}):
        count += 1
        
    total_time = time.perf_counter() - start
    throughput = count / total_time
    
    await prov_client.close()
    await cons_client.close()
    await runner.stop_server()
    
    return {
        "count": count,
        "time": total_time,
        "throughput": throughput
    }

if __name__ == "__main__":
    results = asyncio.run(run_stream_benchmark())
    print(f"\nStream Results:")
    print(f"Chunks: {results['count']}")
    print(f"Total Time: {results['time']:.4f} s")
    print(f"Throughput: {results['throughput']:.2f} chunks/sec")
