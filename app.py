import os
import json
import numpy as np
import tensorflow as tf

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "secret123"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# =========================
# SAFE MODEL LOAD
# =========================
interpreter = None
INDEX_TO_CLASS = {}

try:
    interpreter = tf.lite.Interpreter(model_path="model.tflite")
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    with open("class_indices.json") as f:
        class_indices = json.load(f)
        INDEX_TO_CLASS = {v: k for k, v in class_indices.items()}

    print("✅ Model Loaded Successfully")

except Exception as e:
    print("❌ Model Load Failed:", e)


# =========================
# HELPER
# =========================
def preprocess_image(img_path):
    img = tf.keras.preprocessing.image.load_img(img_path, target_size=(224, 224))
    img = tf.keras.preprocessing.image.img_to_array(img)
    img = img / 255.0
    return np.expand_dims(img, axis=0).astype("float32")


def predict_logic(file):
    if interpreter is None:
        return "Model not loaded ❌"

    if file is None or file.filename == "":
        return "No file uploaded ❌"

    path = os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(file.filename))
    file.save(path)

    img = preprocess_image(path)

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
# ROUTES
# =========================
@app.route("/")
def home():
    return render_template("home.html")


@app.route("/dr")
def dr():
    return render_template("index.html")


@app.route("/pcod")
def pcod():
    return render_template("pcod.html")


@app.route("/diabetes")
def diabetes():
    return render_template("diabetes.html")


@app.route("/chatbot")
def chatbot():
    return render_template("chatbot.html")


@app.route("/live_health")
def live_health():
    return render_template("live_health.html")


# =========================
# PREDICT ROUTES
# =========================
@app.route("/predict", methods=["POST"])
def predict():
    return predict_logic(request.files.get("file"))


@app.route("/pcod_predict", methods=["POST"])
def pcod_predict():
    return predict_logic(request.files.get("file"))


@app.route("/diabetes_predict", methods=["POST"])
def diabetes_predict():
    return predict_logic(request.files.get("file"))


# =========================
# EXTRA
# =========================
@app.route("/live_sensor")
def live_sensor():
    return jsonify({"heart_rate": 72})


@app.route("/health_analysis")
def health_analysis():
    return jsonify({"status": "OK"})


@app.route("/chat", methods=["POST"])
def chat():
    msg = request.json.get("message", "")
    return jsonify({"reply": msg})


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)