import asyncio
import time
from benchmark.utils import BenchmarkRunner, calculate_stats

async def run_pubsub_benchmark(num_msgs=5000, transport_params=None):
    runner = BenchmarkRunner(**(transport_params or {}))
    await runner.start_server()
    
    # Spawn Subscriber in separate process
    results_queue = await runner.spawn_subscriber("bench_ps", num_msgs)
    
    # Publisher Client in main process
    pub_client = await runner.get_client()
    chan_pub = await pub_client.open("bench_ps")
    await chan_pub.add_subscription("topic")
    
    # Warmup
    for _ in range(20):
        await chan_pub.publish("topic", {"val": "warmup"})
    
    print(f"Running PubSub Latency benchmark ({num_msgs} messages)...")
    for _ in range(num_msgs):
        await chan_pub.publish("topic", {"t": time.perf_counter()})
        # Micro-sleep to avoid overwhelming the socket buffer synchronously,
        # ensuring the server process gets a chance to broadcast.
        if num_msgs > 1000 and _ % 100 == 0:
            await asyncio.sleep(0) 

    # Wait for subscriber process to finish and return results
    latencies = []
    try:
        # Wait for the latencies list from the results_queue
        # The subscriber process puts the list there once it has num_msgs
        start_wait = time.perf_counter()
        while len(latencies) == 0 and time.perf_counter() - start_wait < 30:
            if not results_queue.empty():
                latencies = results_queue.get()
            else:
                await asyncio.sleep(0.1)
    except Exception as e:
        print(f"Error collecting results: {e}")

    stats = calculate_stats(latencies)
    
    await pub_client.close()
    await runner.stop_all()

    return stats

if __name__ == "__main__":
    results = asyncio.run(run_pubsub_benchmark(num_msgs=1000))
    print("\nPubSub Results:")
    for k, v in results.items():
        print(f"{k}: {v:.4f} ms")
