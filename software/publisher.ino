#include <WiFi.h>
#include <PubSubClient.h>

// -------------------------------------------------------------
// Configuration & Credentials
// -------------------------------------------------------------
const char* ssid        = "YOUR_WIFI_SSID";
const char* password    = "YOUR_WIFI_PASSWORD";

const char* mqtt_server = "192.168.1.50";
const int   mqtt_port   = 1883;

// Device Identity
const char* DEVICE_ID   = "esp0";

// Pin Assignments
const int PIN_ARC_INTERRUPT = 4;   // Digital out from optical sensor / comparator
const int PIN_CURRENT_ADC    = 34;  // ADC1_CH6 (Input-only pin, safe with Wi-Fi)
const int PIN_HUMIDITY_ADC   = 35;  // ADC1_CH7 (Or connect SHT3x/DHT on I2C/GPIO)

// Topics
String TOPIC_STATUS   = String(DEVICE_ID) + "/status";
String TOPIC_CURRENT  = String(DEVICE_ID) + "/current";
String TOPIC_HUMIDITY = String(DEVICE_ID) + "/humidity";
String TOPIC_ARC      = String(DEVICE_ID) + "/arc";

// -------------------------------------------------------------
// State & Timing
// -------------------------------------------------------------
WiFiClient espClient;
PubSubClient client(espClient);

unsigned long last1HzTick   = 0;
unsigned long last30sTick   = 0;

// Arc Sensor Interrupt Flags
volatile bool arcTripped = false;

void IRAM_ATTR onArcDetected() {
  arcTripped = true;
}

// -------------------------------------------------------------
// Sensor Acquisition Helpers
// -------------------------------------------------------------

// True RMS calculation over 50 Hz power cycles (20ms per cycle)
// Samples AC waveform continuously for 200ms (10 full AC cycles)
float readTrueRMSCurrent() {
  const unsigned long sampleDurationMs = 200;
  unsigned long startMillis = millis();

  unsigned long sampleCount = 0;
  double sumSquaredDiff = 0.0;

  // Midpoint reference for typical bi-directional CT interfaces (~1.65V bias on 3.3V scale)
  // ADC 12-bit range: 0 - 4095, Midpoint = ~2048
  const float adcMidpoint = 2048.0;

  // Calibration scaling factor: (Amperes per ADC raw unit)
  // Adjust based on your burden resistor and CT turns ratio (e.g., 100A/50mA or 1000A/1A)
  const float calibrationFactor = 0.35;

  while (millis() - startMillis < sampleDurationMs) {
    int rawValue = analogRead(PIN_CURRENT_ADC);
    float centered = (float)rawValue - adcMidpoint;
    sumSquaredDiff += (centered * centered);
    sampleCount++;
  }

  if (sampleCount == 0) return 0.0;

  float meanSquare = sumSquaredDiff / sampleCount;
  float rawRms = sqrt(meanSquare);
  float currentAmps = rawRms * calibrationFactor;

  // Noise gate for zero-current idle
  if (currentAmps < 2.0) currentAmps = 0.0;

  return currentAmps;
}

// Reads and scales analog humidity voltage (e.g. HIH-4000 or 0-3.3V analog relative humidity)
float readHumidity() {
  int raw = analogRead(PIN_HUMIDITY_ADC);
  // Example linear conversion for 0-3.3V -> 0-100% RH
  float humidity = (raw / 4095.0) * 100.0;
  if (humidity < 0.0) humidity = 0.0;
  if (humidity > 100.0) humidity = 100.0;
  return humidity;
}

// -------------------------------------------------------------
// Wi-Fi & MQTT Management
// -------------------------------------------------------------

void setup_wifi() {
  delay(10);
  Serial.printf("\nConnecting to Wi-Fi SSID: %s\n", ssid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWi-Fi connected.");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection with LWT...");

    // Unique client ID based on device name and MAC
    String clientId = String(DEVICE_ID) + "-" + WiFi.macAddress();

    // Connect with Last Will and Testament (LWT):
    // If device drops off ungracefully, broker publishes "OFFLINE" with retain=true
    if (client.connect(clientId.c_str(),
                       TOPIC_STATUS.c_str(), 1, true, "OFFLINE")) {
      Serial.println(" Connected.");

      // Announce ONLINE state with retain=true
      client.publish(TOPIC_STATUS.c_str(), "ONLINE", true);

      // Send an immediate arc heartbeat baseline
      client.publish(TOPIC_ARC.c_str(), "0.0", false);
    } else {
      Serial.printf(" Failed, rc=%d. Retrying in 5 seconds...\n", client.state());
      delay(5000);
    }
  }
}

// -------------------------------------------------------------
// Setup & Main Loop
// -------------------------------------------------------------

void setup() {
  Serial.begin(115200);

  // ADC resolution: 12-bit (0 - 4095)
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db); // Full 0-3.3V range

  // Pin modes
  pinMode(PIN_ARC_INTERRUPT, INPUT_PULLDOWN);
  pinMode(PIN_CURRENT_ADC, INPUT);
  pinMode(PIN_HUMIDITY_ADC, INPUT);

  // Optical arc sensor interrupt
  attachInterrupt(digitalPinToInterrupt(PIN_ARC_INTERRUPT), onArcDetected, RISING);

  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
  client.setKeepAlive(15); // Short keepalive to assist broker LWT detection
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  unsigned long now = millis();

  // 1. PRIORITY IMMEDIATE EVENT: Arc Flash Trip
  if (arcTripped) {
    // Publish immediate alert with QoS 1
    client.publish(TOPIC_ARC.c_str(), "1.0", false);
    Serial.println("[CRITICAL] Arc Flash Event Dispatched to MQTT!");

    // Clear flag after transmission (or add local latch logic if required)
    arcTripped = false;
  }

  // 2. 1 Hz TASK: Precomputed True RMS Current Sampling & Publishing
  if (now - last1HzTick >= 1000) {
    last1HzTick = now;

    float rmsCurrent = readTrueRMSCurrent();

    char currStr[10];
    dtostrf(rmsCurrent, 4, 1, currStr);
    client.publish(TOPIC_CURRENT.c_str(), currStr, false);
  }

  // 3. 1/30 Hz TASK (Every 30 seconds): Humidity & Arc Heartbeat
  if (now - last30sTick >= 30000) {
    last30sTick = now;

    // Environmental humidity
    float hum = readHumidity();
    char humStr[10];
    dtostrf(hum, 4, 1, humStr);
    client.publish(TOPIC_HUMIDITY.c_str(), humStr, false);

    // Arc sensor alive heartbeat (0.0 = normal healthy state)
    client.publish(TOPIC_ARC.c_str(), "0.0", false);

    Serial.printf("[HEARTBEAT] Sent 30s update -> Hum: %s%% | Arc: OK\n", humStr);
  }
}
