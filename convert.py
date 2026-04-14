import tensorflow as tf

print("Loading model...")
model = tf.keras.models.load_model("dr_cnn_model.h5")

print("Converting to TFLite...")
converter = tf.lite.TFLiteConverter.from_keras_model(model)
tflite_model = converter.convert()

with open("model.tflite", "wb") as f:
    f.write(tflite_model)

print("✅ Conversion Done: model.tflite created")