#include <WiFi.h>
#include <PubSubClient.h>

// 1. Enter your Wi-Fi credentials
const char* ssid = "ADDRESS";
const char* password = "PASSWRD";

// 2. MQTT Broker settings (using a public test broker)
const char* mqtt_server = "localhost";
const int mqtt_port = 1883;
const char* mqtt_topic = "esp32s2/test/metrics";

WiFiClient espClient;
PubSubClient client(espClient);

unsigned long lastMsg = 0;
int value = 0;

void setup_wifi() {
  delay(10);
  Serial.println();
  Serial.print("Connecting to ");
  Serial.println(ssid);

  WiFi.begin(ssid, password);

  // Wait until Wi-Fi is connected
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("");
  Serial.println("WiFi connected");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());
}

void callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("Message arrived [");
  Serial.print(topic);
  Serial.print("] ");
  for (int i = 0; i < length; i++) {
    Serial.print((char)payload[i]);
  }
  Serial.println();
}

void reconnect() {
  // Loop until we're reconnected
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    
    // Create a unique client ID based on MAC address
    String clientId = "ESP32S2Client-";
    clientId += String(WiFi.macAddress());
    
    // Attempt to connect
    if (client.connect(clientId.c_str())) {
      Serial.println("connected");
      // Once connected, resubscribe (optional)
      client.subscribe("esp32s2/test/command");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      // Wait 5 seconds before retrying
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(callback);
}

void loop() {
  // Ensure MQTT client stays connected and handles incoming callbacks
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // Publish a message every 5 seconds
  unsigned long now = millis();
  if (now - lastMsg > 5000) {
    lastMsg = now;
    
    // Create a payload string
    String payload = "Hello from ESP32-S2 count: " + String(value++);
    
    Serial.print("Publishing message: ");
    Serial.println(payload);
    
    // Publish to topic
    client.publish(mqtt_topic, payload.c_str());
  }
}
