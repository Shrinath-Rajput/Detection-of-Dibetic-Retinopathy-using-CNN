import json

from src.components.data_transformation import DataTransformation
from src.components.model_trainer import ModelTrainer


if __name__ == "__main__":

    print("\n🚀 Starting CareSense DR Training Pipeline...\n")

    # ==========================
    # Data Transformation
    # ==========================
    transformation = DataTransformation()

    train_data, val_data = transformation.get_data_generators()

    # ==========================
    # Save Class Indices
    # ==========================
    with open("class_indices.json", "w") as f:
        json.dump(
            train_data.class_indices,
            f,
            indent=4
        )

    print("\n✅ CLASS INDICES SAVED")
    print(train_data.class_indices)

    # ==========================
    # Model Training
    # ==========================
    trainer = ModelTrainer()

    trainer.train(
        train_data,
        val_data
    )

    print("\n🎉 Training Completed Successfully")
    print("✅ Model Saved : dr_cnn_model.h5")
    print("✅ Class Mapping Saved : class_indices.json")