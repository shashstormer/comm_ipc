import asyncio
from benchmark.bench_rpc import run_rpc_benchmark
from benchmark.bench_pubsub import run_pubsub_benchmark
from benchmark.bench_stream import run_stream_benchmark
from benchmark.bench_group import run_group_benchmark

async def main():
    try:
        import uvloop
        uvloop.install()
        print("⚡ Using uvloop for high performance")
    except ImportError:
        pass

    print("🚀 Starting CommIPC Performance Benchmarks...")
    print("-" * 50)
    
    # 1. RPC
    rpc_res = await run_rpc_benchmark(num_calls=1000)
    
    # 2. PubSub
    ps_res = await run_pubsub_benchmark(num_msgs=500)
    
    # 3. Stream
    st_res = await run_stream_benchmark(num_chunks=1000)

    # 4. Group (Load Balanced)
    grp_res = await run_group_benchmark(num_calls=1000)

    print("\n## CommIPC Benchmark Results\n")
    print("| Metric                     | Mean     | Median   | P95      | P99      |")
    print("|----------------------------|----------|----------|----------|----------|")
    
    r_lat = rpc_res["latency"]
    print(f"| RPC Latency (RTT)          | {r_lat['mean']:>7.2f}ms | {r_lat['median']:>7.2f}ms | {r_lat['p95']:>7.2f}ms | {r_lat['p99']:>7.2f}ms |")
    
    g_lat = grp_res["latency"]
    print(f"| Group Latency (LB RTT)     | {g_lat['mean']:>7.2f}ms | {g_lat['median']:>7.2f}ms | {g_lat['p95']:>7.2f}ms | {g_lat['p99']:>7.2f}ms |")

    ps_lat = ps_res
    if "mean" in ps_lat:
        print(f"| PubSub Latency (Relay)     | {ps_lat['mean']:>7.2f}ms | {ps_lat['median']:>7.2f}ms | {ps_lat['p95']:>7.2f}ms | {ps_lat['p99']:>7.2f}ms |")
    else:
        print(f"| PubSub Latency (Relay)     |      N/A |      N/A |      N/A |      N/A |")
    
    print("\n| Throughput Metric          | Result                 |")
    print("|----------------------------|------------------------|")
    print(f"| RPC Throughput             | {rpc_res['throughput']:>8.1f} calls/sec  |")
    print(f"| Group Throughput (LB)      | {grp_res['throughput']:>8.1f} calls/sec  |")
    print(f"| Streaming Throughput       | {st_res['throughput']:>8.1f} chunks/sec |")
    
    print("\n*All benchmarks performed locally using Unix Domain Sockets.*")

if __name__ == "__main__":
    asyncio.run(main())
