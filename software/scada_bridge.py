"""
scada_bridge.py
Standalone Modbus TCP Server Bridge for SCADA/RTU Polling.
Provides zero-based discrete inputs and holding registers per panel.
"""

from pyModbusTCP.server import ModbusServer


class ScadaModbusBridge:

  def __init__(self, host: str = "0.0.0.0", port: int = 5020):
    # Port 5020 runs without requiring root/sudo privileges (standard 502 requires root)
    self.server = ModbusServer(host=host, port=port, no_block=True)
    self.db = self.server.data_bank

  def start(self):
    self.server.start()
    print(
        f"⚡ [SCADA BRIDGE] Modbus TCP Server listening on port"
        f" {self.server.port}"
    )

  def stop(self):
    self.server.stop()
    print("⚡ [SCADA BRIDGE] Modbus TCP Server stopped.")

  def _get_device_idx(self, device_id: str) -> int:
    """Extracts integer index from 'dummy1' -> 0, 'dummy100' -> 99."""
    try:
      return int("".join(filter(str.isdigit, device_id))) - 1
    except ValueError:
      return 0

  def update_telemetry(self, device_id: str, sensor_id: str, value: float):
    """Updates 16-bit holding registers and discrete input bits.

    Register Map per Panel (10 registers base per device):
      Holding Register base + 0: Current RMS (scaled x10, e.g. 450.2 A -> 4502)
      Holding Register base + 1: Humidity % (scaled x10, e.g. 65.4% -> 654)
      Discrete Input   base + 0: Optical Arc Trip bit (1 = TRIP, 0 = OK)
    """
    idx = self._get_device_idx(device_id)
    reg_base = idx * 10
    bit_base = idx * 10

    if sensor_id == "current":
      scaled = int(min(65535, max(0, value * 10)))
      self.db.set_holding_registers(reg_base + 0, [scaled])
    elif sensor_id == "humidity":
      scaled = int(min(65535, max(0, value * 10)))
      self.db.set_holding_registers(reg_base + 1, [scaled])
    elif sensor_id == "arc":
      is_trip = 1 if value >= 1.0 else 0
      self.db.set_discrete_inputs(bit_base + 0, [is_trip])

  def update_alarm_state(self, device_id: str, sensor_id: str, action: str):
    """Updates discrete alarm flags and overall state code.

    Discrete Input base + 1: Overcurrent Alarm (1/0)
    Discrete Input base + 2: High Humidity Alarm (1/0)
    Discrete Input base + 3: Communication Lost / LWT (1/0)
    Holding Reg    base + 2: Panel State Enum (0: Normal, 1: Alert, 2: Inspection Required)
    """
    idx = self._get_device_idx(device_id)
    reg_base = idx * 10
    bit_base = idx * 10

    is_alert = 1 if action == "TRIGGER" else 0

    if sensor_id == "current":
      self.db.set_discrete_inputs(bit_base + 1, [is_alert])
    elif sensor_id == "humidity":
      self.db.set_discrete_inputs(bit_base + 2, [is_alert])
    elif sensor_id == "status":
      self.db.set_discrete_inputs(bit_base + 3, [is_alert])

    # State Code Enum for SCADA Display
    state_code = (
        1
        if action == "TRIGGER"
        else (2 if action == "INSPECTION_REQUIRED" else 0)
    )
    self.db.set_holding_registers(reg_base + 2, [state_code])


# Global instance
scada = ScadaModbusBridge(port=5020)