"""
app.py
Central Switchgear Gateway Service.
Handles MQTT Ingest (LWT, fast interrupts), Anomaly State Machine,
External Alert Dispatching, Modbus SCADA Bridge, and FastAPI / WebSockets.
"""

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from enum import Enum
import json
import threading
import time
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import paho.mqtt.client as mqtt

import config
import database
from scada_bridge import scada

# =====================================================================
# 1. Stateful Anomaly & Alarm Machine (Edge Trigger + Deadband)
# =====================================================================


class AlertState(str, Enum):
  OK = "OK"
  ALERT = "ALERT"


class AlarmManager:

  def __init__(self):
    self.states: Dict[tuple, AlertState] = {}
    self.last_dispatched: Dict[tuple, float] = {}

  def process(
      self, device_id: str, sensor_id: str, current_val: float
  ) -> Optional[dict]:
    rule = config.SENSOR_CONFIGS.get(sensor_id)
    if not rule:
      return None

    key = (device_id, sensor_id)
    current_state = self.states.get(key, AlertState.OK)
    now = time.time()
    event = None

    # Rising edge trigger: OK -> ALERT
    if current_state == AlertState.OK and current_val >= rule["trigger"]:
      self.states[key] = AlertState.ALERT
      event = {
          "action": "TRIGGER",
          "severity": rule["severity"],
          "device_id": device_id,
          "sensor_id": sensor_id,
          "value": round(current_val, 2),
          "threshold": rule["trigger"],
          "unit": rule["unit"],
          "timestamp": now,
          "message": (
              f"[{rule['severity']}] {device_id} {sensor_id.upper()} breached"
              f" limit: {round(current_val, 2)} {rule['unit']} (Threshold:"
              f" {rule['trigger']})"
          ),
      }

    # Falling edge recovery: ALERT -> OK (Safety inspection required)
    elif current_state == AlertState.ALERT and current_val <= rule["clear"]:
      self.states[key] = AlertState.OK
      event = {
          "action": "INSPECTION_REQUIRED",
          "severity": "MAINTENANCE",
          "device_id": device_id,
          "sensor_id": sensor_id,
          "value": round(current_val, 2),
          "clear_threshold": rule["clear"],
          "unit": rule["unit"],
          "timestamp": now,
          "message": (
              f"[INSPECTION REQUIRED] {device_id} {sensor_id.upper()} normalized"
              f" to {round(current_val, 2)} {rule['unit']}. Manual safety check"
              " required."
          ),
      }

    return event


# =====================================================================
# 2. Throttled External Dispatcher (SMS / WhatsApp)
# =====================================================================


def dispatch_external_alert(alert_event: dict):
  """Dispatches external notifications on initial rising-edge TRIGGER events."""
  if alert_event.get("action") != "TRIGGER":
    return

  device_id = alert_event["device_id"]
  sensor_id = alert_event["sensor_id"]
  key = (device_id, sensor_id)

  rule = config.SENSOR_CONFIGS.get(sensor_id, {})
  cooldown_sec = rule.get("cooldown_sec", 300)
  now = time.time()

  last_time = alarm_mgr.last_dispatched.get(key, 0.0)
  if (now - last_time) < cooldown_sec:
    return

  alarm_mgr.last_dispatched[key] = now
  print(
      f"🚨 [EXTERNAL OUTBOX] ({alert_event['severity']}) ->"
      f" {alert_event['message']}"
  )


# Runtime objects
rolling_windows: Dict[tuple, deque] = {}
alarm_mgr = AlarmManager()
active_websockets = set()
loop: Optional[asyncio.AbstractEventLoop] = None


def get_sensor_window(device_id: str, sensor_id: str) -> deque:
  key = (device_id, sensor_id)
  if key not in rolling_windows:
    cfg = config.SENSOR_CONFIGS.get(sensor_id, {"window_n": 5})
    rolling_windows[key] = deque(maxlen=cfg["window_n"])
  return rolling_windows[key]


# =====================================================================
# 3. MQTT Callback & Data Flow Pipeline
# =====================================================================


