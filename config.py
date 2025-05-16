# config.py — chứa các setting chung của app

import os
import certifi
from motor.motor_asyncio import AsyncIOMotorClient

# Lấy SECRET_KEY từ env hoặc dùng default
SECRET_KEY = os.getenv("SECRET_KEY")

# Kết nối MongoDB
MONGODB_URL = os.getenv("MONGODB")

_client = AsyncIOMotorClient(
    MONGODB_URL,
    tls=True,
    tlsCAFile=certifi.where()
)

db = _client["hotel_database"]
