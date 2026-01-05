import serial
import threading
import time

# =========================
# CONFIG
# =========================
COM_PORT = "COM4"        # 🔴 तुझा port
BAUD_RATE = 115200

# =========================
# SHARED SENSOR DATA
# =========================
sensor_data = {
    "heart_rate": None,
    "spo2": None,
    "status": "DISCONNECTED"
}

# =========================
# SENSOR READER THREAD
# =========================
def read_sensor():
    global sensor_data

    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)

        sensor_data["status"] = "CONNECTED"
        print(f"✅ Sensor Connected on {COM_PORT}")

        while True:
            try:
                if ser.in_waiting > 0:
                    raw = ser.readline()
                    line = raw.decode("utf-8", errors="ignore").strip()

                    if not line:
                        continue

                    print("RAW:", line)

                    # ❌ Ignore ESP noise
                    bad_words = ["ets", "rst", "boot", "load", "wifi"]
                    if any(word in line.lower() for word in bad_words):
                        continue

                    # ❌ No finger
                    if "no finger" in line.lower():
                        sensor_data["heart_rate"] = None
                        sensor_data["spo2"] = None
                        continue

                    # ✅ Expected format:
                    # HR: 78 BPM | SpO2: 97 %
                    if "HR" in line and "SpO2" in line:
                        hr = None
                        spo2 = None

                        hr_text = line.split("HR")[1].split("BPM")[0]
                        hr_text = hr_text.replace(":", "").strip()

                        spo2_text = line.split("SpO2")[1]
                        spo2_text = spo2_text.replace(":", "").replace("%", "").strip()

                        if hr_text.isdigit():
                            hr = int(hr_text)
                        if spo2_text.isdigit():
                            spo2 = int(spo2_text)

                        sensor_data["heart_rate"] = hr
                        sensor_data["spo2"] = spo2
                        sensor_data["status"] = "CONNECTED"

            except Exception as e:
                print("❌ Read error:", e)

            time.sleep(0.3)

    except Exception as e:
        sensor_data["status"] = "DISCONNECTED"
        print("❌ Sensor connection failed:", e)


# =========================
# THREAD STARTER
# =========================
def start_sensor_thread():
    t = threading.Thread(target=read_sensor, daemon=True)
    t.start()


# =========================
# HEALTH ANALYSIS
# =========================
def analyze_health(heart_rate, spo2):
    if heart_rate is None or spo2 is None:
        return {
            "hr_status": "UNKNOWN",
            "spo2_status": "UNKNOWN",
            "risk": "Waiting for finger on sensor",
            "advice": "Place finger properly on sensor"
        }

    hr_status = "NORMAL"
    spo2_status = "NORMAL"
    risks = []
    advice = []

    if heart_rate < 60:
        hr_status = "LOW"
        risks.append("Low heart rate (Bradycardia)")
        advice.append("Consult a doctor")

    elif heart_rate > 100:
        hr_status = "HIGH"
        risks.append("High heart rate (Stress / Hypertension)")
        advice.append("Reduce stress and take rest")

    if spo2 < 95:
        spo2_status = "LOW"
        risks.append("Low oxygen level (Breathing issue)")
        advice.append("Practice deep breathing")

    if hr_status == "HIGH" and spo2_status == "LOW":
        risks.append("Combined cardiovascular + respiratory risk")
        advice.append("Seek medical attention if persists")

    if not risks:
        risks.append("No immediate risk detected")
        advice.append("Maintain healthy lifestyle")

    return {
        "hr_status": hr_status,
        "spo2_status": spo2_status,
        "risk": ", ".join(risks),
        "advice": ", ".join(advice)
    }
