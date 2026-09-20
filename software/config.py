import os

# MQTT Broker Settings
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC_TELEMETRY = "+/+"

# SQLite Database Settings
DB_FILE = os.getenv("DB_FILE", "sensors.db")
BATCH_SIZE = 500
FLUSH_INTERVAL_SEC = 1.0
RETENTION_DAYS = 3

# Sensor Profiles: (N-sample window, trigger threshold, clear threshold with deadband, aggregation mode)
SENSOR_CONFIGS = {
    "arc": {
        "window_n": 1,
        "trigger": 1.0,
        "clear": 0.0,
        "mode": "max",
        "unit": "state",
        "severity": "CRITICAL",
        "cooldown_sec": 60,
    },
    "current": {
        "window_n": 5,
        "trigger": 600.0,
        "clear": 570.0,  # 5% Deadband
        "mode": "avg",
        "unit": "A",
        "severity": "CRITICAL",
        "cooldown_sec": 300,
    },
    "humidity": {
        "window_n": 2,
        "trigger": 85.0,
        "clear": 80.0,  # 5% Deadband
        "mode": "avg",
        "unit": "%RH",
        "severity": "WARNING",
        "cooldown_sec": 900,
    },
}