import os
import mlflow
import mlflow.tensorflow
import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Conv2D, MaxPooling2D, Flatten, Dense, Dropout, Input
from tensorflow.keras.optimizers import Adam

# =========================
# MLflow (DagsHub)
# =========================
mlflow.set_experiment("Diabetic_Retinopathy_CNN")

# =========================
# CORRECT DATASET PATHS
# =========================
TRAIN_DIR = "data/train"
VAL_DIR   = "data/val"

IMG_SIZE = (224, 224)
BATCH_SIZE = 32
EPOCHS = 10
LR = 0.0001

# =========================
# Data Generators
# =========================
train_datagen = ImageDataGenerator(
    rescale=1./255,
    rotation_range=20,
    zoom_range=0.2,
    horizontal_flip=True
)

val_datagen = ImageDataGenerator(rescale=1./255)

train_data = train_datagen.flow_from_directory(
    TRAIN_DIR,
    target_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    class_mode="categorical"
)

val_data = val_datagen.flow_from_directory(
    VAL_DIR,
    target_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    class_mode="categorical"
)

NUM_CLASSES = train_data.num_classes

# =========================
# CNN Model
# =========================
model = Sequential([
    Input(shape=(224, 224, 3)),
    Conv2D(32, (3,3), activation="relu"),
    MaxPooling2D(2,2),

    Conv2D(64, (3,3), activation="relu"),
    MaxPooling2D(2,2),

    Conv2D(128, (3,3), activation="relu"),
    MaxPooling2D(2,2),

    Flatten(),
    Dense(256, activation="relu"),
    Dropout(0.5),
    Dense(NUM_CLASSES, activation="softmax")
])

model.compile(
    optimizer=Adam(learning_rate=LR),
    loss="categorical_crossentropy",
    metrics=["accuracy"]
)

# =========================
# Training + MLflow Logging
# =========================
with mlflow.start_run():
    mlflow.log_param("epochs", EPOCHS)
    mlflow.log_param("batch_size", BATCH_SIZE)
    mlflow.log_param("learning_rate", LR)

    history = model.fit(
        train_data,
        validation_data=val_data,
        epochs=EPOCHS
    )

    mlflow.log_metric("final_train_accuracy", history.history["accuracy"][-1])
    mlflow.log_metric("final_val_accuracy", history.history["val_accuracy"][-1])

    model.save("dr_cnn_model.h5")
    mlflow.tensorflow.log_model(model, artifact_path="model")

print("✅ Training completed successfully")
print("✅ Model logged to DagsHub MLflow")
