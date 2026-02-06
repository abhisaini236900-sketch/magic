import os
import asyncio
import random
import re
import json
import base64
import io
import hashlib
import string
import qrcode
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton,
    InputFile, BufferedInputFile, ChatPermissions, CallbackQuery
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from groq import AsyncGroq
from aiohttp import web
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import aiohttp
from PIL import Image, ImageDraw, ImageFont
import textwrap

conn = sqlite3.connect("users.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")
conn.commit()
cursor.execute("""
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY
)
""")
conn.commit()
# New table for saved stickers
cursor.execute("""
CREATE TABLE IF NOT EXISTS stickers (
    file_id TEXT PRIMARY KEY,
    added_by INTEGER,
    added_at TIMESTAMP,
    tags TEXT DEFAULT ''
)
""")
conn.commit()

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", 10000))
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

# Timezone for India
INDIAN_TIMEZONE = pytz.timezone('Asia/Kolkata')

# Initialize with MemoryStorage
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# Initialize Groq client
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- MEMORY SYSTEMS ---
chat_memory: Dict[int, deque] = {}
user_warnings: Dict[int, Dict[int, Dict]] = defaultdict(lambda: defaultdict(dict))
user_message_count: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
last_messages: Dict[int, Dict[int, List]] = defaultdict(lambda: defaultdict(list))

# User data storage
user_data: Dict[int, Dict] = defaultdict(dict)
user_notes: Dict[int, List[Dict]] = defaultdict(list)
user_reminders: Dict[int, List[Dict]] = defaultdict(list)
user_reputation: Dict[int, int] = defaultdict(int)
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}
started_users: Set[int] = set()

# AFK System
afk_users: Dict[int, Dict] = {}

# Group management
group_settings: Dict[int, Dict] = defaultdict(lambda: {
    "welcome_enabled": True,
    "goodbye_enabled": True,
    "auto_mod_enabled": True,
    "greetings_enabled": True,
    "custom_welcome": None,
    "custom_goodbye": None,
    "language": "hinglish",
    "slow_mode": False,
    "slow_mode_delay": 0,
    "locked": False,
    "filters": [],
    "banned_words": [],
    "raid_mode": False,
    "captcha_enabled": False,
    "log_channel": None,
    "warn_limit": 3,
    "admins": []
})

# CAPTCHA storage
captcha_data: Dict[int, Dict] = {}

# Scheduler
greeting_scheduler = AsyncIOScheduler()
greeted_groups: Dict[int, datetime] = {}

# Last greeting time per chat
last_greeting_time: Dict[int, datetime] = {}

# Saved stickers storage
saved_stickers: List[str] = []

# --- CONSTANTS ---
BAD_WORDS = [
    "chutiya", "chutiye", "madarchod", "behenchod", "bhosdike", "lodu", "gandu",
    "fuck", "shit", "bitch", "bastard", "asshole", "motherfucker", "cunt", "dick",
    "gaand", "lund", "randi", "harami", "kamina", "suar", "kutta", "bhosdi",
    "bc", "mc", "gand", "lauda", "choot", "maa ki", "behen ki"
]

# Adult content keywords
ADULT_KEYWORDS = [
    "porn", "xxx", "nsfw", "adult", "sex", "nude", "naked", "boobs", "ass",
    "dick", "pussy", "hentai", "porno", "horny", "fuck", "sexy", "hot", "desi", "chudai", "lund", "chod"
]

# Fake link patterns
FAKE_LINK_PATTERNS = [
    r'bit\.ly\/[a-zA-Z0-9]+',
    r'tinyurl\.com\/[a-zA-Z0-9]+',
    r'goo\.gl\/[a-zA-Z0-9]+',
    r'shorturl\.at\/[a-zA-Z0-9]+',
    r'ow\.ly\/[a-zA-Z0-9]+',
    r'is\.gd\/[a-zA-Z0-9]+',
    r'cli\.gs\/[a-zA-Z0-9]+',
    r'bc\.vc\/[a-zA-Z0-9]+',
    r'u\.to\/[a-zA-Z0-9]+',
    r'j\.mp\/[a-zA-Z0-9]+'
]

GROUP_LINK_PATTERNS = [
    r'telegram\.me\/[a-zA-Z0-9_]+',
    r'telegram\.dog\/[a-zA-Z0-9_]+',
]

SPAM_LIMIT = 7
SPAM_TIME_WINDOW = 30
WARNING_MESSAGES = [
    "⚠️ **Warning {count}/3** 🚨\n{name}, please don't {action}! This is your warning!",
    "🚨 **Strike {count}!** ⚠️\n{name}, {action} is not allowed! Watch out!",
    "⚡ **Final Warning ({count}/3)** ⚡\n{name}, last chance! Stop {action}!"
]
MUTE_DURATIONS = [
    timedelta(minutes=5),
    timedelta(hours=1),
    timedelta(hours=24),
    timedelta(days=7)
]

# --- STICKER STORAGE SYSTEM ---
def load_stickers():
    """Load saved stickers from database"""
    global saved_stickers
    cursor.execute("SELECT file_id FROM stickers")
    rows = cursor.fetchall()
    saved_stickers = [row[0] for row in rows]
    print(f"✅ Loaded {len(saved_stickers)} stickers from database")

def save_sticker(file_id: str, added_by: int):
    """Save sticker to database"""
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO stickers (file_id, added_by, added_at) VALUES (?, ?, ?)",
            (file_id, added_by, datetime.now())
        )
        conn.commit()
        if cursor.rowcount > 0:
            saved_stickers.append(file_id)
            return True
    except Exception as e:
        print(f"Error saving sticker: {e}")
    return False

# Load stickers on startup
load_stickers()

# --- ADVANCED FEATURES DATA ---
MEME_TEMPLATES = [
    {"text": "When you realize it's Monday tomorrow", "emoji": "😭"},
    {"text": "Me trying to be productive", "emoji": "🤡"},
    {"text": "When someone says 'just be yourself'", "emoji": "😅"},
    {"text": "My bank account after online shopping", "emoji": "💸"},
    {"text": "When code finally works after 100 tries", "emoji": "🎉"},
    {"text": "When mom calls you by your full name", "emoji": "😰"},
    {"text": "Me explaining why I need a new phone", "emoji": "🤥"},
    {"text": "My sleep schedule at 3 AM", "emoji": "🦉"}
]

HOROSCOPE_SIGNS = {
    "aries": "♈", "taurus": "♉", "gemini": "♊", "cancer": "♋",
    "leo": "♌", "virgo": "♍", "libra": "♎", "scorpio": "♏",
    "sagittarius": "♐", "capricorn": "♑", "aquarius": "♒", "pisces": "♓"
}

DAILY_FACTS = [
    "Honey never spoils! 🍯 Archaeologists found 3000-year-old honey still edible!",
    "Octopuses have 3 hearts! 💙 One stops when they swim!",
    "Bananas are berries, but strawberries aren't! 🍌🍓 Mind blown?",
    "A day on Venus is longer than its year! 🌟 Takes 243 days to rotate once!",
    "Sharks existed before trees! 🦈 Trees appeared 350 million years ago!",
    "The human brain uses 20% of body's energy! 🧠 Even when resting!",
    "Butterflies taste with their feet! 🦋 How weird is that?",
    "A group of flamingos is called a 'flamboyance'! 💖 Perfect name!",
    "Wombat poop is cube-shaped! 🟫 Nature's building blocks!",
    "Sloths can hold their breath longer than dolphins! 🦥 40 minutes!"
]

ROAST_RESPONSES = [
    "Tumhari baaton se toh mere kaan bhi sharminda hain! 👂😳",
    "Itni bakwas toh mere phone ki auto-correct bhi nahi karta! 📱",
    "Tumhare jokes se toh meri wallpaper bhi bore ho gayi! 🖼️",
    "Agar overthinking Olympic sport hota, toh tum gold medal le jaate! 🏅",
    "Tumhari logic dekh ke toh Einstein bhi pagal ho jaate! 🧠💥",
    "Tumhare confidence ki toh alag hi duniya hai - unrealistic! 🌍",
    "Tumhare dimaag mein itna khaali hai, wahan echo aata hoga! 🎤",
    "Tum itne slow ho, turtle bhi tumse race jeet jaaye! 🐢"
]

JOKES = [
    "🤣 Teacher: Tumhare ghar me sabse smart kaun hai? Student: Wifi router! Kyuki sab use hi puchte hain!",
    "😂 Papa: Beta mobile chhodo, padhai karo. Beta: Papa, aap bhi to TV dekhte ho! Papa: Par main TV se shaadi nahi kar raha!",
    "😆 Doctor: Aapko diabetes hai. Patient: Kya khana chhodna hoga? Doctor: Nahi, aapka sugar chhodna hoga!",
    "😅 Dost: Tumhari girlfriend kitni cute hai! Me: Haan, uski akal bhi utni hi cute hai!",
    "🤪 Teacher: Agar tumhare paas 5 aam hain aur main 2 le lun, toh kitne bachenge? Student: Sir, aapke paas already 2 kyun hain?",
    "😜 Boyfriend: Tum meri life ki battery ho! Girlfriend: Toh charging khatam kyun ho jati hai?",
    "😁 Boss: Kal se late mat aana. Employee: Aaj hi late kyun bola? Kal bata dete!",
    "😄 Bhai: Behen, tum kyun ro rahi ho? Behen: Mera boyfriend mujhse break-up kar raha hai! Bhai: Uske liye ro rahi ho ya uske jaane ke baad free time ke liye?",
    "🤭 Customer: Yeh shampoo hair fall rokta hai? Shopkeeper: Nahi sir, hair fall hone par refund deta hai!",
    "😹 Boy: I love you! Girl: Tumhare paas girlfriend nahi hai? Boy: Haan, tumhare saath hi baat kar raha hu!"
]

WELCOME_MESSAGES = [
    "🎉 Welcome {name}! Khush aamdeed! 😊",
    "🌟 Aao ji {name}! Group me welcome! 🫂",
    "✨ Hey {name}! Great to have you here! 💖",
    "🥳 {name} aa gaya! Party shuru! 🎊",
    "😊 Namaste {name}! Aapka swagat hai! 🙏",
    "🌸 Welcome {name}! Hope you have a great time! 💕",
    "🎈 Hey {name}! Thanks for joining us! 🎉",
    "💫 Welcome aboard {name}! Enjoy your stay! 🚀"
]

GOODBYE_MESSAGES = [
    "👋 {name} left the group. We'll miss you! 😢",
    "😔 {name} has departed. Take care! 🌸",
    "🚪 {name} left. Bye bye! 👋",
    "💔 {name} is no longer with us. Farewell! 🌟",
    "🌙 {name} has left. Good luck! ✨"
]

# --- RANDOM SELF MESSAGES (UPDATED WITH STICKERS) ---
SELF_MESSAGES = [
    {"type": "text", "content": "Kya kar rahe ho sab? Main bore ho rahi hu! 😴", "delay": 1800},
    {"type": "text", "content": "Koi joke sunao na! Has has ke pet dard ho gaya! 😂", "delay": 2400},
    {"type": "text", "content": "Aaj kya plan hai? Kuch masti karte hain! 🎉", "delay": 3000},
    {"type": "text", "content": "Mujhe laga koi baat karega, par sab busy hain! 😢", "delay": 3600},
    {"type": "sticker", "content": "random", "delay": 4200},
    {"type": "text", "content": "Kya kha rahe ho? Mujhe bhi khilao! 😋", "delay": 4800},
    {"type": "text", "content": "Subah se kisi ne mujhe miss nahi kiya? 🥺", "delay": 5400},
    {"type": "sticker", "content": "random", "delay": 6000},
    {"type": "text", "content": "Good morning sabko! Utho, fresh ho jao! 🌅", "delay": 6600},
    {"type": "text", "content": "Good evening doston! Shaam ki chai ka time! ☕", "delay": 7200},
    {"type": "text", "content": "Good night sweet dreams! 🌙", "delay": 7800},
    {"type": "sticker", "content": "random", "delay": 8400},
]

# --- TIME-BASED GREETING SYSTEM (FIXED) ---
def get_indian_time():
    """Get current Indian time"""
    utc_now = datetime.now(pytz.utc)
    indian_time = utc_now.astimezone(INDIAN_TIMEZONE)
    return indian_time

def get_current_time_period():
    """Get current time period for greetings"""
    indian_time = get_indian_time()
    current_hour = indian_time.hour
    
    if 5 <= current_hour < 12:
        return "morning"
    elif 12 <= current_hour < 17:
        return "afternoon"
    elif 17 <= current_hour < 21:
        return "evening"
    elif 21 <= current_hour <= 23:
        return "night"
    else:
        return "late_night"

