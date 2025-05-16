# config.py — chứa các setting chung của app

import os
import certifi
from motor.motor_asyncio import AsyncIOMotorClient

# Lấy SECRET_KEY từ env hoặc dùng default
SECRET_KEY = os.getenv("SECRET_KEY")

# Kết nối MongoDB
# MONGODB_URL = os.getenv("MONGODB")
MONGODB_URL = "mongodb+srv://kiritosamsung:ngQte96hSvW6WiI2@cluster0.xi8yzg4.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

_client = AsyncIOMotorClient(
    MONGODB_URL,
    tls=True,
    tlsCAFile=certifi.where()
)

db = _client["hotel_database"]
