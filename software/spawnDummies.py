import asyncio
import random
from aiomqtt import Client

BROKER = "localhost"
PORT = 1883
N_CLIENTS = 200
SENSORS = ["sensorA", "sensorB", "sensorC"]
PUBLISH_INTERVAL = 1.0


async def dummy_worker(client_id: str):
    await asyncio.sleep(random.uniform(0.0, 2.0))

    try:
        async with Client(hostname=BROKER, port=PORT, identifier=client_id) as client:
            while True:
                for sensor in SENSORS:
                    topic = f"{client_id}/{sensor}"  # e.g., dummy1/sensorA
                    val = random.randint(1, 100)
                    await client.publish(topic, payload=val)

                await asyncio.sleep(PUBLISH_INTERVAL)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[{client_id}] Error: {e}")


async def main():
    print(f"Spawning {N_CLIENTS} async dummy clients...")
    tasks = [
        asyncio.create_task(dummy_worker(f"dummy{i}"))
        for i in range(1, N_CLIENTS + 1)
    ]
    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass