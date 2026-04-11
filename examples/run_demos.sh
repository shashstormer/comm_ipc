#!/bin/bash

# Configuration
export PYTHONPATH=.
SOCKET_PATH="/tmp/comm_ipc_demo.sock"

# Cleanup function
cleanup() {
    echo "Cleaning up..."
    # Kill all background python processes started by this script
    pkill -P $$ python
    [ -e "$SOCKET_PATH" ] && rm "$SOCKET_PATH"
    [ -e "/tmp/comm_ipc_decoupled.sock" ] && rm "/tmp/comm_ipc_decoupled.sock"
}

# Trap exit/interrupt
trap cleanup EXIT

echo "=== CommIPC Bash Integration Suite ==="

# 1. Start Server
echo "Starting Server..."
python examples/server.py > /dev/null 2>&1 &
SERVER_PID=$!

# Wait for socket
COUNT=0
while [ ! -S "$SOCKET_PATH" ] && [ $COUNT -lt 20 ]; do
    sleep 0.5
    ((COUNT++))
done

if [ ! -S "$SOCKET_PATH" ]; then
    echo "ERROR: Server failed to start."
    exit 1
fi

run_test() {
    local name=$1
    local prov=$2
    local client=$3
    
    echo -e "\n>>> Testing $name..."
    echo "  Starting Provider: $prov"
    python "$prov" > /dev/null 2>&1 &
    local PROV_PID=$!
    sleep 2
    
    echo "  Running Client: $client"
    python "$client"
    local EXIT_CODE=$?
    
    echo "  Stopping Provider..."
    kill $PROV_PID
    wait $PROV_PID 2>/dev/null
    
    if [ $EXIT_CODE -ne 0 ]; then
        echo "❌ $name FAILED"
        return 1
    fi
    echo "✅ $name PASSED"
    return 0
}

# Run Demos
FAILED=0

run_test "Standard RPC" "examples/rpc_prov.py" "examples/rpc_client.py" || FAILED=1
run_test "PubSub" "examples/pub_prov.py" "examples/sub_client.py" || FAILED=1
run_test "Streaming" "examples/stream_prov.py" "examples/stream_client.py" || FAILED=1
run_test "Decorator" "examples/decorator_prov.py" "examples/decorator_client.py" || FAILED=1

echo -e "\n>>> Testing Decoupled App Demo..."
python examples/decoupled_demo.py
if [ $? -eq 0 ]; then
    echo "✅ Decoupled App PASSED"
else
    echo "❌ Decoupled App FAILED"
    FAILED=1
fi

echo -e "\n>>> Testing FastAPI Integration..."
python examples/fastapi_integration.py
if [ $? -eq 0 ]; then
    echo "✅ FastAPI Integration PASSED"
else
    echo "❌ FastAPI Integration FAILED"
    FAILED=1
fi

if [ $FAILED -eq 0 ]; then
    echo -e "\n🎉 ALL DEMOS PASSED SUCCESSFULLY!"
else
    echo -e "\n⛔ SOME DEMOS FAILED."
    exit 1
fi
