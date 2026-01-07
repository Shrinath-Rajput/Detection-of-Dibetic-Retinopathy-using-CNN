import os
import json
import sys
import pymongo
from dotenv import load_dotenv

# =========================
# Load Environment
# =========================
load_dotenv()

MONGO_DB_URL = os.getenv("MONGO_DB_URL", "mongodb://localhost:27017")

# =========================
# MongoDB Utility Class
# =========================
class ProjectDataPush:
    def __init__(self, database_name: str, collection_name: str):
        self.client = pymongo.MongoClient(MONGO_DB_URL)
        self.database = self.client[database_name]
        self.collection = self.database[collection_name]

    def insert_records(self, records: list):
        if not records:
            print("⚠️ No records to insert")
            return 0

        self.collection.insert_many(records)
        return len(records)


# =========================
# Example Usage
# =========================
if __name__ == "__main__":

    DATABASE_NAME = "dr_project"
    COLLECTION_NAME = "prediction_history"

    # 🔹 Example records (same structure as app.py inserts)
    sample_records = [
        {
            "image": "test1.jpg",
            "prediction": "Moderate",
            "confidence": 72.45
        },
        {
            "image": "test2.jpg",
            "prediction": "No_DR",
            "confidence": 88.12
        }
    ]

    mongo_push = ProjectDataPush(
        database_name=DATABASE_NAME,
        collection_name=COLLECTION_NAME
    )

    count = mongo_push.insert_records(sample_records)
    print(f"✅ Inserted {count} records into MongoDB")
