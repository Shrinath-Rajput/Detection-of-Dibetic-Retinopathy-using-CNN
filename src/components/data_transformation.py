from tensorflow.keras.preprocessing.image import ImageDataGenerator
from src.logger import logging
from src.exception import CustomException

class DataTransformation:

    def get_data_generators(self, dataset_path):
        try:
            logging.info("Starting Data Transformation")

            datagen = ImageDataGenerator(
                rescale=1./255,
                validation_split=0.2
            )

            train_data = datagen.flow_from_directory(
                dataset_path,
                target_size=(224, 224),
                batch_size=32,
                class_mode="categorical",
                subset="training"
            )

            val_data = datagen.flow_from_directory(
                dataset_path,
                target_size=(224, 224),
                batch_size=32,
                class_mode="categorical",
                subset="validation"
            )

            logging.info("Data Generators Created")
            return train_data, val_data

        except Exception as e:
            raise CustomException(e)
