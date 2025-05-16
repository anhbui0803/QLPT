# config.py — chứa các setting chung của app

import os
from motor.motor_asyncio import AsyncIOMotorClient

# Lấy SECRET_KEY từ env hoặc dùng default
SECRET_KEY = os.getenv("SESSION_SECRET", "dev-secret-do-not-use")

# Kết nối MongoDB
MONGODB_URL = os.getenv("MONGODB", "mongodb://localhost:27017")
_client = AsyncIOMotorClient(MONGODB_URL)
db = _client["hotel_database"]
