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
    "port": None,
    "raw_ir": 0,
    "raw_red": 0
}

_sensor_thread = None
_active_serial = None
_SERIAL_LOCK_PATH = os.path.join(tempfile.gettempdir(), "dr_cnn_sensor_serial.lock")
_attempt_start_time = None
_logged_states = {
    "connected": False,
    "finger": False,
    "measuring": False,
    "hr": None,
    "spo2": None
}


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
    global _logged_states, _attempt_start_time
    _attempt_start_time = None
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
    sensor_data["raw_ir"] = 0
    sensor_data["raw_red"] = 0

    if _logged_states.get("connected"):
        safe_print("[SENSOR] HARDWARE DISCONNECTED")
        _logged_states["connected"] = False
        _logged_states["finger"] = False
        _logged_states["measuring"] = False
        _logged_states["hr"] = None
        _logged_states["spo2"] = None


def reset_finger_timeout():
    global _active_serial, _logged_states, _attempt_start_time
    _attempt_start_time = time.time()
    sensor_data["finger_detected"] = False
    sensor_data["finger_status"] = "WAITING FOR FINGER"
    sensor_data["measurement_status"] = "WAITING"
    sensor_data["status_message"] = "Waiting for finger"
    sensor_data["heart_rate"] = "--"
    sensor_data["spo2"] = "--"
    sensor_data["timeout_remaining"] = 30
    _logged_states["finger"] = False
    _logged_states["measuring"] = False
    _logged_states["hr"] = None
    _logged_states["spo2"] = None
    if _active_serial is not None:
        try:
            if _active_serial.is_open:
                _active_serial.reset_input_buffer()
        except Exception:
            pass


