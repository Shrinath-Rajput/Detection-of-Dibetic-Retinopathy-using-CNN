class HypertensionRisk:
    def predict(self, hr, spo2):
        if hr > 100 or spo2 < 95:
            return "Hypertension Risk"
        return "Normal"
