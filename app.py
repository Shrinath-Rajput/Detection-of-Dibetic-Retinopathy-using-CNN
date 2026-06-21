# app.py
import os
import json
import numpy as np
import tensorflow as tf
import time

from flask import Flask, render_template, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename

from src.services.sensor_service import sensor_data, start_sensor_thread
from src.chatbot.bot import chatbot_response

app = Flask(__name__)
app.secret_key = "clinsense_ai_secret"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config['JSON_SORT_KEYS'] = False

import gdown

MODEL_PATH = "dr_cnn_model.h5"

if not os.path.exists(MODEL_PATH):
    url = "https://drive.google.com/uc?id=1r-jqC-X67DQo2yf_ozOr2LiGLVMbNL_J"
    gdown.download(url, MODEL_PATH, quiet=False)

model = tf.keras.models.load_model(MODEL_PATH, compile=False)

with open("class_indices.json") as f:
    class_indices = json.load(f)

INDEX_TO_CLASS = {v: k for k, v in class_indices.items()}

print("[STARTUP] Initializing sensor thread...")
start_sensor_thread()
print(f"[STARTUP] Sensor data: {sensor_data}")

def preprocess_image(img_path):
    img = tf.keras.preprocessing.image.load_img(img_path, target_size=(224, 224))
    img = tf.keras.preprocessing.image.img_to_array(img) / 255.0
    return np.expand_dims(img, axis=0)

def analyze_health(hr, spo2):
    hr_status = "UNKNOWN"
    spo2_status = "UNKNOWN"
    risk = []
    advice = []

    try:
        if hr != "--":
            hr = int(hr)
        else:
            hr = None
    except:
        hr = None

    try:
        if spo2 != "--":
            spo2 = int(spo2)
        else:
            spo2 = None
    except:
        spo2 = None

    if hr is not None:
        if hr < 60:
            hr_status = "LOW"
            risk.append("Low heart rate (Bradycardia)")
        elif hr > 100:
            hr_status = "HIGH"
            risk.append("High heart rate (Stress/Hypertension)")
        else:
            hr_status = "NORMAL"
    else:
        hr_status = "WAITING"

    if spo2 is not None:
        if spo2 < 95:
            spo2_status = "LOW"
            risk.append("Low oxygen level (Breathing issue)")
        else:
            spo2_status = "NORMAL"
    else:
        spo2_status = "WAITING"

    if not risk:
        advice = [
            "All vitals are normal. Maintain healthy lifestyle.",
            "Continue monitoring your health regularly.",
            "Stay active and exercise regularly.",
            "Ensure proper sleep and rest."
        ]
    else:
        advice = [
            "Take proper rest",
            "Practice deep breathing",
            "Reduce stress",
            "Drink enough water",
            "Consult doctor if values persist"
        ]

    return {
        "heart_rate_status": hr_status,
        "spo2_status": spo2_status,
        "risk": risk,
        "advice": advice
    }

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/dr")
def dr_page():
    return render_template("index.html")

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

@app.route("/live_health")
def live_health():
    return render_template("live_health.html")

@app.route("/get_sensor_data")
def get_sensor_data():
    data = {
        "heart_rate": sensor_data.get("heart_rate", "--"),
        "spo2": sensor_data.get("spo2", "--"),
        "status": sensor_data.get("status", "DISCONNECTED")
    }
    response = jsonify(data)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Accel-Expires'] = '0'
    return response

@app.route("/health_analysis")
def health_analysis():
    hr = sensor_data.get("heart_rate")
    spo2 = sensor_data.get("spo2")
    return jsonify(analyze_health(hr, spo2))

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
        return render_template(
            "migraine_result.html",
            risk="Unable to calculate risk",
            risks=["Please fill all fields correctly"],
            advice=["Try submitting the form again", "Contact support if issue persists"]
        )

@app.route("/chatbot")
def chatbot():
    return render_template("chatbot.html")

@app.route("/chat-health", methods=["GET"])
def chat_health():
    """Debug endpoint to verify chatbot route is available"""
    return jsonify({"status": "ok", "message": "Chat endpoint is available"}), 200

@app.route("/chat", methods=["POST"])
def chat():
    try:
        # Get JSON data
        data = request.get_json(force=True, silent=True)
        
        if data is None:
            print("[CHAT ERROR] No JSON data received")
            return jsonify({"reply": "Invalid request format"}), 400
        
        user_msg = data.get("message", "").strip()
        
        if not user_msg:
            print("[CHAT ERROR] Empty message received")
            return jsonify({"reply": "Please ask a question"}), 400
        
        print(f"[CHAT] User message: {user_msg}")
        
        # Call chatbot
        try:
            reply = chatbot_response(user_msg)
            print(f"[CHAT] Bot reply: {reply}")
            return jsonify({"reply": reply}), 200
        except Exception as bot_error:
            print(f"[CHAT BOT ERROR] {str(bot_error)}")
            return jsonify({"reply": "Chatbot service error. Please try again."}), 500
            
    except Exception as e:
        print(f"[CHAT ROUTE ERROR] {str(e)}")
        return jsonify({"reply": "Server error. Please try again."}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)