def parse_sensor_line(line):
    global sensor_data, _logged_states, _attempt_start_time
    line_clean = line.strip()
    if not line_clean:
        return

    line_lower = line_clean.lower()
    line_compact = line_lower.replace(" ", "")

    # 1. Hardware connection confirmation
    if any(token in line_lower for token in [
        "status:connected",
        "max30102 initialized successfully",
        "ready for finger",
        "[sensor] connected"
    ]):
        sensor_data["connected"] = True
        sensor_data["esp32_connected"] = True
        sensor_data["sensor_initialized"] = True
        sensor_data["status"] = "CONNECTED"
        if not _logged_states.get("connected"):
            safe_print("[SENSOR] CONNECTED")
            _logged_states["connected"] = True

    # 2. Finger removed / no finger placed
    # CRITICAL: FINGER:0 DOES NOT MEAN DISCONNECTED.
    # ESP32/Serial connected + FINGER:0 -> CONNECTED + WAITING FOR FINGER
    if any(token in line_compact for token in [
        "finger:0", "finger=0", "finger:false", "finger=false",
        "waitingforfinger", "nofinger"
    ]) or "waiting for finger" in line_lower:
        sensor_data["status"] = "CONNECTED"
        sensor_data["connected"] = True
        sensor_data["esp32_connected"] = True
        sensor_data["sensor_initialized"] = True
        sensor_data["finger_detected"] = False
        sensor_data["finger_status"] = "WAITING FOR FINGER"
        sensor_data["measurement_status"] = "WAITING"
        sensor_data["status_message"] = "Waiting for finger"
        sensor_data["heart_rate"] = "--"
        sensor_data["spo2"] = "--"
        sensor_data["timeout_remaining"] = 30
        _attempt_start_time = None

        if _logged_states.get("finger"):
            safe_print("[SENSOR] FINGER REMOVED")
            _logged_states["finger"] = False
            _logged_states["measuring"] = False
            _logged_states["hr"] = None
            _logged_states["spo2"] = None
        return

    # 3. Finger detected
    if any(token in line_compact for token in [
        "finger:1", "finger=1", "finger:true", "finger=true",
        "fingerdetected"
    ]) or "finger detected" in line_lower or "finger_detected" in line_lower:
        sensor_data["status"] = "CONNECTED"
        sensor_data["connected"] = True
        sensor_data["esp32_connected"] = True
        sensor_data["sensor_initialized"] = True
        sensor_data["finger_detected"] = True
        sensor_data["finger_status"] = "FINGER DETECTED"

        if sensor_data.get("measurement_status") != "COMPLETED":
            sensor_data["measurement_status"] = "MEASURING"
            sensor_data["status_message"] = "Measuring..."
            if _attempt_start_time is None or sensor_data.get("measurement_status") == "TRY_AGAIN":
                _attempt_start_time = time.time()

        if not _logged_states.get("finger"):
            safe_print("[SENSOR] FINGER DETECTED")
            safe_print("[SENSOR] MEASURING")
            _logged_states["finger"] = True
            _logged_states["measuring"] = True
        return

    # 4. IR / RED reading parser (e.g. IR: 15420 or RED: 12000)
    for prefix in ["ir", "red"]:
        if f"{prefix}:" in line_compact or f"{prefix}=" in line_compact:
            try:
                sep = ":" if f"{prefix}:" in line_compact else "="
                val_part = line_clean.lower().split(sep)[1].split(",")[0].split()[0].strip()
                if val_part.isdigit():
                    raw_val = int(val_part)
                    sensor_data[f"raw_{prefix}"] = raw_val
                    if raw_val >= 4000:
                        sensor_data["status"] = "CONNECTED"
                        sensor_data["connected"] = True
                        sensor_data["esp32_connected"] = True
                        sensor_data["sensor_initialized"] = True
                        sensor_data["finger_detected"] = True
                        sensor_data["finger_status"] = "FINGER DETECTED"
                        if sensor_data.get("measurement_status") != "COMPLETED":
                            sensor_data["measurement_status"] = "MEASURING"
                            sensor_data["status_message"] = "Measuring..."
                            if _attempt_start_time is None:
                                _attempt_start_time = time.time()
                        if not _logged_states.get("finger"):
                            safe_print("[SENSOR] FINGER DETECTED")
                            safe_print("[SENSOR] MEASURING")
                            _logged_states["finger"] = True
                            _logged_states["measuring"] = True
                    elif raw_val < 2500 and sensor_data.get("measurement_status") != "COMPLETED":
                        sensor_data["finger_detected"] = False
                        sensor_data["finger_status"] = "WAITING FOR FINGER"
                        sensor_data["measurement_status"] = "WAITING"
                        sensor_data["status_message"] = "Waiting for finger"
                        _attempt_start_time = None
            except Exception:
                pass

    # 5. Machine-readable HR parsing (e.g. HR:72 or HR:--)
    if line_clean.startswith("HR:") or line_clean.startswith("hr:"):
        val_str = line_clean.split(":", 1)[1].strip()
        if val_str.isdigit():
            val = int(val_str)
            if 40 <= val <= 220:
                sensor_data["heart_rate"] = val
                sensor_data["finger_detected"] = True
                sensor_data["finger_status"] = "FINGER DETECTED"
                if not _logged_states.get("finger"):
                    safe_print("[SENSOR] FINGER DETECTED")
                    safe_print("[SENSOR] MEASURING")
                    _logged_states["finger"] = True
                    _logged_states["measuring"] = True
                if _logged_states.get("hr") != val:
                    safe_print(f"[SENSOR] HR: {val}")
                    _logged_states["hr"] = val

                if sensor_data.get("spo2") not in ("--", None):
                    sensor_data["measurement_status"] = "COMPLETED"
                    sensor_data["status_message"] = "Measurement complete"
                elif sensor_data.get("measurement_status") != "COMPLETED":
                    sensor_data["measurement_status"] = "MEASURING"
                    sensor_data["status_message"] = "Measuring..."
        elif val_str == "--":
            if sensor_data.get("finger_detected"):
                sensor_data["finger_status"] = "FINGER DETECTED"
                if sensor_data.get("measurement_status") != "COMPLETED":
                    sensor_data["measurement_status"] = "MEASURING"
                    sensor_data["status_message"] = "Measuring..."
        return

    # 6. Machine-readable SpO2 parsing (e.g. SPO2:98 or SPO2:--)
    if line_clean.startswith("SPO2:") or line_clean.startswith("spo2:"):
        val_str = line_clean.split(":", 1)[1].strip().replace("%", "")
        if val_str.isdigit():
            val = int(val_str)
            if 70 <= val <= 100:
                sensor_data["spo2"] = val
                sensor_data["finger_detected"] = True
                sensor_data["finger_status"] = "FINGER DETECTED"
                if not _logged_states.get("finger"):
                    safe_print("[SENSOR] FINGER DETECTED")
                    safe_print("[SENSOR] MEASURING")
                    _logged_states["finger"] = True
                    _logged_states["measuring"] = True
                if _logged_states.get("spo2") != val:
                    safe_print(f"[SENSOR] SPO2: {val}")
                    _logged_states["spo2"] = val

                if sensor_data.get("heart_rate") not in ("--", None):
                    sensor_data["measurement_status"] = "COMPLETED"
                    sensor_data["status_message"] = "Measurement complete"
                elif sensor_data.get("measurement_status") != "COMPLETED":
                    sensor_data["measurement_status"] = "MEASURING"
                    sensor_data["status_message"] = "Measuring..."
        elif val_str == "--":
            if sensor_data.get("finger_detected"):
                sensor_data["finger_status"] = "FINGER DETECTED"
                if sensor_data.get("measurement_status") != "COMPLETED":
                    sensor_data["measurement_status"] = "MEASURING"
                    sensor_data["status_message"] = "Measuring..."
        return

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
                    sensor_data["status_message"] = "Measurement complete"
                    if not _logged_states.get("finger"):
                        safe_print("[SENSOR] FINGER DETECTED")
                        _logged_states["finger"] = True
                    if _logged_states.get("hr") != val_hr:
                        safe_print(f"[SENSOR] HR: {val_hr}")
                        _logged_states["hr"] = val_hr
                    if _logged_states.get("spo2") != val_spo2:
                        safe_print(f"[SENSOR] SPO2: {val_spo2}")
                        _logged_states["spo2"] = val_spo2
            elif "--" in hr_str or "--" in spo2_str:
                sensor_data["finger_detected"] = True
                sensor_data["finger_status"] = "FINGER DETECTED"
                if sensor_data.get("measurement_status") != "COMPLETED":
                    sensor_data["measurement_status"] = "MEASURING"
                    sensor_data["status_message"] = "Measuring..."
                    if not _logged_states.get("finger"):
                        safe_print("[SENSOR] FINGER DETECTED")
                        safe_print("[SENSOR] MEASURING")
                        _logged_states["finger"] = True
                        _logged_states["measuring"] = True
        except Exception:
            pass


