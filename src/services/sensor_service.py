
import serial
import threading
import time

COM_PORT = "COM4"
BAUD_RATE = 115200

sensor_data = {
    "heart_rate": "--",
    "spo2": "--",
    "status": "DISCONNECTED"
}

_sensor_thread = None

def read_sensor():
    global sensor_data

    try:
        ser = serial.Serial(
            COM_PORT,
            BAUD_RATE,
            timeout=1
        )

        sensor_data["status"] = "CONNECTED"
        print(f"✅ Sensor connected on {COM_PORT}")
        time.sleep(3)

        while True:
            if ser.in_waiting:
                line = ser.readline().decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

                print("RAW:", line)

                if any(
                    x in line.lower()
                    for x in ["ets","boot","rst"]
                ):
                    continue

                if "No finger" in line:
                    sensor_data["heart_rate"] = "--"
                    sensor_data["spo2"] = "--"
                    sensor_data["status"] = "CONNECTED"
                    print("👆 Waiting for finger")
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
                            print("⏳ Sensor reading invalid, waiting for valid data")
                            sensor_data["status"] = "CONNECTED"
                            continue

                        hr = int(hr_str)
                        spo2 = int(spo2_str)

                        sensor_data["heart_rate"] = hr
                        sensor_data["spo2"] = spo2
                        sensor_data["status"] = "CONNECTED"

                        print(f"❤️ HR={hr} | 🫁 SpO2={spo2}")

                    except Exception as e:
                        print(f"❌ Parse Error: {e}")
                        sensor_data["status"] = "CONNECTED"

            time.sleep(0.2)

    except Exception as e:
        sensor_data["status"] = "DISCONNECTED"
        print(f"❌ Sensor error: {e}")


def start_sensor_thread():
    global _sensor_thread
    
    if _sensor_thread is None or not _sensor_thread.is_alive():
        _sensor_thread = threading.Thread(target=read_sensor, daemon=True)
        _sensor_thread.start()
        print("🔄 Sensor thread started")

