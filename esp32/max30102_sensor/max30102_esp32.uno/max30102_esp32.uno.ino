#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include "spo2_algorithm.h"

MAX30105 particleSensor;

// Heart rate variables
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute;
int beatAvg;

// SpO2 variables
uint32_t irBuffer[100];
uint32_t redBuffer[100];
int32_t spo2;
int8_t validSPO2;
int32_t heartRate;
int8_t validHeartRate;

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("❌ MAX30102 not found");
    while (1);
  }

  particleSensor.setup(); // default config
  particleSensor.setPulseAmplitudeRed(0x1F);
  particleSensor.setPulseAmplitudeIR(0x1F);

  Serial.println("✅ MAX30102 initialized");
}

void loop() {

  // Collect 100 samples
  for (byte i = 0; i < 100; i++) {
    while (particleSensor.available() == false)
      particleSensor.check();

    redBuffer[i] = particleSensor.getRed();
    irBuffer[i] = particleSensor.getIR();
    particleSensor.nextSample();
  }

  // Calculate HR & SpO2
  maxim_heart_rate_and_oxygen_saturation(
    irBuffer, 100, redBuffer,
    &spo2, &validSPO2,
    &heartRate, &validHeartRate
  );

  // Finger detection
  if (irBuffer[99] < 10000) {
    Serial.println("❌ No finger detected");
  } else {

    Serial.print("❤️ HR: ");
    if (validHeartRate)
      Serial.print(heartRate);
    else
      Serial.print("--");

    Serial.print(" BPM | 🫁 SpO2: ");
    if (validSPO2)
      Serial.print(spo2);
    else
      Serial.print("--");

    Serial.println(" %");
  }

  delay(1000);
}
