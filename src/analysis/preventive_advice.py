def preventive_advice(hr, spo2):
    advice = []

    if hr is not None and hr > 100:
        advice.append("Give the Rest and Take Care")

    if spo2 is not None and spo2 < 95:
        advice.append("Deep breathing exercise ")

    advice.append("If growth the Problem then meet to doctor")

    return advice
