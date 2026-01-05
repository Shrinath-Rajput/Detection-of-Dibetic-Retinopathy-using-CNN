from src.components.serial_reader import read_sensor_data
from src.components.body_analysis import analyze_body
from src.components.hypertension import predict_health_risk

def health_monitoring_pipeline():
    bpm, spo2 = read_sensor_data()

    body_status = analyze_body(bpm, spo2)
    risks = predict_health_risk(body_status)

    return {
        "Heart Rate": bpm,
        "SpO2": spo2,
        "Body Analysis": body_status,
        "Risk Prediction": risks
    }
