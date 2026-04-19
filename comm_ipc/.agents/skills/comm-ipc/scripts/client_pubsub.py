"""
CommIPC Client Publisher/Subscriber Skill

This skill demonstrates how to implement a Pub/Sub pattern using CommIPC.
It shows schema declaration, subscribing to events, and publishing data.
"""

import asyncio
from pydantic import BaseModel

try:
    from comm_ipc import CommIPC, CommData
except ImportError:
    pass

class User(BaseModel):
    id: int
    name: str

async def run_pubsub_demo():
    """
    Demonstrates setting up a subscriber and a publisher.
    """
    client = CommIPC(return_type="model", verbose=True)
    await client.connect()
    
    # 1. Open the channel
    channel = await client.open("social")

    # 2. Define the Subscriber Callback
    async def on_user_join(cd: CommData):
        # Because we'll declare the schema later, cd.data is automatically validated
        user: User = cd.data
        print(f"[Subscriber] Notification: User {user.name} (ID: {user.id}) joined!")

    # 3. Subscribe to the topic
    await channel.subscribe("join_events", on_user_join)
    print("Subscribed to 'join_events'.")

    # 4. Declare the Subscription Schema
    # This must be done at least once by any client before publishing to register the schema with the server
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

if __name__ == "__main__":
    # Note: A server must be running at /tmp/comm_ipc.sock for this to work
    asyncio.run(run_pubsub_demo())
