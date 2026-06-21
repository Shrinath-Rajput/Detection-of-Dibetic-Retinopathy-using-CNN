from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.layers import Dense, GlobalAveragePooling2D, Dropout
from tensorflow.keras.models import Model
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

from src.logger import logging
from src.exception import CustomException


class ModelTrainer:

    def train(self, train_data, val_data):

        try:

            logging.info("Starting Model Training")

            base_model = MobileNetV2(
                weights="imagenet",
                include_top=False,
                input_shape=(224, 224, 3)
            )

            base_model.trainable = False

            x = base_model.output
            x = GlobalAveragePooling2D()(x)

            x = Dense(
                256,
                activation='relu'
            )(x)

            x = Dropout(0.5)(x)

            predictions = Dense(
                7,
                activation='softmax'
            )(x)

            model = Model(
                inputs=base_model.input,
                outputs=predictions
            )

            model.compile(
                optimizer='adam',
                loss='categorical_crossentropy',
                metrics=['accuracy']
            )

            early_stop = EarlyStopping(
                monitor='val_loss',
                patience=5,
                restore_best_weights=True
            )

            reduce_lr = ReduceLROnPlateau(
                monitor='val_loss',
                factor=0.2,
                patience=3,
                verbose=1
            )

            history = model.fit(
                train_data,
                validation_data=val_data,
                epochs=20,
                callbacks=[
                    early_stop,
                    reduce_lr
                ]
            )

            model.save("dr_cnn_model.h5")

            print("\n✅ MODEL SAVED SUCCESSFULLY")
            print("📁 File: dr_cnn_model.h5")
            print(f"🎯 Final Train Accuracy: {history.history['accuracy'][-1]:.4f}")
            print(f"🎯 Final Val Accuracy: {history.history['val_accuracy'][-1]:.4f}")

            logging.info("Training Completed Successfully")

        except Exception as e:
            raise CustomException(e)