# config.py — chứa các setting chung của app

import os
import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv


load_dotenv()
# Lấy SECRET_KEY từ env hoặc dùng default
SECRET_KEY = os.getenv("SECRET_KEY")

# Sau đó mới lấy biến môi trường
MONGODB_URI = os.getenv("MONGODB_URI")
print(MONGODB_URI)
if not MONGODB_URI:
    raise RuntimeError("MISSING ENV VAR: MONGODB_URI")

async def get_db():
    client = AsyncIOMotorClient(
        MONGODB_URI,
        tls=True,
        tlsCAFile=certifi.where(),
    )
    try:
        yield client["hotel_database"]
    finally:
        client.close()
