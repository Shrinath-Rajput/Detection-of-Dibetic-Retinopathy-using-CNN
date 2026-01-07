from pymongo import MongoClient

uri = "mongodb+srv://rajputshrinath349_db_user:shrinathrajput123@cluster0.g4gxwbw.mongodb.net/?retryWrites=true&w=majority"

client = MongoClient(uri)

try:
    client.admin.command("ping")
    print("✅ MongoDB connected successfully!")
except Exception as e:
    print("❌ MongoDB connection failed")
    print(e)
