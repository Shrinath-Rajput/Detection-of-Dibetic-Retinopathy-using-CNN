@app.route("/health_analysis")
def health_analysis():
    hr = sensor_data.get("heart_rate")
    spo2 = sensor_data.get("spo2")

    hr_status = "UNKNOWN"
    spo2_status = "UNKNOWN"
    risk_level = "UNKNOWN"
    issues = []
    advice = []

    # ❤️ Heart Rate Analysis
    if hr is not None:
        if hr < 60:
            hr_status = "LOW"
            issues.append("Low heart rate (Bradycardia)")
            risk_level = "MODERATE"
        elif 60 <= hr <= 100:
            hr_status = "NORMAL"
        elif 100 < hr <= 120:
            hr_status = "ELEVATED"
            issues.append("Mild tachycardia (Stress / Anxiety)")
            risk_level = "MODERATE"
        elif 120 < hr <= 150:
            hr_status = "HIGH"
            issues.append("High heart rate (Stress / Overexertion)")
            risk_level = "HIGH"
        else:
            hr_status = "CRITICAL"
            issues.append("Dangerously high heart rate")
            risk_level = "CRITICAL"

    # 🫁 SpO₂ Analysis
    if spo2 is not None:
        if spo2 >= 95:
            spo2_status = "NORMAL"
        elif 90 <= spo2 < 95:
            spo2_status = "LOW"
            issues.append("Mild oxygen deficiency")
            risk_level = max(risk_level, "MODERATE")
        elif 85 <= spo2 < 90:
            spo2_status = "VERY LOW"
            issues.append("Low blood oxygen (Possible lung issue)")
            risk_level = "HIGH"
        else:
            spo2_status = "CRITICAL"
            issues.append("Severe oxygen deficiency")
            risk_level = "CRITICAL"

    # 🔥 Combined Risk
    if hr and spo2 and hr > 120 and spo2 < 95:
        issues.append("Combined cardiovascular + respiratory stress")
        risk_level = "CRITICAL"

    # ✅ Advice
    if risk_level in ["UNKNOWN", "NONE"]:
        advice.append("Vitals normal. Maintain healthy lifestyle.")
    else:
        advice.extend([
            "Sit or lie down and relax",
            "Practice deep breathing (4-7-8 method)",
            "Drink water",
            "Avoid physical exertion"
        ])

        if risk_level in ["HIGH", "CRITICAL"]:
            advice.append("Seek medical attention if persists")

    return jsonify({
        "heart_rate_status": hr_status,
        "spo2_status": spo2_status,
        "risk_level": risk_level,
        "issues": issues,
        "advice": advice
    })
