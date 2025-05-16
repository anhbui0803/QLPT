import motor.motor_asyncio
from configs import get_configs

# Get MongoDB connection string from configs
MONGODB_URL = get_configs().mongodb

# Create Motor client
client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URL)

# Get database instance
hotel_database = client.hotel_database

# Initialize collections
# booking_collection = hotel_database.bookings
# hotel_collection = hotel_database.hotels
# apartment_collection = hotel_database.apartments
account_collection = hotel_database.accounts
# favorite_collection = hotel_database.favorites
# review_collection = hotel_database.reviews
# rating_collection = hotel_database.ratings
# payment_collection = hotel_database.payments

# Database connection test function
async def check_database_connection():
    try:
        await client.admin.command('ping')
        print("Successfully connected to MongoDB!")
        return True
    except Exception as e:
        print(f"Failed to connect to MongoDB: {e}")
        return False
