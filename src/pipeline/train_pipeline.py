from src.components.data_ingestion import DataIngestion
from src.components.data_transformation import DataTransformation
from src.components.model_trainer import ModelTrainer

if __name__ == "__main__":

    ingestion = DataIngestion()
    dataset_path = ingestion.initiate_data_ingestion()

    transformation = DataTransformation()
    train_data, val_data = transformation.get_data_generators(dataset_path)

    trainer = ModelTrainer()
    trainer.train(train_data, val_data)
