import asyncio
import os
import time
import statistics
import uuid
import multiprocessing
from comm_ipc.server import CommIPCServer
from comm_ipc.client import CommIPC

def _run_server_proc(socket_path):
    """Entry point for the server process."""
    server = CommIPCServer(verbose=False)
    asyncio.run(server.run(socket_path=socket_path))

class BenchmarkRunner:
    def __init__(self, socket_path=None):
        self.socket_path = socket_path or f"/tmp/bench_{uuid.uuid4().hex[:8]}.sock"
        self.server_proc = None

    async def start_server(self):
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        
        self.server_proc = multiprocessing.Process(
            target=_run_server_proc, 
            args=(self.socket_path,)
        )
        self.server_proc.start()
        
        # Wait for socket to be ready
        count = 0
        while not os.path.exists(self.socket_path) and count < 100:
            await asyncio.sleep(0.05)
            count += 1
            
        if not os.path.exists(self.socket_path):
             raise Exception("Server process failed to create socket in time")

    async def stop_server(self):
        if self.server_proc:
            self.server_proc.terminate()
            self.server_proc.join(timeout=5)
            if self.server_proc.is_alive():
                self.server_proc.kill()
            self.server_proc = None
            
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass

    async def get_client(self, return_type="dict"):
        client = CommIPC(socket_path=self.socket_path, return_type=return_type, verbose=False)
        await client.connect()
        return client

def calculate_stats(latencies):
    if not latencies:
        return {}
    return {
        "mean": statistics.mean(latencies) * 1000, # ms
        "median": statistics.median(latencies) * 1000, # ms
        "p95": sorted(latencies)[int(len(latencies) * 0.95)] * 1000 if len(latencies) >= 20 else 0,
        "p99": sorted(latencies)[int(len(latencies) * 0.99)] * 1000 if len(latencies) >= 100 else 0,
        "min": min(latencies) * 1000,
        "max": max(latencies) * 1000
    }

def print_table_row(name, stats):
    print(f"| {name:<20} | {stats['mean']:>8.2f}ms | {stats['median']:>8.2f}ms | {stats['p95']:>8.2f}ms | {stats['p99']:>8.2f}ms |")
