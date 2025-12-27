import os
from src.logger import logging
from src.exception import CustomException

class DataIngestion:

    def initiate_data_ingestion(self):
        try:
            logging.info("Starting Data Ingestion")

            project_root = os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )

            raw_dir = os.path.join(
                project_root,
                "data",
                "raw",
                "Dibetic Retinopathy"
            )

            if not os.path.isdir(raw_dir):
                raise Exception(f"Raw directory not found: {raw_dir}")

            logging.info(f"Searching colored_images inside: {raw_dir}")

            colored_images_path = None

            # 🔥 recursive search
            for root, dirs, files in os.walk(raw_dir):
                if "colored_images" in dirs:
                    colored_images_path = os.path.join(root, "colored_images")
                    break

            if colored_images_path is None:
                raise Exception("colored_images folder not found anywhere")

            logging.info(f"Found dataset at: {colored_images_path}")
            return colored_images_path

        except Exception as e:
            raise CustomException(e)
