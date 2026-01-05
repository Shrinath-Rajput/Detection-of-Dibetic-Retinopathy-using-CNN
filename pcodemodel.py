import pandas as pd
from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestClassifier
import joblib

data = {
    "Age": [22,28,30,24,35,26,29,32],
    "BMI": [21,29,31,27,34,25,30,33],
    "Fatigue": ["No","Yes","Yes","No","Yes","No","Yes","Yes"],
    "Sleep": ["Good","Poor","Poor","Average","Poor","Good","Poor","Poor"],
    "Stress": ["Low","High","High","Medium","High","Low","High","High"],
    "Activity": ["High","Low","Low","Medium","Low","High","Low","Low"],
    "Diet": ["Healthy","Junk","Junk","Mixed","Junk","Healthy","Junk","Junk"],
    "FamilyHistory": ["No","Yes","Yes","No","Yes","No","Yes","Yes"],
    "PCOD": [0,1,1,0,1,0,1,1]
}

df = pd.DataFrame(data)

encoders = {}
for col in df.columns:
    if df[col].dtype == "object":
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col])
        encoders[col] = le

X = df.drop("PCOD", axis=1)
y = df["PCOD"]

model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X, y)

joblib.dump(model, "pcod_model.pkl")
joblib.dump(encoders, "pcod_encoders.pkl")

print("✅ PCOD model trained & saved")
