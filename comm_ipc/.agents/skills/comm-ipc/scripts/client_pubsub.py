import asyncio
from pydantic import BaseModel
import os
from comm_ipc import CommIPC, CommData
from comm_ipc.server import CommIPCServer

class User(BaseModel):
    id: int
    name: str

async def run_pubsub_demo():
    """
    Spins up a server in the background, connects a client, and sets up pub/sub.
    """
    socket_path = "/tmp/comm_ipc_pubsub.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)
        
    server = CommIPCServer(socket_path=socket_path)
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1) # Wait for server
    
    client = CommIPC(socket_path=socket_path, return_type="model", verbose=False)
    await client.connect()
    
    # 1. Open the channel
    channel = await client.open("social")

    # 2. Define the Subscriber Callback
    async def on_user_join(cd: CommData):
        user: User = cd.data
        print(f"[Subscriber] Notification: User {user.name} (ID: {user.id}) joined!")

    # 3. Subscribe to the topic
    await channel.subscribe("join_events", on_user_join)
    print("Subscribed to 'join_events'.")

    # 4. Declare the Subscription Schema
    await channel.add_subscription("join_events", model=User)

    # 5. Publish to the topic
    print("Publishing to 'join_events'...")
    await channel.publish("join_events", User(id=1, name="Alice"))
    await channel.publish("join_events", User(id=2, name="Bob"))
    
    # Wait a bit for the async messages to arrive and be processed
    await asyncio.sleep(0.5)
    
    # 6. Clean up
    await channel.unsubscribe("join_events")
    await client.close()
    await server.stop()
    print("Pub/Sub Demo completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_pubsub_demo())
