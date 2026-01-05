def risk_prediction(hr, spo2):
    risks = []

    if spo2 is not None and spo2 < 95:
        risks.append("Breathing related problem होऊ शकतो")

    if hr is not None and hr > 100:
        risks.append("Stress / Hypertension risk")

    if hr is not None and spo2 is not None:
        if hr > 100 and spo2 < 95:
            risks.append("Combined health risk")

    return risks
