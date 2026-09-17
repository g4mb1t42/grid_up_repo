# uvicorn app:app --host 0.0.0.0 --port 8000
# also requires websockets

import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883

# In-memory storage: { "dummy1": {"sensorA": "23.4", "sensorB": "50"}, ... }
devices_data = {}

# Active connected web browser clients
connected_clients: list[WebSocket] = []

# Main event loop reference for scheduling from MQTT thread
main_loop: asyncio.AbstractEventLoop = None


async def broadcast_update(device: str, sensor: str, value: str):
    """Send live update to all open browser windows."""
    payload = json.dumps({"device": device, "sensor": sensor, "value": value})
    disconnected = []
    for ws in connected_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connected_clients.remove(ws)


# --- MQTT Callbacks ---
def on_connect(client, userdata, flags, reason_code, properties):
    print("Connected to MQTT Broker. Subscribing to topics...")
    # Matches <dummy_id>/<sensor_name> (e.g., dummy1/sensorA, dummy2/sensorB)
    client.subscribe("+/+")


def on_message(client, userdata, msg):
    try:
        parts = msg.topic.split("/")
        if len(parts) == 2:
            device, sensor = parts[0], parts[1]
            value = msg.payload.decode("utf-8").strip()

            # Optional: ensure device starts with 'dummy' and is a known sensor
            if device.startswith("dummy"):
                if device not in devices_data:
                    devices_data[device] = {}
                devices_data[device][sensor] = value

                # Schedule the WebSocket broadcast inside FastAPI's async loop
                if main_loop and main_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        broadcast_update(device, sensor, value), main_loop
                    )
    except Exception as e:
        print(f"Error handling message: {e}")


# --- FastAPI App Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()

    # Start MQTT client in a background network loop
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(BROKER, PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"Could not connect to MQTT broker: {e}")

    yield

    mqtt_client.loop_stop()
    mqtt_client.disconnect()


app = FastAPI(lifespan=lifespan)


# --- HTML Dashboard ---
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Sensor Telemetry</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
      background: #0f172a;
      color: #e2e8f0;
      margin: 0;
      padding: 1.5rem;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
    }
    h1 {
      font-size: 1.25rem;
      font-weight: 600;
      margin: 0;
      color: #f8fafc;
    }
    .status-badge {
      font-size: 0.75rem;
      padding: 0.2rem 0.5rem;
      border-radius: 9999px;
      background: #1e293b;
      border: 1px solid #334155;
      color: #94a3b8;
    }
    .table-container {
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 6px;
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.875rem;
    }
    th {
      background: #0f172a;
      color: #94a3b8;
      font-weight: 600;
      padding: 0.6rem 1rem;
      border-bottom: 1px solid #334155;
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.05em;
    }
    td {
      padding: 0.5rem 1rem;
      border-bottom: 1px solid #334155;
      white-space: nowrap;
    }
    tr:last-child td {
      border-bottom: none;
    }
    tr:hover td {
      background: #273549;
    }
    .device-name {
      font-weight: 600;
      color: #38bdf8;
    }
    .sensor-val {
      font-family: monospace;
      display: inline-block;
      min-width: 4rem;
    }
    .dimmed {
      color: #475569;
    }
    .highlight {
      animation: flash 0.6s ease;
    }
    @keyframes flash {
      0% { color: #4ade80; }
      100% { color: #e2e8f0; }
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>Live Telemetry</h1>
    <span class="status-badge" id="conn-status">Connecting...</span>
  </div>

  <div class="table-container">
    <table>
      <thead>
        <tr>
          <th>Publisher</th>
          <th>Sensor A</th>
          <th>Sensor B</th>
          <th>Sensor C</th>
        </tr>
      </thead>
      <tbody id="device-rows"></tbody>
    </table>
  </div>

  <script>
    const socket = new WebSocket(`ws://${location.host}/ws`);
    const tbody = document.getElementById("device-rows");
    const statusEl = document.getElementById("conn-status");

    socket.onopen = () => {
      statusEl.textContent = "● Connected";
      statusEl.style.color = "#4ade80";
    };

    socket.onclose = () => {
      statusEl.textContent = "○ Disconnected";
      statusEl.style.color = "#f87171";
    };

    function sortRows() {
      const rows = Array.from(tbody.querySelectorAll("tr"));
      rows.sort((a, b) => {
        const idA = a.dataset.device || "";
        const idB = b.dataset.device || "";
        // Natural numeric sort: dummy1, dummy2, ..., dummy10
        return idA.localeCompare(idB, undefined, { numeric: true, sensitivity: 'base' });
      });
      rows.forEach(row => tbody.appendChild(row));
    }

    function getOrCreateRow(deviceId) {
      let row = document.getElementById(`row-${deviceId}`);
      if (!row) {
        row = document.createElement("tr");
        row.id = `row-${deviceId}`;
        row.dataset.device = deviceId;
        row.innerHTML = `
          <td class="device-name">${deviceId}</td>
          <td><span id="val-${deviceId}-sensorA" class="sensor-val dimmed">--</span></td>
          <td><span id="val-${deviceId}-sensorB" class="sensor-val dimmed">--</span></td>
          <td><span id="val-${deviceId}-sensorC" class="sensor-val dimmed">--</span></td>
        `;
        tbody.appendChild(row);
        sortRows();
      }
      return row;
    }

    function updateSensorValue(deviceId, sensor, val) {
      getOrCreateRow(deviceId);
      const span = document.getElementById(`val-${deviceId}-${sensor}`);
      if (span) {
        span.innerText = val;
        span.classList.remove("dimmed");
        span.classList.remove("highlight");
        void span.offsetWidth; // Re-trigger CSS animation
        span.classList.add("highlight");
      }
    }

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "init") {
        for (const [dev, sensors] of Object.entries(data.data)) {
          for (const [sensor, val] of Object.entries(sensors)) {
            updateSensorValue(dev, sensor, val);
          }
        }
      } else {
        updateSensorValue(data.device, data.sensor, data.value);
      }
    };
  </script>
</body>
</html>
"""

@app.get("/")
async def get_index():
    return HTMLResponse(HTML_PAGE)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        # Send current initial state on connection
        await websocket.send_text(json.dumps({"type": "init", "data": devices_data}))
        while True:
            # Keep connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)