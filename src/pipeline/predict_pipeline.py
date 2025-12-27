import tensorflow as tf
import numpy as np
from tensorflow.keras.preprocessing import image

class PredictPipeline:
    def predict(self, img_path):
        model = tf.keras.models.load_model("artifacts/dr_model.h5")
        img = image.load_img(img_path, target_size=(224,224))
        img = image.img_to_array(img)/255.0
        img = np.expand_dims(img, axis=0)

        pred = model.predict(img)
        return pred
