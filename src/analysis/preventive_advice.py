def preventive_advice(hr, spo2):
    advice = []

    if hr is not None and hr > 100:
        advice.append("Rest घ्या आणि stress कमी करा")

    if spo2 is not None and spo2 < 95:
        advice.append("Deep breathing exercise करा")

    advice.append("Problem जास्त वाटल्यास doctor ला भेटा")

    return advice
