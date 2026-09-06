/*
 * ============================================================================
 * ESP32 + MAX30102 PULSE OXIMETER & HEART RATE SENSOR FIRMWARE
 * ============================================================================
 *
 * HARDWARE CONNECTIONS:
 *   - ESP32 GPIO21 (SDA) -> MAX30102 SDA
 *   - ESP32 GPIO22 (SCL) -> MAX30102 SCL
 *   - ESP32 3.3V or VIN  -> MAX30102 VDD/VIN
 *   - ESP32 GND          -> MAX30102 GND
 *
 * SERIAL COMMUNICATION: 115200 baud
 * I2C HARDWARE BUS: SDA=21, SCL=22, 100kHz
 * ============================================================================
 */

#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include "spo2_algorithm.h"

MAX30105 particleSensor;

// Pin Definitions & I2C Address
const uint8_t SDA_PIN = 21;
const uint8_t SCL_PIN = 22;

// Sensor & Detection State
bool sensorConnected = false;
bool fingerDetected = false;
uint32_t latestIR = 0;
const uint32_t FINGER_DETECT_THRESHOLD = 20000; // IR threshold for finger contact

// Buffer for Maxim Algorithm (100 samples)
const int MAX_BUFFER_LENGTH = 100;
uint32_t irBuffer[MAX_BUFFER_LENGTH];
uint32_t redBuffer[MAX_BUFFER_LENGTH];
int bufferIndex = 0;
bool bufferFilled = false;

// Vital Signs
int32_t spo2 = 0;
int8_t validSPO2 = 0;
int32_t heartRate = 0;
int8_t validHeartRate = 0;

// Rolling Beat Detection
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
int beatAvg = 0;

// Timing Trackers
unsigned long lastHeartbeatTime = 0;
unsigned long lastDataPrintTime = 0;
unsigned long lastAlgorithmTime = 0;
unsigned long lastRetryTime = 0;

// Sensor Initialization
bool initSensor() {
  Serial.println("[SENSOR] Initializing MAX30102...");

  bool ok = false;
  for (int attempt = 1; attempt <= 5; attempt++) {
    if (particleSensor.begin(Wire, 100000L)) {
      ok = true;
      break;
    }
    delay(150);
  }

  if (!ok) {
    Serial.println("MAX30102 initialization failed");
    Serial.println("STATUS:CONNECTED");
    Serial.println("FINGER:0");
    Serial.println("HR:--");
    Serial.println("SPO2:--");
    return false;
  }

  // Setup MAX30102 parameters:
  // power ~10.6mA (0x35), 4 sample average, mode 2 (Red + IR), 100Hz, 411us pulse width, 4096 ADC
  particleSensor.setup(0x35, 4, 2, 100, 411, 4096);
  particleSensor.setPulseAmplitudeRed(0x35);
  particleSensor.setPulseAmplitudeIR(0x35);
  particleSensor.enableFIFORollover();
  particleSensor.clearFIFO();

  // Reset buffers
  bufferIndex = 0;
  bufferFilled = false;
  rateSpot = 0;
  lastBeat = 0;
  beatAvg = 0;
  spo2 = 0;
  validSPO2 = 0;
  heartRate = 0;
  validHeartRate = 0;
  for (byte x = 0; x < RATE_SIZE; x++) rates[x] = 0;

  Serial.println("[SENSOR] MAX30102 initialized successfully");
  Serial.println("STATUS:CONNECTED");
  Serial.println("FINGER:0");
  Serial.println("HR:--");
  Serial.println("SPO2:--");
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n\n========================================");
  Serial.println("[STARTUP] ESP32 MAX30102 Sensor Module");
  Serial.println("========================================\n");

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000L);
  Wire.setTimeOut(50);
  delay(200);

  // Attempt sensor initialization
  sensorConnected = initSensor();
  lastHeartbeatTime = millis();
}

