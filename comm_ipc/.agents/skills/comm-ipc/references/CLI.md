# CommIPC CLI Reference

The `comm-ipc` command-line interface provides a convenient set of subcommands to start an IPC server, invoke RPC events, publish and subscribe to topics, and explore active channel schemas and members directly from the terminal.

## Installation
The CLI is installed as an entry point script with the `comm-ipc` package:
```bash
# Example if installed via pip / poetry
comm-ipc --help
```

---

## Commands

### 1. `server`
Starts a local or network-reachable `CommIPCServer`.

**Usage**:
```bash
comm-ipc server [flags]
```

**Flags**:
- `--socket-path`: Unix domain socket path to listen on (Default: Uses system default `/tmp/comm_ipc.sock`).
- `--host`: Host IP address to bind to for TCP network connections.
- `--port`: Port number to bind to for TCP network connections.
- `--connection-secret`: Secret key used for authenticating client handshakes.
- `--verbose`: Boolean flag to print out detailed log output of messaging frames.

**Example**:
```bash
comm-ipc server --socket-path /tmp/test.sock --verbose
```

---

### 2. `call`
Invokes a standard or streaming RPC event synchronously on a registered IPC provider channel and returns the JSON output.

**Usage**:
```bash
comm-ipc call -c <channel> -e <event> [flags]
```

**Arguments and Flags**:
- `-c`, `--channel`: **Required.** Name of the target IPC channel.
- `-e`, `--event`: **Required.** Name of the specific event to call.
- `-d`, `--data`: JSON string or raw text data payload to send to the event handler.
- `--socket-path`: Path to the local server's Unix domain socket.
- `--host`: Host IP of the server for TCP network connections.
- `--port`: Port of the server for TCP network connections.
- `--connection-secret`: Authentication secret.
- `--verbose`: Prints detailed call lifecycle logs.

**Example**:
```bash
comm-ipc call -c math -e add -d '{"a": 5, "b": 12}'
```

---

### 3. `publish`
Publishes a data message to a 1-to-many topic on a specific IPC channel.

**Usage**:
```bash
comm-ipc publish -c <channel> -t <topic> [flags]
```

**Arguments and Flags**:
- `-c`, `--channel`: **Required.** Name of the target IPC channel.
- `-t`, `--topic`: **Required.** Name of the subscription topic.
- `-d`, `--data`: JSON data string payload to publish.
- `--socket-path`: Path to the Unix domain socket.
- `--host`: Server IP for TCP network connection.
- `--port`: Server port for TCP network connection.
- `--connection-secret`: Authentication secret.

**Example**:
```bash
comm-ipc publish -c inventory -t restock -d '{"item_id": "SKU-992", "qty": 50}'
```

---

### 4. `subscribe`
Subscribes to a specific 1-to-many topic on an IPC channel and streams published items to standard output.

**Usage**:
```bash
comm-ipc subscribe -c <channel> -t <topic> [flags]
```

**Arguments and Flags**:
- `-c`, `--channel`: **Required.** Name of the target IPC channel.
- `-t`, `--topic`: **Required.** Name of the subscription topic.
- `--socket-path`: Path to the Unix domain socket.
- `--host`: Server IP for TCP network connection.
- `--port`: Server port for TCP network connection.
- `--connection-secret`: Authentication secret.

**Example**:
```bash
comm-ipc subscribe -c inventory -t restock
```

---

### 5. `explore`
Fetches and displays the JSON schema, events, and subscription capabilities of an active IPC channel.

**Usage**:
```bash
comm-ipc explore -c <channel> [flags]
```

**Arguments and Flags**:
- `-c`, `--channel`: **Required.** Name of the channel to inspect.
- `--socket-path`: Path to the Unix domain socket.
- `--host`: Server IP for TCP network connection.
- `--port`: Server port for TCP network connection.
- `--connection-secret`: Authentication secret.

**Example**:
```bash
comm-ipc explore -c math
```

---

### 6. `members`
Fetches and lists all active client or provider node members joined to a given IPC channel.

**Usage**:
```bash
comm-ipc members -c <channel> [flags]
```

**Arguments and Flags**:
- `-c`, `--channel`: **Required.** Name of the channel to query.
- `--socket-path`: Path to the Unix domain socket.
- `--host`: Server IP for TCP network connection.
- `--port`: Server port for TCP network connection.
- `--connection-secret`: Authentication secret.

**Example**:
```bash
comm-ipc members -c math
```
