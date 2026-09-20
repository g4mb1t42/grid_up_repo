# Project Overview

### Description
This project utilizes low bandwidth cost, connection speed, scalability, and reliability of MQTT networks while also having direct integration support to existing SCADA networks using Modbus protocol. A microcontroller is used as a publisher and sends sensor readings to network while a server subscribes to these sensor readings. It can process the data to detect anomalies and send warning signals via a web based user interface or the chosen sms/whatsapp service, store it on a database with a hot/warm tier downsampling system to minimize storage usage, convert the readings and warning signals to Modbus protocol for SCADA integration.

---

### Built With
This project is built using:
- **Mosquitto** (MQTT broker)
- **External Python Libraries:**
  - `fastapi`
  - `uvicorn`
  - `pyModbusTCP`
  - `paho-mqtt`
  - `pydantic`

---

### Requirements
- The project needs an MQTT broker on the configured address/port to run.

---

### File Descriptions
- `app.py` — The entry point for the subscriber server code.
- `spawnTestDevices.py` — Creates simulated publishers. It can be used to test the system.
- `espTest.py` — Creates a single simulated publisher with id `1001` that can be controlled by the user. It can be used to test warning systems.
- `scada_cli_monitor.py` — Can be used to test connection via Modbus protocol.

---

### Notifications
The SMS/WhatsApp system is created in a flexible way to work with any chosen service. Currently, CallMeBot API is used for testing and can be used via `config.py`.
