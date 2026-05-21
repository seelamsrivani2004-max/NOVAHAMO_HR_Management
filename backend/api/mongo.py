import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv('MONGODB_URI', 'mongodb://127.0.0.1:27017/hamo_employees')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

try:
    client.admin.command('ping')
    db_obj = client.get_default_database()
    DATABASE_NAME = db_obj.name if db_obj is not None else 'hamo_employees'
    print(f"MongoDB connected successfully to '{DATABASE_NAME}' at {MONGO_URI}")
except Exception as exc:
    DATABASE_NAME = 'hamo_employees'
    print(f"MongoDB connection failed: {exc}")

try:
    db = client[DATABASE_NAME]
except Exception:
    db = None
