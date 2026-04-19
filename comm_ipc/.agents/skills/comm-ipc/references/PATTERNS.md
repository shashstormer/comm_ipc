# CommIPC Architectural Patterns

CommIPC is highly flexible. Because it natively supports RPC, Pub/Sub, load-balanced groups, and high-performance routing, it can be used to implement almost any modern distributed systems architecture.

This document serves as a guide for implementing 14 common architectural patterns using CommIPC primitives.

---

## 1. Scatter-Gather
A central client broadcasts a task to multiple workers. The workers process the task in parallel and return the results to the client.

**CommIPC Implementation**:
The client publishes an event to a topic including an `aggregation_id`. Multiple workers subscribe to the topic, do the work, and send their results back via a designated RPC channel using the `aggregation_id`. The client waits for a specific aggregation timing window to gather the responses.

```mermaid
graph TD
    Client["Client (Aggregator)"] -- "publish('task', {id: 123})" --> Hub
    Hub -- "Topic: 'task'" --> WorkerA
    Hub -- "Topic: 'task'" --> WorkerB
    WorkerA -- "event('result', {id: 123, res: ...})" --> Hub
    WorkerB -- "event('result', {id: 123, res: ...})" --> Hub
    Hub --> Client
```

**Snippet**:
```python
# Client Side
results = []
AGGREGATION_WINDOW_SECS = 2.0

async def gather_results(cd: CommData):
    # Only accept responses that match our aggregation ID
    if cd.data["agg_id"] == current_agg_id:
        results.append(cd.data["result"])

@app.provide("submit_result")
async def _(cd: CommData): await gather_results(cd)

# Trigger and wait
await channel.publish("task_topic", {"agg_id": "job-1", "work": "..."})
# Wait for the aggregation window to close
await asyncio.sleep(AGGREGATION_WINDOW_SECS) 
print(f"Gathered {len(results)} responses.")
```

---

