def body_analysis(hr, spo2):
    issues = []

    if hr is not None:
        if hr > 100:
            issues.append("Heart Rate जास्त आहे")
        elif hr < 60:
            issues.append("Heart Rate कमी आहे")

    if spo2 is not None and spo2 < 95:
        issues.append("Oxygen level कमी आहे")

    return issues
