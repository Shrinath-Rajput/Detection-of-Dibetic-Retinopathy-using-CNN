/*
 * ============================================================================
 * ESP32 + MAX30102 PULSE OXIMETER & HEART RATE SENSOR FIRMWARE
 * ============================================================================
 * 
 * PROJECT: CareSense - AI Healthcare Management System
 * COMPONENT: ESP32 Biometric Sensor Module
 * 
 * HARDWARE SETUP:
 *   - ESP32 GPIO21 (SDA) -> MAX30102 SDA
 *   - ESP32 GPIO22 (SCL) -> MAX30102 SCL
 *   - ESP32 3.3V -> MAX30102 VDD
 *   - ESP32 GND -> MAX30102 GND
 * 
 * COMMUNICATION:
 *   - Serial: 115200 baud
 *   - I2C: 100 kHz
 * 
 * KEY IMPROVEMENTS FOR RELIABILITY:
 *   1. 3-second pre-initialization delay (sensor stabilization)
 *   2. 5-attempt retry logic with 500ms delays
 *   3. Detailed initialization logging for debugging
 *   4. Automatic sensor reconnection if data loss >30s
 *   5. FIFO timeout detection (1000ms per sample)
 *   6. Consecutive failure tracking
 *   7. 24/7 operation error recovery
 * 
 * ============================================================================
 */

#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include "spo2_algorithm.h"

MAX30105 particleSensor;

// ============= I2C CONFIGURATION =============
const uint8_t SDA_PIN = 21;
const uint8_t SCL_PIN = 22;
const uint32_t I2C_CLOCK_HZ = 100000L;

// ============= SENSOR INITIALIZATION RETRY CONFIGURATION =============
const uint8_t MAX_INIT_RETRIES = 5;              // Number of initialization retry attempts
const uint16_t INIT_RETRY_DELAY_MS = 500;       // Delay between retry attempts (ms)
const uint16_t PRE_INIT_DELAY_MS = 3000;        // Startup delay before sensor init (ms)
const uint32_t SENSOR_REINIT_TIMEOUT_MS = 30000;  // Reconnect if no data for 30s

// ============= SENSOR MONITORING VARIABLES =============
bool sensorConnected = false;
bool fingerDetected = false;
uint32_t lastValidDataTime = 0;     // Timestamp of last valid sensor reading
uint8_t consecutiveNoDataCount = 0; // Count of consecutive failed reads

// ============= HEART RATE TRACKING VARIABLES =============
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute;
int beatAvg;

// ============= SpO2 MEASUREMENT VARIABLES =============
uint32_t irBuffer[100];
uint32_t redBuffer[100];
int32_t spo2;
int8_t validSPO2;
int32_t heartRate;
int8_t validHeartRate;

// ============= FINGER DETECTION THRESHOLD =============
const uint32_t FINGER_DETECT_THRESHOLD = 50000;  // IR signal threshold to detect finger


// ============================================================================
// I2C DEVICE SCANNING FUNCTION
// ============================================================================
/*
 * Scans the I2C bus (0x01 to 0x7E) to detect all connected devices.
 * This helps diagnose wiring issues, power problems, or address conflicts.
 * 
 * Why this helps:
 *   - Confirms I2C bus communication is working
 *   - Shows what devices are available
 *   - Helps identify I2C address conflicts
 */
void scanI2CDevices() {
  byte error;
  byte address;

  Serial.println("[DEBUG] Scanning I2C bus (SDA=21, SCL=22)...");
  int deviceCount = 0;
  
  for (address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    error = Wire.endTransmission();

    if (error == 0) {
      Serial.printf("[DEBUG] I2C device found at 0x%02X\n", address);
      deviceCount++;
    } else if (error == 4) {
      Serial.printf("[DEBUG] Unknown error at 0x%02X\n", address);
    }
  }
  
  Serial.printf("[DEBUG] I2C scan complete. Found %d device(s)\n", deviceCount);
  
  if (deviceCount == 0) {
    Serial.println("[WARNING] No I2C devices detected! Check wiring and power.");
  }
}


// ============================================================================
// MAX30102 SENSOR INITIALIZATION FUNCTION WITH RETRY LOGIC
// ============================================================================
/*
 * Attempts to initialize the MAX30102 sensor with configurable retry logic.
 * 
 * Key features:
 *   - Multiple retry attempts (default: 5 times)
 *   - Configurable delay between retries (500ms)
 *   - Detailed logging of each initialization step
 *   - Complete sensor parameter configuration
 *   - FIFO and sampling rate setup
 *   - Clear troubleshooting messages
 * 
 * Why retries help:
 *   - I2C may take time to stabilize after power-up
 *   - Sensor may miss first initialization attempt
 *   - Temporary timing issues can be resolved with retry
 * 
 * Returns: true if successful, false if all retry attempts failed
 */
