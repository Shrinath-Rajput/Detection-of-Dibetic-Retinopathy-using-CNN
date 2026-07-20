Sensor troubleshooting and configuration

If you see PermissionError when the app tries to open COM4, try these steps:

- Quick workaround (disable sensor):
  - PowerShell: `$env:SENSOR_ENABLED = 'false'; python app.py`
  - CMD: `set SENSOR_ENABLED=false && python app.py`

- To change the COM port used by the app:
  - PowerShell: `$env:COM_PORT = 'COM3'; python app.py`
  - CMD: `set COM_PORT=COM3 && python app.py`

- Common fixes for PermissionError (Access denied):
  - Ensure no other application (Serial monitor, Arduino IDE, other services) is holding the COM port.
  - Close apps that may use the port, then retry.
  - Run the terminal as Administrator (Windows) and restart the app.
  - In Device Manager, verify the device appears under Ports (COM & LPT) and note the correct COM number.
  - Try a different USB cable or port if the device is not detected.

- Notes for developers:
  - `COM_PORT`, `BAUD_RATE`, and `SENSOR_ENABLED` can be set via environment variables.
  - `SENSOR_ENABLED=false` will skip attempting to connect and set the sensor status to `DISABLED`.
