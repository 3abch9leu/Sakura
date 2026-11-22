/*
  INBETWEEN monitor - Arduino Uno / Nano

  Hardware (hackathon kit):
    A0  potentiometer = SIMULATED reservoir level sensor (0..1023). Replace by a real level sensor later.
    D2  DHT11 temperature / humidity
    D8  active buzzer
    I2C LCD 16x2 (address 0x27, SDA=A4, SCL=A5)

  Serial (115200 baud), one JSON line every 2 s:
    {"source":"arduino","level_raw":512,"temp_c":29.0,"humidity":41.0,"simulated_level":true}
  The PC bridge (arduino/sensor_bridge.py) posts it to the API and sends back, as text lines:
    L1:<16 chars>    first LCD line
    L2:<16 chars>    second LCD line
    BZ:1 / BZ:0      buzzer on (beeping) / off
  The thresholds are NOT on the board: the API computes them dynamically (plants, sun, weather, refill plan).

  Libraries: "DHT sensor library" (Adafruit), "LiquidCrystal I2C" (Frank de Brabander).
*/
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>

#define PIN_LEVEL A0
#define PIN_DHT 2
#define PIN_BUZZER 8

DHT dht(PIN_DHT, DHT11);
LiquidCrystal_I2C lcd(0x27, 16, 2);

bool buzz = false;
unsigned long lastSend = 0, lastBeep = 0;
String inLine = "";

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUZZER, OUTPUT);
  dht.begin();
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0); lcd.print("INBETWEEN");
  lcd.setCursor(0, 1); lcd.print("starting...");
}

void showLine(int row, String text) {
  lcd.setCursor(0, row);
  text = text.substring(0, 16);
  while (text.length() < 16) text += " ";
  lcd.print(text);
}

void handle(String line) {
  line.trim();
  if (line.startsWith("L1:")) showLine(0, line.substring(3));
  else if (line.startsWith("L2:")) showLine(1, line.substring(3));
  else if (line.startsWith("BZ:")) buzz = line.substring(3).toInt() == 1;
}

void loop() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') { handle(inLine); inLine = ""; }
    else if (inLine.length() < 40) inLine += ch;
  }
  unsigned long now = millis();
  if (now - lastSend >= 2000) {
    lastSend = now;
    int level = analogRead(PIN_LEVEL);
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    Serial.print("{\"source\":\"arduino\",\"simulated_level\":true,\"level_raw\":");
    Serial.print(level);
    Serial.print(",\"temp_c\":");
    if (isnan(t)) Serial.print("null"); else Serial.print(t, 1);
    Serial.print(",\"humidity\":");
    if (isnan(h)) Serial.print("null"); else Serial.print(h, 0);
    Serial.println("}");
  }
  // gentle beep pattern while an alert asks for it (critical only)
  if (buzz && now - lastBeep > 1500) { lastBeep = now; tone(PIN_BUZZER, 2200, 180); }
}
