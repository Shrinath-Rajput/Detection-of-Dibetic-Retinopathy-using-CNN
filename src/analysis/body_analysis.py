def body_analysis(hr, spo2):
    issues = []

    if hr is not None:
        if hr > 100:
            issues.append("Heart Rate is Growth")
        elif hr < 60:
            issues.append("Heart Rate is low")

    if spo2 is not None and spo2 < 95:
        issues.append("Oxygen level कमी आहे")

    return issues