void loop() {
  unsigned long currentMillis = millis();

  // 1. If sensor failed initial detection, retry every 2 seconds
  if (!sensorConnected) {
    if (currentMillis - lastRetryTime >= 2000) {
      lastRetryTime = currentMillis;
      Wire.begin(SDA_PIN, SCL_PIN);
      Wire.setClock(100000L);
      sensorConnected = initSensor();
    }
    return;
  }

  // 2. Continuous sample acquisition
  particleSensor.check();

  while (particleSensor.available()) {
    uint32_t currentIR = particleSensor.getFIFOIR();
    uint32_t currentRed = particleSensor.getFIFORed();
    particleSensor.nextSample();

    latestIR = currentIR;

    if (currentIR >= FINGER_DETECT_THRESHOLD) {
      // Real-time beat detection
      if (checkForBeat(currentIR)) {
        long delta = currentMillis - lastBeat;
        lastBeat = currentMillis;
        float bpm = 60.0 / (delta / 1000.0);
        if (bpm >= 45.0 && bpm <= 200.0) {
          rates[rateSpot++] = (byte)bpm;
          rateSpot %= RATE_SIZE;
          int sum = 0, count = 0;
          for (byte x = 0; x < RATE_SIZE; x++) {
            if (rates[x] > 0) {
              sum += rates[x];
              count++;
            }
          }
          if (count > 0) {
            beatAvg = sum / count;
          }
        }
      }

      // Collect for SpO2 calculation
      redBuffer[bufferIndex] = currentRed;
      irBuffer[bufferIndex] = currentIR;
      bufferIndex++;
      if (bufferIndex >= MAX_BUFFER_LENGTH) {
        bufferIndex = 0;
        bufferFilled = true;
      }
    }
  }

  // 3. Finger Presence & Status Reporting
  // ONCE SENSOR IS INITIALIZED, STATUS REMAINS CONNECTED!
  if (latestIR < FINGER_DETECT_THRESHOLD) {
    // -------------------------------------------------------------
    // NO FINGER PLACED:
    // Status stays CONNECTED! Heart Rate = --, SpO2 = --
    // -------------------------------------------------------------
    fingerDetected = false;
    bufferIndex = 0;
    bufferFilled = false;
    rateSpot = 0;
    lastBeat = 0;
    beatAvg = 0;
    spo2 = 0;
    validSPO2 = 0;
    heartRate = 0;
    validHeartRate = 0;
    for (byte x = 0; x < RATE_SIZE; x++) rates[x] = 0;

    // Heartbeat every 1 second
    if (currentMillis - lastHeartbeatTime >= 1000) {
      lastHeartbeatTime = currentMillis;
      Serial.println("STATUS:CONNECTED");
      Serial.println("FINGER:0");
      Serial.println("HR:--");
      Serial.println("SPO2:--");
      Serial.println("[SENSOR] Waiting for finger");
    }
  } else {
    // -------------------------------------------------------------
    // FINGER DETECTED:
    // Status stays CONNECTED! Read REAL MAX30102 data
    // -------------------------------------------------------------
    fingerDetected = true;

    // Run Maxim SpO2 algorithm once buffer is ready
    if (bufferFilled && (currentMillis - lastAlgorithmTime >= 1000)) {
      lastAlgorithmTime = currentMillis;
      maxim_heart_rate_and_oxygen_saturation(
        irBuffer, MAX_BUFFER_LENGTH, redBuffer,
        &spo2, &validSPO2,
        &heartRate, &validHeartRate
      );
    }

    // Output live readings every 800ms
    if (currentMillis - lastDataPrintTime >= 800) {
      lastDataPrintTime = currentMillis;
      lastHeartbeatTime = currentMillis;

      Serial.println("[SENSOR] Finger detected");
      Serial.println("STATUS:CONNECTED");
      Serial.println("FINGER:1");

      int displayHR = 0;
      if (validHeartRate && heartRate >= 45 && heartRate <= 200) {
        displayHR = heartRate;
      } else if (beatAvg >= 45 && beatAvg <= 200) {
        displayHR = beatAvg;
      }

      int displaySpO2 = 0;
      if (validSPO2 && spo2 >= 70 && spo2 <= 100) {
        displaySpO2 = spo2;
      }

      if (displayHR > 0) {
        Serial.printf("HR:%d\n", displayHR);
      } else {
        Serial.println("HR:--");
      }

      if (displaySpO2 > 0) {
        Serial.printf("SPO2:%d\n", displaySpO2);
      } else {
        Serial.println("SPO2:--");
      }

      // Backward compatible human readable format
      Serial.print("Heart Rate: ");
      if (displayHR > 0) {
        Serial.print(displayHR);
      } else {
        Serial.print("--");
      }
      Serial.print(" BPM | SpO2: ");
      if (displaySpO2 > 0) {
        Serial.print(displaySpO2);
      } else {
        Serial.print("--");
      }
      Serial.println(" %");
    }
  }

  delay(10);
}