def on_message(client, userdata, msg):
  try:
    topic_parts = msg.topic.split("/")
    if len(topic_parts) != 2:
      return

    device_id, channel = topic_parts
    payload_str = msg.payload.decode("utf-8").strip()
    now = time.time()

    # --- A. Last Will & Testament (LWT) / Connection Status ---
    if channel == "status":
      status = payload_str.upper()

      if status == "OFFLINE":
        # Update Modbus register bit for SCADA
        scada.update_alarm_state(device_id, "status", "TRIGGER")

        loss_alert = {
            "action": "TRIGGER",
            "severity": "CRITICAL",
            "device_id": device_id,
            "sensor_id": "status",
            "value": 0.0,
            "threshold": 1.0,
            "unit": "comm",
            "timestamp": now,
            "message": (
                f"[COMMUNICATION LOST] {device_id} disconnected unexpectedly"
                " (LWT)."
            ),
        }
        dispatch_external_alert(loss_alert)

        if loop and active_websockets:
          asyncio.run_coroutine_threadsafe(
              broadcast_ws({
                  "type": "alarm_event",
                  "action": "TRIGGER",
                  "key": f"{device_id}_status",
                  "device_id": device_id,
                  "sensor_id": "status",
                  "severity": "CRITICAL",
                  "message": loss_alert["message"],
                  "timestamp": round(now, 2),
              }),
              loop,
          )

      elif status == "ONLINE":
        scada.update_alarm_state(device_id, "status", "INSPECTION_REQUIRED")
        if loop and active_websockets:
          asyncio.run_coroutine_threadsafe(
              broadcast_ws({
                  "type": "alarm_event",
                  "action": "INSPECTION_REQUIRED",
                  "key": f"{device_id}_status",
                  "device_id": device_id,
                  "sensor_id": "status",
                  "severity": "MAINTENANCE",
                  "message": (
                      f"[RECONNECTED] {device_id} back online. Connection"
                      " verification required."
                  ),
                  "timestamp": round(now, 2),
              }),
              loop,
          )

      if loop and active_websockets:
        asyncio.run_coroutine_threadsafe(
            broadcast_ws({
                "type": "device_status",
                "device_id": device_id,
                "status": status,
                "time": round(now, 2),
            }),
            loop,
        )
      return

    # --- B. Sensor Telemetry Ingestion ---
    sensor_id = channel
    if sensor_id not in config.SENSOR_CONFIGS:
      return

    try:
      data = json.loads(payload_str)
      value = float(data["value"]) if isinstance(data, dict) else float(data)
    except json.JSONDecodeError:
      value = float(payload_str)

    # 1. Update Modbus Registers synchronously for SCADA polling
    scada.update_telemetry(device_id, sensor_id, value)

    # 2. Asynchronous Queue to SQLite WAL batch writer
    database.db_queue.put((now, device_id, sensor_id, value))

    # 3. Rolling Window evaluation
    cfg = config.SENSOR_CONFIGS[sensor_id]
    window = get_sensor_window(device_id, sensor_id)
    window.append(value)

    stat_val = (
        max(window)
        if cfg["mode"] == "max"
        else (sum(window) / len(window) if window else value)
    )

    alert_event = None
    if len(window) >= cfg["window_n"]:
      alert_event = alarm_mgr.process(device_id, sensor_id, stat_val)

    # 4. Handle Anomaly Transitions
    if alert_event:
      scada.update_alarm_state(
          device_id, sensor_id, alert_event["action"]
      )
      dispatch_external_alert(alert_event)

    # 5. Live UI Broadcast via WebSockets
    if loop and active_websockets:
      asyncio.run_coroutine_threadsafe(
          broadcast_ws({
              "type": "telemetry",
              "device_id": device_id,
              "sensor_id": sensor_id,
              "value": round(value, 2),
              "time": round(now, 2),
          }),
          loop,
      )

      if alert_event:
        asyncio.run_coroutine_threadsafe(
            broadcast_ws({
                "type": "alarm_event",
                "action": alert_event["action"],
                "key": f"{device_id}_{sensor_id}",
                "device_id": device_id,
                "sensor_id": sensor_id,
                "severity": alert_event["severity"],
                "message": alert_event["message"],
                "timestamp": round(now, 2),
            }),
            loop,
        )

  except Exception as e:
    print(f"[Ingest Error]: {e}")


async def broadcast_ws(data: dict):
  msg = json.dumps(data)
  to_remove = set()
  for ws in active_websockets:
    try:
      await ws.send_text(msg)
    except Exception:
      to_remove.add(ws)
  active_websockets.difference_update(to_remove)


# =====================================================================
# 4. FastAPI Lifecycle & Endpoints
# =====================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
  global loop
  loop = asyncio.get_running_loop()

  # 1. Setup DB Schema (WAL mode, hot/warm tables)
  database.init_db()

  # 2. Background SQLite Writer & Downsampling Daemons
  writer = threading.Thread(target=database.db_writer_thread, daemon=True)
  writer.start()

  lifecycle = threading.Thread(target=database.lifecycle_daemon, daemon=True)
  lifecycle.start()

  # 3. Start Modbus TCP SCADA Bridge
  scada.start()

  # 4. Start MQTT Subscriber
  mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
  mqtt_client.on_message = on_message
  mqtt_client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
  mqtt_client.subscribe(config.MQTT_TOPIC_TELEMETRY)
  mqtt_client.loop_start()

  yield

  mqtt_client.loop_stop()
  scada.stop()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
  await websocket.accept()
  active_websockets.add(websocket)
  try:
    while True:
      await websocket.receive_text()
  except WebSocketDisconnect:
    active_websockets.discard(websocket)


@app.get("/api/history")
def get_history(device_id: str, sensor_id: str, limit: int = 50):
  return database.query_history(device_id, sensor_id, limit)


@app.get("/", response_class=HTMLResponse)
def index():
  with open("templates/index.html", "r", encoding="utf-8") as f:
    return f.read()


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)