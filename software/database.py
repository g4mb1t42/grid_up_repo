import queue
import sqlite3
import threading
import time
from typing import Any, Dict, List
import config

# Ingestion FIFO queue
db_queue = queue.Queue()


def init_db():
  """Initializes SQLite WAL mode and the hot/warm schema."""
  with sqlite3.connect(config.DB_FILE) as conn:
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                device_id TEXT,
                sensor_id TEXT,
                value REAL
            );
        """)
    conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_rollups_1m (
                bucket_ts INTEGER,
                device_id TEXT,
                sensor_id TEXT,
                avg_val REAL,
                min_val REAL,
                max_val REAL,
                sample_count INTEGER,
                PRIMARY KEY (bucket_ts, device_id, sensor_id)
            );
        """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stream ON sensor_readings (device_id,"
        " sensor_id, timestamp);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rollups ON sensor_rollups_1m"
        " (device_id, sensor_id, bucket_ts);"
    )


def db_writer_thread():
  """Dedicated background worker that commits queued readings in bulk."""
  conn = sqlite3.connect(config.DB_FILE)
  cursor = conn.cursor()
  batch = []
  last_flush = time.time()

  while True:
    try:
      item = db_queue.get(timeout=0.2)
      batch.append(item)
    except queue.Empty:
      pass

    now = time.time()
    if len(batch) >= config.BATCH_SIZE or (
        batch and (now - last_flush) >= config.FLUSH_INTERVAL_SEC
    ):
      cursor.executemany(
          "INSERT INTO sensor_readings (timestamp, device_id, sensor_id, value)"
          " VALUES (?, ?, ?, ?)",
          batch,
      )
      conn.commit()
      batch.clear()
      last_flush = now


def downsample_and_prune():
  """Aggregates raw data older than RETENTION_DAYS into 1-minute warm tier buckets."""
  cutoff_ts = time.time() - (config.RETENTION_DAYS * 86400)
  try:
    with sqlite3.connect(config.DB_FILE, timeout=15.0) as conn:
      conn.execute("PRAGMA busy_timeout = 10000;")
      conn.execute(
          """
                INSERT OR REPLACE INTO sensor_rollups_1m (
                    bucket_ts, device_id, sensor_id, avg_val, min_val, max_val, sample_count
                )
                SELECT 
                    CAST(timestamp / 60 AS INT) * 60 AS bucket_ts,
                    device_id,
                    sensor_id,
                    ROUND(AVG(value), 2),
                    ROUND(MIN(value), 2),
                    ROUND(MAX(value), 2),
                    COUNT(value)
                FROM sensor_readings
                WHERE timestamp < ?
                GROUP BY bucket_ts, device_id, sensor_id;
            """,
          (cutoff_ts,),
      )
      conn.execute(
          "DELETE FROM sensor_readings WHERE timestamp < ?;", (cutoff_ts,)
      )
      conn.commit()
  except Exception as e:
    print(f"[DB Lifecycle Error]: {e}")


def lifecycle_daemon():
  """Background daemon running downsampling periodically."""
  while True:
    time.sleep(6 * 3600)  # Run once every 6 hours
    downsample_and_prune()


def query_history(
    device_id: str, sensor_id: str, limit: int = 50
) -> List[Dict[str, Any]]:
  """Read-only non-blocking historical query."""
  with sqlite3.connect(
      f"file:{config.DB_FILE}?mode=ro", uri=True, timeout=5.0
  ) as conn:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
            SELECT timestamp, device_id, sensor_id, value 
            FROM sensor_readings 
            WHERE device_id = ? AND sensor_id = ? 
            ORDER BY timestamp DESC LIMIT ?
        """,
        (device_id, sensor_id, limit),
    )
    return [
        {
            "timestamp": r["timestamp"],
            "device": r["device_id"],
            "sensor": r["sensor_id"],
            "value": r["value"],
        }
        for r in cursor.fetchall()
    ]