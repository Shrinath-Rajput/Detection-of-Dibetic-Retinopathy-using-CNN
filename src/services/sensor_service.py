
import serial
import threading
import time
import sys

COM_PORT = "COM4"
BAUD_RATE = 115200

sensor_data = {
    "heart_rate": "--",
    "spo2": "--",
    "status": "DISCONNECTED"
}

_sensor_thread = None

def safe_print(message):
    """Print safely with Unicode encoding fallback"""
    try:
        print(message)
    except UnicodeEncodeError:
        # Fallback for systems that don't support Unicode
        print(message.encode('utf-8', errors='replace').decode('utf-8', errors='replace'))

def read_sensor():
    global sensor_data
    
    retry_count = 0
    max_retries = 3

    try:
        while retry_count < max_retries:
            try:
                ser = serial.Serial(
                    COM_PORT,
                    BAUD_RATE,
                    timeout=1
                )

                sensor_data["status"] = "CONNECTED"
                safe_print(f"[SENSOR] Connected on {COM_PORT}")
                time.sleep(3)
                retry_count = 0  # Reset retry count on successful connection

                while True:
                    if ser.in_waiting:
                        line = ser.readline().decode(
                            "utf-8",
                            errors="ignore"
                        ).strip()

                        if line:
                            safe_print(f"[RAW] {line}")

                        if any(
                            x in line.lower()
                            for x in ["ets","boot","rst"]
                        ):
                            continue

                        if "No finger" in line:
                            sensor_data["heart_rate"] = "--"
                            sensor_data["spo2"] = "--"
                            sensor_data["status"] = "CONNECTED"
                            safe_print("[SENSOR] Waiting for finger")
                            continue

                        if "HR" in line and "SpO2" in line:
                            try:
                                hr_str = (
                                    line.split("HR")[1]
                                    .split("BPM")[0]
                                    .replace(":","")
                                    .strip()
                                )

                                spo2_str = (
                                    line.split("SpO2")[1]
                                    .replace(":","")
                                    .replace("%","")
                                    .strip()
                                )

                                if (
                                    "--" in hr_str
                                    or
                                    "--" in spo2_str
                                    or
                                    not hr_str.isdigit()
                                    or
                                    not spo2_str.isdigit()
                                ):
                                    sensor_data["heart_rate"] = "--"
                                    sensor_data["spo2"] = "--"
                                    safe_print("[SENSOR] Invalid reading, waiting for valid data")
                                    sensor_data["status"] = "CONNECTED"
                                    continue

                                hr = int(hr_str)
                                spo2 = int(spo2_str)

                                sensor_data["heart_rate"] = hr
                                sensor_data["spo2"] = spo2
                                sensor_data["status"] = "CONNECTED"

                                safe_print(f"[SENSOR] HR={hr} BPM | SpO2={spo2}%")

                            except Exception as e:
                                safe_print(f"[SENSOR] Parse Error: {e}")
                                sensor_data["status"] = "CONNECTED"

                    time.sleep(0.2)

            except serial.SerialException as e:
                retry_count += 1
                sensor_data["status"] = "DISCONNECTED"
                safe_print(f"[SENSOR] Connection failed (attempt {retry_count}/{max_retries}): {e}")
                if retry_count < max_retries:
                    time.sleep(2)  # Wait before retry
                else:
                    safe_print(f"[SENSOR] Failed to connect to {COM_PORT} after {max_retries} attempts. Running without sensor.")
                    sensor_data["status"] = "DISCONNECTED"
                    # Exit gracefully, app can run without sensor
                    break
                    
    except Exception as e:
        sensor_data["status"] = "DISCONNECTED"
        safe_print(f"[SENSOR] Unexpected error: {e}")


def start_sensor_thread():
    global _sensor_thread
    
    if _sensor_thread is None or not _sensor_thread.is_alive():
        _sensor_thread = threading.Thread(target=read_sensor, daemon=True)
        _sensor_thread.start()
        safe_print("[SENSOR] Thread started")

