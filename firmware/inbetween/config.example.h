#pragma once
// Copy to config.h (gitignored) and set values before flashing.
#define WIFI_SSID "Wokwi-GUEST"
#define WIFI_PASSWORD ""
// Physical ESP32: use the backend host's LAN IP, e.g. http://192.168.1.20:8000
// Wokwi: use a publicly reachable HTTPS tunnel URL; localhost is not reachable.
#define SERVER_URL "https://YOUR-TUNNEL-HOST"
#define DEVICE_ID "inbetween_esp32_01"
// Keep false unless you deliberately configure a trusted CA certificate.
#define TLS_INSECURE_FOR_DEVELOPMENT false
#define SERVER_ROOT_CA "" // paste server/tunnel root CA PEM here for verified HTTPS
