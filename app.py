import os
import json
import numpy as np
import tensorflow as tf

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

from src.services.sensor_service import sensor_data, start_sensor_thread
from src.chatbot.bot import chatbot_response

# =========================
# Flask Init
# =========================
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = "clinsense_ai_secret"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# =========================
# LOAD TFLITE MODEL 🔥
# =========================
interpreter = tf.lite.Interpreter(model_path="model.tflite")
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# =========================
# LOAD CLASS INDEX
# =========================
with open("class_indices.json") as f:
    class_indices = json.load(f)

INDEX_TO_CLASS = {v: k for k, v in class_indices.items()}

# =========================
# Start Sensor Thread
# =========================
start_sensor_thread()

# =========================
# Helper
# =========================
def preprocess_image(img_path):
    try:
        img = tf.keras.preprocessing.image.load_img(img_path, target_size=(224, 224))
        img = tf.keras.preprocessing.image.img_to_array(img)
        img = img / 255.0
        return np.expand_dims(img, axis=0).astype('float32')
    except:
        return None

# =========================
# ROUTES
# =========================

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/dr")
def dr_page():
    return render_template("index.html")

@app.route("/predict", methods=["POST"])
def predict():
    try:
        file = request.files.get("file")

        if file is None or file.filename == "":
            return "No file uploaded ❌"

        path = os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(file.filename))
        file.save(path)

        img = preprocess_image(path)

        if img is None:
            return "Image processing failed ❌"

        # 🔥 TFLite prediction
        interpreter.set_tensor(input_details[0]['index'], img)
        interpreter.invoke()
        preds = interpreter.get_tensor(output_details[0]['index'])

        class_id = int(np.argmax(preds))
        confidence = float(np.max(preds)) * 100

        return render_template(
            "result.html",
            prediction=INDEX_TO_CLASS.get(class_id, "Unknown"),
            confidence=f"{confidence:.2f}%",
            image_path=path
        )

    except Exception as e:
        return f"ERROR: {str(e)}"

@app.route("/live_sensor")
def live_sensor():
    return jsonify(sensor_data)

@app.route("/chat", methods=["POST"])
def chat():
    msg = request.json.get("message", "")
    return jsonify({"reply": chatbot_response(msg)})

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port) 