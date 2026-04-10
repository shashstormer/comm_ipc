import asyncio
import time
from benchmark.utils import BenchmarkRunner, calculate_stats

async def run_rpc_benchmark(num_calls=1000):
    runner = BenchmarkRunner()
    await runner.start_server()
    
    # Provider Client
    prov_client = await runner.get_client()
    chan_prov = await prov_client.open("bench")
    async def echo_handler(cd):
        return cd.data
    await chan_prov.add_event("echo", echo_handler)
    
    # Consumer Client
    cons_client = await runner.get_client()
    chan_cons = await cons_client.open("bench")
    
    # Warmup
    for _ in range(10):
        await chan_cons.event("echo", {"val": "warmup"})
    
    # 1. Latency Benchmark (Sequential)
    print(f"Running RPC Latency benchmark ({num_calls} calls)...")
    latencies = []
    for i in range(num_calls):
        start = time.perf_counter()
        await chan_cons.event("echo", {"val": i})
        latencies.append(time.perf_counter() - start)
    
    latency_stats = calculate_stats(latencies)
    
    # 2. Throughput Benchmark (Concurrent)
    print(f"Running RPC Throughput benchmark ({num_calls} calls concurrent)...")
    start = time.perf_counter()
    tasks = [chan_cons.event("echo", {"val": i}) for i in range(num_calls)]
    await asyncio.gather(*tasks)
    total_time = time.perf_counter() - start
    throughput = num_calls / total_time
    
    await prov_client.close()
    await cons_client.close()
    await runner.stop_server()
    
    return {
        "latency": latency_stats,
        "throughput": throughput
    }

if __name__ == "__main__":
    results = asyncio.run(run_rpc_benchmark())
    print("\nRPC Results:")
    for k, v in results["latency"].items():
        print(f"{k}: {v:.4f} ms")
    print(f"Throughput: {results['throughput']:.2f} calls/sec")