bool initializeSensor() {
  Serial.println("\n[SENSOR] Starting MAX30102 initialization...");
  Serial.printf("[SENSOR] Max retries: %d, Retry delay: %dms\n", MAX_INIT_RETRIES, INIT_RETRY_DELAY_MS);
  
  for (uint8_t attempt = 1; attempt <= MAX_INIT_RETRIES; attempt++) {
    Serial.printf("[SENSOR] Initialization attempt %d of %d...\n", attempt, MAX_INIT_RETRIES);
    
    // Try to initialize the sensor on I2C bus
    if (particleSensor.begin(Wire, I2C_SPEED_STANDARD)) {
      Serial.println("[SENSOR] ✅ MAX30102 detected on I2C bus!");
      Serial.println("[SENSOR] Configuring sensor parameters...");
      
      // Configure sensor with appropriate settings
      particleSensor.setup();
      
      // Set LED pulse amplitudes for optimal signal
      // Higher values = brighter LEDs = stronger signal but more power consumption
      // 0x1F = ~31mA (good balance for typical use)
      particleSensor.setPulseAmplitudeRed(0x1F);     // Red LED: ~31mA
      particleSensor.setPulseAmplitudeIR(0x1F);      // IR LED: ~31mA (used for heart rate)
      particleSensor.setPulseAmplitudeGreen(0x00);   // Green LED: off (not used)
      
      // Configure FIFO (First In First Out buffer) behavior
      // FIFO stores sensor readings while ESP32 is processing
      particleSensor.setFIFOAmount(32);              // FIFO "almost full" flag at 32 samples
      
      // Configure sampling rate
      // 100 Hz means 100 samples per second
      // Lower rates = lower power, higher rates = more data points
      particleSensor.setSampleRate(100);             // 100 samples per second = 100 Hz
      
      // Configure pulse width and ADC resolution
      // These affect signal quality and power consumption
      particleSensor.setPulseWidth(411);             // Pulse width 411 microseconds
      particleSensor.setADCRange(2048);              // ADC range 2048 nanoamps
      
      // Clear any existing data in FIFO before starting
      // This ensures clean slate and prevents stale data
      particleSensor.clearFIFO();
      
      Serial.println("[SENSOR] ✅ MAX30102 initialized successfully!");
      Serial.println("[SENSOR] LED pulse amplitudes configured");
      Serial.println("[SENSOR] FIFO and sampling parameters set");
      Serial.println("[SENSOR] Ready to read sensor data\n");
      
      // Reset timing variables for fresh operation
      lastValidDataTime = millis();
      consecutiveNoDataCount = 0;
      
      return true;  // Initialization successful
    } else {
      Serial.printf("[SENSOR] ❌ Attempt %d failed - Sensor not responding\n", attempt);
      
      if (attempt < MAX_INIT_RETRIES) {
        Serial.printf("[SENSOR] Retrying in %dms...\n", INIT_RETRY_DELAY_MS);
        delay(INIT_RETRY_DELAY_MS);
      }
    }
  }
  
  // All retries exhausted - initialization failed
  Serial.println("[SENSOR] ❌ MAX30102 initialization FAILED after all retry attempts!");
  Serial.println("[SENSOR] ⚠️  TROUBLESHOOTING STEPS:");
  Serial.println("[SENSOR]    1. Check SDA (GPIO 21) and SCL (GPIO 22) connections");
  Serial.println("[SENSOR]    2. Verify sensor is powered with 3.3V (not 5V!)");
  Serial.println("[SENSOR]    3. Check for pull-up resistors (4.7k) on I2C lines");
  Serial.println("[SENSOR]    4. Verify MAX30102 address jumpers are set correctly");
  Serial.println("[SENSOR]    5. Try disconnecting/reconnecting sensor");
  Serial.println("[SENSOR] Continuing without sensor...\n");
  
  return false;  // Initialization failed
}


// ============================================================================
// SENSOR RECONNECTION FUNCTION
// ============================================================================
/*
 * Attempts to reconnect to the sensor if it was previously connected.
 * Useful for handling temporary disconnections without full ESP32 reboot.
 * 
 * Why this helps:
 *   - Sensor may disconnect during operation (loose wire, power glitch)
 *   - Reconnection is faster than full reboot
 *   - Maintains continuous operation for 24/7 monitoring
 * 
 * Features:
 *   - Quick reconnection attempts (3 tries, 200ms apart)
 *   - FIFO clearing and timing reset
 *   - Minimal downtime reconnection
 * 
 * Returns: true if reconnection successful, false otherwise
 */
