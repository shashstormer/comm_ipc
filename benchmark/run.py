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
    
    transports = [
        ("Unix Domain Sockets (UDS)", {}),
        ("TCP (Localhost)", {"host": "127.0.0.1", "port": 9999})
    ]
    
    results = {}

    for name, params in transports:
        print(f"\n--- Testing Transport: {name} ---")
        
        # 1. RPC
        rpc_res = await run_rpc_benchmark(num_calls=1000, transport_params=params)
        
        # 2. PubSub
        ps_res = await run_pubsub_benchmark(num_msgs=500, transport_params=params)
        
        # 3. Stream
        st_res = await run_stream_benchmark(num_chunks=1000, transport_params=params)

        # 4. Group (Load Balanced)
        grp_res = await run_group_benchmark(num_calls=1000, transport_params=params)
        
        results[name] = {
            "rpc": rpc_res,
            "pubsub": ps_res,
            "stream": st_res,
            "group": grp_res
        }

    print("\n## CommIPC Benchmark Results Comparison\n")
    print("| Metric                     | Transport | Mean     | Median   | P95      | P99      |")
    print("|----------------------------|-----------|----------|----------|----------|----------|")
    
    for name in results:
        r_lat = results[name]["rpc"]["latency"]
        print(f"| RPC Latency (RTT)          | {name[:3]:<9} | {r_lat['mean']:>7.2f}ms | {r_lat['median']:>7.2f}ms | {r_lat['p95']:>7.2f}ms | {r_lat['p99']:>7.2f}ms |")
        
    print("|                            |           |          |          |          |          |")

    for name in results:
        g_lat = results[name]["group"]["latency"]
        print(f"| Group Latency (LB RTT)     | {name[:3]:<9} | {g_lat['mean']:>7.2f}ms | {g_lat['median']:>7.2f}ms | {g_lat['p95']:>7.2f}ms | {g_lat['p99']:>7.2f}ms |")

    print("|                            |           |          |          |          |          |")

    for name in results:
        ps_lat = results[name]["pubsub"]
        if "mean" in ps_lat:
            print(f"| PubSub Latency (Relay)     | {name[:3]:<9} | {ps_lat['mean']:>7.2f}ms | {ps_lat['median']:>7.2f}ms | {ps_lat['p95']:>7.2f}ms | {ps_lat['p99']:>7.2f}ms |")
        else:
            print(f"| PubSub Latency (Relay)     | {name[:3]:<9} |      N/A |      N/A |      N/A |      N/A |")
    
    print("\n| Throughput Metric          | Transport | Result                 |")
    print("|----------------------------|-----------|------------------------|")
    for name in results:
        print(f"| RPC Throughput             | {name[:3]:<9} | {results[name]['rpc']['throughput']:>8.1f} calls/sec  |")
    for name in results:
        print(f"| Group Throughput (LB)      | {name[:3]:<9} | {results[name]['group']['throughput']:>8.1f} calls/sec  |")
    for name in results:
        print(f"| Streaming Throughput       | {name[:3]:<9} | {results[name]['stream']['throughput']:>8.1f} chunks/sec |")
    
    print("\n*Benchmarks performed locally. UDS is expected to be faster than TCP.*")

if __name__ == "__main__":
    asyncio.run(main())