def read_sensor():
    global sensor_data, _active_serial, _logged_states, _attempt_start_time

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
            time.sleep(2)

    while True:
        # Make sure any previous serial instance is completely closed
        if _active_serial is not None:
            try:
                if _active_serial.is_open:
                    _active_serial.close()
            except Exception:
                pass
            _active_serial = None

        selected_port = select_com_port(COM_PORT)
        if not selected_port:
            reset_sensor_data("No ESP32 / MAX30102 serial port detected")
            time.sleep(2)
            continue

        sensor_data["port"] = selected_port

        ser = None
        try:
            ser = serial.Serial()
            ser.port = selected_port
            ser.baudrate = BAUD_RATE
            ser.timeout = 0.1
            ser.dtr = False
            ser.rts = False
            ser.open()
            _active_serial = ser

            _attempt_start_time = None
            sensor_data["esp32_connected"] = True
            sensor_data["port"] = selected_port
            sensor_data["status"] = "CONNECTED"
            sensor_data["connected"] = True
            sensor_data["sensor_initialized"] = True
            sensor_data["finger_detected"] = False
            sensor_data["finger_status"] = "WAITING FOR FINGER"
            sensor_data["measurement_status"] = "WAITING"
            sensor_data["status_message"] = "Waiting for finger"
            sensor_data["heart_rate"] = "--"
            sensor_data["spo2"] = "--"
            sensor_data["timeout_remaining"] = 30

            if not _logged_states.get("connected"):
                safe_print("[SENSOR] CONNECTED")
                _logged_states["connected"] = True

            serial_buffer = ""

            while ser.is_open:
                try:
                    # 30-second measurement timeout window:
                    # Active while measuring; if 30s expires without valid readings -> TRY_AGAIN
                    if sensor_data.get("measurement_status") == "MEASURING":
                        if _attempt_start_time is None:
                            _attempt_start_time = time.time()
                        elapsed = time.time() - _attempt_start_time
                        rem = max(0, int(30 - elapsed))
                        sensor_data["timeout_remaining"] = rem
                        if rem == 0 and sensor_data.get("measurement_status") != "COMPLETED":
                            sensor_data["measurement_status"] = "TRY_AGAIN"
                            sensor_data["finger_status"] = "TRY AGAIN"
                            sensor_data["status_message"] = "Please place your finger correctly on the sensor."
                            sensor_data["heart_rate"] = "--"
                            sensor_data["spo2"] = "--"

                    waiting = ser.in_waiting
                    if waiting > 0:
                        raw_bytes = ser.read(waiting)
                        text_chunk = raw_bytes.decode("utf-8", errors="ignore")
                        serial_buffer += text_chunk
                        if "\n" in serial_buffer:
                            lines = serial_buffer.split("\n")
                            serial_buffer = lines[-1]
                            for raw_line in lines[:-1]:
                                line_clean = raw_line.replace("\r", "").strip()
                                if line_clean:
                                    if any(token in line_clean.lower() for token in ["ets", "boot", "rst", "clk_drv", "configsip", "entry 0x"]):
                                        continue
                                    parse_sensor_line(line_clean)

                    time.sleep(0.01)

                except (serial.SerialException, OSError) as e:
                    break
                except Exception as e:
                    break

        except (PermissionError, serial.SerialException, OSError) as e:
            reset_sensor_data("ESP32 serial port is busy or unavailable")

        except Exception as e:
            reset_sensor_data(f"Error on {selected_port}")

        finally:
            if ser is not None:
                try:
                    if ser.is_open:
                        ser.close()
                except Exception:
                    pass
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
