import serial
import threading
import time

# 🔴 CHANGE ONLY IF COM PORT DIFFERENT
COM_PORT = "COM4"
BAUD_RATE = 115200

# 🔁 Shared live sensor data
sensor_data = {
    "heart_rate": None,
    "spo2": None,
    "status": "DISCONNECTED"
}

def read_sensor():
    global sensor_data
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
        sensor_data["status"] = "CONNECTED"
        print(f"✅ Sensor connected on {COM_PORT}")
        time.sleep(2)

        while True:
            if ser.in_waiting:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                print("RAW:", line)

                # ❌ Ignore boot logs
                if "ets" in line.lower() or "boot" in line.lower() or "rst" in line.lower():
                    continue

                # ❌ NO FINGER → RESET VALUES
                if "No finger" in line:
                    sensor_data["heart_rate"] = None
                    sensor_data["spo2"] = None
                    sensor_data["status"] = "CONNECTED"
                    continue

                # ✅ Parse HR + SpO2
                if "HR" in line and "SpO2" in line:
                    try:
                        hr = int(line.split("HR")[1].split("BPM")[0].replace(":", "").strip())
                        spo2 = int(line.split("SpO2")[1].replace(":", "").replace("%", "").strip())

                        sensor_data["heart_rate"] = hr
                        sensor_data["spo2"] = spo2
                        sensor_data["status"] = "CONNECTED"

                    except Exception as e:
                        print("❌ Parse error:", e)

            time.sleep(0.2)

    except Exception as e:
        sensor_data["status"] = "DISCONNECTED"
        print("❌ Sensor error:", e)

def start_sensor_thread():
    t = threading.Thread(target=read_sensor, daemon=True)
    t.start()
