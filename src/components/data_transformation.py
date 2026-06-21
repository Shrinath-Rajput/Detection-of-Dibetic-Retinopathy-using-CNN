from tensorflow.keras.preprocessing.image import ImageDataGenerator

from src.logger import logging
from src.exception import CustomException


class DataTransformation:

    def get_data_generators(self):

        try:

            train_path = "data/train"
            val_path = "data/val"

            train_datagen = ImageDataGenerator(
                rescale=1./255,
                rotation_range=20,
                zoom_range=0.2,
                shear_range=0.2,
                horizontal_flip=True
            )

            val_datagen = ImageDataGenerator(
                rescale=1./255
            )

            train_data = train_datagen.flow_from_directory(
                train_path,
                target_size=(224,224),
                batch_size=32,
                class_mode='categorical'
            )

            val_data = val_datagen.flow_from_directory(
                val_path,
                target_size=(224,224),
                batch_size=32,
                class_mode='categorical'
            )

            print(train_data.class_indices)

            return train_data, val_data

        except Exception as e:
            raise CustomException(e)