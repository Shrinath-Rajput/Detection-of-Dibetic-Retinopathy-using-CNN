import os
import serial
import serial.tools.list_ports
import threading
import time
import sys
import tempfile

from dotenv import load_dotenv

try:
    import msvcrt
except ImportError:
    msvcrt = None

load_dotenv()

# The ESP32 is intentionally fixed to the verified CP210x port.
COM_PORT = "COM4"
BAUD_RATE = 115200
SENSOR_ENABLED = str(os.environ.get("SENSOR_ENABLED", "true")).lower() not in ("0", "false", "no")

sensor_data = {
    "heart_rate": "--",
    "spo2": "--",
    "status": "DISCONNECTED",
    "connected": False,
    "esp32_connected": False,
    "sensor_initialized": False,
    "finger_detected": False,
    "finger_status": "WAITING FOR FINGER",
    "measurement_status": "DISCONNECTED",
    "timeout_remaining": 30,
    "status_message": "Sensor offline or disconnected",
    "port": None
}

_sensor_thread = None
_waiting_finger_start_time = None
_active_serial = None
_SERIAL_LOCK_PATH = os.path.join(tempfile.gettempdir(), "dr_cnn_sensor_serial.lock")


def safe_print(message):
    """Print safely with Unicode encoding fallback for Windows console."""
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        print(message.encode('ascii', errors='replace').decode('ascii', errors='replace'), flush=True)


def acquire_sensor_process_lock():
    """Allow only one Flask process / worker to own the ESP32 serial port."""
    if msvcrt is None:
        return True

    try:
        lock_file = open(_SERIAL_LOCK_PATH, "a+b")
        lock_file.seek(0)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return lock_file
    except (OSError, IOError):
        try:
            lock_file.close()
        except Exception:
            pass
        return None


def release_sensor_process_lock(lock_file):
    if lock_file is None or lock_file is True or msvcrt is None:
        return
    try:
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    except (OSError, IOError):
        pass
    finally:
        try:
            lock_file.close()
        except Exception:
            pass