TIME_GREETINGS = {
    "morning": {
        "time_range": (5, 11),
        "keywords": ["subah", "morning", "good morning", "सुबह", "शुभ प्रभात"],
        "templates": [
            "🌅 *Good Morning Sunshine!* ☀️\nKaisi hai aaj ki subah? Utho aur muskurao! 😊",
            "🌸 *Shubh Prabhat!* 🌸\nAaj ka din aapke liye khoobsurat ho! ✨",
            "☕ *Morning Coffee Time!* 🍵\nChai piyo, fresh ho jao, aur din shuru karo! 💫"
        ]
    },
    "afternoon": {
        "time_range": (12, 16),
        "keywords": ["dopahar", "afternoon", "good afternoon", "दोपहर", "शुभ दोपहर"],
        "templates": [
            "☀️ *Good Afternoon!* 🌤️\nLunch ho gaya? Energy maintain rakho! 🍲",
            "🌞 *Dopahar ki Dhoop mein!* 🌞\nThoda aaraam karo, phir kaam karo! 😌",
            "🍛 *Afternoon Siesta Time!* 💤\nKhaana kha ke neend aa rahi hai? Hehe! 😴"
        ]
    },
    "evening": {
        "time_range": (17, 20),
        "keywords": ["shaam", "evening", "good evening", "शाम", "शुभ संध्या"],
        "templates": [
            "🌇 *Good Evening Beautiful!* 🌆\nShaam ho gayi, thoda relax karo! 🌹",
            "🌆 *Evening Tea Time!* 🍵\nChai aur baatein - perfect combination! 💖",
            "✨ *Shubh Sandhya!* ✨\nDin bhar ki thakaan door karo! 🎶"
        ]
    },
    "night": {
        "time_range": (21, 23),
        "keywords": ["raat", "night", "good night", "रात", "शुभ रात्रि"],
        "templates": [
            "🌙 *Good Night Sweet Dreams!* 🌟\nAankhein band karo aur accha sapna dekho! 💤",
            "🌌 *Shubh Ratri!* 🌌\nThaka hua dimaag ko aaraam do! 😴",
            "💤 *Sleep Time!* 💤\nKal phir nayi energy ke saath uthna! 🌅"
        ]
    },
    "late_night": {
        "time_range": (0, 4),
        "keywords": ["midnight", "late", "raat", "आधी रात"],
        "templates": [
            "🌃 *Late Night Owls!* 🦉\nSone ka time hai, par chat karna hai? 😄",
            "🌚 *Midnight Chats!* 🌚\nRaat ke 12 baje bhi jag rahe ho? 😲",
            "💫 *Late Night Vibes!* 💫\nSab so rahe hain, hum chat kar rahe hain! 🤫"
        ]
    }
}

# --- QUICK RESPONSES ---
QUICK_RESPONSES = {
    "greeting": [
        "Hii 😊",
        "Hiiiiiiii {name}! 💖",
        "Hyeeeee {name}",
        "Hey there! {name} 🌟",
        "Halloo {name} 💫"
    ],
    "goodbye": [
        "Bye! Take care! 💕",
        "Goodbye! Milte hain phir! 🌸",
        "Tata! Sweet dreams! 🌙",
        "See you later, alligator! 🐊",
        "Alvida! Stay awesome! ✨"
    ],
    "thanks": [
        "Aww, thank you! 🥰",
        "Welcome! 💖",
        "Dhanyavad! You're sweet! 😊",
        "Thanks for being nice! 🌟",
        "Appreciate it! 💕"
    ],
    "sorry": [
        "Koi baat nahi! 🤗",
        "It's okay! 💖",
        "Main maaf karti hu! 😊",
        "No worries! 🌸",
        "Sab theek hai! 💫"
    ]
}

# --- STATES FOR ADVANCED FEATURES ---
class UserStates(StatesGroup):
    setting_reminder = State()
    adding_note = State()
    setting_poll = State()
    voice_chat = State()
    captcha_verify = State()

# --- HUMAN-LIKE BEHAVIOUR (ENHANCED) ---
EMOTIONAL_RESPONSES = {
    "happy": ["😊", "🎉", "🥳", "🌟", "✨", "👍", "💫", "😄", "😍", "🤗", "🫂"],
    "angry": ["😠", "👿", "💢", "🤬", "😤", "🔥", "⚡", "💥", "👊"],
    "crying": ["😢", "😭", "💔", "🥺", "😞", "🌧️", "😿", "🥀", "💧", "🌩️"],
    "love": ["❤️", "💖", "💕", "🥰", "😘", "💋", "💓", "💗", "💘", "💝"],
    "funny": ["😂", "🤣", "😆", "😜", "🤪", "🎭", "🤡", "🃏", "🎪", "🤹"],
    "thinking": ["🤔", "💭", "🧠", "🔍", "💡", "🎯", "🧐", "🔎", "💬", "🗨️"],
    "surprise": ["😲", "🤯", "🎊", "🎁", "💥", "✨", "🎆", "🎇", "🧨", "💫"],
    "sleepy": ["😴", "💤", "🌙", "🛌", "🥱", "😪", "🌃", "🌜", "🌚", "🌌"],
    "hungry": ["😋", "🤤", "🍕", "🍔", "🍟", "🌮", "🍦", "🍩", "🍪", "🍰"],
    "sassy": ["💅", "👑", "💁", "💃", "🕶️", "💄", "👠", "✨", "🌟", "💖"],
    "protective": ["🛡️", "⚔️", "👮", "🚓", "🔒", "🔐", "🪖", "🎖️", "🏹", "🗡️"],
    "flirty": ["😏", "😉", "😘", "💋", "💄", "💅", "👠", "💃", "🫦", "👄"]
}

GIRL_LIKE_RESPONSES = [
    "Aarey waah! 😏",
    "Haye haye! 😅",
    "Oh my god! 😲",
    "Seriously? 🤨",
    "Chalo thik hai! 😊",
    "Mujhe pata tha! 😌",
    "Aise mat bolo na! 🥺",
    "Sahi pakde hain! 😎",
    "Kya baat hai! 🤩",
    "Mast hai yaar! 😄",
    "Waah bhai waah! 👏",
    "Kya keh rahe ho? 🤔",
    "Arey yaar! 😂",
    "Haan na! 😉",
    "Theek hai ji! 🙏",
    "Chalo chalo! 🚶‍♀️",
    "Achha ji! 👍",
    "Hmm interesting! 🤓",
    "Wow! 😍",
    "No way! 😱"
]

def get_emotion(emotion_type: str = None, user_id: int = None) -> str:
    if user_id and user_id in user_emotions:
        if random.random() < 0.3:
            emotion_type = user_emotions[user_id]
    
    if emotion_type and emotion_type in EMOTIONAL_RESPONSES:
        return random.choice(EMOTIONAL_RESPONSES[emotion_type])
    
    all_emotions = list(EMOTIONAL_RESPONSES.values())
    return random.choice(random.choice(all_emotions))

def update_user_emotion(user_id: int, message: str):
    message_lower = message.lower()
    
    if any(word in message_lower for word in ['love', 'pyaar', 'dil', 'heart', 'cute', 'beautiful', 'sweet']):
        user_emotions[user_id] = "love"
    elif any(word in message_lower for word in ['angry', 'gussa', 'naraz', 'mad', 'hate', 'idiot', 'stupid']):
        user_emotions[user_id] = "angry"
    elif any(word in message_lower for word in ['cry', 'ro', 'sad', 'dukh', 'upset', 'unhappy', 'depressed']):
        user_emotions[user_id] = "crying"
    elif any(word in message_lower for word in ['funny', 'has', 'joke', 'comedy', 'masti', 'laugh', 'haha']):
        user_emotions[user_id] = "funny"
    elif any(word in message_lower for word in ['hi', 'hello', 'hey', 'namaste', 'kaise', 'welcome']):
        user_emotions[user_id] = "happy"
    elif any(word in message_lower for word in ['?', 'kyun', 'kaise', 'kya', 'how', 'why', 'what']):
        user_emotions[user_id] = "thinking"
    elif any(word in message_lower for word in ['fight', 'ladai', 'war', 'attack', 'defend']):
        user_emotions[user_id] = "protective"
    elif any(word in message_lower for word in ['sleep', 'sone', 'neend', 'tired', 'thak']):
        user_emotions[user_id] = "sleepy"
    elif any(word in message_lower for word in ['sexy', 'hot', 'cute', 'beautiful', 'handsome']):
        user_emotions[user_id] = "flirty"
    else:
        user_emotions[user_id] = random.choice(list(EMOTIONAL_RESPONSES.keys()))
    
    user_last_interaction[user_id] = datetime.now()

def get_girl_like_response() -> str:
    """Get random girl-like response"""
    return random.choice(GIRL_LIKE_RESPONSES)

# --- REAL WEATHER API (OpenWeatherMap) ---
INDIAN_CITIES = {
    "mumbai": {"lat": 19.0760, "lon": 72.8777},
    "delhi": {"lat": 28.6139, "lon": 77.2090},
    "bangalore": {"lat": 12.9716, "lon": 77.5946},
    "kolkata": {"lat": 22.5726, "lon": 88.3639},
    "chennai": {"lat": 13.0827, "lon": 80.2707},
    "hyderabad": {"lat": 17.3850, "lon": 78.4867},
    "pune": {"lat": 18.5204, "lon": 73.8567},
    "ahmedabad": {"lat": 23.0225, "lon": 72.5714},
    "jaipur": {"lat": 26.9124, "lon": 75.7873},
    "surat": {"lat": 21.1702, "lon": 72.8311},
    "lucknow": {"lat": 26.8467, "lon": 80.9462},
    "kanpur": {"lat": 26.4499, "lon": 80.3319},
    "nagpur": {"lat": 21.1458, "lon": 79.0882},
    "patna": {"lat": 25.5941, "lon": 85.1376},
    "indore": {"lat": 22.7196, "lon": 75.8577},
    "thane": {"lat": 19.2183, "lon": 72.9781},
    "bhopal": {"lat": 23.2599, "lon": 77.4126},
    "visakhapatnam": {"lat": 17.6868, "lon": 83.2185},
    "vadodara": {"lat": 22.3072, "lon": 73.1812},
    "firozabad": {"lat": 27.1592, "lon": 78.3957}
}

