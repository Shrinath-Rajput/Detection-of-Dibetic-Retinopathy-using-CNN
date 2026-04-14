import os
import json
import numpy as np
import tensorflow as tf

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

# =========================
# Flask Init
# =========================
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = "secret123"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# =========================
# LOAD TFLITE MODEL
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
# HELPER
# =========================
def preprocess_image(img_path):
    try:
        img = tf.keras.preprocessing.image.load_img(img_path, target_size=(224, 224))
        img = tf.keras.preprocessing.image.img_to_array(img)
        img = img / 255.0
        return np.expand_dims(img, axis=0).astype("float32")
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


@app.route("/pcod")
def pcod_page():
    return render_template("pcod.html")


@app.route("/diabetes")
def diabetes_page():
    return render_template("diabetes.html")


@app.route("/chatbot")
def chatbot_page():
    return render_template("chatbot.html")


@app.route("/live_health")
def live_health():
    return render_template("live_health.html")


# =========================
# PREDICT (COMMON FUNCTION)
# =========================
def predict_logic(file):
    if file is None or file.filename == "":
        return "No file uploaded ❌"

    path = os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(file.filename))
    file.save(path)

    img = preprocess_image(path)

    if img is None:
        return "Image processing failed ❌"

    interpreter.set_tensor(input_details[0]["index"], img)
    interpreter.invoke()
    preds = interpreter.get_tensor(output_details[0]["index"])

    class_id = int(np.argmax(preds))
    confidence = float(np.max(preds)) * 100

    return render_template(
        "result.html",
        prediction=INDEX_TO_CLASS.get(class_id, "Unknown"),
        confidence=f"{confidence:.2f}%",
        image_path=path
    )


# =========================
# DR PREDICT
# =========================
@app.route("/predict", methods=["POST"])
def predict():
    try:
        return predict_logic(request.files.get("file"))
    except Exception as e:
        return f"ERROR: {str(e)}"


# =========================
# PCOD PREDICT
# =========================
@app.route("/pcod_predict", methods=["POST"])
def pcod_predict():
    try:
        return predict_logic(request.files.get("file"))
    except Exception as e:
        return f"ERROR: {str(e)}"


# =========================
# DIABETES PREDICT
# =========================
@app.route("/diabetes_predict", methods=["POST"])
def diabetes_predict():
    try:
        return predict_logic(request.files.get("file"))
    except Exception as e:
        return f"ERROR: {str(e)}"


# =========================
# CHAT API
# =========================
@app.route("/chat", methods=["POST"])
def chat():
    msg = request.json.get("message", "")
    return jsonify({"reply": f"You said: {msg}"})


# =========================
# SENSOR (DUMMY)
# =========================
sensor_data = {
    "heart_rate": 72,
    "temperature": 36.5,
    "spo2": 98
}

@app.route("/live_sensor")
def live_sensor():
    return jsonify(sensor_data)


@app.route("/health_analysis")
def health_analysis():
    return jsonify({
        "status": "Healthy",
        "message": "All vitals normal"
    })


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # Render compatible
    app.run(host="0.0.0.0", port=port)