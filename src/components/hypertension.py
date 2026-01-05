def predict_health_risk(body_analysis):
    risks = []

    hr_status, hr_value = body_analysis["heart_rate"]
    spo2_status, spo2_value = body_analysis["spo2"]

    if spo2_status == "Low":
        risks.append("Possible breathing problem")

    if hr_status == "High":
        risks.append("Possible stress / hypertension")

    if spo2_status == "Low" and hr_status == "High":
        risks.append("Combined cardio-respiratory risk")

    if not risks:
        risks.append("No immediate health risk detected")

    return risks
