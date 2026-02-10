import os
from dataclasses import dataclass
from typing import Set, Dict
from collections import deque
from motor.motor_asyncio import AsyncIOMotorClient
import pytz

@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
    PORT: int = int(os.getenv("PORT", "10000"))
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    INDIAN_TZ = pytz.timezone('Asia/Kolkata')
    BOT_USERNAME: str = ""
    BOT_ID: int = 0

config = Config()

# MongoDB
mongo_client = AsyncIOMotorClient(config.MONGODB_URI)
db = mongo_client.alita_bot

# Collections
users_col = db.users
groups_col = db.groups
stickers_col = db.stickers
notes_col = db.notes
reminders_col = db.reminders
warnings_col = db.warnings
afk_col = db.afk

# In-memory storage
chat_memory: Dict[int, deque] = {}
user_emotions: Dict[int, str] = {}
started_users: Set[int] = set()
saved_stickers: list = []
