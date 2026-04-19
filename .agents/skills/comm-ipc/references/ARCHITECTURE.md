# CommIPC Architecture

The following diagrams illustrate the core architectural topologies possible with CommIPC. Agents should use these to understand the networking layer before writing complex routing logic.

## 1. Hub-and-Spoke (Standard Topology)

```mermaid
graph TD
    S(CommIPCServer Hub)
    C1(Provider Client 1)
    C2(Provider Client 2)
    C3(Consumer Client)
    
    C1 <-->|Unix/TCP| S
    C2 <-->|Unix/TCP| S
    C3 <-->|Unix/TCP| S

    classDef server fill:#f9f,stroke:#333,stroke-width:2px;
    class S server;
```
*Note: Clients never speak directly to each other. The server routes all messages using `sender_id` and `target_id` (or broadcasts).*

## 2. Load-Balanced Event Groups

```mermaid
graph TD
    S(CommIPCServer)
    C1[Group A: Provider]
    C2[Group A: Provider]
    C3(Consumer)
    
    C1 <--> S
    C2 <--> S
    C3 -.->|Call 'event'| S
    
    subgraph Event Group Handling
        S -.->|Least-Active Route| C1
    end
```
*Note: If multiple providers register to the same group event, the server automatically distributes the load.*

## 3. Bridge Federation (Multi-Hub)

```mermaid
graph LR
    H1(Hub 1 - Linux Desktop)
    H2(Hub 2 - Cloud Gateway)
    B((CommIPCBridge))
    
    C1(Local GUI) <--> H1
    C2(Cloud Service) <--> H2
    
    H1 <--> B
    B <--> H2
```
*Note: The `CommIPCBridge` acts as a transparent proxy. `C1` can call `C2` exactly as if they were on the same local server.*

## 4. FastAPI Gateway Topology

```mermaid
graph TD
    Browser(Web Browser / App)
    API(FastAPI + CommAPI Gateway)
    S(CommIPC Server)
    IPC(Internal IPC Service)
    
    Browser <-->|HTTP REST / SSE| API
    API <-->|CommIPC Protocol| S
    S <--> IPC
```
*Note: The Gateway transparently translates HTTP/JSON into type-safe CommData models, routing them to the internal IPC mesh.*
