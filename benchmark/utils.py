import asyncio
import os
import time
import statistics
import uuid
import multiprocessing
import msgpack
import struct
from comm_ipc.server import CommIPCServer
from comm_ipc.client import CommIPC

try:
    import uvloop
except ImportError:
    uvloop = None

def _run_server_proc(socket_path, verbose=False):
    """Entry point for the server process."""
    if uvloop:
        uvloop.install()
    server = CommIPCServer(verbose=verbose)
    asyncio.run(server.run(socket_path=socket_path))

def _run_provider_proc(socket_path, channel_name, event_name, ready_event, is_group=False):
    """Simple echo provider in its own process."""
    if uvloop:
        uvloop.install()

    async def run():
        try:
            client = CommIPC(socket_path=socket_path, verbose=False)
            await client.connect()
            chan = await client.open(channel_name)

            async def echo_handler(cd):
                return cd.data

            await chan.add_event(event_name, echo_handler, is_group=is_group)
            ready_event.set()
            await client.wait_till_end()
        except Exception as e:
            print(f"Provider Error: {e}")
            import traceback
            traceback.print_exc()

    asyncio.run(run())

def _run_subscriber_proc(socket_path, channel_name, results_queue, num_msgs, ready_event):
    """Subscriber that collects timestamps and pushes to a queue."""
    if uvloop:
        uvloop.install()

    async def run():
        client = CommIPC(socket_path=socket_path, verbose=False)
        await client.connect()
        chan = await client.open(channel_name)
        
        latencies = []
        received_count = 0
        done_event = asyncio.Event()

        async def sub_handler(cd):
            nonlocal received_count
            received_count += 1
            sent_time = cd.data.get("t")
            if sent_time:
                latencies.append(time.perf_counter() - sent_time)
            
            if received_count >= num_msgs:
                done_event.set()

        await chan.subscribe("topic", sub_handler)
        ready_event.set()
        
        try:
            await asyncio.wait_for(done_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
            
        results_queue.put(latencies)
        await client.close()

    asyncio.run(run())

class BenchmarkRunner:
    def __init__(self, socket_path=None):
        self.socket_path = socket_path or f"/tmp/bench_{uuid.uuid4().hex[:8]}.sock"
        self.server_proc = None
        self.child_procs = []

    async def start_server(self, verbose=False):
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        
        self.server_proc = multiprocessing.Process(
            target=_run_server_proc, 
            args=(self.socket_path, verbose)
        )
        self.server_proc.start()
        
        count = 0
        while not os.path.exists(self.socket_path) and count < 100:
            await asyncio.sleep(0.1)
            count += 1
            
        if not os.path.exists(self.socket_path):
             raise Exception("Server process failed to create socket in time")

    async def spawn_provider(self, channel, event, is_group=False):
        ready_event = multiprocessing.Event()
        proc = multiprocessing.Process(
            target=_run_provider_proc,
            args=(self.socket_path, channel, event, ready_event, is_group)
        )
        proc.start()
        self.child_procs.append(proc)
        
        # Wait for provider to register
        count = 0
        while not ready_event.is_set() and count < 100:
            await asyncio.sleep(0.1)
            count += 1
            if not proc.is_alive():
                raise Exception(f"Provider process for {channel} died before registration")

        if not ready_event.is_set():
            raise Exception(f"Provider for {channel} failed to register in time")

    async def spawn_subscriber(self, channel, num_msgs):
        queue = multiprocessing.Queue()
        ready_event = multiprocessing.Event()
        proc = multiprocessing.Process(
            target=_run_subscriber_proc,
            args=(self.socket_path, channel, queue, num_msgs, ready_event)
        )
        proc.start()
        self.child_procs.append(proc)
        
        # Wait for subscriber to be ready
        count = 0
        while not ready_event.is_set() and count < 100:
            await asyncio.sleep(0.1)
            count += 1
            
        return queue

    async def stop_all(self):
        for proc in self.child_procs:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)
                if proc.is_alive(): proc.kill()
        self.child_procs = []

        if self.server_proc:
            self.server_proc.terminate()
            self.server_proc.join(timeout=2)
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
        "mean": statistics.mean(latencies) * 1000, 
        "median": statistics.median(latencies) * 1000, 
        "p95": sorted(latencies)[int(len(latencies) * 0.95)] * 1000 if len(latencies) >= 20 else 0,
        "p99": sorted(latencies)[int(len(latencies) * 0.99)] * 1000 if len(latencies) >= 100 else 0,
        "min": min(latencies) * 1000,
        "max": max(latencies) * 1000
    }
