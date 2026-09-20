import random
import time
import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
NUM_DEVICES = 100
DEVICES = [f"esp{i}" for i in range(1, NUM_DEVICES + 1)]

# Create and connect dedicated MQTT clients per device to demonstrate true per-node LWT
clients = {}
device_states = {}

print(f"Connecting {NUM_DEVICES} devices with MQTT LWT...")
for dev in DEVICES:
  c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
  # Configure Last Will and Testament: broker sets status to OFFLINE if ping drops
  c.will_set(topic=f"{dev}/status", payload="OFFLINE", qos=1, retain=True)
  c.connect(BROKER, PORT, keepalive=15)
  c.loop_start()

  # Announce online status
  c.publish(f"{dev}/status", "ONLINE", qos=1, retain=True)

  clients[dev] = c
  device_states[dev] = {
      "current_rms": random.uniform(220.0, 420.0),
      "humidity": random.uniform(48.0, 62.0),
  }

print(
    "All 100 nodes online. Streaming: current @ 1Hz, arc/humidity @ 1/30Hz..."
)

tick = 0
try:
  while True:
    is_30s_tick = tick % 30 == 0

    for dev in DEVICES:
      c = clients[dev]
      st = device_states[dev]

      # 1. CURRENT SENSOR: 1 Hz (Precomputed True RMS, nominal load 150-520A)
      st["current_rms"] += random.uniform(-4.0, 4.0)
      st["current_rms"] = max(120.0, min(520.0, st["current_rms"]))
      curr_val = (
          random.uniform(620.0, 720.0)
          if random.random() < 0.003
          else st["current_rms"]
      )
      c.publish(f"{dev}/current", f"{curr_val:.1f}", qos=0)

      # 2. ARC SENSOR: Periodic Heartbeat (1/30 Hz) + Immediate Event Trigger
      arc_occurred = random.random() < 0.0003  # Rare optical flash
      if arc_occurred:
        c.publish(f"{dev}/arc", "1.0", qos=1)  # Immediate trip event
      elif is_30s_tick:
        c.publish(f"{dev}/arc", "0.0", qos=0)  # Regular heartbeat

      # 3. HUMIDITY SENSOR: 1/30 Hz (Every 30 seconds)
      if is_30s_tick:
        st["humidity"] += random.uniform(-0.5, 0.5)
        st["humidity"] = max(35.0, min(75.0, st["humidity"]))
        hum_val = (
            random.uniform(86.0, 93.0)
            if random.random() < 0.01
            else st["humidity"]
        )
        c.publish(f"{dev}/humidity", f"{hum_val:.1f}", qos=0)

    tick += 1
    time.sleep(1.0)

except KeyboardInterrupt:
  print("Simulating clean disconnect for all nodes...")
  for dev, c in clients.items():
    c.publish(f"{dev}/status", "OFFLINE", qos=1, retain=True)
    c.disconnect()
    c.loop_stop()