## 2. Request-Response
A standard synchronous (from the caller's perspective) remote procedure call.

**CommIPC Implementation**:
Native RPC using `@app.provide` and `channel.event`.

```mermaid
sequenceDiagram
    Client->>Hub: event("calculate", data)
    Hub->>Provider: CommData (Request)
    Provider-->>Hub: CommData (Response)
    Hub-->>Client: Result
```

---

## 3. Publish-Subscribe (Pub/Sub)
One-to-many communication where publishers emit events without knowing who the subscribers are.

**CommIPC Implementation**:
Native pub/sub using `@app.subscription` and `channel.publish`.

```mermaid
graph LR
    Publisher -- "publish('news')" --> Hub
    Hub -- "Topic: 'news'" --> Sub1
    Hub -- "Topic: 'news'" --> Sub2
```

---

## 4. Event Sourcing
State is determined by a sequence of events rather than saving current state in a database table. 

**CommIPC Implementation**:
All microservices publish state-change events. A dedicated "EventStore" service subscribes to these events and appends them to a log/database. Other services subscribe to reconstruct materialized views.

```mermaid
graph TD
    ServiceA["Order Service"] -- "publish('order_created')" --> Hub
    ServiceB["Payment Service"] -- "publish('payment_done')" --> Hub
    Hub -- "Topic: '*'" --> EventStore["Event Store DB (Append Only)"]
    Hub -- "Topic: '*'" --> ViewBuilder["Materialized View Builder"]
```

---

## 5. Command Query Responsibility Segregation (CQRS)
Separating the data mutation operations (Commands) from data retrieval operations (Queries).

**CommIPC Implementation**:
Use distinct channels or event prefixes. `write_channel` handles all mutations. `read_channel` handles all queries and can be heavily load-balanced using `@app.group`.

```mermaid
graph LR
    Client -- "event('create_user')" --> WriteService
    Client -- "event('get_user')" --> Hub
    Hub -- "Group: Readers" --> ReadServiceA
    Hub -- "Group: Readers" --> ReadServiceB
```

---

## 6. Pipe and Filter
Data flows through a sequence of processing components (filters).

**CommIPC Implementation**:
Daisy-chaining CommIPC streams or pub/sub topics. 

```mermaid
graph LR
    Source -- "publish('raw_data')" --> FilterA
    FilterA -- "publish('clean_data')" --> FilterB
    FilterB -- "publish('final_data')" --> Sink
```

---

## 7. Saga Pattern
Managing distributed transactions across multiple microservices without 2-phase commit.

**CommIPC Implementation (Orchestration)**:
A central coordinator client makes sequential `channel.event` RPC calls. If a step fails, the coordinator catches the exception and issues compensation RPC calls (`rollback_payment`).

```mermaid
sequenceDiagram
    participant Orchestrator
    participant Inventory
    participant Payment
    Orchestrator->>Inventory: event("reserve_item")
    Orchestrator->>Payment: event("charge_card")
    Payment-->>Orchestrator: Error (Declined)
    Orchestrator->>Inventory: event("cancel_reservation")
```

---

## 8. Leader-Follower
Work is delegated to a cluster of workers, often with one leader managing state.

**CommIPC Implementation**:
CommIPC natively handles the "Follower" delegation via `@app.group("workers")`. Because the Hub defaults to `lb_policy="least-active"`, the Hub automatically acts as the implicit leader, routing work to the least busy follower.

```mermaid
graph TD
    Client -- "event('workers.task')" --> Hub
    Hub -- "Least Active" --> WorkerC
    Hub -.-> WorkerA
    Hub -.-> WorkerB
```

---

## 9. Sidecar Pattern
Deploying helper components alongside an application to provide networking or monitoring capabilities.

**CommIPC Implementation**:
Deploy a lightweight CommIPC Python script as a sidecar container in a Kubernetes pod. A legacy application (written in C++ or Go) talks to the Python sidecar via local HTTP/TCP, and the Python sidecar bridges the traffic to the CommIPC Hub.

---

## 10. Ambassador Pattern
An out-of-process proxy that handles network routing and retries on behalf of a client.

**CommIPC Implementation**:
Use `CommIPCBridge` deployed locally on a machine. Local microservices connect to the bridge via `/tmp/local.sock`, and the Bridge handles the complex TLS connection over the internet to the remote central Hub.

---

## 11. Bulkhead Pattern
Isolating components into pools so that if one fails, the others continue to function.

**CommIPC Implementation**:
Run multiple independent `CommIPCServer` instances on different sockets/ports. Connect critical services to `critical.sock` and background jobs to `background.sock`. If the background server crashes from memory exhaustion, the critical server is unaffected.

---

## 12. Circuit Breaker
Preventing a client from continuously attempting an operation that's likely to fail.

**CommIPC Implementation**:
Wrap `channel.event` calls in the client with timeout and failure thresholds. If X timeouts occur, the client stops sending RPCs and returns a cached/fallback response immediately.

```python
try:
    res = await asyncio.wait_for(channel.event("flakey_service", data), timeout=2.0)
except asyncio.TimeoutError:
    circuit_breaker.record_failure()
    return fallback_data()
```

---

## 13. Backend for Frontend (BFF)
Creating specific backend services tailored for specific frontend interfaces (e.g., Mobile vs Web).

**CommIPC Implementation**:
Use the `CommAPI` FastAPI bridge. A mobile frontend makes a single REST request to `/api/mobile/dashboard`. The FastAPI BFF concurrently fires 5 different `comm_ipc` RPC calls to microservices, aggregates the `CommData`, and returns a single JSON blob to the phone.

---

## 14. Strangler Fig Pattern
Incrementally migrating a legacy system by gradually replacing specific pieces of functionality.

**CommIPC Implementation**:
Place the `CommAPI` FastAPI gateway in front of the legacy API. As you rewrite legacy endpoints into CommIPC microservices, you mount them in the gateway using `comm_api.add_event()`. The gateway intercepts the modernized routes and proxies the rest to the legacy monolith.

```mermaid
graph TD
    Traffic["Client Traffic"] --> Gateway["CommAPI Gateway"]
    Gateway -- "Modern Route" --> CommIPC["CommIPC Mesh"]
    Gateway -- "Legacy Route" --> Monolith["Old Monolith API"]
```
