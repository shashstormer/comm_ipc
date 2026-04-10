import asyncio
import time
from benchmark.utils import BenchmarkRunner, calculate_stats

async def run_group_benchmark(num_calls=10000):
    runner = BenchmarkRunner()
    await runner.start_server()
    
    # 2 Providers
    async def echo_handler(cd):
        return cd.data

    prov1 = await runner.get_client()
    chan_p1 = await prov1.open("bench_group")
    await chan_p1.group("workers").provide("task", echo_handler)

    prov2 = await runner.get_client()
    chan_p2 = await prov2.open("bench_group")
    await chan_p2.group("workers").provide("task", echo_handler)

    # 2 Consumers
    cons1 = await runner.get_client()
    chan_c1 = await cons1.open("bench_group")

    cons2 = await runner.get_client()
    chan_c2 = await cons2.open("bench_group")
    
    # Warmup
    for _ in range(20):
        await chan_c1.group("workers").get("task", {"v": 0})
    
    # 1. Latency Benchmark (Sequential)
    print(f"Running Group Latency benchmark ({num_calls//2} calls per consumer)...")
    latencies = []
    
    async def worker(chan, count):
        for i in range(count):
            start = time.perf_counter()
            await chan.group("workers").get("task", {"v": i})
            latencies.append(time.perf_counter() - start)

    # We run them sequentially here to measure raw RTT overhead
    await worker(chan_c1, num_calls // 2)
    
    latency_stats = calculate_stats(latencies)
    
    # 2. Aggregate Throughput Benchmark (Concurrent)
    print(f"Running Group Throughput benchmark ({num_calls} total calls, concurrent)...")
    start = time.perf_counter()
    
    # We split the load between two consumers calling concurrently
    tasks1 = [chan_c1.group("workers").get("task", {"v": i}) for i in range(num_calls // 2)]
    tasks2 = [chan_c2.group("workers").get("task", {"v": i}) for i in range(num_calls // 2)]
    
    await asyncio.gather(asyncio.gather(*tasks1), asyncio.gather(*tasks2))
    
    total_time = time.perf_counter() - start
    throughput = num_calls / total_time
    
    # Cleanup
    await prov1.close()
    await prov2.close()
    await cons1.close()
    await cons2.close()
    await runner.stop_server()
    
    return {
        "latency": latency_stats,
        "throughput": throughput
    }

if __name__ == "__main__":
    import asyncio
    results = asyncio.run(run_group_benchmark(num_calls=1000))
    print("\nGroup Results:")
    for k, v in results["latency"].items():
        print(f"{k}: {v:.4f} ms")
    print(f"Throughput: {results['throughput']:.2f} calls/sec")
