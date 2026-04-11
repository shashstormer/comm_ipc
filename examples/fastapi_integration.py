import asyncio
import sys
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from comm_ipc import CommIPC, CommIPCServer, CommAPI, CommIPCApp, CommData

home_app = CommIPCApp()
user_app = CommIPCApp()


class HelloParams(BaseModel):
    name: str


class HelloResponse(BaseModel):
    message: str


class UserProfile(BaseModel):
    user_id: int
    username: str


class TickerParams(BaseModel):
    count: int = 5


@home_app.provide("hello", parameters=HelloParams, returns=HelloResponse)
async def hello_handler(cd: CommData):
    return {"message": f"Hello, {cd.data.name}! This came from IPC."}


@home_app.provide("ticker", parameters=TickerParams)
async def ticker_handler(cd: CommData):
    count = cd.data.count
    for i in range(count):
        await asyncio.sleep(0.1)
        yield {"tick": i}


@user_app.provide("profile", parameters=UserProfile, returns=UserProfile)
async def profile_handler(cd: CommData):
    uid = cd.data.user_id
    return {"user_id": uid, "username": f"user_{uid}_ipc"}


@home_app.provide("ping")
async def ping_handler(cd: CommData):
    return {"status": "pong"}

@user_app.provide("echo")
async def echo_handler(cd: CommData):
    return {"echo": cd.data}



async def run_example():
    server = CommIPCServer(verbose=True)
    server_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)

    backend = CommIPC(client_id="backend_service", verbose=True, return_type="model")
    await backend.connect()

    home_chan = await backend.open("home")
    await home_app.register(home_chan)

    user_chan = await backend.open("user")
    await user_app.register(user_chan)

    app = FastAPI(title="CommIPC Gateway")

    gateway_client = CommIPC(client_id="api_gateway", verbose=True)
    await gateway_client.connect()

    api_home_chan = await gateway_client.open("home")
    api_user_chan = await gateway_client.open("user")

    api = CommAPI(app, gateway_client)

    api.add_resource(api_home_chan, path_template="/{event}")

    api.add_resource(api_user_chan, path_template="/user/{event}", tags=["User Module"])

    print("🚀 FastAPI is ready. Routes added:")
    for route in app.routes:
        if hasattr(route, "path"):
            print(f"  - {route.path}")
    if "--serve" in sys.argv:
        config = uvicorn.Config(app, host="0.0.0.0", port=8000)
        server = uvicorn.Server(config)
        await server.serve()
    else:

        try:
            from httpx import AsyncClient, ASGITransport

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                print("\nTesting /hello endpoint:")
                resp = await ac.post("/hello", json={"name": "World"})
                print(f"Response: {resp.json()}")

                print("\nTesting /user/profile endpoint:")
                resp = await ac.post("/user/profile", json={"user_id": 123, "username": "ignored"})
                print(f"Response: {resp.json()}")

                print("\nTesting /ticker streaming endpoint:")
                async with ac.stream("GET", "/ticker", params={"count": 3}) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            print(f"Stream: {line}")

        except ImportError:
            print("\nhttpx AsyncClient not available, skipping internal test.")

    await gateway_client.close()
    await backend.close()
    await server.close()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(run_example())
