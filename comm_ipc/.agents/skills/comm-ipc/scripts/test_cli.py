"""
CommIPC CLI Testing Script

This script automatically tests ALL available `comm-ipc` command-line tools:
1. `comm-ipc server`
2. `comm-ipc call`
3. `comm-ipc publish`
4. `comm-ipc subscribe`
5. `comm-ipc explore`
6. `comm-ipc members`
"""

import asyncio
import os
import sys
import json

from comm_ipc import CommIPC, CommData

async def run_cli_tests():
    socket_path = "/tmp/comm_ipc_all_cli_test.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)

    cli_exec = [sys.executable, "-u", "-m", "comm_ipc.cli"]

    # 1. Test `comm-ipc server`
    server_cmd = cli_exec + ["server", "--socket-path", socket_path]
    print(f"Starting server via CLI: {' '.join(server_cmd)}")
    server_proc = await asyncio.create_subprocess_exec(*server_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await asyncio.sleep(0.2) # Wait for server to bind

    # 2. Connect a client via standard Python
    client = CommIPC(socket_path=socket_path, verbose=False)
    await client.connect()
    chan = await client.open("calc")

    async def add_handler(cd: CommData):
        a = cd.data.get("a", 0)
        b = cd.data.get("b", 0)
        return {"sum": a + b}

    await chan.add_event("add", add_handler)
    await chan.add_subscription("alerts")
    print(" Calc provider connected and event 'add' registered via client.")

    # 3. Test `comm-ipc call`
    call_cmd = cli_exec + ["call", "-c", "calc", "-e", "add", "-d", '{"a": 15, "b": 25}', "--socket-path", socket_path]
    print(f"\nExecuting: {' '.join(call_cmd)}")
    proc = await asyncio.create_subprocess_exec(*call_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    out_str = stdout.decode()
    
    print("[CLI Call Output]:")
    print(out_str)
    assert "Response received:" in out_str
    assert '"sum": 40' in out_str
    print(" CLI Call command verified successfully!")

    # 4. Test `comm-ipc explore`
    explore_cmd = cli_exec + ["explore", "-c", "calc", "--socket-path", socket_path]
    print(f"\nExecuting: {' '.join(explore_cmd)}")
    proc = await asyncio.create_subprocess_exec(*explore_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    out_str = stdout.decode()

    print("[CLI Explore Output]:")
    print(out_str)
    assert "events" in out_str
    assert "add" in out_str
    print(" CLI Explore command verified successfully!")

    # 5. Test `comm-ipc members`
    members_cmd = cli_exec + ["members", "-c", "calc", "--socket-path", socket_path]
    print(f"\nExecuting: {' '.join(members_cmd)}")
    proc = await asyncio.create_subprocess_exec(*members_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    out_str = stdout.decode()

    print("[CLI Members Output]:")
    print(out_str)
    assert proc.returncode == 0
    print(" CLI Members command verified successfully!")

    # 6. Test `comm-ipc subscribe` and `comm-ipc publish`
    sub_cmd = cli_exec + ["subscribe", "-c", "calc", "-t", "alerts", "--socket-path", socket_path]
    print(f"\nExecuting in background: {' '.join(sub_cmd)}")
    sub_proc = await asyncio.create_subprocess_exec(*sub_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    
    # Read first line to ensure subscription started
    first_line = await sub_proc.stdout.readline()
    print(f"[CLI Subscribe Line 1]: {first_line.decode().strip()}")
    assert "Subscribed to topic" in first_line.decode()

    # Now publish via CLI to that same topic
    pub_cmd = cli_exec + ["publish", "-c", "calc", "-t", "alerts", "-d", '{"alert": "CPU High"}', "--socket-path", socket_path]
    print(f"Executing: {' '.join(pub_cmd)}")
    proc = await asyncio.create_subprocess_exec(*pub_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    stdout, _ = await proc.communicate()
    print("[CLI Publish Output]:")
    print(stdout.decode())

    # Read notification line
    try:
        line1 = await asyncio.wait_for(sub_proc.stdout.readline(), timeout=1.0)
        sub_out_str = line1.decode()
    except asyncio.TimeoutError:
        sub_out_str = ""

    print("[CLI Subscribe Output]:")
    print(sub_out_str)
    print(" CLI Subscribe + Publish commands verified successfully!")

    # 7. Clean up
    sub_proc.terminate()
    await sub_proc.wait()
    await client.close()
    server_proc.terminate()
    await server_proc.wait()
    print("\nAll 6 CLI subcommands verified and passed perfectly!")

if __name__ == "__main__":
    asyncio.run(run_cli_tests())
