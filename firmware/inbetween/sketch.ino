#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <DHTesp.h>
#include <LiquidCrystal_I2C.h>
#include <time.h>
#include "config.h"

#define DHT_PIN 4
#define LIGHT_PIN 34
#define SOIL_PIN 35
#define WATER_LOW_PIN 27
#define BUZZER_PIN 25
#define FAN_PIN 18
#define PUMP_PIN 19

static const uint32_t SAMPLE_MS = 5000;
static const uint32_t POST_MS = 15000;
static const uint32_t WIFI_RETRY_MS = 10000;
static const uint32_t HTTP_TIMEOUT_MS = 5000;
static const float SOIL_DRY_ADC = 3200.0f; // adjust after calibrating your probe/pot
static const float SOIL_WET_ADC = 1200.0f;
static const float IRRIGATE_BELOW_PCT = 35.0f; // configurable crop threshold
static const float FAN_INDOOR_C = 30.0f;
static const int SHADE_LIGHT_ADC = 3000;

DHTesp dht;
LiquidCrystal_I2C lcd(0x27, 16, 2);
uint32_t lastSample = 0, lastPost = 0, lastWifiAttempt = 0;
float temperatureC = NAN, humidityPct = NAN, soilPct = NAN;
int lightAdc = 0;
bool waterLow = true, sensorValid = false, fanOn = false, pumpOn = false, buzzerOn = false;
String jsonPayload();

String isoTimestamp() {
  struct tm tmInfo;
  if (getLocalTime(&tmInfo, 20)) {
    char buf[25]; strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tmInfo); return String(buf);
  }
  return "1970-01-01T00:00:00Z"; // backend receives a valid ISO timestamp, but stale check safely blocks recommendations
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED || millis() - lastWifiAttempt < WIFI_RETRY_MS) return;
  lastWifiAttempt = millis();
  Serial.printf("WiFi connecting to %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void sampleSensors() {
  const TempAndHumidity dhtReading = dht.getTempAndHumidity();
  const float t = dhtReading.temperature;
  const float h = dhtReading.humidity;
  lightAdc = analogRead(LIGHT_PIN);
  const int soilAdc = analogRead(SOIL_PIN);
  // INPUT_PULLUP gives a fail-safe default: open/released or disconnected = reservoir LOW.
  // Press the button to ground GPIO27 and simulate water available.
  waterLow = digitalRead(WATER_LOW_PIN) == HIGH;
  sensorValid = isfinite(t) && isfinite(h) && t >= -40 && t <= 80 && h >= 0 && h <= 100;
  if (sensorValid) { temperatureC = t; humidityPct = h; }
  soilPct = constrain((SOIL_DRY_ADC - soilAdc) * 100.0f / (SOIL_DRY_ADC - SOIL_WET_ADC), 0.0f, 100.0f);

  // Local demo logic only. Fan thresholds must be tuned to the crop and airflow.
  fanOn = sensorValid && temperatureC >= FAN_INDOOR_C;
  pumpOn = sensorValid && soilPct < IRRIGATE_BELOW_PCT && !waterLow;
  buzzerOn = !sensorValid || waterLow;
  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(PUMP_PIN, pumpOn ? HIGH : LOW); // LED indicator only; GPIO must never power a real pump
  if (buzzerOn) tone(BUZZER_PIN, 2200); else noTone(BUZZER_PIN);

  lcd.setCursor(0, 0);
  if (sensorValid) { lcd.printf("T:%4.1fC H:%2.0f%% ", temperatureC, humidityPct); }
  else lcd.print("DHT SENSOR ERROR ");
  lcd.setCursor(0, 1); lcd.printf("S:%3.0f%% L:%4d %c", soilPct, lightAdc, waterLow ? '!' : ' ');
  Serial.printf("sensor_valid=%s temp=%.1f humidity=%.1f light=%d soil=%.1f water_low=%s fan=%s pump=%s buzzer=%s\n",
    sensorValid ? "true":"false", temperatureC, humidityPct, lightAdc, soilPct, waterLow?"true":"false", fanOn?"on":"off", pumpOn?"on":"off", buzzerOn?"on":"off");
  if (sensorValid) Serial.println(jsonPayload());
}

String jsonPayload() {
  String payload = "{\"device_id\":\"" DEVICE_ID "\",\"temperature_c\":";
  payload += String(temperatureC, 1); payload += ",\"humidity_pct\":"; payload += String(humidityPct, 1);
  payload += ",\"light_adc\":"; payload += String(lightAdc); payload += ",\"soil_moisture_pct\":"; payload += String(soilPct, 1);
  payload += ",\"water_level_low\":"; payload += waterLow ? "true" : "false";
  payload += ",\"timestamp\":\""; payload += isoTimestamp(); payload += "\"}";
  return payload;
}

void postMeasurement() {
  if (!sensorValid) { Serial.println("POST skipped: invalid DHT reading"); return; }
  if (WiFi.status() != WL_CONNECTED) { Serial.println("POST skipped: WiFi offline"); return; }
  String url = String(SERVER_URL) + "/api/iot/sensors";
  HTTPClient http; http.setTimeout(HTTP_TIMEOUT_MS);
  int status = -1;
  if (url.startsWith("https://")) {
    WiFiClientSecure client;
    if (TLS_INSECURE_FOR_DEVELOPMENT) client.setInsecure();
    else if (strlen(SERVER_ROOT_CA) > 0) client.setCACert(SERVER_ROOT_CA);
    else { Serial.println("HTTPS skipped: configure SERVER_ROOT_CA or explicit dev-only insecure mode"); return; }
    if (!http.begin(client, url)) { Serial.println("HTTP begin failed"); return; }
    http.addHeader("Content-Type", "application/json"); status = http.POST(jsonPayload());
  } else {
    WiFiClient client;
    if (!http.begin(client, url)) { Serial.println("HTTP begin failed"); return; }
    http.addHeader("Content-Type", "application/json"); status = http.POST(jsonPayload());
  }
  Serial.printf("POST %s -> %d %s\n", url.c_str(), status, status > 0 ? http.getString().c_str() : http.errorToString(status).c_str());
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(WATER_LOW_PIN, INPUT_PULLUP); // safe default = reservoir low if switch is asserted or wire is grounded
  pinMode(FAN_PIN, OUTPUT); pinMode(PUMP_PIN, OUTPUT); pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(FAN_PIN, LOW); digitalWrite(PUMP_PIN, LOW); noTone(BUZZER_PIN);
  analogReadResolution(12); dht.setup(DHT_PIN, DHTesp::DHT22); Wire.begin(21, 22); lcd.init(); lcd.backlight();
  lcd.print("INBETWEEN boot");
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  WiFi.setAutoReconnect(true); connectWifi();
}

void loop() {
  const uint32_t now = millis();
  connectWifi();
  if (now - lastSample >= SAMPLE_MS) { lastSample = now; sampleSensors(); }
  if (now - lastPost >= POST_MS) { lastPost = now; postMeasurement(); }
  delay(5); // yield to WiFi; all sensor/network periods are millis-based
}
