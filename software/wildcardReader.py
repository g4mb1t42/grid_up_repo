# Test script that reads sensor values using wildcards
# Eg. read sensorA values for all dummies

import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
TOPIC = "+/sensorA"  # Matches any topic ending in /sensorA (e.g., dummy1/sensorA)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"Connected to broker. Subscribing to {TOPIC}...")
        client.subscribe(TOPIC)
    else:
        print(f"Connection failed: {reason_code}")


def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8")
    topic = msg.topic

    # Filter to ensure it strictly matches 'dummy' prefix if needed
    publisher_id = topic.split("/")[0]
    if publisher_id.startswith("dummy"):
        print(f"[{publisher_id}] sensorA: {payload}")


# Initialize client (paho-mqtt v2.x CallbackAPIVersion)
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER, PORT, 60)
client.loop_forever()