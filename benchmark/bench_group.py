import asyncio
import time
import multiprocessing
from benchmark.utils import BenchmarkRunner, calculate_stats

async def run_group_benchmark(num_calls=10000):
    runner = BenchmarkRunner()
    await runner.start_server()
    
    # Spawn 2 Providers in separate processes
    await runner.spawn_provider("bench_group", "workers.task", is_group=True)
    await runner.spawn_provider("bench_group", "workers.task", is_group=True)
    await asyncio.sleep(1)
    # Main process is the Consumer
    cons_client = await runner.get_client()
    chan_cons = await cons_client.open("bench_group")
    
    # Warmup
    for _ in range(20):
        await chan_cons.group("workers").get("task", {"v": 0})
    
    # 1. Latency Benchmark (Sequential)
    print(f"Running Group Latency benchmark ({num_calls//10} calls)...")
    latencies = []
    for i in range(num_calls // 10):
        start = time.perf_counter()
        await chan_cons.group("workers").get("task", {"v": i})
        latencies.append(time.perf_counter() - start)

    latency_stats = calculate_stats(latencies)
    
    # 2. Aggregate Throughput Benchmark (Concurrent)
    print(f"Running Group Throughput benchmark ({num_calls} calls concurrent)...")
    start = time.perf_counter()
    
    batch_size = 500
    for i in range(0, num_calls, batch_size):
        tasks = [chan_cons.group("workers").get("task", {"v": j}) for j in range(i, min(i + batch_size, num_calls))]
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
    results = asyncio.run(run_group_benchmark(num_calls=1000))
    print("\nGroup Results:")
    for k, v in results["latency"].items():
        print(f"{k}: {v:.4f} ms")
    print(f"Throughput: {results['throughput']:.2f} calls/sec")
