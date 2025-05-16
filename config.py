# config.py — chứa các setting chung của app

import os
import certifi
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv


load_dotenv()
# Lấy SECRET_KEY từ env hoặc dùng default
SECRET_KEY = os.getenv("SECRET_KEY")

# Sau đó mới lấy biến môi trường
MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    raise RuntimeError("MISSING ENV VAR: MONGODB_URI")

# 1) Synchronous client to do a blocking ping (SSL handshake) at import time
_sync = MongoClient(
    MONGODB_URI,
    tls=True,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=5_000,
)
# this will raise immediately if TLS fails
_sync.admin.command("ping")

# 2) Your async client (re-uses certifi bundle)
_async_client = AsyncIOMotorClient(
    MONGODB_URI,
    tls=True,
    tlsCAFile=certifi.where(),
)
db = _async_client["hotel_database"]
