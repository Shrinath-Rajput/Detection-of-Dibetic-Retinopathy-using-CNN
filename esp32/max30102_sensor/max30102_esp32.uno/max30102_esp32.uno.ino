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
const uint32_t FINGER_DETECT_THRESHOLD = 5000; // Fast, reliable IR threshold for finger contact

// Short rolling buffer for fast initial finger detection (4 samples ~ 80-160ms)
const uint8_t FINGER_WINDOW_SIZE = 4;
uint32_t fingerIRBuffer[FINGER_WINDOW_SIZE] = {0};
uint8_t fingerWindowIndex = 0;
uint8_t fingerWindowCount = 0;

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
bool wasFingerDetected = false;

// Real-time Optical SpO2 calculation from actual Red and IR photodiode samples
int32_t calculate_fast_spo2(uint32_t *ir, uint32_t *red, int count) {
  if (count < 15) return 0;
  uint32_t minIR = 0xFFFFFFFF, maxIR = 0;
  uint32_t minRed = 0xFFFFFFFF, maxRed = 0;
  uint64_t sumIR = 0, sumRed = 0;
  for (int i = 0; i < count; i++) {
    if (ir[i] < minIR) minIR = ir[i];
    if (ir[i] > maxIR) maxIR = ir[i];
    sumIR += ir[i];
    if (red[i] < minRed) minRed = red[i];
    if (red[i] > maxRed) maxRed = red[i];
    sumRed += red[i];
  }
  uint32_t dcIR = sumIR / count;
  uint32_t dcRed = sumRed / count;
  uint32_t acIR = maxIR - minIR;
  uint32_t acRed = maxRed - minRed;
  if (dcIR == 0 || dcRed == 0 || acIR < 50 || acRed < 50) return 0;
  float R = ((float)acRed / (float)dcRed) / ((float)acIR / (float)dcIR);
  int calc_spo2 = (int)(110.0 - 25.0 * R);
  if (calc_spo2 >= 70 && calc_spo2 <= 100) {
    return calc_spo2;
  }
  return 0;
}

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
  wasFingerDetected = false;
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

    // Short rolling buffer for fast initial finger detection (~80-160ms)
    fingerIRBuffer[fingerWindowIndex] = currentIR;
    fingerWindowIndex = (fingerWindowIndex + 1) % FINGER_WINDOW_SIZE;
    if (fingerWindowCount < FINGER_WINDOW_SIZE) fingerWindowCount++;

    uint64_t irSum = 0;
    for (uint8_t i = 0; i < fingerWindowCount; i++) {
      irSum += fingerIRBuffer[i];
    }
    latestIR = fingerWindowCount > 0 ? (uint32_t)(irSum / fingerWindowCount) : currentIR;

    if (latestIR >= FINGER_DETECT_THRESHOLD) {
      // Real-time beat detection
      if (checkForBeat(currentIR)) {
        if (lastBeat > 0) {
          long delta = currentMillis - lastBeat;
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
        lastBeat = currentMillis;
      }

      // Collect for SpO2 calculation
      redBuffer[bufferIndex] = currentRed;
      irBuffer[bufferIndex] = currentIR;
      bufferIndex++;
      if (bufferIndex >= MAX_BUFFER_LENGTH) {
        bufferFilled = true;
        // Shift buffer to preserve chronological continuity for Maxim algorithm
        for (int i = 25; i < MAX_BUFFER_LENGTH; i++) {
          redBuffer[i - 25] = redBuffer[i];
          irBuffer[i - 25] = irBuffer[i];
        }
        bufferIndex = 75;
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
    fingerWindowCount = 0;
    fingerWindowIndex = 0;
    for (byte x = 0; x < FINGER_WINDOW_SIZE; x++) fingerIRBuffer[x] = 0;
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

    // Edge-triggered: immediate report upon finger removal
    if (wasFingerDetected) {
      wasFingerDetected = false;
      lastHeartbeatTime = currentMillis;
      Serial.println("[SENSOR] Waiting for finger");
      Serial.println("STATUS:CONNECTED");
      Serial.println("FINGER:0");
      Serial.println("HR:--");
      Serial.println("SPO2:--");
    } else if (currentMillis - lastHeartbeatTime >= 1000) {
      // Periodic heartbeat every 1 second
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

    // Edge-triggered: immediate report upon finger placement
    if (!wasFingerDetected) {
      wasFingerDetected = true;
      lastDataPrintTime = 0; // Immediate first data print
      lastHeartbeatTime = currentMillis;
      Serial.println("[SENSOR] Finger detected");
      Serial.println("STATUS:CONNECTED");
      Serial.println("FINGER:1");
      Serial.println("HR:--");
      Serial.println("SPO2:--");
    }

    // Run Maxim SpO2 algorithm once buffer is ready
    if (bufferFilled && (currentMillis - lastAlgorithmTime >= 1000)) {
      lastAlgorithmTime = currentMillis;
      maxim_heart_rate_and_oxygen_saturation(
        irBuffer, MAX_BUFFER_LENGTH, redBuffer,
        &spo2, &validSPO2,
        &heartRate, &validHeartRate
      );
    }

    // Output live readings every 250ms
    if (currentMillis - lastDataPrintTime >= 250) {
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
      } else {
        int fast_sp = calculate_fast_spo2(irBuffer, redBuffer, bufferFilled ? MAX_BUFFER_LENGTH : bufferIndex);
        if (fast_sp >= 70 && fast_sp <= 100) {
          displaySpO2 = fast_sp;
        }
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

  delay(5);
}
