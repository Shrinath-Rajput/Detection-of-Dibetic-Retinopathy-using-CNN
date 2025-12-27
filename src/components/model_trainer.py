import mlflow
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Conv2D, MaxPooling2D, Flatten, Dense, Dropout
from src.logger import logging
from src.exception import CustomException

class ModelTrainer:

    def train(self, train_data, val_data):
        try:
            logging.info("Model Training Started")

            model = Sequential([
                Conv2D(32, (3,3), activation='relu', input_shape=(224,224,3)),
                MaxPooling2D(2,2),

                Conv2D(64, (3,3), activation='relu'),
                MaxPooling2D(2,2),

                Conv2D(128, (3,3), activation='relu'),
                MaxPooling2D(2,2),

                Flatten(),
                Dense(128, activation='relu'),
                Dropout(0.5),
                Dense(5, activation='softmax')
            ])

            model.compile(
                optimizer='adam',
                loss='categorical_crossentropy',
                metrics=['accuracy']
            )

            with mlflow.start_run():
                history = model.fit(
                    train_data,
                    validation_data=val_data,
                    epochs=10
                )

                mlflow.log_param("epochs", 10)
                mlflow.log_param("optimizer", "adam")
                mlflow.log_metric("train_accuracy", history.history["accuracy"][-1])
                mlflow.log_metric("val_accuracy", history.history["val_accuracy"][-1])

                model.save("dr_cnn_model.h5")
                mlflow.log_artifact("dr_cnn_model.h5")

            logging.info("Model Training Completed")

        except Exception as e:
            raise CustomException(e)
