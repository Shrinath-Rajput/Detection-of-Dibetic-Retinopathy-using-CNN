import serial

class SensorModule:
    def read_sensor(self):
        ser = serial.Serial("COM3", 9600)
        data = ser.readline().decode().strip()
        return data
