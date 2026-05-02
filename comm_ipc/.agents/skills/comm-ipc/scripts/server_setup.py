"""
CommIPC Server Setup Skill

This skill demonstrates how to configure, start, and cleanly shut down a CommIPCServer.
It covers typical options like load balancing policies, connection secrets, and system passwords.
"""

import asyncio
from typing import Optional, Dict

# Assumes comm_ipc is installed or available in the path
try:
    from comm_ipc.server import CommIPCServer
except ImportError:
    pass


async def create_and_run_server(
    socket_path: str = "/tmp/comm_ipc.sock",
    host: Optional[str] = None,
    port: Optional[int] = None,
    connection_secret: Optional[str] = None,
    system_passwords: Optional[Dict[str, str]] = None,
) -> CommIPCServer:
    """
    Creates and starts a CommIPCServer.

    Args:
        socket_path (str): The local unix domain socket path to listen on (default /tmp/comm_ipc.sock)
        host (str, optional): The host IP to bind to for TCP connections (e.g., '127.0.0.1').
        port (int, optional): The port to bind to for TCP connections.
        connection_secret (str, optional): A secret used to verify clients during handshake.
        system_passwords (dict, optional): A dict of {channel_name: password} to enforce access control.

    Returns:
        CommIPCServer: The running server instance.
    """
    # 1. Initialize the server with various policies
    server = CommIPCServer(
        server_id="main_server",           # Unique ID for routing
        socket_path=socket_path,           # Default Unix socket path
        error_policy="broadcast",          # Broadcast errors to the channel instead of raising (Default is "ignore")
        channel_policy="terminate",        # If the channel owner disconnects, terminate the channel (This is the default)
        lb_policy="least-active",          # Group load balancing policy (Default is "least-active")
        connection_secret=connection_secret, # Security handshake secret
        system_passwords=system_passwords,   # Predefined channel passwords
        verbose=True                       # Enable verbose logging
    )

    # 2. Start the server (non-blocking)
    # The run() method acts as the main task that keeps the server alive
    print(f"Starting CommIPC server...")
    if host and port:
        print(f"Listening on TCP {host}:{port} and Socket {socket_path}")
    else:
        print(f"Listening on Socket {socket_path}")
        
    await server.run(host=host, port=port)
    
    return server


async def demo_server_lifecycle():
    """Demonstrates starting and then gracefully stopping the server."""
    # Initialize the server
    server = CommIPCServer(
        server_id="demo_server",
        socket_path="/tmp/comm_ipc_demo.sock",
        verbose=True
    )
    
    # Run the server in a background task so it doesn't block
    print("Starting server in the background...")
    server_task = asyncio.create_task(server.run())
    
    # Wait for the server to spin up
    await asyncio.sleep(0.5)
    print("Server is running.")
    
    # Keep the server running for a while
    await asyncio.sleep(2)
    
    # Gracefully stop the server
    print("Shutting down server...")
    await server.stop()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
    print("Server stopped.")


if __name__ == "__main__":
    # To run this standalone
    asyncio.run(demo_server_lifecycle())
