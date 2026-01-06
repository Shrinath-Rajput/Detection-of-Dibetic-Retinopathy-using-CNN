import os
import json
import numpy as np
import tensorflow as tf

from flask import Flask, render_template, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename

from src.services.sensor_service import sensor_data, start_sensor_thread

# =========================
# Flask Init
# =========================
app = Flask(__name__)
app.secret_key = "clinsense_ai_secret"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# =========================
# Load DR Model
# =========================
model = tf.keras.models.load_model("dr_cnn_model.h5", compile=False)

with open("class_indices.json") as f:
    class_indices = json.load(f)

INDEX_TO_CLASS = {v: k for k, v in class_indices.items()}

# =========================
# Start Sensor Thread
# =========================
start_sensor_thread()

# =========================
# Helper Functions
# =========================
def preprocess_image(img_path):
    img = tf.keras.preprocessing.image.load_img(img_path, target_size=(224, 224))
    img = tf.keras.preprocessing.image.img_to_array(img) / 255.0
    return np.expand_dims(img, axis=0)


def analyze_health(hr, spo2):
    hr_status = "UNKNOWN"
    spo2_status = "UNKNOWN"
    risk = []
    advice = []

    if hr is not None:
        if hr < 60:
            hr_status = "LOW"
            risk.append("Low heart rate (Bradycardia)")
        elif hr > 100:
            hr_status = "HIGH"
            risk.append("High heart rate (Stress / Hypertension)")
        else:
            hr_status = "NORMAL"

    if spo2 is not None:
        if spo2 < 95:
            spo2_status = "LOW"
            risk.append("Low oxygen level (Breathing issue)")
        else:
            spo2_status = "NORMAL"

    if not risk:
        advice.append("All vitals are normal. Maintain healthy lifestyle.")
    else:
        advice.extend([
            "Take proper rest",
            "Practice deep breathing",
            "Reduce stress",
            "Consult doctor if values persist"
        ])

    return {
        "heart_rate_status": hr_status,
        "spo2_status": spo2_status,
        "risk": risk,
        "advice": advice
    }

# =========================
# ROUTES
# =========================

# ✅ HOME → Project Overview
@app.route("/")
def home():
    return render_template("home.html")


# ✅ DR PAGE → Image Upload Page
@app.route("/dr")
def dr_page():
    return render_template("index.html")


# ---------- DR PREDICT ----------
@app.route("/predict", methods=["POST"])
def predict():
    file = request.files.get("image")
    if not file or file.filename == "":
        return redirect(url_for("dr_page"))

    path = os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(file.filename))
    file.save(path)

    preds = model.predict(preprocess_image(path))
    class_id = int(np.argmax(preds))
    confidence = float(np.max(preds)) * 100

    return render_template(
        "result.html",
        prediction=INDEX_TO_CLASS[class_id],
        confidence=f"{confidence:.2f}%",
        image_path=path
    )


# ---------- LIVE SENSOR ----------
@app.route("/live_health")
def live_health():
    return render_template("live_health.html")


@app.route("/live_sensor")
def live_sensor():
    return jsonify({
        "heart_rate": sensor_data.get("heart_rate"),
        "spo2": sensor_data.get("spo2"),
        "status": sensor_data.get("status")
    })


@app.route("/health_analysis")
def health_analysis():
    hr = sensor_data.get("heart_rate")
    spo2 = sensor_data.get("spo2")
    return jsonify(analyze_health(hr, spo2))


# ---------- PCOD ----------
@app.route("/pcod")
def pcod():
    return render_template("pcod.html")


@app.route("/pcod_predict", methods=["POST"])
def pcod_predict():
    try:
        bmi = float(request.form.get("bmi", 0))
        fatigue = int(request.form.get("fatigue", 0))
        sleep = int(request.form.get("sleep", 0))
        stress = int(request.form.get("stress", 0))
        activity = request.form.get("activity", "moderate")
        diet = request.form.get("diet", "balanced")
        family = request.form.get("family_history", "no")

        score = 0
        score += 2 if bmi >= 25 else 0
        score += fatigue + stress
        score += 2 if family == "yes" else 0
        score += 1 if activity == "low" else 0
        score += 1 if diet == "junk" else 0

        risk = "HIGH PCOD RISK" if score >= 10 else "MODERATE PCOD RISK" if score >= 6 else "LOW PCOD RISK"

        advice = [
            "Maintain healthy BMI",
            "Follow balanced diet",
            "Exercise regularly",
            "Improve sleep quality",
            "Reduce stress",
            "Consult gynecologist if symptoms persist"
        ]

        return render_template("pcod_result.html", risk=risk, advice=advice)

    except Exception as e:
        return f"PCOD Error: {e}"


# ---------- DIABETES ----------
@app.route("/diabetes")
def diabetes():
    return render_template("diabetes.html")


@app.route("/diabetes_predict", methods=["POST"])
def diabetes_predict():
    try:
        bmi = float(request.form.get("bmi", 0))
        family = request.form.get("family", "no")
        urination = request.form.get("urination", "no")
        thirst = request.form.get("thirst", "no")
        fatigue = request.form.get("fatigue", "no")
        activity = request.form.get("activity", "moderate")
        diet = request.form.get("diet", "no")
        bp = request.form.get("bp", "no")

        score = (
            (2 if bmi >= 25 else 0) +
            (2 if family == "yes" else 0) +
            (1 if urination == "yes" else 0) +
            (1 if thirst == "yes" else 0) +
            (1 if fatigue == "yes" else 0) +
            (1 if activity == "low" else 0) +
            (1 if diet == "yes" else 0) +
            (1 if bp == "yes" else 0)
        )

        risk = "HIGH DIABETES RISK" if score >= 7 else "MODERATE DIABETES RISK" if score >= 4 else "LOW DIABETES RISK"

        advice = [
            "Maintain healthy body weight",
            "Follow low sugar balanced diet",
            "Exercise regularly",
            "Monitor blood glucose levels",
            "Consult physician if symptoms persist"
        ]

        return render_template("diabetes_result.html", risk=risk, advice=advice)

    except Exception as e:
        return f"DIABETES Error: {e}"


# ---------- MIGRAINE ----------
@app.route("/migraine")
def migraine():
    return render_template("migraine.html")


@app.route("/migraine_predict", methods=["POST"])
def migraine_predict():
    try:
        score = 0
        risks = []

        yes_fields = [
            "family","unilateral","throbbing","nausea","light",
            "sound","aura","dizziness","activity_worse",
            "insomnia","meals","hormonal"
        ]

        for field in yes_fields:
            if request.form.get(field) == "yes":
                score += 1
                risks.append(field.replace("_"," ").title())

        def safe_int(val):
            try: return int(val)
            except: return 0

        intensity = safe_int(request.form.get("intensity"))
        stress = safe_int(request.form.get("stress"))
        sleep = safe_int(request.form.get("sleep"))

        score += intensity // 3 + stress // 3

        if sleep and sleep < 6:
            score += 1
            risks.append("Low Sleep Duration")

        risk = "HIGH MIGRAINE RISK" if score >= 10 else "MODERATE MIGRAINE RISK" if score >= 6 else "LOW MIGRAINE RISK"

        advice = [
            "Maintain regular sleep routine",
            "Reduce stress",
            "Avoid migraine triggers",
            "Stay hydrated",
            "Limit caffeine",
            "Consult neurologist if frequent headaches"
        ]

        return render_template("migraine_result.html", risk=risk, risks=risks, advice=advice)

    except Exception as e:
        return f"MIGRAINE Error: {e}"


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)