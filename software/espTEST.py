import os
import signal
import threading
import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import paho.mqtt.client as mqtt
from pydantic import BaseModel
import uvicorn

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
DEVICE_ID = "espTEST"

state = {"arc": 0.0, "current": 250.0, "humidity": 50.0}
state_lock = threading.Lock()

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
# Register LWT before connect
mqtt_client.will_set(
    topic=f"{DEVICE_ID}/status", payload="OFFLINE", qos=1, retain=True
)
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=10)
mqtt_client.loop_start()

# Announce online
mqtt_client.publish(f"{DEVICE_ID}/status", "ONLINE", qos=1, retain=True)


def publisher_loop():
  tick = 0
  while True:
    is_30s_tick = tick % 30 == 0
    with state_lock:
      curr_arc = state["arc"]
      curr_current = state["current"]
      curr_humidity = state["humidity"]

    # 1. Current @ 1 Hz
    mqtt_client.publish(f"{DEVICE_ID}/current", f"{curr_current:.1f}", qos=0)

    # 2. Arc @ 1/30 Hz Heartbeat OR immediate if non-zero
    if curr_arc >= 1.0 or is_30s_tick:
      mqtt_client.publish(f"{DEVICE_ID}/arc", f"{curr_arc:.1f}", qos=1)

    # 3. Humidity @ 1/30 Hz
    if is_30s_tick:
      mqtt_client.publish(
          f"{DEVICE_ID}/humidity", f"{curr_humidity:.1f}", qos=0
      )

    tick += 1
    time.sleep(1.0)


pub_thread = threading.Thread(target=publisher_loop, daemon=True)
pub_thread.start()

app = FastAPI(title="espTEST Controller")


class SensorOverride(BaseModel):
  arc: float
  current: float
  humidity: float


@app.post("/api/update")
def update_state(data: SensorOverride):
  with state_lock:
    state["arc"] = data.arc
    state["current"] = data.current
    state["humidity"] = data.humidity

  # Immediate publish if arc trip is toggled
  if data.arc >= 1.0:
    mqtt_client.publish(f"{DEVICE_ID}/arc", "1.0", qos=1)

  return {"status": "ok", "state": state}


@app.post("/api/disconnect_clean")
def disconnect_clean():
  mqtt_client.publish(f"{DEVICE_ID}/status", "OFFLINE", qos=1, retain=True)
  return {"status": "Clean disconnect sent"}


@app.post("/api/reconnect")
def reconnect():
  mqtt_client.publish(f"{DEVICE_ID}/status", "ONLINE", qos=1, retain=True)
  return {"status": "Reconnected"}


@app.post("/api/simulate_crash")
def simulate_crash():
  # Abruptly kill the process without MQTT disconnect to force Mosquitto to emit LWT
  os.kill(os.getpid(), signal.SIGKILL)


@app.get("/", response_class=HTMLResponse)
def control_panel():
  return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>espTEST Controller</title>
    <style>
        body { font-family: monospace; margin: 16px; font-size: 13px; color: #111; background: #fff; }
        h1 { font-size: 16px; margin: 0 0 12px 0; }
        .panel { max-width: 480px; border: 1px solid #ccc; padding: 12px; background: #fafafa; }
        .row { margin-bottom: 10px; }
        label { display: block; font-weight: bold; margin-bottom: 4px; }
        input[type="number"], select {
            width: 100%;
            box-sizing: border-box;
            font-family: inherit;
            font-size: 12px;
            padding: 3px 6px;
            border: 1px solid #999;
            background: #fff;
        }
        .btn-group { display: flex; gap: 8px; margin-top: 8px; }
        button {
            flex: 1;
            font-family: inherit;
            font-size: 12px;
            padding: 4px 8px;
            cursor: pointer;
            background: #eaeaea;
            border: 1px solid #999;
            font-weight: bold;
        }
        button:hover { background: #dcdcdc; }
        button.btn-danger { background: #fee; color: #dc2626; border-color: #dc2626; }
        button.btn-danger:hover { background: #fca5a5; color: #fff; }
        .status-box {
            margin-top: 12px;
            border-top: 1px solid #ccc;
            padding-top: 8px;
            font-size: 11px;
            color: #555;
        }
    </style>
</head>
<body>
    <h1>espTEST Controller (LWT Enabled)</h1>
    
    <div class="panel">
        <div class="row">
            <label>Arc Flash State (Immediate Event Trigger)</label>
            <select id="arcInput">
                <option value="0.0">0.0 - Normal Heartbeat (1/30Hz)</option>
                <option value="1.0">1.0 - TRIP (Immediate)</option>
            </select>
        </div>

        <div class="row">
            <label>Current RMS (A) - 1 Hz (Limit: 600 A)</label>
            <input type="number" id="currentInput" step="1.0" value="250.0">
        </div>

        <div class="row">
            <label>Relative Humidity (%) - 1/30 Hz (Limit: 85 %)</label>
            <input type="number" id="humidityInput" step="1.0" value="50.0">
        </div>

        <div class="btn-group">
            <button class="btn-danger" onclick="submitValues()">Inject Values</button>
            <button onclick="resetSafe()">Reset Safe</button>
        </div>

        <div class="btn-group">
            <button onclick="toggleConn(false)">Set OFFLINE</button>
            <button onclick="toggleConn(true)">Set ONLINE</button>
        </div>

        <div class="btn-group">
            <button class="btn-danger" onclick="simulateCrash()">Force Hard Crash (Test LWT)</button>
        </div>

        <div class="status-box" id="statusMessage">Initial state: ONLINE, baseline values.</div>
    </div>

    <script>
        async function submitValues() {
            const payload = {
                arc: parseFloat(document.getElementById("arcInput").value),
                current: parseFloat(document.getElementById("currentInput").value),
                humidity: parseFloat(document.getElementById("humidityInput").value)
            };
            await fetch("/api/update", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            document.getElementById("statusMessage").innerText = `Injected: Arc ${payload.arc}, Curr ${payload.current} A, Hum ${payload.humidity} %`;
        }

        async function resetSafe() {
            document.getElementById("arcInput").value = "0.0";
            document.getElementById("currentInput").value = "250.0";
            document.getElementById("humidityInput").value = "50.0";
            await submitValues();
            document.getElementById("statusMessage").innerText = "Reset to normal baseline.";
        }

        async function toggleConn(online) {
            const endpoint = online ? "/api/reconnect" : "/api/disconnect_clean";
            await fetch(endpoint, { method: "POST" });
            document.getElementById("statusMessage").innerText = `Device reported: ${online ? 'ONLINE' : 'OFFLINE'}`;
        }

        async function simulateCrash() {
            if (confirm("Kill process abruptly to trigger broker LWT?")) {
                await fetch("/api/simulate_crash", { method: "POST" });
            }
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
  uvicorn.run(app, host="0.0.0.0", port=8070)