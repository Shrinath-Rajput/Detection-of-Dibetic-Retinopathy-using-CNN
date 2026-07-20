import os
import serial
import serial.tools.list_ports
import threading
import time
import sys

# Allow overriding COM port and enabling/disabling the sensor via environment variables
COM_PORT = os.environ.get("COM_PORT", "COM4")
BAUD_RATE = int(os.environ.get("BAUD_RATE", "115200"))
SENSOR_ENABLED = str(os.environ.get("SENSOR_ENABLED", "true")).lower() not in ("0", "false", "no")

sensor_data = {
    "heart_rate": "--",
    "spo2": "--",
    "status": "DISCONNECTED",
    "port": None
}

_sensor_thread = None


def safe_print(message):
    """Print safely with Unicode encoding fallback"""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode('utf-8', errors='replace').decode('utf-8', errors='replace'))


def list_com_ports():
    ports = []
    try:
        ports = list(serial.tools.list_ports.comports())
    except Exception as e:
        safe_print(f"[SENSOR] Could not enumerate COM ports: {e}")
    return [
        {
            "device": port.device,
            "description": port.description,
            "hwid": port.hwid
        }
        for port in ports
    ]


def select_com_port(preferred_port=None, exclude_ports=None):
    exclude_ports = exclude_ports or []
    ports = [port for port in list_com_ports() if port["device"] not in exclude_ports]

    if preferred_port:
        for port in ports:
            if port["device"] == preferred_port or port["device"].endswith(preferred_port):
                safe_print(f"[SENSOR] Preferred port available: {port['device']} ({port['description']})")
                return port["device"]

    keywords = [
        "esp32",
        "arduino",
        "usb serial",
        "cp210",
        "ch340",
        "silicon labs",
        "ftdi",
        "usb-to-serial",
        "usb uart",
        "bluno"
    ]

    for keyword in keywords:
        for port in ports:
            summary = f"{port['device']} {port['description']} {port['hwid']}".lower()
            if keyword in summary:
                safe_print(f"[SENSOR] Auto-selected port {port['device']} based on keyword '{keyword}' ({port['description']})")
                return port["device"]

    if ports:
        selected = ports[0]["device"]
        safe_print(f"[SENSOR] No ESP32/Arduino-specific port found. Falling back to first available port {selected} ({ports[0]['description']})")
        return selected

    return None


def reset_sensor_data():
    sensor_data["heart_rate"] = "--"
    sensor_data["spo2"] = "--"
    sensor_data["status"] = "DISCONNECTED"
    sensor_data["port"] = None


def parse_sensor_line(line):
    if "No finger" in line:
        sensor_data["heart_rate"] = "--"
        sensor_data["spo2"] = "--"
        safe_print("[SENSOR] Waiting for finger")
        return

    if "HR" in line and "SpO2" in line:
        try:
            hr_str = (
                line.split("HR")[1]
                .split("BPM")[0]
                .replace(":", "")
                .strip()
            )

            spo2_str = (
                line.split("SpO2")[1]
                .replace(":", "")
                .replace("%", "")
                .strip()
            )

            if (
                "--" in hr_str
                or "--" in spo2_str
                or not hr_str.isdigit()
                or not spo2_str.isdigit()
            ):
                sensor_data["heart_rate"] = "--"
                sensor_data["spo2"] = "--"
                safe_print("[SENSOR] Invalid reading, waiting for valid data")
                return

            sensor_data["heart_rate"] = int(hr_str)
            sensor_data["spo2"] = int(spo2_str)
            safe_print(f"[SENSOR] HR={sensor_data['heart_rate']} BPM | SpO2={sensor_data['spo2']}%")
        except Exception as e:
            safe_print(f"[SENSOR] Parse Error: {e}")
            sensor_data["heart_rate"] = "--"
            sensor_data["spo2"] = "--"


def read_sensor():
    global sensor_data

    if not SENSOR_ENABLED:
        sensor_data["status"] = "DISABLED"
        safe_print("[SENSOR] Sensor disabled via SENSOR_ENABLED environment variable. Skipping connection.")
        return

    excluded_ports = set()

    while True:
        ports = list_com_ports()
        port_list = [f"{p['device']} ({p['description']})" for p in ports]
        safe_print(f"[SENSOR] Detected COM ports: {port_list if port_list else 'none'}")

        selected_port = select_com_port(COM_PORT, exclude_ports=excluded_ports)
        if not selected_port:
            reset_sensor_data()
            excluded_ports.clear()
            safe_print("[SENSOR] No valid serial ports detected. Retrying in 5 seconds.")
            time.sleep(5)
            continue

        sensor_data["port"] = selected_port
        if selected_port != COM_PORT:
            safe_print(f"[SENSOR] Preferred port {COM_PORT} unavailable. Using {selected_port} instead.")
        else:
            safe_print(f"[SENSOR] Selected COM port: {selected_port}")

        ser = None
        try:
            safe_print(f"[SENSOR] Attempting connection on {selected_port} at {BAUD_RATE} baud")
            ser = serial.Serial(selected_port, BAUD_RATE, timeout=1)
            sensor_data["status"] = "CONNECTED"
            safe_print(f"[SENSOR] Connected on {selected_port}")

            while ser.is_open:
                try:
                    if ser.in_waiting:
                        line = ser.readline().decode("utf-8", errors="ignore").strip()
                        if line:
                            safe_print(f"[RAW] {line}")
                        if any(token in line.lower() for token in ["ets", "boot", "rst"]):
                            continue
                        parse_sensor_line(line)
                    else:
                        time.sleep(0.1)
                except (serial.SerialException, OSError, ValueError) as e:
                    safe_print(f"[SENSOR] Serial error while reading from {selected_port}: {e}")
                    break

        except PermissionError as e:
            safe_print(f"[SENSOR] Permission denied when opening {selected_port}: {e}")
            safe_print("[SENSOR] Another process may hold the port, or the current user lacks permissions.")
            excluded_ports.add(selected_port)

        except serial.SerialException as e:
            safe_print(f"[SENSOR] Connection failed on {selected_port}: {e}")
            excluded_ports.add(selected_port)

        except OSError as e:
            safe_print(f"[SENSOR] OS error when opening {selected_port}: {e}")
            excluded_ports.add(selected_port)

        except Exception as e:
            safe_print(f"[SENSOR] Unexpected error when handling {selected_port}: {e}")
            excluded_ports.add(selected_port)

        finally:
            if ser is not None:
                try:
                    if ser.is_open:
                        ser.close()
                        safe_print(f"[SENSOR] Closed serial port {selected_port}")
                except Exception as e:
                    safe_print(f"[SENSOR] Error closing serial port {selected_port}: {e}")

        reset_sensor_data()

        if excluded_ports:
            available_ports = [p for p in list_com_ports() if p["device"] not in excluded_ports]
            if not available_ports:
                excluded_ports.clear()

        time.sleep(5)


def start_sensor_thread():
    global _sensor_thread

    if _sensor_thread is None or not _sensor_thread.is_alive():
        _sensor_thread = threading.Thread(target=read_sensor, daemon=True)
        _sensor_thread.start()
        safe_print("[SENSOR] Thread started")

