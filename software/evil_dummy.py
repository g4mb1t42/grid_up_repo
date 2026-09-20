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
DEVICE_ID = "dummy666"

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

app = FastAPI(title="dummy666 Controller")


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
<html>
<head>
    <title>Evil dummy666 Manual Control</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #111827; color: #f9fafb; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .card { background: #1f2937; padding: 24px; border-radius: 12px; border: 1px solid #374151; width: 400px; }
        h2 { color: #f87171; margin-top: 0; text-align: center; }
        .row { margin-bottom: 14px; }
        label { display: block; font-size: 13px; color: #9ca3af; margin-bottom: 6px; }
        input[type="number"], select { width: 100%; box-sizing: border-box; background: #374151; border: 1px solid #4b5563; color: white; padding: 8px 12px; border-radius: 6px; }
        .btn-group { display: flex; gap: 8px; margin-top: 10px; }
        button { flex: 1; padding: 10px; border-radius: 6px; border: none; font-weight: bold; cursor: pointer; }
        .btn-apply { background: #dc2626; color: white; }
        .btn-safe { background: #10b981; color: white; }
        .btn-warn { background: #f59e0b; color: white; }
        .btn-kill { background: #450a0a; border: 1px solid #ef4444; color: #fca5a5; }
        .status-box { margin-top: 15px; font-size: 12px; color: #9ca3af; text-align: center; border-top: 1px solid #374151; padding-top: 10px; }
    </style>
</head>
<body>
    <div class="card">
        <h2>😈 dummy666 Controller (LWT Enabled)</h2>
        
        <div class="row">
            <label>Arc Flash State (Immediate Event Trigger)</label>
            <select id="arcInput">
                <option value="0.0">0.0 - Normal Heartbeat (1/30Hz)</option>
                <option value="1.0">1.0 - ⚡ Immediate ARC TRIP</option>
            </select>
        </div>

        <div class="row">
            <label>Current RMS (A) - 1 Hz (Threshold > 600 A)</label>
            <input type="number" id="currentInput" step="1.0" value="250.0">
        </div>

        <div class="row">
            <label>Relative Humidity (%) - 1/30 Hz (Threshold > 85 %RH)</label>
            <input type="number" id="humidityInput" step="1.0" value="50.0">
        </div>

        <div class="btn-group">
            <button class="btn-apply" onclick="submitValues()">Inject Values</button>
            <button class="btn-safe" onclick="resetSafe()">Reset Safe</button>
        </div>

        <div class="btn-group">
            <button class="btn-warn" onclick="toggleConn(false)">Set OFFLINE</button>
            <button class="btn-safe" onclick="toggleConn(true)">Set ONLINE</button>
        </div>

        <div class="btn-group">
            <button class="btn-kill" onclick="simulateCrash()">💥 Force Hard Crash (Test Broker LWT)</button>
        </div>

        <div class="status-box" id="statusMessage">Initial state: ONLINE, non-anomaly values.</div>
    </div>

    <script>
        async function submitValues() {
            const payload = {
                arc: parseFloat(document.getElementById("arcInput").value),
                current: parseFloat(document.getElementById("currentInput").value),
                humidity: parseFloat(document.getElementById("humidityInput").value)
            };
            const res = await fetch("/api/update", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            document.getElementById("statusMessage").innerText = `Injected: Arc ${payload.arc}, Curr ${payload.current}A, Hum ${payload.humidity}%`;
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
            if (confirm("This will kill evil_dummy process abruptly to trigger broker LWT within keepalive interval. Continue?")) {
                await fetch("/api/simulate_crash", { method: "POST" });
            }
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
  uvicorn.run(app, host="0.0.0.0", port=8090)