# INBETWEEN Wokwi project

Open a new ESP32 DevKit V1 project at [Wokwi](https://wokwi.com/projects/new/esp32), then add this folder's `diagram.json`, `sketch.ino`, and `libraries.txt`. Copy `config.example.h` to `config.h`; config.h is gitignored. For local simulation without a backend, leave the URL placeholder. The Serial Monitor still shows JSON samples and the LEDs/LCD/buzzer work locally.

Adjust temperature and humidity from the DHT22 popup; use the LDR and soil potentiometer controls for light and soil proxy readings. The reservoir button is fail-safe: released or disconnected means LOW water; press it to indicate water available. The button label is a prompt to think of it as a reservoir override, not a physical float.

Public Wokwi networking cannot reach the computer's localhost. Use a public HTTPS tunnel/deployed endpoint with `SERVER_ROOT_CA` configured, or use Wokwi's Private IoT Gateway with `host.wokwi.internal`. This project has not been run in the Wokwi simulator, and network reachability must be tested in the chosen Wokwi setup.

All actuator outputs are simulation LEDs. For hardware, use a suitable relay/MOSFET driver and separate load supply; never power a motor from GPIO. Physical LCD I2C pull-ups must be safe for 3.3V ESP32 pins. Add a DHT22 data pull-up to 3.3V on a physical circuit if your module does not include one.