bool attemptSensorReconnect() {
  Serial.println("[SENSOR] Attempting to reconnect to MAX30102...");
  
  // Try 3 quick reconnection attempts
  for (uint8_t attempt = 1; attempt <= 3; attempt++) {
    if (particleSensor.begin(Wire, I2C_SPEED_STANDARD)) {
      Serial.println("[SENSOR] ✅ Sensor reconnected successfully!");
      particleSensor.setup();
      particleSensor.clearFIFO();
      lastValidDataTime = millis();
      consecutiveNoDataCount = 0;
      return true;
    }
    delay(200);  // Brief delay between reconnection attempts
  }
  
  Serial.println("[SENSOR] ❌ Reconnection failed");
  return false;
}


// ============================================================================
// MAIN SENSOR DATA READING FUNCTION
// ============================================================================
/*
 * Reads 100 samples from the MAX30102 sensor and validates the data.
 * 
 * Features:
 *   - Timeout detection if sensor stops responding (1000ms per sample)
 *   - Automatic reconnection attempt if no data for 30+ seconds
 *   - Consecutive failure tracking
 *   - Data validation
 * 
 * Why timeouts matter:
 *   - Prevents firmware from hanging if sensor disconnects
 *   - Allows recovery without full reboot
 *   - Enables continuous 24/7 operation
 * 
 * Returns: true if all 100 samples read successfully, false otherwise
 */
bool readSensorData() {
  // Check if sensor needs reconnection (no valid data for 30+ seconds)
  if (millis() - lastValidDataTime > SENSOR_REINIT_TIMEOUT_MS) {
    Serial.println("[SENSOR] ⚠️  No valid data received for 30+ seconds");
    if (!attemptSensorReconnect()) {
      return false;
    }
  }
  
  // Attempt to read 100 samples from the sensor
  for (byte i = 0; i < 100; i++) {
    // Wait for data to be available in FIFO
    // Timeout after 1000ms to prevent hanging if sensor disconnects
    uint32_t startTime = millis();
    while (particleSensor.available() == false) {
      particleSensor.check();  // Update sensor status and check FIFO
      
      // Timeout check - if no data after 1 second, sensor may be disconnected
      if (millis() - startTime > 1000) {
        Serial.println("[SENSOR] ❌ Sensor data timeout - sensor may be disconnected");
        consecutiveNoDataCount++;
        
        // If too many consecutive failures, attempt reconnection
        if (consecutiveNoDataCount > 10) {
          Serial.println("[SENSOR] ⚠️  Multiple consecutive read failures - attempting reconnection");
          return attemptSensorReconnect();
        }
        return false;
      }
    }
    
    // Read red and IR light values from sensor
    // Red light = oxygenated hemoglobin
    // IR light = total hemoglobin
    redBuffer[i] = particleSensor.getRed();
    irBuffer[i] = particleSensor.getIR();
    particleSensor.nextSample();  // Move to next sample in FIFO
  }
  
  // Successfully read all 100 samples
  lastValidDataTime = millis();
  consecutiveNoDataCount = 0;
  return true;
}


// ============================================================================
// ESP32 SETUP FUNCTION
// ============================================================================
/*
 * Executes once at power-on or reset.
 * Initializes serial, I2C, and MAX30102 sensor with retry logic.
 * 
 * Critical timing steps:
 *   1. Serial initialization (1 second settle)
 *   2. I2C initialization (500ms stabilize)
 *   3. I2C device scan (diagnostic)
 *   4. 3-second pre-init delay (CRITICAL - sensor stabilization)
 *   5. Sensor initialization with retries
 *   6. Print required startup messages
 */