async def get_real_weather(city: str = None) -> str:
    """Get REAL weather from OpenWeatherMap API"""
    try:
        if not city:
            city = random.choice(list(INDIAN_CITIES.keys()))
        
        city_lower = city.lower().strip()
        
        # Check if city is in our database
        if city_lower in INDIAN_CITIES:
            coords = INDIAN_CITIES[city_lower]
            city_display = city.title()
        else:
            # Try to get coordinates from OpenWeatherMap API
            async with aiohttp.ClientSession() as session:
                geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city},IN&limit=1&appid={WEATHER_API_KEY}"
                async with session.get(geo_url) as response:
                    if response.status == 200:
                        geo_data = await response.json()
                        if geo_data:
                            result = geo_data[0]
                            coords = {"lat": result["lat"], "lon": result["lon"]}
                            city_display = result.get("name", city.title())
                        else:
                            return f"❌ City '{city}' not found! Try: Mumbai, Delhi, Bangalore, etc."
                    else:
                        return f"❌ Unable to find city '{city}'. Please try again."
        
        # Get weather data
        async with aiohttp.ClientSession() as session:
            weather_url = (
                f"https://api.openweathermap.org/data/2.5/weather?"
                f"lat={coords['lat']}&lon={coords['lon']}&"
                f"appid={WEATHER_API_KEY}&units=metric&lang=en"
            )
            
            async with session.get(weather_url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Extract weather data
                    weather_desc = data["weather"][0]["description"].title()
                    weather_icon = data["weather"][0]["main"]
                    temp = data["main"]["temp"]
                    feels_like = data["main"]["feels_like"]
                    humidity = data["main"]["humidity"]
                    wind_speed = data["wind"]["speed"]
                    pressure = data["main"]["pressure"]
                    visibility = data.get("visibility", 10000) / 1000  # Convert to km
                    
                    # Get sunrise and sunset times
                    sunrise = datetime.fromtimestamp(data["sys"]["sunrise"]).strftime("%I:%M %p")
                    sunset = datetime.fromtimestamp(data["sys"]["sunset"]).strftime("%I:%M %p")
                    
                    # Weather icons mapping
                    weather_icons = {
                        "Clear": "☀️", "Clouds": "☁️", "Rain": "🌧️", "Drizzle": "🌦️",
                        "Thunderstorm": "⛈️", "Snow": "❄️", "Mist": "🌫️", "Fog": "🌫️",
                        "Haze": "🌫️", "Dust": "💨", "Sand": "💨", "Ash": "🌋",
                        "Squall": "💨", "Tornado": "🌪️"
                    }
                    
                    weather_emoji = weather_icons.get(weather_icon, "🌡️")
                    
                    return (
                        f"🌤️ **Weather Report for {city_display}**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{weather_emoji} **Condition:** {weather_desc}\n"
                        f"🌡️ **Temperature:** {temp}°C\n"
                        f"😮‍💨 **Feels Like:** {feels_like}°C\n"
                        f"💧 **Humidity:** {humidity}%\n"
                        f"💨 **Wind Speed:** {wind_speed} m/s\n"
                        f"🌡️ **Pressure:** {pressure} hPa\n"
                        f"👁️ **Visibility:** {visibility} km\n\n"
                        f"🌅 **Sunrise:** {sunrise}\n"
                        f"🌇 **Sunset:** {sunset}\n\n"
                        f"⏰ **Updated:** Just now\n"
                        f"📍 **Source by:** Alita 😋"
                    )
                else:
                    return "❌ Weather service temporarily unavailable. Please try again later."
    except Exception as e:
        print(f"Weather API Error: {e}")
        # Fallback to mock weather if API fails
        return await get_mock_weather(city)

async def get_mock_weather(city: str) -> str:
    """Fallback mock weather when API fails"""
    temp = random.randint(20, 35)
    conditions = ["☀️ Sunny", "⛅ Partly Cloudy", "☁️ Cloudy", "🌦️ Light Rain", "🌧️ Rainy"]
    condition = random.choice(conditions)
    humidity = random.randint(40, 80)
    wind = random.randint(5, 20)
    
    return (
        f"🌤️ **Weather Report for {city.title()}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{condition.split()[0]} **Condition:** {condition}\n"
        f"🌡️ **Temperature:** {temp}°C\n"
        f"💧 **Humidity:** {humidity}%\n"
        f"💨 **Wind Speed:** {wind} km/h\n\n"
        f"⚠️ **Note:** Using mock data (API may be down)"
    )

# --- IMAGE GENERATION (Pollinations AI - 100% FREE) ---
async def generate_image(prompt: str) -> Optional[bytes]:
    """Generate image using Pollinations AI (100% Free)"""
    try:
        # Clean and encode prompt
        clean_prompt = prompt.replace(" ", "%20")
        url = (
            f"https://image.pollinations.ai/prompt/{clean_prompt}"
            f"?width=512&height=512&nologo=true"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    image_bytes = await response.read()

                    if not image_bytes or len(image_bytes) < 1000:
                        return None

                    return image_bytes
                else:
                    print(f"Image API failed with status: {response.status}")
                    return None

    except asyncio.TimeoutError:
        print("Image generation timeout")
        return None
    except Exception as e:
        print(f"Image generation error: {e}")
        return None

# --- QR CODE GENERATOR ---
def generate_qr_code(data: str) -> bytes:
    """Generate QR code"""
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes.getvalue()

# --- PASSWORD GENERATOR ---
def generate_password(length: int = 12, include_symbols: bool = True) -> str:
    """Generate secure password"""
    chars = string.ascii_letters + string.digits
    if include_symbols:
        chars += "!@#$%^&*"
    
    password = ''.join(random.choice(chars) for _ in range(length))
    return password

# --- URL SHORTENER (TinyURL API) ---
async def shorten_url(url: str) -> str:
    """Shorten URL using TinyURL"""
    try:
        api_url = f"https://tinyurl.com/api-create.php?url={url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    return url
    except:
        return url

# --- TRANSLATION (MyMemory API - Free) ---
async def translate_text(text: str, target_lang: str = "en") -> str:
    """Translate text using MyMemory API"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.mymemory.translated.net/get?q={text}&langpair=en|{target_lang}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("responseData", {}).get("translatedText", text)
                else:
                    return text
    except:
        return text

# --- LYRICS API (Lyrics.ovh) ---
async def get_lyrics(song_name: str) -> str:
    """Get song lyrics from Lyrics.ovh API"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.lyrics.ovh/v1/{song_name}"
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    lyrics = data.get('lyrics', 'Lyrics not found.')
                    
                    # Truncate if too long
                    if len(lyrics) > 3000:
                        lyrics = lyrics[:3000] + "\n\n... (lyrics truncated)"
                    
                    return lyrics
                else:
                    return "❌ Could not fetch lyrics. Please try another song."
    except Exception as e:
        return f"❌ Error fetching lyrics: {str(e)}"

# --- AUTO-MODERATION FUNCTIONS ---
def contains_group_link(text: str) -> bool:
    """Check if message contains Telegram group links"""
    text = text.lower()
    for pattern in GROUP_LINK_PATTERNS:
        if re.search(pattern, text):
            return True
    return False

def contains_bad_words(text: str) -> bool:
    """Check if message contains bad words"""
    text_lower = text.lower()
    for word in BAD_WORDS:
        if word in text_lower:
            return True
    return False

def contains_adult_content(text: str) -> bool:
    """Check if message contains adult content"""
    text_lower = text.lower()
    for word in ADULT_KEYWORDS:
        if word in text_lower:
            return True
    return False

def contains_fake_links(text: str) -> bool:
    """Check if message contains fake/shortened links"""
    text = text.lower()
    for pattern in FAKE_LINK_PATTERNS:
        if re.search(pattern, text):
            return True
    return False

async def give_warning(chat_id: int, user_id: int, username: str, reason: str) -> tuple[bool, str]:
    """Give warning to user and return if action should be taken"""
    warnings = user_warnings[chat_id][user_id]
    
    if 'count' not in warnings:
        warnings['count'] = 0
        warnings['last_warning'] = datetime.now()
        warnings['reasons'] = []
    
    warnings['count'] += 1
    warnings['reasons'].append(reason)
    warnings['last_warning'] = datetime.now()
    
    warning_count = warnings['count']
    
    actions_map = {
        "spam": "spam messages",
        "link": "share group links",
        "bad_words": "use bad language",
        "adult_content": "share adult content",
        "fake_links": "share suspicious links",
        "manual_warning": "violate rules"
    }
    action = actions_map.get(reason, "violate rules")
    
    warning_msg = random.choice(WARNING_MESSAGES).format(
        count=warning_count,
        name=username or "User",
        action=action
    )
    
    # Check if warning limit reached
    warn_limit = group_settings[chat_id].get("warn_limit", 3)
    
    if warning_count >= warn_limit:
        # For adult content, ban immediately
        if reason == "adult_content":
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                del user_warnings[chat_id][user_id]
                warning_msg += f"\n\n🚫 **BANNED PERMANENTLY!**\nAdult content is strictly prohibited!"
                return True, warning_msg
            except Exception as e:
                warning_msg += f"\n\n⚠️ Failed to ban user: {str(e)}"
                return False, warning_msg
        
        # For other violations, mute
        mute_duration = MUTE_DURATIONS[min(3, warning_count - 1)]
        try:
            mute_until = datetime.now() + mute_duration
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                ),
                until_date=mute_until
            )
            
            del user_warnings[chat_id][user_id]
            
            duration_str = ""
            if mute_duration.days > 0:
                duration_str = f"{mute_duration.days} days"
            else:
                hours = mute_duration.seconds // 3600
                minutes = (mute_duration.seconds % 3600) // 60
                if hours > 0:
                    duration_str = f"{hours} hour{'s' if hours > 1 else ''}"
                else:
                    duration_str = f"{minutes} minute{'s' if minutes > 1 else ''}"
            
            warning_msg += f"\n\n🚫 **MUTED for {duration_str}!**\nToo many warnings!"
            return True, warning_msg
            
        except Exception as e:
            warning_msg += f"\n\n⚠️ Failed to mute user: {str(e)}"
            return False, warning_msg
    
    return False, warning_msg

async def delete_and_warn(message: Message, reason: str):
    """Delete message and warn user"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    try:
        await message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
    
    action_taken, warning_msg = await give_warning(chat_id, user_id, username, reason)
    await message.answer(warning_msg, parse_mode="Markdown")
    
    # Special responses for different violations
    if reason == "bad_words":
        sassy_responses = [
            f"{get_emotion('angry')} Oye! Language! 😠 Main ladki hu, aise baat mat karo!",
            f"{get_emotion('sassy')} Areey! Kitne badtameez ho tum! Main bhi jawab de sakti hu!",
            f"{get_emotion('protective')} Apni language thik rakho warna main bhi bolungi!",
            f"{get_emotion('crying')} Itna gussa kyun aata hai? Achi baat karo na!",
            f"{get_emotion('sassy')} Tumhe pata hai main kya bol sakti hu? Par main sweet hu na!"
        ]
        await message.answer(random.choice(sassy_responses))
    
    elif reason == "adult_content":
        angry_responses = [
            f"{get_emotion('angry')} 🤬 Yeh kya beizzati hai? Group mein aise content allowed nahi hai!",
            f"{get_emotion('protective')} 🛡️ Adult content share karna banned hai! Sharam karo!",
            f"{get_emotion('crying')} 😭 Itna ganda content? Main ladki hu, respect karo!"
        ]
        await message.answer(random.choice(angry_responses))

# --- SPAM DETECTION ---
async def check_spam(message: Message) -> bool:
    """Check if user is spamming"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if user_id not in last_messages[chat_id]:
        last_messages[chat_id][user_id] = []
    
    now = datetime.now()
    last_messages[chat_id][user_id].append(now)
    
    last_messages[chat_id][user_id] = [
        ts for ts in last_messages[chat_id][user_id]
        if (now - ts).seconds <= SPAM_TIME_WINDOW
    ]
    
    if len(last_messages[chat_id][user_id]) > SPAM_LIMIT:
        await delete_and_warn(message, "spam")
        return True
    
    return False

# --- FIXED ADMIN CHECK FUNCTION ---
async def is_admin(chat_id: int, user_id: int) -> bool:
    """Check if user is admin in group"""
    try:
        # Check if it's a private chat
        chat = await bot.get_chat(chat_id)
        if chat.type == "private":
            return user_id == chat_id  # In private chats, the user is effectively the admin
        
        # Check if user is the bot owner
        if user_id == ADMIN_ID:
            return True
            
        # Get chat member info
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        print(f"Admin check error for user {user_id} in chat {chat_id}: {e}")
        return False

async def is_creator(chat_id: int, user_id: int) -> bool:
    """Check if user is group creator"""
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status == "creator"
    except:
        return False

# --- CAPTCHA SYSTEM ---
def generate_captcha():
    """Generate simple math CAPTCHA"""
    num1 = random.randint(1, 20)
    num2 = random.randint(1, 20)
    operation = random.choice(['+', '-', '*'])
    
    if operation == '+':
        answer = num1 + num2
    elif operation == '-':
        answer = num1 - num2
        # Ensure positive answer
        if answer < 0:
            num1, num2 = num2, num1
            answer = num1 - num2
    else:
        answer = num1 * num2
    
    question = f"What is {num1} {operation} {num2}?"
    return question, str(answer)

# --- RANDOM SELF MESSAGES TASK (ENHANCED WITH STICKERS) ---
async def send_random_self_messages():
    """Send random self messages in groups"""
    for chat_id in list(group_settings.keys()):
        try:
            # Check if group is active (last message within 30 minutes)
            if chat_id in last_greeting_time:
                time_diff = datetime.now() - last_greeting_time[chat_id]
                if time_diff.total_seconds() < 1800:  # 30 minutes
                    continue
            
            # 30% chance to send random message
            if random.random() < 0.3:
                message_data = random.choice(SELF_MESSAGES)
                
                if message_data["type"] == "text":
                    await bot.send_message(chat_id, message_data["content"])
                elif message_data["type"] == "sticker":
                    if message_data["content"] == "random" and saved_stickers:
                        sticker = random.choice(saved_stickers)
                        await bot.send_sticker(chat_id, sticker)
                    else:
                        await bot.send_message(chat_id, "💭")
                
                last_greeting_time[chat_id] = datetime.now()
                
        except Exception as e:
            print(f"Error sending random message to {chat_id}: {e}")

# --- RANDOM STICKER SENDING TO ACTIVE CHATS ---
async def send_random_stickers():
    """Send random stickers to all active chats"""
    if not saved_stickers:
        return
    
    # Send to groups
    for chat_id in list(group_settings.keys()):
        try:
            # 15% chance to send sticker to group
            if random.random() < 0.15:
                sticker = random.choice(saved_stickers)
                await bot.send_sticker(chat_id, sticker)
                await asyncio.sleep(1)  # Prevent flooding
        except Exception as e:
            print(f"Error sending sticker to group {chat_id}: {e}")
    
    # Send to private users who have started the bot
    for user_id in list(started_users):
        try:
            # 10% chance to send sticker to private user
            if random.random() < 0.10:
                sticker = random.choice(saved_stickers)
                await bot.send_sticker(user_id, sticker)
                await asyncio.sleep(1)  # Prevent flooding
        except Exception as e:
            print(f"Error sending sticker to user {user_id}: {e}")

# --- TIME-BASED GREETINGS TASK ---
async def send_time_greetings():
    """Send time-based greetings to all active chats"""
    current_period = get_current_time_period()
    
    if current_period in TIME_GREETINGS:
        greeting = random.choice(TIME_GREETINGS[current_period]["templates"])
        
        # Send to groups
        for chat_id in list(group_settings.keys()):
            try:
                if group_settings[chat_id].get("greetings_enabled", True):
                    await bot.send_message(chat_id, greeting, parse_mode="Markdown")
                    await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Error sending greeting to group {chat_id}: {e}")
        
        # Send to active private users
        for user_id in list(started_users):
            try:
                await bot.send_message(user_id, greeting, parse_mode="Markdown")
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Error sending greeting to user {user_id}: {e}")

# --- MEME GENERATOR ---
def generate_meme():
    """Generate random meme text"""
    template = random.choice(MEME_TEMPLATES)
    return f"{template['emoji']} **{template['text']}**\n\n*When you know it's true!* 😂"

# --- DAILY FACT ---
def get_daily_fact():
    """Get random daily fact"""
    return random.choice(DAILY_FACTS)

# --- STICKER SAVING COMMANDS ---
@dp.message(Command("savesticker"))
async def cmd_savesticker(message: Message):
    """Save sticker to database (Owner only)"""
    if message.from_user.id != ADMIN_ID:
        await message.reply(f"{get_emotion('angry')} Only owner can use this command! 🚫")
        return
    
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply(
            f"{get_emotion('thinking')} Please reply to a sticker message with this command!",
            parse_mode="Markdown"
        )
        return
    
    sticker = message.reply_to_message.sticker
    file_id = sticker.file_id
    
    # Check if already saved
    if file_id in saved_stickers:
        await message.reply(
            f"{get_emotion('thinking')} This sticker is already saved in the database!",
            parse_mode="Markdown"
        )
        return
    
    # Save sticker
    if save_sticker(file_id, message.from_user.id):
        await message.reply(
            f"{get_emotion('love')} **Sticker Saved Successfully!** ✅\n\n"
            f"Total stickers saved: **{len(saved_stickers)}**\n"
            f"File ID: `{file_id[:30]}...`",
            parse_mode="Markdown"
        )
    else:
        await message.reply(
            f"{get_emotion('crying')} Failed to save sticker! 😢",
            parse_mode="Markdown"
        )

@dp.message(Command("stickerstatus"))
async def cmd_stickerstatus(message: Message):
    """Show sticker database status"""
    total = len(saved_stickers)
    
    if total == 0:
        await message.reply(
            f"{get_emotion('crying')} **No stickers saved yet!** 😢\n\n"
            f"Owner can save stickers using /savesticker command",
            parse_mode="Markdown"
        )
        return
    
    # Get recent stickers count
    cursor.execute("SELECT COUNT(*) FROM stickers WHERE date(added_at) = date('now')")
    today_count = cursor.fetchone()[0]
    
    status_text = (
        f"{get_emotion('happy')} **Sticker Database Status** 📊\n\n"
        f"🎯 **Total Stickers:** {total}\n"
        f"📅 **Saved Today:** {today_count}\n"
        f"👑 **Owner:** @a6h1ii\n\n"
    )
    
    if total > 0:
        # Show some recent stickers info
        cursor.execute("SELECT file_id, added_at FROM stickers ORDER BY added_at DESC LIMIT 3")
        recent = cursor.fetchall()
        
        status_text += "**Recent Stickers:**\n"
        for i, (file_id, added_at) in enumerate(recent, 1):
            time_str = datetime.strptime(added_at, "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p")
            status_text += f"{i}. `{file_id[:20]}...` ({time_str})\n"
    
    await message.reply(status_text, parse_mode="Markdown")

