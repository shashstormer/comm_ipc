import asyncio
import time
from benchmark.utils import BenchmarkRunner, calculate_stats


async def run_pubsub_benchmark(num_msgs=1000):
    runner = BenchmarkRunner()
    await runner.start_server()

    # Subscriber Client
    sub_client = await runner.get_client()
    chan_sub = await sub_client.open("bench_pubsub")

    delays = []
    received_event = asyncio.Event()

    async def sub_handler(cd):
        sent_time = cd.data["t"]
        delays.append(time.perf_counter() - sent_time)
        if len(delays) >= num_msgs:
            received_event.set()

    await chan_sub.subscribe("topic", sub_handler)

    # Publisher Client
    pub_client = await runner.get_client()
    chan_pub = await pub_client.open("bench_pubsub")
    await chan_pub.add_subscription("topic", model=None)

    # Warmup
    for _ in range(10):
        await chan_pub.publish("topic", {"t": time.perf_counter()})
        await asyncio.sleep(0.01)
    delays.clear()

    print(f"Running PubSub Latency benchmark ({num_msgs} messages)...")
    for _ in range(num_msgs):
        await chan_pub.publish("topic", {"t": time.perf_counter()})
        await asyncio.sleep(0) # Yield to subscriber loop

    try:
        await asyncio.wait_for(received_event.wait(), timeout=10)
    except asyncio.TimeoutError:
        print(f"PubSub benchmark timed out! Received {len(delays)}/{num_msgs}")

    stats = calculate_stats(delays)

    await sub_client.close()
    await pub_client.close()
    await runner.stop_server()

    return stats


if __name__ == "__main__":
    results = asyncio.run(run_pubsub_benchmark())
    print("\nPubSub Results:")
    for k, v in results.items():
        print(f"{k}: {v:.4f} ms")
