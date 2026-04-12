import asyncio
import time
from benchmark.utils import BenchmarkRunner, calculate_stats

async def run_rpc_benchmark(num_calls=10000, transport_params=None):
    runner = BenchmarkRunner(**(transport_params or {}))
    await runner.start_server()
    
    # Spawn Provider in separate process
    await runner.spawn_provider("bench", "echo")
    
    # Main process is the Consumer
    cons_client = await runner.get_client()
    chan_cons = await cons_client.open("bench")
    
    # Warmup
    for _ in range(50):
        await chan_cons.event("echo", {"val": "warmup"})
    
    # 1. Latency Benchmark (Sequential)
    print(f"Running RPC Latency benchmark ({num_calls//10} calls)...")
    latencies = []
    for i in range(num_calls // 10):
        start = time.perf_counter()
        await chan_cons.event("echo", {"val": i})
        latencies.append(time.perf_counter() - start)
    
    latency_stats = calculate_stats(latencies)
    
    # 2. Throughput Benchmark (Concurrent)
    print(f"Running RPC Throughput benchmark ({num_calls} calls concurrent)...")
    start = time.perf_counter()
    
    batch_size = 500
    for i in range(0, num_calls, batch_size):
        tasks = [chan_cons.event("echo", {"val": j}) for j in range(i, min(i + batch_size, num_calls))]
        await asyncio.gather(*tasks)
        
    total_time = time.perf_counter() - start
    throughput = num_calls / total_time
    
    await cons_client.close()
    await runner.stop_all()
    
    return {
        "latency": latency_stats,
        "throughput": throughput
    }

if __name__ == "__main__":
    results = asyncio.run(run_rpc_benchmark(num_calls=1000))
    print("\nRPC Results:")
    for k, v in results["latency"].items():
        print(f"{k}: {v:.4f} ms")
    print(f"Throughput: {results['throughput']:.2f} calls/sec")