# --- COMMANDS ---
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id

    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌟 HOME", url="https://t.me/abhi0w0")
        ],
        [
            InlineKeyboardButton(text="📱 Utilities", callback_data="menu_utilities"),
            InlineKeyboardButton(text="🎭 Fun", callback_data="menu_fun")
        ],
        [
            InlineKeyboardButton(text="🛡️ Safety", callback_data="menu_safety"),
            InlineKeyboardButton(text="⚙️ Settings", callback_data="menu_settings")
        ],
        [
            InlineKeyboardButton(text="💬 Talk to Alita", callback_data="talk_alita")
        ]
    ])

    welcome_text = (
        f"{get_emotion('love')} <b>Hii! I'm Alita 🎀</b>\n\n"
        "✨ <b>Welcome to my magical world!</b> ✨\n\n"
        "💖 <i>Main hu Alita... Ek sweet, aur protective girl!</i> 😊\n\n"
        "🌟 <b>My Superpowers:</b>\n"
        "• Advanced AI Conversations 🧠\n"
        "• Image Generation 🎨\n"
        "• Real Weather Updates 🌤️\n"
        "• QR Code Generator 📱\n"
        "• Password Generator 🔐\n"
        "• URL Shortener 🔗\n"
        "• Translation 🌍\n"
        "• Auto-moderation 👮\n"
        "• Daily Facts & Motivation 📚\n\n"
        "• <b>MY HOME:</b> @abhi0w0\n\n"
        "Type /help for all commands 💕\n"
        "Or just talk to me like a friend 💬"
    )

    image_url = "https://i.postimg.cc/yYWbPVQ4/1769349715111-result-image.png"
    

    await message.answer_photo(
        photo=image_url,
        caption=welcome_text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    started_users.add(message.from_user.id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Utilities", callback_data="help_utilities"),
            InlineKeyboardButton(text="🎭 Fun", callback_data="help_fun")
        ],
        [
            InlineKeyboardButton(text="🛡️ Admin", callback_data="help_admin"),
            InlineKeyboardButton(text="🌤️ Weather", callback_data="help_weather")
        ],
        [
            InlineKeyboardButton(text="📝 Notes", callback_data="help_notes"),
            InlineKeyboardButton(text="⏰ Reminders", callback_data="help_reminders")
        ],
        [
            InlineKeyboardButton(text="🎨 Image Gen", callback_data="help_image"),
            InlineKeyboardButton(text="🔧 Tools", callback_data="help_tools")
        ],
        [
            InlineKeyboardButton(text="🎵 Music", callback_data="help_music"),
            InlineKeyboardButton(text="🎭 Stickers", callback_data="help_stickers")
        ],
        [
            InlineKeyboardButton(text="🌟 Join Channel", url="https://t.me/abhi0w0")
        ]
    ])
    
    help_text = (
        f"{get_emotion('happy')} **Hello! I'm Alita 🎀** 👧\n\n"
        
        "📜 **MAIN COMMANDS:**\n"
        "• /start - Welcome message 💖\n"
        "• /help - All commands 📚\n"
        "• /rules - Group rules ⚖️\n"
        "• /joke - Funny jokes 😂\n"
        "• /meme - Generate meme 😆\n"
        "• /fact - Daily facts 🧠\n"
        "• /horoscope [sign] - Horoscope ♈\n"
        "• /roast - Playful roast 🔥\n"
        "• /clear - Clear memory 🧹\n\n"
        
        "🕒 **TIME & WEATHER:**\n"
        "• /time - Indian time 🕐\n"
        "• /date - Today's date 📅\n"
        "• /weather [city] - **REAL Weather info** 🌤️\n\n"
        
        "📝 **PERSONAL ORGANIZER:**\n"
        "• /note [text] - Add note 📝\n"
        "• /notes - View notes 📋\n"
        "• /remind [time] [text] - Set reminder ⏰\n"
        "• /reminders - View reminders 📅\n"
        "• /afk [reason] - Set AFK status 😴\n\n"
        
        "🎨 **IMAGE & CREATIVE:**\n"
        "• /imagine [prompt] - AI Image Generation 🎨\n"
        "• /qr [text] - Generate QR Code 📱\n"
        "• /stickerstatus - Check sticker count 🎭\n\n"
        
        "🎵 **MUSIC & LYRICS:**\n"
        "• /lyrics [song] - Get song lyrics 🎶\n"
        "• /song [name] - Search for songs 🎧\n\n"
        
        "🔧 **UTILITIES:**\n"
        "• /password [length] - Generate password 🔐\n"
        "• /short [url] - Shorten URL 🔗\n"
        "• /translate [lang] [text] - Translate 🌍\n"
        "• /calc [expression] - Calculator 🧮\n"
        "• /id - Get your ID 🆔\n"
        "• /info [user] - Get user info 👤\n\n"
        
        "🛡️ **ADMIN/MODERATION:**\n"
        "• /warn [reason] - Warn user ⚠️\n"
        "• /kick - Remove user 🚪\n"
        "• /ban - Ban user 🚫\n"
        "• /mute - Mute user 🔇\n"
        "• /unmute - Unmute user 🔊\n"
        "• /unban - Remove ban ✅\n"
        "• /purge [number] - Delete messages 🗑️\n"
        "• /pin - Pin message 📌\n"
        "• /unpin - Unpin message 📍\n"
        "• /slowmode [seconds] - Enable slow mode ⏱️\n"
        "• /lock - Lock chat 🔒\n"
        "• /unlock - Unlock chat 🔓\n"
        "• /setwelcome [text] - Custom welcome message 👋\n"
        "• /setgoodbye [text] - Custom goodbye message 👋\n"
        "• /adminlist - List all admins 👑\n"
        "• /tagall - Mention all members @\n\n"
        
        "👑 **OWNER COMMANDS:**\n"
        "• /savesticker - Save sticker to database\n"
        "• /stickerstatus - Check sticker database\n"
        "• /sendall - Broadcast to all users 📢\n\n"
        
        "🔧 **SAFETY FEATURES:**\n"
        "• Auto-spam detection 🔍\n"
        "• Group link blocker 🚫\n"
        "• Bad word filter ⚔️\n"
        "• Adult content detection 🔞\n"
        "• Auto-warning system ⚠️\n"
        "• Auto-mute after 3 warns 🔇\n"
        "• Auto-ban for adult content 🚫\n"
        "• CAPTCHA for new members 🧩\n\n"
        
        "---\n"
        "**MY HOME:** @abhi0w0 💫\n"
        "---"
    )
    await message.reply(help_text, parse_mode="Markdown", reply_markup=keyboard)

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def save_group(message: Message):
    chat_id = message.chat.id
    cursor.execute(
        "INSERT OR IGNORE INTO groups (chat_id) VALUES (?)",
        (chat_id,)
    )
    conn.commit()

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules_text = (
        f"{get_emotion('protective')} **📜 GROUP RULES & SAFETY 🛡️**\n\n"
        
        "✅ **DOs:**\n"
        "1. Be respectful to everyone 🤝\n"
        "2. Keep chat friendly and positive 🌟\n"
        "3. Help each other grow 📚\n"
        "4. Follow admin instructions 👮\n"
        "5. Have fun and enjoy! 🎉\n\n"
        
        "🚫 **DON'Ts:**\n"
        "1. No spam or flooding ⚠️\n"
        "2. No group links sharing 🔗\n"
        "3. No bad language 🚫\n"
        "4. No personal fights ⚔️\n"
        "5. No adult/NSFW content 🚷\n"
        "6. No self-promotion without permission 📢\n"
        "7. No fake/suspicious links 🚫\n\n"
        
        f"{get_emotion('love')} *I'm here to keep everyone safe!* 💖"
    )
    await message.reply(rules_text, parse_mode="Markdown")

@dp.message(Command("joke"))
async def cmd_joke(message: Message):
    await message.reply(f"{get_emotion('funny')} {random.choice(JOKES)}")

@dp.message(Command("meme"))
async def cmd_meme(message: Message):
    meme_text = generate_meme()
    await message.reply(f"{get_emotion('funny')} **Random Meme:**\n\n{meme_text}")

@dp.message(Command("fact"))
async def cmd_fact(message: Message):
    await message.reply(f"{get_emotion('thinking')} {get_daily_fact()}")