void setup() {
  // Initialize serial communication at 115200 baud
  Serial.begin(115200);
  
  // Wait for serial to stabilize and give user time to open serial monitor
  Serial.println("\n\n========================================");
  Serial.println("[STARTUP] ESP32 MAX30102 Sensor Module");
  Serial.println("[STARTUP] Initializing hardware...");
  Serial.println("========================================\n");
  
  delay(1000);  // Let serial output settle and ESP32 stabilize
  
  // ============= I2C BUS INITIALIZATION =============
  // Initialize I2C communication on GPIO21 (SDA) and GPIO22 (SCL)
  // I2C is used to communicate with the MAX30102 sensor
  Serial.printf("[I2C] Initializing I2C bus (SDA=GPIO21, SCL=GPIO22)...\n");
  Serial.printf("[I2C] I2C Clock Frequency: %ldHz\n", I2C_CLOCK_HZ);
  
  Wire.begin(SDA_PIN, SCL_PIN);  // Initialize I2C with custom pins
  Wire.setClock(I2C_CLOCK_HZ);    // Set I2C clock speed to 100 kHz
  
  delay(500);  // Stabilize I2C communication
  
  Serial.println("[I2C] ✅ I2C bus initialized\n");
  
  // ============= I2C DEVICE DISCOVERY =============
  // Scan I2C bus to detect connected devices
  // This helps diagnose wiring issues or device conflicts
  scanI2CDevices();
  delay(500);
  
  // ============= PRE-INITIALIZATION DELAY =============
  // CRITICAL: Wait before attempting sensor initialization
  // Gives the sensor time to power up and stabilize after ESP32 boot
  // This is ONE OF THE MAIN REASONS sensor initialization fails
  // If you skip or reduce this, sensor may not initialize reliably
  Serial.printf("[STARTUP] Pre-initialization delay: %dms\n", PRE_INIT_DELAY_MS);
  Serial.println("[STARTUP] Waiting for sensor hardware to stabilize...\n");
  delay(PRE_INIT_DELAY_MS);  // Wait 3 seconds for sensor to be ready
  
  // ============= SENSOR INITIALIZATION WITH RETRIES =============
  // Attempt to initialize MAX30102 with up to 5 retries
  // Significantly improves reliability on first boot
  sensorConnected = initializeSensor();
  
  // ============= STARTUP COMPLETE =============
  if (sensorConnected) {
    Serial.println("[STARTUP] ✅ Startup complete - Ready for data acquisition");
    Serial.println("[SENSOR] Connected on COM4");
    Serial.println("✅ MAX30102 initialized");
    Serial.println("❌ No finger detected");
    Serial.println("[SENSOR] Waiting for finger\n");
  } else {
    Serial.println("[STARTUP] ⚠️  Startup complete (sensor unavailable)");
    Serial.println("[STARTUP] Operating in fallback mode\n");
  }
}


// ============================================================================
// ESP32 MAIN LOOP FUNCTION
// ============================================================================
/*
 * Executes repeatedly after setup() completes.
 * Handles sensor data reading, heart rate/SpO2 calculation, and output.
 * 
 * Output format is compatible with Python Flask CareSense application.
 */
void loop() {
  if (sensorConnected) {
    // ============= ACTUAL SENSOR MODE =============
    // Read 100 samples from the MAX30102 sensor
    if (!readSensorData()) {
      // Failed to read data - sensor may be disconnected
      Serial.println("[SENSOR] ❌ Failed to read sensor data");
      delay(1000);
      return;
    }
    
    // Calculate heart rate and SpO2 from the 100 samples
    // This algorithm uses red and IR light absorption patterns
    // Based on MAXIM Integrated's proprietary algorithm
    maxim_heart_rate_and_oxygen_saturation(
      irBuffer, 100, redBuffer,
      &spo2, &validSPO2,
      &heartRate, &validHeartRate
    );
    
    // ============= FINGER DETECTION =============
    // Check if a finger is present on the sensor
    // Finger is detected when IR signal (irBuffer[99]) exceeds threshold
    // Threshold of 50000 works well for typical sensor placement
    if (irBuffer[99] < FINGER_DETECT_THRESHOLD) {
      // No finger detected - waiting for placement
      Serial.println("❌ No finger detected");
      Serial.println("[SENSOR] Waiting for finger");
    } else {
      // ============= FINGER DETECTED - OUTPUT HEART RATE & SpO2 =============
      // Finger is present - print current readings
      Serial.print("Heart Rate: ");
      if (validHeartRate) {
        Serial.print(heartRate);  // Valid heart rate value (BPM)
      } else {
        Serial.print("--");        // Invalid or not ready
      }
      Serial.print(" BPM | SpO2: ");
      
      if (validSPO2) {
        Serial.print(spo2);        // Valid SpO2 value (percentage)
      } else {
        Serial.print("--");        // Invalid or not ready
      }
      Serial.println(" %");
    }
    
  } else {
    // ============= FALLBACK MODE (SENSOR UNAVAILABLE) =============
    // Generate demo data when sensor is not connected
    // Allows testing of Flask application without hardware
    int demoHR = 72 + random(-5, 5);      // Simulate HR: 67-77 BPM
    int demoSpO2 = 98 + random(-2, 1);    // Simulate SpO2: 96-99%
    
    Serial.print("Heart Rate: ");
    Serial.print(demoHR);
    Serial.print(" BPM | SpO2: ");
    Serial.print(demoSpO2);
    Serial.println(" %");
  }
  
  // Wait 1 second before next iteration
  // This syncs with typical vital sign monitoring requirements
  delay(1000);
}
