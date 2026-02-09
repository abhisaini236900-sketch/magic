import os
from dataclasses import dataclass
from typing import Set
from motor.motor_asyncio import AsyncIOMotorClient
import pytz

@dataclass
class Config:
    # Bot Config
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
    PORT: int = int(os.getenv("PORT", "10000"))
    
    # API Keys
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    
    # Timezone
    INDIAN_TZ = pytz.timezone('Asia/Kolkata')
    
    # Bot Info
    BOT_USERNAME: str = ""
    BOT_ID: int = 0

# Global config instance
config = Config()

# MongoDB Setup
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

# In-memory storage for fast access
chat_memory = {}  # {chat_id: deque}
user_emotions = {}
started_users: Set[int] = set()
group_settings_cache = {}
saved_stickers: list = []