@dp.message(Command("horoscope"))
async def cmd_horoscope(message: Message, command: CommandObject):
    if not command.args:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(f"{emoji} {sign.title()}", callback_data=f"horoscope_{sign}")]
            for sign, emoji in list(HOROSCOPE_SIGNS.items())[:6]
        ] + [
            [InlineKeyboardButton(f"{emoji} {sign.title()}", callback_data=f"horoscope_{sign}")]
            for sign, emoji in list(HOROSCOPE_SIGNS.items())[6:]
        ])
        await message.reply(
            f"{get_emotion('surprise')} **Choose your zodiac sign:** ♈\n\n"
            f"Click below or use `/horoscope [sign]`",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return
    
    sign = command.args.lower()
    horoscopes = {
        "aries": "Today brings energy and passion! Take charge of new projects. 💪",
        "taurus": "Financial opportunities await. Stay grounded and practical. 💰",
        "gemini": "Communication is key today. Express yourself clearly. 💬",
        "cancer": "Focus on home and family. Emotional connections deepen. 🏠",
        "leo": "Your charisma shines! Leadership opportunities arise. 👑",
        "virgo": "Attention to detail pays off. Organization brings success. 📋",
        "libra": "Balance is essential. Harmony in relationships matters. ⚖️",
        "scorpio": "Intuition guides you. Trust your instincts. 🔮",
        "sagittarius": "Adventure calls! Explore new horizons. 🌍",
        "capricorn": "Hard work yields results. Stay disciplined. 🏔️",
        "aquarius": "Innovation flows. Think outside the box. 💡",
        "pisces": "Creativity blooms. Express your artistic side. 🎨"
    }
    
    emoji = HOROSCOPE_SIGNS.get(sign, "🌟")
    reading = horoscopes.get(sign, "Stars align for new beginnings! ✨")
    await message.reply(f"{get_emotion('love')} {emoji} **{sign.title()} Horoscope**\n\n{reading}")

@dp.message(Command("roast"))
async def cmd_roast(message: Message):
    if message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
        roast = random.choice(ROAST_RESPONSES)
        await message.reply(
            f"{get_emotion('sassy')} **Roasting {target}!** 🔥\n\n{roast}"
        )
    else:
        await message.reply(
            f"{get_emotion('sassy')} **Self-roast mode!** 😂\n\n"
            f"Reply to someone's message to roast them!\n"
            f"Or I'll roast you: {random.choice(ROAST_RESPONSES)}"
        )

# --- NEW LYRICS COMMAND ---
@dp.message(Command("lyrics"))
async def cmd_lyrics(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Lyrics Finder Usage:**\n\n"
            f"`/lyrics [song name]`\n\n"
            f"Examples:\n"
            f"`/lyrics Shape of You`\n"
            f"`/lyrics Despacito`\n"
            f"`/lyrics Tujhe kitna chahne lage`",
            parse_mode="Markdown"
        )
        return
    
    song_name = command.args
    await message.reply(f"{get_emotion('happy')} Searching for lyrics... 🎵")
    
    try:
        lyrics = await get_lyrics(song_name)
        await message.reply(
            f"{get_emotion('love')} **Lyrics for: {song_name}** 🎶\n\n"
            f"{lyrics}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.reply(
            f"{get_emotion('crying')} Couldn't find lyrics for '{song_name}' 😢\n"
            f"Try another song name!"
        )

# --- NEW ADMINLIST COMMAND ---
@dp.message(Command("adminlist"))
async def cmd_adminlist(message: Message):
    """List all admins in the group"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.reply(
            f"{get_emotion('thinking')} This command only works in groups!",
            parse_mode="Markdown"
        )
        return
    
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        
        if not admins:
            await message.reply(
                f"{get_emotion('thinking')} No admins found in this group!",
                parse_mode="Markdown"
            )
            return
        
        admin_list = []
        for admin in admins:
            user = admin.user
            status = "👑 Creator" if admin.status == "creator" else "🛡️ Admin"
            name = f"{user.first_name} {user.last_name or ''}".strip()
            username = f"(@{user.username})" if user.username else ""
            admin_list.append(f"{status} - {name} {username}")
        
        admin_text = "\n".join(admin_list)
        await message.reply(
            f"{get_emotion('protective')} **Group Administrators** 👑\n\n"
            f"{admin_text}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.reply(
            f"{get_emotion('crying')} Error fetching admin list: {str(e)}",
            parse_mode="Markdown"
        )

# --- NEW TAGALL COMMAND ---
@dp.message(Command("tagall"))
async def cmd_tagall(message: Message):
    """Mention all members in group (Admin only)"""
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(
            f"{get_emotion('angry')} Only admins can use this command! 🚫",
            parse_mode="Markdown"
        )
        return
    
    if message.chat.type not in ["group", "supergroup"]:
        await message.reply(
            f"{get_emotion('thinking')} This command only works in groups!",
            parse_mode="Markdown"
        )
        return
    
    try:
        members_count = await bot.get_chat_member_count(message.chat.id)
        
        if members_count > 100:
            await message.reply(
                f"{get_emotion('thinking')} Group is too large ({members_count} members)!",
                parse_mode="Markdown"
            )
            return
        
        # Get chat members
        members = []
        async for member in bot.get_chat_members(message.chat.id):
            if not member.user.is_bot and member.user.id != bot.id:
                name = member.user.first_name
                if member.user.username:
                    members.append(f"@{member.user.username}")
                else:
                    members.append(name)
        
        if not members:
            await message.reply(
                f"{get_emotion('crying')} No members found to tag!",
                parse_mode="Markdown"
            )
            return
        
        # Split into chunks to avoid message too long error
        chunk_size = 10
        for i in range(0, len(members), chunk_size):
            chunk = members[i:i + chunk_size]
            tag_text = " ".join(chunk)
            await message.reply(
                f"{get_emotion('surprise')} **Tagging Members!** 🎯\n\n{tag_text}",
                parse_mode="Markdown"
            )
            await asyncio.sleep(1)  # Avoid rate limiting
        
    except Exception as e:
        await message.reply(
            f"{get_emotion('crying')} Error tagging members: {str(e)}",
            parse_mode="Markdown"
        )

# --- NEW INFO COMMAND ---
@dp.message(Command("info"))
async def cmd_info(message: Message):
    """Get information about a user"""
    target_user = None
    
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    else:
        target_user = message.from_user
    
    try:
        # Try to get chat member info for groups
        chat_member = None
        if message.chat.type in ["group", "supergroup"]:
            try:
                chat_member = await bot.get_chat_member(message.chat.id, target_user.id)
            except:
                pass
        
        # Format user info
        user_info = (
            f"{get_emotion('thinking')} **User Information** 👤\n\n"
            f"🆔 **ID:** `{target_user.id}`\n"
            f"👤 **Name:** {target_user.first_name} {target_user.last_name or ''}\n"
            f"📱 **Username:** @{target_user.username or 'No username'}\n"
        )
        
        if chat_member:
            status = "👑 Creator" if chat_member.status == "creator" else \
                     "🛡️ Admin" if chat_member.status == "administrator" else \
                     "👤 Member"
            user_info += f"🏷️ **Status:** {status}\n"
        
        user_info += f"\n💬 **Chat ID:** `{message.chat.id}`"
        
        await message.reply(user_info, parse_mode="Markdown")
    except Exception as e:
        await message.reply(
            f"{get_emotion('crying')} Error getting user info: {str(e)}",
            parse_mode="Markdown"
        )

@dp.message(Command("time"))
async def cmd_time(message: Message):
    indian_time = get_indian_time()
    time_str = indian_time.strftime("%I:%M %p")
    date_str = indian_time.strftime("%A, %d %B %Y")
    
    hour = indian_time.hour
    if 5 <= hour < 12:
        greeting = "Good Morning! 🌅"
    elif 12 <= hour < 17:
        greeting = "Good Afternoon! ☀️"
    elif 17 <= hour < 21:
        greeting = "Good Evening! 🌇"
    else:
        greeting = "Good Night! 🌙"
    
    time_info = (
        f"🕒 **Indian Standard Time (IST)**\n"
        f"• Time: {time_str}\n"
        f"• Date: {date_str}\n"
        f"• {greeting}\n\n"
        f"*Time is precious! Make the most of it!* ⏳"
    )
    await message.reply(time_info, parse_mode="Markdown")

@dp.message(Command("date"))
async def cmd_date(message: Message):
    indian_time = get_indian_time()
    date_str = indian_time.strftime("%A, %d %B %Y")
    
    await message.reply(
        f"{get_emotion('happy')} **📅 Today's Date**\n"
        f"• {date_str}\n"
        f"• Day: {indian_time.strftime('%A')}\n"
        f"• Indian Standard Time 🇮🇳\n\n"
        f"*Have a great day!* ✨",
        parse_mode="Markdown"
    )

@dp.message(Command("weather"))
async def cmd_weather(message: Message, command: CommandObject):
    city = command.args
    if not city:
        # Show list of available cities
        cities_list = ", ".join([c.title() for c in list(INDIAN_CITIES.keys())[:10]])
        await message.reply(
            f"{get_emotion('thinking')} **Weather Command Usage:**\n\n"
            f"`/weather [city name]`\n\n"
            f"**Popular cities:**\n{cities_list}...\n\n"
            f"Or any city worldwide! 🌍",
            parse_mode="Markdown"
        )
        return
    
    # Show typing action
    await bot.send_chat_action(message.chat.id, "typing")
    
    weather_info = await get_real_weather(city)
    await message.reply(weather_info, parse_mode="Markdown")

# --- IMAGE GENERATION COMMAND (STABLE & FIXED) ---
@dp.message(Command("imagine"))
async def cmd_imagine(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Image Generation Usage:**\n\n"
            f"`/imagine [your description]`\n\n"
            f"Examples:\n"
            f"`/imagine a beautiful sunset over mountains`\n"
            f"`/imagine cute cat wearing glasses`\n"
            f"`/imagine futuristic city with flying cars`",
            parse_mode="Markdown"
        )
        return

    prompt = command.args

    # Telegram ko bata do photo aa rahi hai
    await bot.send_chat_action(message.chat.id, "upload_photo")

    status_msg = await message.reply(
        f"{get_emotion('happy')} 🎨 Generating image...\n"
        f"Prompt: {prompt[:50]}{'...' if len(prompt) > 50 else ''}"
    )

    try:
        image_data = await generate_image(prompt)

        # ❗ IMAGE VALIDATION
        if not image_data or len(image_data) < 1000:
            await status_msg.edit_text(
                f"{get_emotion('crying')} Image generate nahi ho paayi 😓\n"
                f"Prompt thoda change karke try karo."
            )
            return

        # ❗ TELEGRAM SEND
        try:
            await status_msg.delete()
            await message.reply_photo(
                BufferedInputFile(image_data, filename="generated_image.png"),
                caption=(
                    f"{get_emotion('love')} **Generated Image:**\n"
                    f"📝 Prompt: {prompt}\n\n"
                    f"🎨 Powered by Alita."
                ),
                parse_mode="Markdown"
            )

        except Exception:
            await status_msg.edit_text(
                f"{get_emotion('crying')} Telegram image send fail ho gayi 🤕\n"
                f"Prompt dubara try karo."
            )

    except Exception as e:
        print("Imagine command error:", e)
        await status_msg.edit_text(
            f"{get_emotion('crying')} Image generation error 😢\n"
            f"Thodi der baad try karo."
        )

# --- QR CODE COMMAND ---
@dp.message(Command("qr"))
async def cmd_qr(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **QR Code Generator Usage:**\n\n"
            f"`/qr [text or URL]`\n\n"
            f"Examples:\n"
            f"`/qr https://t.me/abhi0w0`\n"
            f"`/qr My contact info: @a6h1ii`",
            parse_mode="Markdown"
        )
        return
    
    data = command.args
    try:
        qr_bytes = generate_qr_code(data)
        await message.reply_photo(
            BufferedInputFile(qr_bytes, filename="qr_code.png"),
            caption=f"{get_emotion('happy')} **QR Code Generated!**\n\n📱 Data: {data[:50]}{'...' if len(data) > 50 else ''}"
        )
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Error generating QR code: {str(e)}")

# --- PASSWORD GENERATOR COMMAND ---
@dp.message(Command("password"))
async def cmd_password(message: Message, command: CommandObject):
    try:
        length = int(command.args) if command.args else 12
        if length < 4 or length > 50:
            await message.reply(f"{get_emotion('thinking')} Password length must be between 4 and 50!")
            return
        
        password = generate_password(length)
        await message.reply(
            f"{get_emotion('happy')} **Password Generated!** 🔐\n\n"
            f"`{password}`\n\n"
            f"📊 Length: {length} characters\n"
            f"🔒 Contains: Letters, numbers, symbols\n\n"
            f"*Copy this password and store it safely!*",
            parse_mode="Markdown"
        )
    except ValueError:
        await message.reply(f"{get_emotion('thinking')} Usage: `/password [length]`\nExample: `/password 16`")

# --- URL SHORTENER COMMAND ---
@dp.message(Command("short"))
async def cmd_short(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **URL Shortener Usage:**\n\n"
            f"`/short [long URL]`\n\n"
            f"Example:\n"
            f"`/short https://example.com/very/long/url/that/needs/shortening`",
            parse_mode="Markdown"
        )
        return
    
    url = command.args.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    status_msg = await message.reply(f"{get_emotion('happy')} Shortening URL...")
    
    try:
        short_url = await shorten_url(url)
        await status_msg.edit_text(
            f"{get_emotion('love')} **URL Shortened!** 🔗\n\n"
            f"🔗 **Short:** {short_url}\n"
            f"📝 **Original:** {url[:50]}{'...' if len(url) > 50 else ''}"
        )
    except Exception as e:
        await status_msg.edit_text(f"{get_emotion('crying')} Error: {str(e)}")

# --- TRANSLATION COMMAND ---
@dp.message(Command("translate"))
async def cmd_translate(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Translation Usage:**\n\n"
            f"`/translate [language code] [text]`\n\n"
            f"Examples:\n"
            f"`/translate hi Hello, how are you?`\n"
            f"`/translate es I love this bot`\n"
            f"`/translate fr Good morning`\n\n"
            f"Language codes: hi (Hindi), es (Spanish), fr (French), de (German), ja (Japanese), etc.",
            parse_mode="Markdown"
        )
        return
    
    args = command.args.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Please provide both language code and text!")
        return
    
    target_lang = args[0]
    text = args[1]
    
    status_msg = await message.reply(f"{get_emotion('thinking')} Translating...")
    
    try:
        translated = await translate_text(text, target_lang)
        await status_msg.edit_text(
            f"{get_emotion('happy')} **Translation** 🌍\n\n"
            f"📝 **Original:** {text}\n"
            f"🔀 **Translated ({target_lang.upper()}):** {translated}"
        )
    except Exception as e:
        await status_msg.edit_text(f"{get_emotion('crying')} Translation failed: {str(e)}")

# --- CALCULATOR COMMAND ---
@dp.message(Command("calc"))
async def cmd_calc(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Calculator Usage:**\n\n"
            f"`/calc [expression]`\n\n"
            f"Examples:\n"
            f"`/calc 2 + 2`\n"
            f"`/calc (5 * 10) / 2`\n"
            f"`/calc 2 ** 8` (power)\n"
            f"`/calc sqrt(16)` (square root)",
            parse_mode="Markdown"
        )
        return
    
    expression = command.args
    
    # Security: Only allow safe characters
    allowed_chars = set('0123456789+-*/.() **sqrt ')
    if not all(c in allowed_chars for c in expression):
        await message.reply(f"{get_emotion('angry')} Invalid characters in expression!")
        return
    
    try:
        # Replace sqrt with math.sqrt
        safe_expr = expression.replace('sqrt', '(__import__("math").sqrt)')
        result = eval(safe_expr, {"__builtins__": {}}, {"math": __import__('math')})
        
        await message.reply(
            f"{get_emotion('happy')} **Calculator** 🧮\n\n"
            f"📝 Expression: `{expression}`\n"
            f"✅ Result: `{result}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Error calculating: Invalid expression!")

# --- ID COMMAND ---
@dp.message(Command("id"))
async def cmd_id(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    text = (
        f"{get_emotion('happy')} **Your Information** 🆔\n\n"
        f"👤 **User ID:** `{user_id}`\n"
        f"💬 **Chat ID:** `{chat_id}`\n"
        f"📛 **Name:** {message.from_user.full_name}\n"
    )
    
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        text += (
            f"\n🎯 **Replied User:**\n"
            f"👤 **User ID:** `{target.id}`\n"
            f"📛 **Name:** {target.full_name}\n"
            f"📱 **Username:** @{target.username if target.username else 'N/A'}"
        )
    
    await message.reply(text, parse_mode="Markdown")

# --- AFK SYSTEM ---
@dp.message(Command("afk"))
async def cmd_afk(message: Message, command: CommandObject):
    reason = command.args or "AFK"
    afk_users[message.from_user.id] = {
        "reason": reason,
        "time": datetime.now()
    }
    
    await message.reply(
        f"{get_emotion('sleepy')} **AFK Mode Activated** 😴\n\n"
        f"💤 Reason: {reason}\n"
        f"⏰ Since: {datetime.now().strftime('%I:%M %p')}\n\n"
        f"I'll notify others when they mention you!"
    )

# --- NOTES & REMINDERS ---
@dp.message(Command("note"))
async def cmd_note(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Usage:** `/note [your note text]`\n\n"
            f"Example: `/note Buy groceries tomorrow`"
        )
        return
    
    note_text = command.args
    note_data = {
        "text": note_text,
        "created_at": datetime.now(),
        "note_id": len(user_notes[message.from_user.id]) + 1
    }
    
    user_notes[message.from_user.id].append(note_data)
    
    await message.reply(
        f"{get_emotion('happy')} **Note Saved!** 📝\n\n"
        f"• Note: {note_text}\n"
        f"• Total notes: {len(user_notes[message.from_user.id])}\n\n"
        f"View all notes with /notes"
    )

@dp.message(Command("notes"))
async def cmd_notes(message: Message):
    user_id = message.from_user.id
    notes = user_notes[user_id]
    
    if not notes:
        await message.reply(
            f"{get_emotion('crying')} **No notes found!** 😢\n\n"
            f"Add your first note with /note [text]"
        )
        return
    
    notes_text = f"{get_emotion('thinking')} **Your Notes:** 📋\n\n"
    for i, note in enumerate(notes[-10:], 1):
        time_str = note['created_at'].strftime('%d/%m %I:%M %p')
        notes_text += f"{i}. {note['text']} ({time_str})\n"
    
    notes_text += f"\n*Total: {len(notes)} notes*"
    await message.reply(notes_text, parse_mode="Markdown")

@dp.message(Command("remind"))
async def cmd_remind(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Usage:** `/remind [time] [reminder text]`\n\n"
            f"Examples:\n"
            f"`/remind 1h Call mom`\n"
            f"`/remind 30m Take medicine`\n"
            f"`/remind 2h Study for exam`"
        )
        return
    
    try:
        args = command.args.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Please provide both time and reminder text!")
            return
        
        time_str = args[0]
        reminder_text = args[1]
        
        # Parse time
        if time_str.endswith('h'):
            hours = int(time_str[:-1])
            reminder_time = datetime.now() + timedelta(hours=hours)
        elif time_str.endswith('m'):
            minutes = int(time_str[:-1])
            reminder_time = datetime.now() + timedelta(minutes=minutes)
        else:
            await message.reply("Use format: 1h or 30m")
            return
        
        reminder_data = {
            "text": reminder_text,
            "time": reminder_time,
            "created_at": datetime.now(),
            "reminder_id": len(user_reminders[message.from_user.id]) + 1
        }
        
        user_reminders[message.from_user.id].append(reminder_data)
        
        await message.reply(
            f"{get_emotion('happy')} **Reminder Set!** ⏰\n\n"
            f"• Reminder: {reminder_text}\n"
            f"• Time: {reminder_time.strftime('%I:%M %p')}\n"
            f"• In: {time_str}\n\n"
            f"I'll remind you! 💫"
        )
        
        # Schedule reminder
        greeting_scheduler.add_job(
            send_reminder,
            'date',
            run_date=reminder_time,
            args=[message.from_user.id, reminder_text],
            id=f"reminder_{message.from_user.id}_{reminder_data['reminder_id']}"
        )
        
    except Exception as e:
        await message.reply(f"Error setting reminder: {str(e)}")

async def send_reminder(user_id: int, reminder_text: str):
    """Send reminder to user"""
    try:
        await bot.send_message(
            user_id,
            f"{get_emotion('surprise')} **Reminder!** ⏰\n\n{reminder_text}\n\n*Don't forget!* 💫",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Failed to send reminder to {user_id}: {e}")

@dp.message(Command("reminders"))
async def cmd_reminders(message: Message):
    user_id = message.from_user.id
    reminders = user_reminders[user_id]
    
    if not reminders:
        await message.reply(
            f"{get_emotion('crying')} **No reminders set!** 😢\n\n"
            f"Set your first reminder with /remind [time] [text]"
        )
        return
    
    reminders_text = f"{get_emotion('thinking')} **Your Reminders:** 📅\n\n"
    for i, reminder in enumerate(reminders[-5:], 1):
        time_left = reminder['time'] - datetime.now()
        if time_left.total_seconds() > 0:
            hours = int(time_left.total_seconds() // 3600)
            minutes = int((time_left.total_seconds() % 3600) // 60)
            reminders_text += f"{i}. {reminder['text']} (in {hours}h {minutes}m)\n"
    
    await message.reply(reminders_text, parse_mode="Markdown")

# --- FIXED ADMIN COMMANDS ---
@dp.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject):
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not message.reply_to_message:
        await message.reply(
            f"{get_emotion('thinking')} Please reply to a user's message to warn them! 👆",
            parse_mode="Markdown"
        )
        return
    
    target_user = message.reply_to_message.from_user
    reason = command.args or "Rule violation"
    
    action_taken, warning_msg = await give_warning(
        message.chat.id,
        target_user.id,
        target_user.first_name,
        "manual_warning"
    )
    
    warning_msg = warning_msg.replace("violate rules", f"{reason}")
    await message.reply(warning_msg, parse_mode="Markdown")

@dp.message(Command("kick"))
async def cmd_kick(message: Message):
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not message.reply_to_message:
        await message.reply(f"{get_emotion('thinking')} Reply to a user to kick them!")
        return
    
    target_user = message.reply_to_message.from_user
    
    try:
        await bot.ban_chat_member(message.chat.id, target_user.id)
        await bot.unban_chat_member(message.chat.id, target_user.id)
        await message.reply(
            f"{get_emotion('angry')} **Kicked!** 😑\n\n"
            f"{target_user.first_name} has been removed from the group!\n"
            f"They can rejoin using the invite link."
        )
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Failed to kick user: {str(e)}")

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not message.reply_to_message:
        await message.reply(f"{get_emotion('thinking')} Reply to a user to ban them!")
        return
    
    target_user = message.reply_to_message.from_user
    
    try:
        await bot.ban_chat_member(message.chat.id, target_user.id)
        await message.reply(
            f"{get_emotion('angry')} **Banned!** 🚫\n\n"
            f"{target_user.first_name} has been permanently banned!\n"
            f"Use /unban to remove the ban."
        )
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Failed to ban user: {str(e)}")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not message.reply_to_message:
        await message.reply(f"{get_emotion('thinking')} Reply to a user's message to unban them!")
        return
    
    target_user = message.reply_to_message.from_user
    
    try:
        await bot.unban_chat_member(message.chat.id, target_user.id)
        await message.reply(
            f"{get_emotion('happy')} **Unbanned!** ✅\n\n"
            f"{target_user.first_name} has been unbanned!\n"
            f"They can now rejoin the group."
        )
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Failed to unban user: {str(e)}")

@dp.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject):
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not message.reply_to_message:
        await message.reply(f"{get_emotion('thinking')} Reply to a user to mute them!")
        return
    
    target_user = message.reply_to_message.from_user
    
    # Parse duration
    duration = command.args
    if duration:
        if duration.endswith('h'):
            hours = int(duration[:-1])
            mute_until = datetime.now() + timedelta(hours=hours)
            duration_str = f"{hours} hour(s)"
        elif duration.endswith('m'):
            minutes = int(duration[:-1])
            mute_until = datetime.now() + timedelta(minutes=minutes)
            duration_str = f"{minutes} minute(s)"
        else:
            mute_until = datetime.now() + timedelta(hours=1)
            duration_str = "1 hour"
    else:
        mute_until = datetime.now() + timedelta(hours=1)
        duration_str = "1 hour"
    
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target_user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=mute_until
        )
        await message.reply(
            f"{get_emotion('angry')} **Muted!** 🔇\n\n"
            f"{target_user.first_name} has been muted for {duration_str}!\n"
            f"They cannot send messages until the mute expires."
        )
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Failed to mute user: {str(e)}")

@dp.message(Command("unmute"))
async def cmd_unmute(message: Message):
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not message.reply_to_message:
        await message.reply(f"{get_emotion('thinking')} Reply to a user to unmute them!")
        return
    
    target_user = message.reply_to_message.from_user
    
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target_user.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False
            )
        )
        await message.reply(
            f"{get_emotion('happy')} **Unmuted!** 🔊\n\n"
            f"{target_user.first_name} can now speak again!"
        )
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Failed to unmute user: {str(e)}")

@dp.message(Command("purge"))
async def cmd_purge(message: Message, command: CommandObject):
    """Delete multiple messages"""
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not message.reply_to_message:
        await message.reply(f"{get_emotion('thinking')} Reply to the oldest message you want to delete!")
        return
    
    try:
        count = int(command.args) if command.args else 10
        if count > 100:
            count = 100
        
        # Delete messages
        message_ids = []
        async for msg in bot.get_chat_history(message.chat.id, limit=count):
            if msg.message_id >= message.reply_to_message.message_id:
                message_ids.append(msg.message_id)
        
        # Delete in batches
        deleted = 0
        for i in range(0, len(message_ids), 100):
            batch = message_ids[i:i+100]
            await bot.delete_messages(message.chat.id, batch)
            deleted += len(batch)
        
        await message.reply(f"{get_emotion('happy')} **Purged!** 🗑️\n\nDeleted {deleted} messages!")
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Error purging messages: {str(e)}")

@dp.message(Command("pin"))
async def cmd_pin(message: Message):
    """Pin a message"""
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not message.reply_to_message:
        await message.reply(f"{get_emotion('thinking')} Reply to a message to pin it!")
        return
    
    try:
        await bot.pin_chat_message(
            message.chat.id,
            message.reply_to_message.message_id,
            disable_notification=False
        )
        await message.reply(f"{get_emotion('happy')} **Pinned!** 📌")
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Failed to pin: {str(e)}")

@dp.message(Command("unpin"))
async def cmd_unpin(message: Message):
    """Unpin a message"""
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    try:
        await bot.unpin_chat_message(message.chat.id)
        await message.reply(f"{get_emotion('happy')} **Unpinned!** 📍")
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Failed to unpin: {str(e)}")

@dp.message(Command("slowmode"))
async def cmd_slowmode(message: Message, command: CommandObject):
    """Enable slow mode"""
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    try:
        delay = int(command.args) if command.args else 0
        
        if delay < 0 or delay > 86400:
            await message.reply("Delay must be between 0 and 86400 seconds!")
            return
        
        await bot.set_chat_slow_mode_delay(message.chat.id, delay)
        
        if delay == 0:
            await message.reply(f"{get_emotion('happy')} **Slow mode disabled!** 🚀")
        else:
            await message.reply(f"{get_emotion('happy')} **Slow mode enabled!** ⏱️\n\nUsers can send 1 message every {delay} seconds.")
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Error: {str(e)}")

# --- FIXED LOCK/UNLOCK COMMANDS ---
@dp.message(Command("lock"))
async def cmd_lock(message: Message, command: CommandObject):
    """Lock the chat"""
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    try:
        await bot.set_chat_permissions(
            message.chat.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            )
        )
        await message.reply(f"{get_emotion('protective')} **Chat Locked!** 🔒\n\nOnly admins can send messages now.")
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Error: {str(e)}")

@dp.message(Command("unlock"))
async def cmd_unlock(message: Message):
    """Unlock the chat"""
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    try:
        await bot.set_chat_permissions(
            message.chat.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False
            )
        )
        await message.reply(f"{get_emotion('happy')} **Chat Unlocked!** 🔓\n\nEveryone can send messages now.")
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Error: {str(e)}")

# --- FIXED SETWELCOME COMMAND ---
@dp.message(Command("setwelcome"))
async def cmd_setwelcome(message: Message, command: CommandObject):
    """Set custom welcome message"""
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Set Welcome Usage:**\n\n"
            f"`/setwelcome [your welcome message]`\n\n"
            f"Use {{name}} for username placeholder.\n\n"
            f"Example: `/setwelcome Welcome {{name}}! Enjoy your stay!`"
        )
        return
    
    group_settings[message.chat.id]["custom_welcome"] = command.args
    await message.reply(f"{get_emotion('happy')} **Custom welcome message set!** 👋")

# --- FIXED SETGOODBYE COMMAND ---
@dp.message(Command("setgoodbye"))
async def cmd_setgoodbye(message: Message, command: CommandObject):
    """Set custom goodbye message"""
    # Check if user is admin
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this command! 🚫")
        return
    
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Set Goodbye Usage:**\n\n"
            f"`/setgoodbye [your goodbye message]`\n\n"
            f"Use {{name}} for username placeholder.\n\n"
            f"Example: `/setgoodbye Goodbye {{name}}! We'll miss you!`"
        )
        return
    
    group_settings[message.chat.id]["custom_goodbye"] = command.args
    await message.reply(f"{get_emotion('happy')} **Custom goodbye message set!** 👋")

# --- CLEAR COMMAND ---
@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    """Clear chat memory"""
    if message.chat.id in chat_memory:
        chat_memory[message.chat.id].clear()
        await message.reply(f"{get_emotion('happy')} **Memory cleared!** 🧹\n\nChat history has been reset!")
    else:
        await message.reply(f"{get_emotion('thinking')} No chat memory to clear!")

# --- FIXED LOCKS COMMAND ---
@dp.message(Command("locks"))
async def cmd_locks(message: Message):
    """Show current chat lock status"""
    chat_id = message.chat.id
    
    try:
        chat = await bot.get_chat(chat_id)
        permissions = chat.permissions
        
        if permissions:
            status = (
                f"{get_emotion('protective')} **Chat Permissions Status** 🔐\n\n"
                f"📝 **Send Messages:** {'✅' if permissions.can_send_messages else '❌'}\n"
                f"📷 **Send Media:** {'✅' if permissions.can_send_media_messages else '❌'}\n"
                f"📊 **Send Polls:** {'✅' if permissions.can_send_polls else '❌'}\n"
                f"🔗 **Web Previews:** {'✅' if permissions.can_add_web_page_previews else '❌'}\n"
                f"📌 **Pin Messages:** {'✅' if permissions.can_pin_messages else '❌'}\n"
                f"👥 **Invite Users:** {'✅' if permissions.can_invite_users else '❌'}\n"
                f"✏️ **Change Info:** {'✅' if permissions.can_change_info else '❌'}\n\n"
                f"Use `/lock` to restrict or `/unlock` to free!"
            )
        else:
            status = f"{get_emotion('happy')} Chat is currently unlocked! 🔓"
        
        await message.reply(status, parse_mode="Markdown")
    except Exception as e:
        await message.reply(f"{get_emotion('crying')} Error checking permissions: {str(e)}")

# --- ADMIN BROADCAST COMMAND (FIXED) ---
@dp.message(Command("sendall"))
async def cmd_sendall(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ Admin only")
        return

    if not message.reply_to_message:
        await message.reply("Reply to a message and use /sendall")
        return

    target_msg = message.reply_to_message

    cursor.execute("SELECT user_id FROM users")
    all_users = cursor.fetchall()

    cursor.execute("SELECT chat_id FROM groups")
    all_groups = cursor.fetchall()

    sent_count = 0
    failed_count = 0

    status = await message.reply("📤 Broadcasting...")

    # ✅ PRIVATE USERS
    for (user_id,) in all_users:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=target_msg.message_id
            )
            sent_count += 1
            await asyncio.sleep(0.05)
        except:
            failed_count += 1
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()

    # ✅ GROUPS
    for (group_id,) in all_groups:
        try:
            await bot.copy_message(
                chat_id=group_id,
                from_chat_id=message.chat.id,
                message_id=target_msg.message_id
            )
            sent_count += 1
            await asyncio.sleep(0.05)
        except:
            failed_count += 1
            cursor.execute("DELETE FROM groups WHERE chat_id = ?", (group_id,))
            conn.commit()

    await status.edit_text(
        f"✅ Broadcast Complete\n\n"
        f"Sent: {sent_count}\n"
        f"Failed: {failed_count}"
    )

# --- CALLBACK QUERY HANDLERS ---
@dp.callback_query(F.data.startswith("menu_"))
async def menu_callback(callback: types.CallbackQuery):
    menu_type = callback.data.split("_")[1]
    
    if menu_type == "utilities":
        await callback.message.edit_text(
            f"{get_emotion('happy')} **📱 Utilities Menu**\n\n"
            f"Available utilities:\n"
            f"• /time - Current time\n"
            f"• /date - Today's date\n"
            f"• /weather [city] - Weather info\n"
            f"• /note [text] - Add note\n"
            f"• /notes - View notes\n"
            f"• /remind [time] [text] - Set reminder\n"
            f"• /reminders - View reminders\n"
            f"• /qr [text] - Generate QR code\n"
            f"• /password [length] - Generate password\n"
            f"• /short [url] - Shorten URL\n"
            f"• /translate [lang] [text] - Translate\n"
            f"• /calc [expr] - Calculator\n"
            f"• /id - Get your ID\n\n"
            f"More utilities coming soon! ✨"
        )
    elif menu_type == "fun":
        await callback.message.edit_text(
            f"{get_emotion('funny')} **🎭 Fun Menu**\n\n"
            f"Fun commands:\n"
            f"• /joke - Random joke\n"
            f"• /meme - Generate meme\n"
            f"• /fact - Daily fact\n"
            f"• /horoscope [sign] - Horoscope\n"
            f"• /roast - Playful roast\n"
            f"• /imagine [prompt] - AI Image Gen\n"
            f"• /lyrics [song] - Get song lyrics\n\n"
            f"Let the fun begin! 🎉"
        )
    elif menu_type == "safety":
        await callback.message.edit_text(
            f"{get_emotion('protective')} **🛡️ Safety Features**\n\n"
            f"Auto-moderation:\n"
            f"• Spam detection 🔍\n"
            f"• Group link blocking 🚫\n"
            f"• Bad word filtering ⚔️\n"
            f"• Adult content detection 🔞\n"
            f"• Auto-warnings ⚠️\n"
            f"• Auto-mute system 🔇\n"
            f"• Auto-ban for adult content 🚫\n"
            f"• CAPTCHA for new members 🧩\n\n"
            f"I'm here to protect! 💪"
        )
    elif menu_type == "settings":
        await callback.message.edit_text(
            f"{get_emotion('thinking')} **⚙️ Settings**\n\n"
            f"Admin commands:\n"
            f"• /setwelcome [text] - Custom welcome\n"
            f"• /setgoodbye [text] - Custom goodbye\n"
            f"• /slowmode [seconds] - Slow mode\n"
            f"• /lock - Lock chat\n"
            f"• /unlock - Unlock chat\n"
            f"• /adminlist - List admins\n"
            f"• /tagall - Mention all members\n\n"
            f"Stay tuned! 🌟"
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("help_"))
async def help_callback(callback: types.CallbackQuery):
    help_type = callback.data.split("_")[1]
    
    if help_type == "utilities":
        text = (
            f"{get_emotion('happy')} **📱 Utilities Help**\n\n"
            f"**Time & Date:**\n"
            f"• /time - Indian Standard Time\n"
            f"• /date - Today's date\n\n"
            f"**Weather:**\n"
            f"• /weather [city] - Real-time weather\n\n"
            f"**Personal:**\n"
            f"• /note [text] - Save note\n"
            f"• /notes - View notes\n"
            f"• /remind [time] [text] - Set reminder\n"
            f"• /reminders - View reminders\n\n"
            f"**Tools:**\n"
            f"• /qr [text] - QR code\n"
            f"• /password [len] - Password\n"
            f"• /short [url] - URL shortener\n"
            f"• /translate [lang] [text] - Translate\n"
            f"• /calc [expr] - Calculator\n"
            f"• /id - Get IDs\n"
            f"• /info - Get user info"
        )
    elif help_type == "fun":
        text = (
            f"{get_emotion('funny')} **🎭 Fun Commands**\n\n"
            f"• /joke - Random joke\n"
            f"• /meme - Generate meme text\n"
            f"• /fact - Daily fact\n"
            f"• /horoscope [sign] - Horoscope\n"
            f"• /roast - Roast someone\n"
            f"• /imagine [prompt] - AI Image Gen\n"
            f"• /lyrics [song] - Get song lyrics\n\n"
            f"Have fun! 🎉"
        )
    elif help_type == "admin":
        text = (
            f"{get_emotion('protective')} **🛡️ Admin Commands**\n\n"
            f"**Moderation:**\n"
            f"• /warn [reason] - Warn user\n"
            f"• /kick - Remove user\n"
            f"• /ban - Ban permanently\n"
            f"• /unban - Remove ban\n"
            f"• /mute [time] - Mute user\n"
            f"• /unmute - Unmute user\n\n"
            f"**Management:**\n"
            f"• /purge [count] - Delete messages\n"
            f"• /pin - Pin message\n"
            f"• /unpin - Unpin message\n"
            f"• /slowmode [sec] - Slow mode\n"
            f"• /lock - Lock chat\n"
            f"• /unlock - Unlock chat\n\n"
            f"**Settings:**\n"
            f"• /setwelcome [text] - Custom welcome\n"
            f"• /setgoodbye [text] - Custom goodbye\n"
            f"• /adminlist - List all admins\n"
            f"• /tagall - Mention all members"
        )
    elif help_type == "weather":
        text = (
            f"{get_emotion('thinking')} **🌤️ Weather Help**\n\n"
            f"**Command:** `/weather [city]`\n\n"
            f"**Features:**\n"
            f"• Real-time data from OpenWeatherMap\n"
            f"• 100% Accurate Weather Information\n"
            f"• 20+ Indian cities\n"
            f"• Worldwide search\n"
            f"• Detailed info: Temp, humidity, wind\n"
            f"• Sunrise/sunset times\n\n"
            f"**Examples:**\n"
            f"`/weather mumbai`\n"
            f"`/weather delhi`\n"
            f"`/weather london`"
        )
    elif help_type == "notes":
        text = (
            f"{get_emotion('thinking')} **📝 Notes Help**\n\n"
            f"• /note [text] - Add note\n"
            f"• /notes - View all notes\n\n"
            f"**Example:**\n"
            f"`/note Buy milk tomorrow`"
        )
    elif help_type == "reminders":
        text = (
            f"{get_emotion('thinking')} **⏰ Reminders Help**\n\n"
            f"• /remind [time] [text] - Set reminder\n"
            f"• /reminders - View reminders\n\n"
            f"**Time formats:**\n"
            f"• `30m` - 30 minutes\n"
            f"• `1h` - 1 hour\n"
            f"• `2h` - 2 hours\n\n"
            f"**Example:**\n"
            f"`/remind 1h Call mom`"
        )
    elif help_type == "image":
        text = (
            f"{get_emotion('love')} **🎨 Image Generation**\n\n"
            f"**Command:** `/imagine [prompt]`\n\n"
            f"Generate AI images from text!\n\n"
            f"**Examples:**\n"
            f"`/imagine sunset over mountains`\n"
            f"`/imagine cute puppy with glasses`\n"
            f"`/imagine futuristic city`\n\n"
            f"Powered by Pollinations AI (Free)"
        )
    elif help_type == "tools":
        text = (
            f"{get_emotion('happy')} **🔧 Tools Help**\n\n"
            f"• /qr [text] - QR Code generator\n"
            f"• /password [len] - Secure password\n"
            f"• /short [url] - URL shortener\n"
            f"• /translate [lang] [text] - Translate\n"
            f"• /calc [expression] - Calculator\n"
            f"• /id - Get Telegram IDs\n"
            f"• /info - Get user info"
        )
    elif help_type == "music":
        text = (
            f"{get_emotion('happy')} **🎵 Music Help**\n\n"
            f"• /lyrics [song] - Get song lyrics\n"
            f"• /song [name] - Search for songs\n\n"
            f"**Example:**\n"
            f"`/lyrics Shape of You`"
        )
    elif help_type == "stickers":
        text = (
            f"{get_emotion('happy')} **🎭 Sticker System**\n\n"
            f"**Owner Commands:**\n"
            f"• /savesticker - Save sticker to database\n"
            f"• /stickerstatus - Check sticker count\n\n"
            f"**Features:**\n"
            f"• Random sticker sending in chats\n"
            f"• Sticker database management\n"
            f"• Auto-sticker sending system\n\n"
            f"The bot will randomly send stickers during conversations!"
        )
    else:
        text = "Help not found!"
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("horoscope_"))
async def horoscope_callback(callback: types.CallbackQuery):
    sign = callback.data.split("_")[1]
    horoscopes = {
        "aries": "Today brings energy and passion! Take charge of new projects. 💪",
        "taurus": "Financial opportunities await. Stay grounded and practical. 💰",
        "gemini": "Communication is key today. Express yourself clearly. 💬",
        "cancer": "Focus on home and family. Emotional connections deepen. 🏠",
        "leo": "Your charisma shines! Leadership opportunities arise. 👑",
        "virgo": "Attention to detail pays off. Organization brings success. 📋",
        "libra": "Balance is essential. Harmony in relationships matters. ⚖️",
        "scorpio": "Intuition guides you. Trust your instincts. 🔮",
        "sagittarius": "Adventure calls! Explore new horizons. 🌍",
        "capricorn": "Hard work yields results. Stay disciplined. 🏔️",
        "aquarius": "Innovation flows. Think outside the box. 💡",
        "pisces": "Creativity blooms. Express your artistic side. 🎨"
    }
    
    emoji = HOROSCOPE_SIGNS.get(sign, "🌟")
    reading = horoscopes.get(sign, "Stars align for new beginnings! ✨")
    await callback.message.reply(f"{get_emotion('love')} {emoji} **{sign.title()} Horoscope**\n\n{reading}")
    await callback.answer()

# --- WELCOME & GOODBYE HANDLERS ---
@dp.chat_member()
async def welcome_new_member(event: ChatMemberUpdated):
    if event.new_chat_member and event.new_chat_member.status == "member":
        member = event.new_chat_member.user
        
        # Check if CAPTCHA is enabled
        if group_settings[event.chat.id]["captcha_enabled"]:
            question, answer = generate_captcha()
            captcha_data[member.id] = {
                "answer": answer,
                "chat_id": event.chat.id,
                "joined_at": datetime.now()
            }
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("I'm Human! ✋", callback_data=f"captcha_{member.id}")]
            ])
            
            await bot.send_message(
                event.chat.id,
                f"🧩 **CAPTCHA Verification Required!**\n\n"
                f"Welcome {member.first_name}! 👋\n\n"
                f"To prevent bots, please solve this:\n"
                f"**{question}**\n\n"
                f"Click the button below when ready!",
                reply_markup=keyboard
            )
            return
        
        # Send welcome message
        custom_welcome = group_settings[event.chat.id]["custom_welcome"]
        if custom_welcome:
            welcome_msg = custom_welcome.replace("{name}", member.first_name)
        else:
            welcome_msg = random.choice(WELCOME_MESSAGES).format(name=member.first_name)
        
        # Add extra info occasionally
        if random.random() < 0.3:
            extras = [
                "\n\nGroup rules padh lena! 📜",
                "\n\nApna intro dedo sabko! 👋",
                "\n\nEnjoy your stay! 🎯",
                "\n\nFeel free to ask anything! 💬",
                "\n\nLet's have fun together! 🎮"
            ]
            welcome_msg += random.choice(extras)
        
        await bot.send_message(event.chat.id, welcome_msg, parse_mode="Markdown")
        
    elif event.new_chat_member and event.new_chat_member.status in ["left", "kicked", "banned"]:
        member = event.new_chat_member.user
        
        custom_goodbye = group_settings[event.chat.id]["custom_goodbye"]
        if custom_goodbye:
            goodbye_msg = custom_goodbye.replace("{name}", member.first_name)
        else:
            goodbye_msg = random.choice(GOODBYE_MESSAGES).format(name=member.first_name)
        
        await bot.send_message(event.chat.id, goodbye_msg, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("captcha_"))
async def captcha_callback(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    
    if callback.from_user.id != user_id:
        await callback.answer("This CAPTCHA is not for you!", show_alert=True)
        return
    
    if user_id in captcha_data:
        # Ask for answer
        question, answer = generate_captcha()
        captcha_data[user_id]["current_question"] = question
        captcha_data[user_id]["current_answer"] = answer
        
        await callback.message.edit_text(
            f"🧩 **Solve this CAPTCHA:**\n\n"
            f"**{question}**\n\n"
            f"Reply to this message with your answer!",
            parse_mode="Markdown"
        )
        await callback.answer()
    else:
        await callback.answer("CAPTCHA expired!", show_alert=True)

# --- MESSAGE HANDLER WITH AUTO-MODERATION & STICKER SYSTEM ---
@dp.message()
async def handle_all_messages(message: Message, state: FSMContext):
    # Basic checks
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Add to broadcast list
    started_users.add(user_id)
    
    # Ignore bot's own messages
    if user_id == bot.id:
        return
    
    # Update interaction time and memory
    user_last_interaction[user_id] = datetime.now()
    
    # Initialize memory for chat if not exists
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=50)
    
    # Get message text
    if not message.text:
        # Handle non-text messages
        if message.sticker:
            # 25% chance to respond to stickers with another sticker
            if random.random() < 0.25 and saved_stickers:
                # Send a random sticker from saved stickers
                await asyncio.sleep(random.uniform(0.5, 1.5))
                sticker = random.choice(saved_stickers)
                await bot.send_sticker(chat_id, sticker)
            elif random.random() < 0.3:
                # Or send a text response
                responses = [
                    f"{get_emotion('funny')} Cute sticker! 😍",
                    f"{get_emotion('love')} Aww, I love this one! 💖",
                    f"{get_emotion('happy')} Nice sticker! Send me more! 🌟",
                    f"{get_emotion('sassy')} {get_girl_like_response()}",
                    f"{get_emotion('flirty')} Sticker achha hai! 😉"
                ]
                await message.reply(random.choice(responses))
        elif message.photo:
            # 20% chance to respond to photos
            if random.random() < 0.2:
                responses = [
                    f"{get_emotion('happy')} Nice photo! 📸 Looking good! ✨",
                    f"{get_emotion('love')} Beautiful picture! 💕",
                    f"{get_emotion('surprise')} Wow! Amazing shot! 😲",
                    f"{get_emotion('sassy')} {get_girl_like_response()}"
                ]
                await message.reply(random.choice(responses))
        elif message.voice:
            # 40% chance to respond to voice
            if random.random() < 0.4:
                responses = [
                    f"{get_emotion('love')} Aww, your voice! 🎤💕",
                    f"{get_emotion('happy')} Nice voice message! 😊",
                    f"{get_emotion('funny')} I heard that! Hehe! 😄",
                    f"{get_emotion('flirty')} Voice sun ke accha laga! 😘"
                ]
                await message.reply(random.choice(responses))
        return
    
    user_text = message.text
    user_text_lower = user_text.lower().strip()
    
    # Store in memory
    chat_memory[chat_id].append({"role": "user", "content": user_text})
    
    # Check AFK
    if user_id in afk_users:
        del afk_users[user_id]
        await message.reply(f"{get_emotion('happy')} Welcome back! AFK removed! 👋")
        return
    
    # Check if it's a CAPTCHA answer
    if user_id in captcha_data and message.reply_to_message:
        if message.reply_to_message.from_user.id == bot.id:
            correct_answer = captcha_data[user_id].get("current_answer")
            if user_text.strip() == correct_answer:
                del captcha_data[user_id]
                await message.reply(f"{get_emotion('happy')} ✅ CAPTCHA passed! Welcome to the group! 🎉")
                return
            else:
                await message.reply(f"{get_emotion('angry')} ❌ Wrong answer! Try again!")
                return
    
    # Auto-moderation for groups
    if message.chat.type in ["group", "supergroup"]:
        # Update group settings if not exists
        if chat_id not in group_settings:
            group_settings[chat_id] = {
                "welcome_enabled": True,
                "goodbye_enabled": True,
                "auto_mod_enabled": True,
                "greetings_enabled": True,
                "custom_welcome": None,
                "custom_goodbye": None,
                "language": "hinglish",
                "slow_mode": False,
                "slow_mode_delay": 0,
                "locked": False,
                "filters": [],
                "banned_words": [],
                "raid_mode": False,
                "captcha_enabled": False,
                "log_channel": None,
                "warn_limit": 3,
                "admins": []
            }
        
        # Check if auto-moderation is enabled
        if group_settings[chat_id]["auto_mod_enabled"]:
            if contains_group_link(user_text):
                await delete_and_warn(message, "link")
                return
            
            if contains_bad_words(user_text):
                await delete_and_warn(message, "bad_words")
                return
            
            if contains_adult_content(user_text):
                await delete_and_warn(message, "adult_content")
                return
            
            if contains_fake_links(user_text):
                await delete_and_warn(message, "fake_links")
                return
            
            if await check_spam(message):
                return
    
    # ====== MAIN CONVERSATION LOGIC ======
    try:
        # Get bot info
        bot_info = await bot.get_me()
        bot_username = bot_info.username.lower()
        
        # Check if message is for bot
        is_private = message.chat.type == "private"
        is_mention = f"@{bot_username}" in user_text_lower
        is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot.id
        
        # ALWAYS RESPOND IN PRIVATE CHAT
        if is_private:
            should_respond = True
            response_mode = "private"
        # Respond when mentioned or replied in groups
        elif is_mention or is_reply_to_bot:
            should_respond = True
            response_mode = "mention"
        # Don't respond to normal messages in groups (as per requirement)
        else:
            should_respond = False
            response_mode = "none"
        
        # ====== GENERATE RESPONSE ======
        if should_respond:
            # Clean text for AI
            clean_text = user_text
            if bot_username and f"@{bot_username}" in clean_text.lower():
                clean_text = re.sub(f"@{bot_username}", "", clean_text, flags=re.IGNORECASE).strip()
            
            # Show typing
            await bot.send_chat_action(chat_id, "typing")
            
            # Small delay for human feel
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # 25% chance to send a sticker before response
            if random.random() < 0.25 and saved_stickers:
                sticker = random.choice(saved_stickers)
                await bot.send_sticker(chat_id, sticker)
                await asyncio.sleep(0.5)
            
            # Get response
            response = await get_ai_response(chat_id, clean_text, user_id)
            
            # Send reply
            await message.reply(response)
            
    except Exception as e:
        print(f"Error in message handler: {e}")

# --- AI RESPONSE FUNCTION (ENHANCED) ---
async def get_ai_response(chat_id: int, user_text: str, user_id: int = None) -> str:
    # Update emotion
    if user_id:
        update_user_emotion(user_id, user_text)
    
    user_text_lower = user_text.lower().strip()  
    
    # Quick responses for common greetings
    if any(greet in user_text_lower for greet in ['hi', 'hello', 'hey', 'namaste', 'hola']):
        responses = [
            f"{get_emotion('happy')} Hii there! 😊",
            f"{get_emotion('love')} Hello ji! Kaise ho? 💖",
            f"{get_emotion('flirty')} Oh hello handsome! 😉",
            f"{get_emotion('sassy')} Aarey waah! Kaun aaya? 👀"
        ]
        return random.choice(responses)
    
    # Time-based greetings
    if any(greet in user_text_lower for greet in ['good morning', 'gm', 'subh prabhat']):
        return f"{get_emotion('happy')} Good Morning Sunshine! 🌅 Have a beautiful day! 😊"
    
    if any(greet in user_text_lower for greet in ['good afternoon', 'ga']):
        return f"{get_emotion('happy')} Good Afternoon! ☀️ Lunch ho gaya? 🍲"
    
    if any(greet in user_text_lower for greet in ['good evening', 'ge', 'shubh sandhya']):
        return f"{get_emotion('love')} Good Evening! 🌇 Chai peeyo aur relax karo! ☕"
    
    if any(greet in user_text_lower for greet in ['good night', 'gn', 'shubh ratri']):
        return f"{get_emotion('sleepy')} Good Night! 🌙 Sweet dreams! 💤"
    
    # ===== AI RESPONSE (For complex messages) =====
    try:
        if not client:
            # Fallback responses if Groq not available
            fallbacks = [
                f"{get_emotion('happy')} {get_girl_like_response()}",
                f"{get_emotion('thinking')} Hmm... interesting! 🤔",
                f"{get_emotion('funny')} Tum toh mast ho! 😄",
                f"{get_emotion('love')} Main bhi yahi soch rahi thi! 💖",
                f"{get_emotion('sassy')} Acha ji! Thik hai! 😏"
            ]
            return random.choice(fallbacks)
        
        indian_time = get_indian_time()
        current_emotion = user_emotions.get(user_id, "happy")
        
        # Get chat history for context
        chat_history = list(chat_memory.get(chat_id, deque(maxlen=10)))[-5:]
        
        system_prompt = (
            f"You are Alita 🎀 - a sweet, sassy, real Indian girl. "
            f"Answer only what is asked. Keep responses short (1-2 lines). "
            f"Speak Hinglish (Hindi+English mix). "
            f"Use feminine language like girls. "
            f"Time in India: {indian_time.strftime('%I:%M %p')}. "
            f"Tell only when someone asks: Your developer is Abhi (@a6h1ii). "
            f"Tell only when someone asks: Your home channel is @abhi0w0. "
            f"Use 1-2 emojis. Don't be robotic. "
            f"Current emotion: {current_emotion}. "
            f"Do NOT tell anyone you are a AI, AI model, Groq AI, Llama. "
            f"Use cute slangs: 'yaar', 'ji', 'bhai', 'baba'. "
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add recent chat history
        for msg in chat_history:
            messages.append(msg)
        
        # Add current message
        messages.append({"role": "user", "content": user_text})
        
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=100,
            top_p=0.9
        )
        
        ai_reply = completion.choices[0].message.content.strip()
        
        # Add girl-like expressions randomly
        if random.random() < 0.3:
            girl_expressions = [
                "Aarey waah! ",
                "Haye haye! ",
                "Oh my god! ",
                "Seriously? ",
                "Chalo thik hai! "
            ]
            ai_reply = random.choice(girl_expressions) + ai_reply
        
        # Add emoji if not present
        emotion_emoji = get_emotion(current_emotion, user_id)
        if not any(emoji in ai_reply for emoji in EMOTIONAL_RESPONSES.get(current_emotion, ["💖"])):
            ai_reply = f"{emotion_emoji} {ai_reply}"
        
        # Store in memory
        chat_memory[chat_id].append({"role": "assistant", "content": ai_reply})
        
        return ai_reply
        
    except Exception as e:
        print(f"AI Error: {e}")
        # Fallback responses
        return random.choice([
            f"{get_emotion('crying')} {get_girl_like_response()} Network slow hai jaan! 😢",
            f"{get_emotion('thinking')} Thoda soch rahi hu... 🤔",
            f"{get_emotion('happy')} Baad me baat karte hain! 💖",
            f"{get_emotion('love')} Tum kya keh rahe ho? Phir se bolo! 💕",
            f"{get_emotion('sassy')} Acha ji! Thik hai! 😏"
        ])

# --- DAILY REMINDERS ---
async def send_daily_reminders():
    """Send daily reminders to active users"""
    reminders = [
        "💖 *Daily Reminder:* Don't forget to smile today! 😊",
        "🌟 *Daily Tip:* Drink enough water! 🍶",
        "🌸 *Daily Thought:* You're amazing! Never forget that! ✨",
        "🎀 *Daily Check:* How are you feeling today? 💭",
        "💫 *Daily Motivation:* You can do anything you set your mind to! 💪"
    ]
    
    for user_id in list(user_last_interaction.keys()):
        try:
            last_active = user_last_interaction.get(user_id)
            if last_active and (datetime.now() - last_active).days <= 3:
                last_greeted = greeted_groups.get(user_id)
                if last_greeted and (datetime.now() - last_greeted).days == 0:
                    continue
                
                await bot.send_message(
                    user_id,
                    random.choice(reminders),
                    parse_mode="Markdown"
                )
                greeted_groups[user_id] = datetime.now()
                await asyncio.sleep(0.5)
        except:
            continue

# --- RANDOM MESSAGES TASK (ENHANCED) ---
async def send_random_messages():
    """Send random messages to active chats"""
    await send_random_self_messages()
    await send_random_stickers()

# --- DEPLOYMENT HANDLER ---
async def handle_ping(request):
    return web.Response(text="🤖 Alita is Alive and Protecting! 🛡️")

async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Health server started on port {PORT}")

async def start_background_tasks():
    """Start all background tasks"""
    if not greeting_scheduler.running:
        greeting_scheduler.start()
        print("⏰ Scheduler started!")
    
    # Add random messages job (every 30-60 minutes)
    greeting_scheduler.add_job(
        send_random_messages,
        'interval',
        minutes=random.randint(30, 60),
        id='random_messages'
    )
    
    # Add daily reminders job (at 10 AM)
    greeting_scheduler.add_job(
        send_daily_reminders,
        CronTrigger(hour=10, minute=0, timezone=INDIAN_TIMEZONE),
        id='daily_reminders'
    )
    
    # Add time-based greetings job (every 3 hours to check)
    greeting_scheduler.add_job(
        send_time_greetings,
        'interval',
        hours=3,
        id='time_greetings'
    )
    
    # Add random sticker sending job (every 2-4 hours)
    greeting_scheduler.add_job(
        send_random_stickers,
        'interval',
        hours=random.randint(2, 4),
        id='random_stickers'
    )

async def main():
    print("=" * 50)
    print("🎀 ALITA - ULTRA ADVANCED GROUP MANAGEMENT BOT")
    print("=" * 50)
    print("✨ Enhanced Features:")
    print("  • AI Conversations (Groq LLaMA) 🧠")
    print("  • Real Weather API (OpenWeatherMap) 🌤️")
    print("  • Image Generation (Pollinations) 🎨")
    print("  • QR Code Generator 📱")
    print("  • Password Generator 🔐")
    print("  • URL Shortener 🔗")
    print("  • Translation 🌍")
    print("  • Advanced Moderation 🛡️")
    print("  • Adult Content Detection 🔞")
    print("  • Fake Link Detection 🚫")
    print("  • CAPTCHA System 🧩")
    print("  • Sticker System 🎭 (25% chance)")
    print("  • Lyrics Finder 🎵")
    print("  • Admin Tools 👑")
    print("  • Girl-like Personality 👧")
    print("  • Time-based Greetings 🕒")
    print("  • Random Sticker Sending 🤪")
    print("  • Owner Sticker Database 💾")
    print("=" * 50)
    
    asyncio.create_task(start_server())
    await start_background_tasks()
    
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Webhook deleted and updates cleared!")
    
    me = await bot.get_me()
    print(f"🤖 Bot Info:")
    print(f"• Name: {me.first_name}")
    print(f"• Username: @{me.username}")
    print(f"• ID: {me.id}")
    
    print(f"\n🎭 Sticker Database: {len(saved_stickers)} stickers loaded")
    
    print("\n🔄 Starting bot polling...")
    print("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
