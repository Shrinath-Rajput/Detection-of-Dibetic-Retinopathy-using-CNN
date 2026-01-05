import os
import json
import numpy as np
import tensorflow as tf

from flask import Flask, render_template, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename

from src.services.sensor_service import (
    sensor_data,
    start_sensor_thread
)

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
print("✅ DR Model Loaded")

with open("class_indices.json") as f:
    class_indices = json.load(f)

INDEX_TO_CLASS = {v: k for k, v in class_indices.items()}

# =========================
# Start Sensor Thread (ONLY ONCE)
# =========================
start_sensor_thread()
print("✅ Sensor thread started")

# =========================
# Helper Functions
# =========================
def preprocess_image(img_path):
    img = tf.keras.preprocessing.image.load_img(img_path, target_size=(224, 224))
    img = tf.keras.preprocessing.image.img_to_array(img)
    img = img / 255.0
    img = np.expand_dims(img, axis=0)
    return img


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

    if hr_status == "HIGH" and spo2_status == "LOW":
        risk.append("Combined cardiovascular & respiratory risk")

    if not risk:
        advice.append("All vitals are normal. Maintain healthy lifestyle.")
    else:
        advice.extend([
            "Take proper rest",
            "Practice deep breathing exercises",
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
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/predict", methods=["POST"])
def predict():
    file = request.files.get("image")
    if not file or file.filename == "":
        return redirect(url_for("home"))

    filename = secure_filename(file.filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(path)

    img = preprocess_image(path)
    preds = model.predict(img)
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
    # page only
    return render_template("live_health.html")


@app.route("/live_sensor")
def live_sensor_api():
    """
    Only RAW SENSOR DATA
    """
    return jsonify({
        "heart_rate": sensor_data.get("heart_rate"),
        "spo2": sensor_data.get("spo2"),
        "status": sensor_data.get("status")
    })


@app.route("/health_analysis")
def health_analysis_api():
    """
    Risk + Advice logic
    """
    hr = sensor_data.get("heart_rate")
    spo2 = sensor_data.get("spo2")

    analysis = analyze_health(hr, spo2)

    return jsonify(analysis)


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    app.run(
        debug=False,        # 🔥 MUST be False
        use_reloader=False # 🔥 MUST be False
    )