def list_com_ports():
    ports = []
    try:
        ports = list(serial.tools.list_ports.comports())
    except Exception as e:
        safe_print(f"[SENSOR] Could not enumerate COM ports: {e}")
    return [
        {
            "device": port.device,
            "description": port.description or "",
            "hwid": port.hwid or ""
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
        safe_print(f"[SENSOR] Configured COM port {preferred_port} is unavailable; refusing to select another port")
        return None

    keywords = [
        "cp210",
        "silicon labs",
        "ch340",
        "ch341",
        "ftdi",
        "usb to uart",
        "usb-to-uart",
        "esp32",
        "usb serial",
        "usb-serial",
        "arduino"
    ]

    for keyword in keywords:
        for port in ports:
            summary = f"{port['device']} {port['description']} {port['hwid']}".lower()
            if keyword in summary:
                safe_print(f"[SENSOR] Auto-selected port {port['device']} based on keyword '{keyword}' ({port['description']})")
                return port["device"]

    # Candidate physical non-Bluetooth serial ports
    for port in ports:
        summary = f"{port['device']} {port['description']} {port['hwid']}".lower()
        if "bthenum" not in summary and "bluetooth" not in summary:
            safe_print(f"[SENSOR] Selected candidate physical serial port: {port['device']} ({port['description']})")
            return port["device"]

    return None


def reset_sensor_data(message="ESP32/Sensor disconnected"):
    global _waiting_finger_start_time
    sensor_data["heart_rate"] = "--"
    sensor_data["spo2"] = "--"
    sensor_data["status"] = "DISCONNECTED"
    sensor_data["connected"] = False
    sensor_data["esp32_connected"] = False
    sensor_data["sensor_initialized"] = False
    sensor_data["finger_detected"] = False
    sensor_data["finger_status"] = "WAITING FOR FINGER"
    sensor_data["measurement_status"] = "DISCONNECTED"
    sensor_data["timeout_remaining"] = 30
    sensor_data["status_message"] = message
    sensor_data["port"] = None
    _waiting_finger_start_time = None


def reset_finger_timeout():
    global _waiting_finger_start_time, _active_serial
    _waiting_finger_start_time = time.time()
    sensor_data["finger_detected"] = False
    sensor_data["finger_status"] = "WAITING FOR FINGER"
    sensor_data["timeout_remaining"] = 30
    sensor_data["measurement_status"] = "WAITING"
    sensor_data["status_message"] = "Waiting for finger (30s)"
    sensor_data["heart_rate"] = "--"
    sensor_data["spo2"] = "--"
    if _active_serial is not None:
        try:
            if _active_serial.is_open:
                _active_serial.reset_input_buffer()
        except Exception:
            pass


def parse_sensor_line(line):
    global _waiting_finger_start_time
    line_clean = line.strip()
    if not line_clean:
        return

    line_lower = line_clean.lower()

    # 1. Temporary sensor reset / unready message from ESP32
    # While physical serial communication is active, ESP32 status remains CONNECTED!
    if "status:disconnected" in line_lower:
        sensor_data["status"] = "CONNECTED"
        sensor_data["connected"] = True
        sensor_data["esp32_connected"] = True
        sensor_data["finger_detected"] = False
        sensor_data["finger_status"] = "WAITING FOR FINGER"
        sensor_data["measurement_status"] = "WAITING"
        sensor_data["heart_rate"] = "--"
        sensor_data["spo2"] = "--"
        sensor_data["status_message"] = "Waiting for finger"
        return

    # 2. Hardware initialized & connected state
    if any(token in line_lower for token in [
        "status:connected",
        "max30102 initialized successfully",
        "ready for finger",
        "[sensor] connected"
    ]):
        sensor_data["sensor_initialized"] = True
        sensor_data["connected"] = True
        sensor_data["esp32_connected"] = True
        sensor_data["status"] = "CONNECTED"
        if not sensor_data.get("finger_detected", False):
            sensor_data["measurement_status"] = "WAITING"
            sensor_data["status_message"] = "Waiting for finger"
        safe_print("[SENSOR] Verified hardware communication -> Status: CONNECTED")

    # 3. Finger Status: Removed / Waiting
    # VERY IMPORTANT: FINGER:0 DOES NOT MEAN DISCONNECTED.
    # ESP32/Serial connected + FINGER:0 -> CONNECTED + WAITING FOR FINGER
    if "finger:0" in line_lower or "waiting for finger" in line_lower:
        sensor_data["status"] = "CONNECTED"
        sensor_data["connected"] = True
        sensor_data["esp32_connected"] = True
        sensor_data["sensor_initialized"] = True
        sensor_data["finger_detected"] = False
        sensor_data["heart_rate"] = "--"
        sensor_data["spo2"] = "--"
        if _waiting_finger_start_time is None:
            _waiting_finger_start_time = time.time()
        elapsed = time.time() - _waiting_finger_start_time
        remaining = max(0, int(30 - elapsed))
        sensor_data["timeout_remaining"] = remaining
        if remaining > 0:
            sensor_data["measurement_status"] = "WAITING"
            sensor_data["finger_status"] = "WAITING FOR FINGER"
            sensor_data["status_message"] = f"Waiting for finger ({remaining}s)"
        else:
            sensor_data["measurement_status"] = "TRY_AGAIN"
            sensor_data["finger_status"] = "TRY AGAIN"
            sensor_data["status_message"] = "Please place your finger correctly on the sensor"
        return

    # 4. Finger Status: Detected
    if "finger:1" in line_lower or "finger detected" in line_lower:
        sensor_data["status"] = "CONNECTED"
        sensor_data["connected"] = True
        sensor_data["esp32_connected"] = True
        sensor_data["sensor_initialized"] = True
        sensor_data["finger_detected"] = True
        sensor_data["finger_status"] = "FINGER DETECTED"
        sensor_data["status_message"] = "Measuring..."
        sensor_data["timeout_remaining"] = 30
        _waiting_finger_start_time = None
        if sensor_data["heart_rate"] == "--" or sensor_data["spo2"] == "--":
            sensor_data["measurement_status"] = "MEASURING"
        else:
            sensor_data["measurement_status"] = "COMPLETED"
        safe_print("[SENSOR] Finger detected!")
        return

    # 5. Machine-readable HR parsing (e.g. HR:72 or HR:--)
    if line_clean.startswith("HR:") or line_clean.startswith("hr:"):
        val_str = line_clean.split(":", 1)[1].strip()
        if val_str.isdigit():
            val = int(val_str)
            if 40 <= val <= 220:
                sensor_data["heart_rate"] = val
                sensor_data["finger_detected"] = True
                sensor_data["finger_status"] = "FINGER DETECTED"
                _waiting_finger_start_time = None
                if sensor_data["spo2"] != "--":
                    sensor_data["measurement_status"] = "COMPLETED"
                    sensor_data["status_message"] = "Measurement complete / Monitoring"
                else:
                    sensor_data["measurement_status"] = "MEASURING"
                    sensor_data["status_message"] = "Measuring..."
            else:
                sensor_data["heart_rate"] = "--"
        else:
            sensor_data["heart_rate"] = "--"

    # 6. Machine-readable SpO2 parsing (e.g. SPO2:98 or SPO2:--)
    if line_clean.startswith("SPO2:") or line_clean.startswith("spo2:"):
        val_str = line_clean.split(":", 1)[1].strip().replace("%", "")
        if val_str.isdigit():
            val = int(val_str)
            if 70 <= val <= 100:
                sensor_data["spo2"] = val
                sensor_data["finger_detected"] = True
                sensor_data["finger_status"] = "FINGER DETECTED"
                _waiting_finger_start_time = None
                if sensor_data["heart_rate"] != "--":
                    sensor_data["measurement_status"] = "COMPLETED"
                    sensor_data["status_message"] = "Measurement complete / Monitoring"
                else:
                    sensor_data["measurement_status"] = "MEASURING"
                    sensor_data["status_message"] = "Measuring..."
            else:
                sensor_data["spo2"] = "--"
        else:
            sensor_data["spo2"] = "--"

    # 7. Composite human-readable parsing (e.g. Heart Rate: 72 BPM | SpO2: 98 %)
    normalized = line_clean.replace("Heart Rate", "HR")
    if "HR" in normalized and "SpO2" in normalized and "BPM" in normalized:
        try:
            hr_str = normalized.split("HR")[1].split("BPM")[0].replace(":", "").strip()
            spo2_str = normalized.split("SpO2")[1].replace(":", "").replace("%", "").strip()

            if hr_str.isdigit() and spo2_str.isdigit():
                val_hr = int(hr_str)
                val_spo2 = int(spo2_str)
                if 40 <= val_hr <= 220 and 70 <= val_spo2 <= 100:
                    sensor_data["heart_rate"] = val_hr
                    sensor_data["spo2"] = val_spo2
                    sensor_data["finger_detected"] = True
                    sensor_data["finger_status"] = "FINGER DETECTED"
                    sensor_data["measurement_status"] = "COMPLETED"
                    sensor_data["status_message"] = "Measurement complete / Monitoring"
                    _waiting_finger_start_time = None
                    safe_print(f"[SENSOR] HR={val_hr} BPM | SpO2={val_spo2}%")
            elif "--" in hr_str or "--" in spo2_str:
                sensor_data["finger_detected"] = True
                sensor_data["finger_status"] = "FINGER DETECTED"
                sensor_data["measurement_status"] = "MEASURING"
                sensor_data["status_message"] = "Measuring..."
                _waiting_finger_start_time = None
        except Exception as e:
            safe_print(f"[SENSOR] Parse Error: {e}")


def read_sensor():
    global sensor_data, _waiting_finger_start_time, _active_serial

    if not SENSOR_ENABLED:
        sensor_data["status"] = "DISABLED"
        sensor_data["status_message"] = "Sensor disabled via configuration"
        safe_print("[SENSOR] Sensor disabled via SENSOR_ENABLED. Skipping connection.")
        return

    process_lock = None
    while process_lock is None:
        process_lock = acquire_sensor_process_lock()
        if process_lock is None:
            reset_sensor_data("Another application process owns the ESP32 serial connection.")
            safe_print("[SENSOR] Another application process owns the ESP32 serial connection. Retrying in 2 seconds.")
            time.sleep(2)

    safe_print(f"[SENSOR] Serial connection ownership acquired")

    while True:
        # Make sure any previous serial instance is completely closed
        if _active_serial is not None:
            try:
                if _active_serial.is_open:
                    _active_serial.close()
            except Exception:
                pass
            _active_serial = None

        ports = list_com_ports()
        port_list = [f"{p['device']} ({p['description']})" for p in ports]
        safe_print(f"[SENSOR] Detected COM ports: {port_list if port_list else 'none'}")

        selected_port = select_com_port(COM_PORT)
        if not selected_port:
            reset_sensor_data("No ESP32 / MAX30102 serial port detected")
            safe_print("[SENSOR] No ESP32 / MAX30102 serial port detected. Retrying in 2 seconds.")
            time.sleep(2)
            continue

        sensor_data["port"] = selected_port
        safe_print(f"[SENSOR] Selected candidate port: {selected_port}")

        ser = None
        try:
            safe_print(f"[SENSOR] Attempting connection on {selected_port} at {BAUD_RATE} baud")
            ser = serial.Serial()
            ser.port = selected_port
            ser.baudrate = BAUD_RATE
            ser.timeout = 0.5
            ser.dtr = False
            ser.rts = False
            ser.open()
            _active_serial = ser

            # ESP32 USB serial connection is opened - state is CONNECTED
            _waiting_finger_start_time = time.time()
            sensor_data["esp32_connected"] = True
            sensor_data["port"] = selected_port
            sensor_data["status"] = "CONNECTED"
            sensor_data["connected"] = True
            sensor_data["sensor_initialized"] = True
            sensor_data["finger_detected"] = False
            sensor_data["finger_status"] = "WAITING FOR FINGER"
            sensor_data["timeout_remaining"] = 30
            sensor_data["measurement_status"] = "WAITING"
            sensor_data["status_message"] = "Waiting for finger (30s)"
            sensor_data["heart_rate"] = "--"
            sensor_data["spo2"] = "--"
            safe_print(f"[SENSOR] Connection opened on {selected_port} at {BAUD_RATE} baud -> Status: CONNECTED")

            while ser.is_open:
                try:
                    # Check if physical COM port still exists in the OS
                    # When USB cable is unplugged, Windows drops the COM port from device list
                    current_ports = [p["device"] for p in list_com_ports()]
                    if selected_port not in current_ports:
                        safe_print(f"[SENSOR] {selected_port} physically removed from system. Disconnecting.")
                        break

                    # Drain and process all available lines from serial buffer
                    lines = []
                    while ser.in_waiting > 0:
                        raw_bytes = ser.readline()
                        l = raw_bytes.decode("utf-8", errors="ignore").strip()
                        if l:
                            lines.append(l)
                        if len(lines) >= 15:
                            break

                    for line in lines:
                        safe_print(f"[RAW] {line}")
                        # Ignore ESP-IDF bootloader register logs
                        if any(token in line.lower() for token in ["ets", "boot", "rst", "clk_drv", "configsip", "entry 0x"]):
                            continue

                        parse_sensor_line(line)

                    # Manage the active 30-second finger detection window
                    if sensor_data["status"] == "CONNECTED" and not sensor_data.get("finger_detected", False):
                        if _waiting_finger_start_time is None:
                            _waiting_finger_start_time = time.time()

                        elapsed = time.time() - _waiting_finger_start_time
                        remaining = max(0, int(30 - elapsed))
                        sensor_data["timeout_remaining"] = remaining

                        if remaining > 0:
                            sensor_data["finger_status"] = "WAITING FOR FINGER"
                            sensor_data["measurement_status"] = "WAITING"
                            sensor_data["status_message"] = f"Waiting for finger ({remaining}s)"
                        else:
                            sensor_data["finger_status"] = "TRY AGAIN"
                            sensor_data["measurement_status"] = "TRY_AGAIN"
                            sensor_data["status_message"] = "Please place your finger correctly on the sensor"

                        sensor_data["heart_rate"] = "--"
                        sensor_data["spo2"] = "--"

                    time.sleep(0.04)

                except (serial.SerialException, OSError) as e:
                    safe_print(f"[SENSOR] Physical serial disconnect on {selected_port}: {e}")
                    break
                except Exception as e:
                    safe_print(f"[SENSOR] Serial error on {selected_port}: {e}")
                    break

        except PermissionError as e:
            safe_print(f"[SENSOR] Connection failed on {selected_port}: PermissionError(13, 'Access is denied.')")
            reset_sensor_data("ESP32 serial port is busy or unavailable")

        except serial.SerialException as e:
            safe_print(f"[SENSOR] Connection failed on {selected_port}: {e}")
            reset_sensor_data(f"Connection failed on {selected_port}")

        except OSError as e:
            safe_print(f"[SENSOR] OS error when opening {selected_port}: {e}")
            reset_sensor_data(f"OS error on {selected_port}")

        except Exception as e:
            safe_print(f"[SENSOR] Unexpected error when handling {selected_port}: {e}")
            reset_sensor_data(f"Error on {selected_port}")

        finally:
            if ser is not None:
                try:
                    if ser.is_open:
                        ser.close()
                        safe_print(f"[SENSOR] Closed serial port {selected_port}")
                except Exception as e:
                    safe_print(f"[SENSOR] Error closing serial port {selected_port}: {e}")
                ser = None
            _active_serial = None

        reset_sensor_data("ESP32/Sensor disconnected")
        time.sleep(1.5)


def start_sensor_thread():
    global _sensor_thread

    if _sensor_thread is None or not _sensor_thread.is_alive():
        _sensor_thread = threading.Thread(target=read_sensor, daemon=True)
        _sensor_thread.start()
        safe_print("[SENSOR] Thread started")
