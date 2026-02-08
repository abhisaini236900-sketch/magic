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
import logging
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

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database setup - Render compatible
DB_PATH = "/tmp/alita_bot.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Create all tables
def init_db():
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            type TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS stickers (
            file_id TEXT PRIMARY KEY,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tags TEXT DEFAULT ''
        );
        
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            reason TEXT,
            warned_by INTEGER,
            warned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            note_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS afk_users (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            since TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

init_db()

# Configuration
TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PORT = int(os.getenv("PORT", "10000"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")

if not TOKEN:
    raise ValueError("BOT_TOKEN is required!")

# Initialize bot
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Timezone
INDIAN_TIMEZONE = pytz.timezone('Asia/Kolkata')

# Memory systems
chat_memory: Dict[int, deque] = {}
user_warnings: Dict[int, Dict[int, List]] = defaultdict(lambda: defaultdict(list))
user_message_count: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
last_messages: Dict[int, Dict[int, List]] = defaultdict(lambda: defaultdict(list))

# Data storage
user_data: Dict[int, Dict] = defaultdict(dict)
user_notes: Dict[int, List[Dict]] = defaultdict(list)
user_reminders: Dict[int, List[Dict]] = defaultdict(list)
user_reputation: Dict[int, int] = defaultdict(int)
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}
started_users: Set[int] = set()

# AFK system
afk_users: Dict[int, Dict] = {}

# Group settings
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
last_greeting_time: Dict[int, datetime] = {}

# Stickers
saved_stickers: List[str] = []

# Bot info cache
bot_info = None

# Constants
BAD_WORDS = [
    "chutiya", "chutiye", "madarchod", "behenchod", "bhosdike", "lodu", "gandu",
    "fuck", "shit", "bitch", "bastard", "asshole", "motherfucker", "cunt", "dick",
    "gaand", "lund", "randi", "harami", "kamina", "suar", "kutta", "bhosdi",
    "bc", "mc", "gand", "lauda", "choot", "maa ki", "behen ki"
]

ADULT_KEYWORDS = [
    "porn", "xxx", "nsfw", "adult", "sex", "nude", "naked", "boobs", "ass",
    "dick", "pussy", "hentai", "porno", "horny", "fuck", "sexy", "hot", "desi", 
    "chudai", "lund", "chod", "blowjob", "handjob", "tits", "cum", "orgasm"
]

FAKE_LINK_PATTERNS = [
    r'bit\.ly\/[a-zA-Z0-9]+', r'tinyurl\.com\/[a-zA-Z0-9]+',
    r'goo\.gl\/[a-zA-Z0-9]+', r'shorturl\.at\/[a-zA-Z0-9]+',
    r'ow\.ly\/[a-zA-Z0-9]+', r'is\.gd\/[a-zA-Z0-9]+',
    r'cli\.gs\/[a-zA-Z0-9]+', r't\.co\/[a-zA-Z0-9]+'
]

GROUP_LINK_PATTERNS = [
    r't\.me\/[a-zA-Z0-9_]+', r'telegram\.me\/[a-zA-Z0-9_]+',
    r'telegram\.dog\/[a-zA-Z0-9_]+', r'@\+[a-zA-Z0-9_]+'
]

SPAM_LIMIT = 7
SPAM_TIME_WINDOW = 30

WARNING_MESSAGES = [
    "⚠️ **Warning {count}/{limit}** 🚨\n{name}, please don't {action}!",
    "🚨 **Strike {count}!** ⚠️\n{name}, {action} is not allowed!",
    "⚡ **Final Warning** ⚡\n{name}, last chance! Stop {action}!"
]

MUTE_DURATIONS = [
    timedelta(minutes=5),
    timedelta(hours=1),
    timedelta(hours=24),
    timedelta(days=7)
]

# Data templates
MEME_TEMPLATES = [
    {"text": "When you realize it's Monday tomorrow", "emoji": "😭"},
    {"text": "Me trying to be productive", "emoji": "🤡"},
    {"text": "When mom calls you by your full name", "emoji": "😰"},
    {"text": "My bank account after online shopping", "emoji": "💸"},
    {"text": "When code finally works after 100 tries", "emoji": "🎉"},
    {"text": "Me explaining why I need a new phone", "emoji": "🤥"},
    {"text": "My sleep schedule at 3 AM", "emoji": "🦉"},
    {"text": "When someone says 'just be yourself'", "emoji": "😅"}
]

HOROSCOPE_SIGNS = {
    "aries": "♈", "taurus": "♉", "gemini": "♊", "cancer": "♋",
    "leo": "♌", "virgo": "♍", "libra": "♎", "scorpio": "♏",
    "sagittarius": "♐", "capricorn": "♑", "aquarius": "♒", "pisces": "♓"
}

DAILY_FACTS = [
    "Honey never spoils! Archaeologists found 3000-year-old honey still edible! 🍯",
    "Octopuses have 3 hearts! One stops when they swim! 💙",
    "Bananas are berries, but strawberries aren't! 🍌🍓",
    "A day on Venus is longer than its year! 🌟",
    "Sharks existed before trees! 🦈",
    "The human brain uses 20% of body's energy! 🧠",
    "Butterflies taste with their feet! 🦋",
    "A group of flamingos is called a 'flamboyance'! 💖",
    "Wombat poop is cube-shaped! 🟫",
    "Sloths can hold their breath longer than dolphins! 🦥"
]

ROAST_RESPONSES = [
    "Tumhari baaton se toh mere kaan bhi sharminda hain! 👂😳",
    "Itni bakwas toh mere phone ki auto-correct bhi nahi karta! 📱",
    "Tumhare jokes se toh meri wallpaper bhi bore ho gayi! 🖼️",
    "Agar overthinking Olympic sport hota, toh tum gold medal le jaate! 🏅",
    "Tumhari logic dekh ke toh Einstein bhi pagal ho jaate! 🧠💥",
    "Tumhare confidence ki toh alag hi duniya hai - unrealistic! 🌍",
    "Tumhare dimaag mein itna khaali hai, wahan echo aata hoga! 🎤",
    "Tum itne slow ho, turtle bhi tumse race jeet jaaye! 🐢",
    "Tumhari shakal dekh ke mirror bhi ro deta hoga! 🪞😭",
    "Tumhare liye 'intelligent' word bhi sharma jaye! 📚"
]

JOKES = [
    "Teacher: Tumhare ghar me sabse smart kaun hai?\nStudent: WiFi router! Kyuki sab use hi puchte hain! 🤣",
    "Papa: Beta mobile chhodo, padhai karo.\nBeta: Papa, aap bhi to TV dekhte ho!\nPapa: Par main TV se shaadi nahi kar raha! 😂",
    "Doctor: Aapko diabetes hai.\nPatient: Kya khana chhodna hoga?\nDoctor: Nahi, aapka sugar chhodna hoga! 😆",
    "Dost: Tumhari girlfriend kitni cute hai!\nMe: Haan, uski akal bhi utni hi cute hai! 😅",
    "Teacher: Agar 5 aam hain aur main 2 le lun?\nStudent: Sir, aapke paas already 2 kyun hain? 🤪",
    "Boyfriend: Tum meri life ki battery ho!\nGirlfriend: Toh charging khatam kyun ho jati hai? 😜",
    "Boss: Kal se late mat aana.\nEmployee: Aaj hi late kyun bola? Kal bata dete! 😁",
    "Customer: Yeh shampoo hair fall rokta hai?\nShopkeeper: Nahi sir, hair fall hone par refund deta hai! 🤭",
    "Boy: I love you!\nGirl: Tumhare paas girlfriend nahi hai?\nBoy: Haan, tumhare saath hi baat kar raha hu! 😹",
    "Bhai: Behen kyun ro rahi ho?\nBehen: Boyfriend break-up kar raha hai!\nBhai: Uske liye ro rahi ho ya free time ke liye? 😄"
]

WELCOME_MESSAGES = [
    "🎉 Welcome {name}! Group mein swagat hai! 🎊",
    "🌟 Aao ji {name}! Masti karenge! ✨",
    "✨ Hey {name}! Great to have you here! 💖",
    "🥳 {name} aa gaye! Party shuru! 🎈",
    "😊 Namaste {name}! Aapka swagat hai! 🙏",
    "🌸 Welcome {name}! Enjoy your stay! 💕",
    "🎈 Hey {name}! Thanks for joining! 🎉",
    "💫 Welcome aboard {name}! Let's have fun! 🚀"
]

GOODBYE_MESSAGES = [
    "👋 {name} left. We'll miss you! 😢",
    "😔 {name} has departed. Take care! 🌸",
    "🚪 {name} left. Bye bye! 👋",
    "💔 {name} is no longer with us. Farewell! 🌟",
    "🌙 {name} has left. Good luck! ✨"
]

TIME_GREETINGS = {
    "morning": {
        "templates": [
            "🌅 *Good Morning Sunshine!* ☀️\nKaisi hai aaj ki subah? Utho aur muskurao! 😊",
            "🌸 *Shubh Prabhat!* 🌸\nAaj ka din aapke liye khoobsurat ho! ✨",
            "☕ *Morning Coffee Time!* 🍵\nChai piyo, fresh ho jao! 💫"
        ]
    },
    "afternoon": {
        "templates": [
            "☀️ *Good Afternoon!* 🌤️\nLunch ho gaya? Energy maintain rakho! 🍲",
            "🌞 *Dopahar ki Dhoop!* 🌞\nThoda aaraam karo! 😌",
            "🍛 *Afternoon Siesta!* 💤\nKhaana kha ke neend aa rahi hai? 😴"
        ]
    },
    "evening": {
        "templates": [
            "🌇 *Good Evening Beautiful!* 🌆\nShaam ho gayi, relax karo! 🌹",
            "🌆 *Evening Tea Time!* 🍵\nChai aur baatein! 💖",
            "✨ *Shubh Sandhya!* ✨\nDin bhar ki thakaan door karo! 🎶"
        ]
    },
    "night": {
        "templates": [
            "🌙 *Good Night Sweet Dreams!* 🌟\nAccha sapna dekho! 💤",
            "🌌 *Shubh Ratri!* 🌌\nThaka hua dimaag ko aaraam do! 😴",
            "💤 *Sleep Time!* 💤\nKal phir nayi energy! 🌅"
        ]
    }
}

EMOTIONAL_RESPONSES = {
    "happy": ["😊", "🎉", "🥳", "🌟", "✨", "😄", "😍", "🤗", "💫", "💖"],
    "angry": ["😠", "👿", "💢", "🤬", "😤", "🔥", "⚡", "💥", "👊", "😡"],
    "crying": ["😢", "😭", "💔", "🥺", "😞", "🌧️", "😿", "🥀", "💧", "😰"],
    "love": ["❤️", "💖", "💕", "🥰", "😘", "💋", "💓", "💗", "💘", "💝"],
    "funny": ["😂", "🤣", "😆", "😜", "🤪", "🎭", "🤡", "🃏", "😹", "🤭"],
    "thinking": ["🤔", "💭", "🧠", "🔍", "💡", "🎯", "🧐", "🔎", "💬", "🗨️"],
    "surprise": ["😲", "🤯", "😱", "🎊", "🎁", "💥", "✨", "🎆", "🎇", "😮"],
    "sleepy": ["😴", "💤", "🌙", "🛌", "🥱", "😪", "🌃", "🌜", "🌚", "😌"],
    "sassy": ["💅", "👑", "💁", "💃", "🕶️", "💄", "👠", "✨", "🌟", "😏"],
    "protective": ["🛡️", "⚔️", "👮", "🚓", "🔒", "🔐", "🪖", "🎖️", "🏹", "🗡️"]
}

# Load stickers
def load_stickers():
    global saved_stickers
    try:
        cursor.execute("SELECT file_id FROM stickers")
        saved_stickers = [row[0] for row in cursor.fetchall()]
        logger.info(f"Loaded {len(saved_stickers)} stickers")
    except Exception as e:
        logger.error(f"Error loading stickers: {e}")
        saved_stickers = []

load_stickers()

# Helper functions
def get_indian_time():
    return datetime.now(INDIAN_TIMEZONE)

def get_current_time_period():
    hour = get_indian_time().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"

def get_emotion(emotion_type: str = "happy"):
    return random.choice(EMOTIONAL_RESPONSES.get(emotion_type, EMOTIONAL_RESPONSES["happy"]))

def update_user_emotion(user_id: int, message: str):
    msg_lower = message.lower()
    if any(w in msg_lower for w in ['love', 'pyaar', 'dil']):
        user_emotions[user_id] = "love"
    elif any(w in msg_lower for w in ['angry', 'gussa', 'hate']):
        user_emotions[user_id] = "angry"
    elif any(w in msg_lower for w in ['cry', 'sad', 'ro']):
        user_emotions[user_id] = "crying"
    elif any(w in msg_lower for w in ['funny', 'joke', 'haha']):
        user_emotions[user_id] = "funny"
    else:
        user_emotions[user_id] = random.choice(list(EMOTIONAL_RESPONSES.keys()))
    user_last_interaction[user_id] = datetime.now()

# Admin check
async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        if user_id == ADMIN_ID:
            return True
            
        chat = await bot.get_chat(chat_id)
        if chat.type == "private":
            return False
            
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Admin check error: {e}")
        return False

# Auto-moderation
def contains_bad_words(text: str) -> bool:
    return any(word in text.lower() for word in BAD_WORDS)

def contains_adult_content(text: str) -> bool:
    return any(word in text.lower() for word in ADULT_KEYWORDS)

def contains_group_link(text: str) -> bool:
    text_lower = text.lower()
    return any(re.search(pattern, text_lower) for pattern in GROUP_LINK_PATTERNS)

def contains_fake_link(text: str) -> bool:
    text_lower = text.lower()
    return any(re.search(pattern, text_lower) for pattern in FAKE_LINK_PATTERNS)

async def check_spam(message: Message) -> bool:
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
    
    return len(last_messages[chat_id][user_id]) > SPAM_LIMIT

async def give_warning(chat_id: int, user_id: int, name: str, reason: str) -> Tuple[bool, str]:
    cursor.execute(
        "SELECT COUNT(*) FROM warnings WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id)
    )
    count = cursor.fetchone()[0] + 1
    
    limit = group_settings[chat_id].get("warn_limit", 3)
    
    actions = {
        "spam": "spamming",
        "link": "sharing links",
        "bad_words": "using bad language",
        "adult": "sharing adult content"
    }
    action = actions.get(reason, "violating rules")
    
    msg = random.choice(WARNING_MESSAGES).format(
        count=count, limit=limit, name=name, action=action
    )
    
    if count >= limit:
        if reason == "adult":
            try:
                await bot.ban_chat_member(chat_id, user_id)
                cursor.execute(
                    "DELETE FROM warnings WHERE chat_id = ? AND user_id = ?",
                    (chat_id, user_id)
                )
                conn.commit()
                return True, msg + "\n\n🚫 **BANNED PERMANENTLY!**"
            except Exception as e:
                return False, msg + f"\n\n⚠️ Ban failed: {e}"
        
        # Mute
        duration = MUTE_DURATIONS[min(3, count - 1)]
        try:
            until = datetime.now() + duration
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            cursor.execute(
                "DELETE FROM warnings WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            conn.commit()
            return True, msg + f"\n\n🔇 **MUTED for {duration}!"
        except Exception as e:
            return False, msg + f"\n\n⚠️ Mute failed: {e}"
    
    return False, msg

async def delete_and_warn(message: Message, reason: str):
    try:
        await message.delete()
    except:
        pass
    
    action, warning_msg = await give_warning(
        message.chat.id,
        message.from_user.id,
        message.from_user.first_name,
        reason
    )
    await message.answer(warning_msg, parse_mode="Markdown")

# Weather API
INDIAN_CITIES = {
    "mumbai": (19.0760, 72.8777), "delhi": (28.6139, 77.2090),
    "bangalore": (12.9716, 77.5946), "kolkata": (22.5726, 88.3639),
    "chennai": (13.0827, 80.2707), "hyderabad": (17.3850, 78.4867),
    "pune": (18.5204, 73.8567), "ahmedabad": (23.0225, 72.5714),
    "jaipur": (26.9124, 75.7873), "lucknow": (26.8467, 80.9462)
}

async def get_weather(city: str) -> str:
    try:
        city_lower = city.lower().strip()
        
        if city_lower in INDIAN_CITIES:
            lat, lon = INDIAN_CITIES[city_lower]
        else:
            # Geocoding
            async with aiohttp.ClientSession() as session:
                geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={WEATHER_API_KEY}"
                async with session.get(geo_url) as resp:
                    if resp.status != 200:
                        return "❌ Weather service error"
                    data = await resp.json()
                    if not data:
                        return f"❌ City '{city}' not found"
                    lat, lon = data[0]['lat'], data[0]['lon']
        
        # Get weather
        async with aiohttp.ClientSession() as session:
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric"
            async with session.get(url) as resp:
                if resp.status != 200:
                    return "❌ Weather data unavailable"
                data = await resp.json()
                
                weather = data['weather'][0]
                main = data['main']
                wind = data['wind']
                
                icons = {
                    "Clear": "☀️", "Clouds": "☁️", "Rain": "🌧️",
                    "Drizzle": "🌦️", "Thunderstorm": "⛈️", "Snow": "❄️"
                }
                icon = icons.get(weather['main'], "🌡️")
                
                return (
                    f"🌤️ **Weather in {city.title()}**\n"
                    f"{'━' * 20}\n"
                    f"{icon} **Condition:** {weather['description'].title()}\n"
                    f"🌡️ **Temperature:** {main['temp']}°C\n"
                    f"😮‍💨 **Feels Like:** {main['feels_like']}°C\n"
                    f"💧 **Humidity:** {main['humidity']}%\n"
                    f"💨 **Wind:** {wind['speed']} m/s\n"
                    f"🌡️ **Pressure:** {main['pressure']} hPa\n\n"
                    f"📍 Powered by Alita"
                )
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return "❌ Weather service temporarily unavailable"

# Image Generation
async def generate_image(prompt: str) -> Optional[bytes]:
    try:
        clean = prompt.replace(" ", "%20")
        url = f"https://image.pollinations.ai/prompt/{clean}?width=512&height=512&nologo=true"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 1000:
                        return data
        return None
    except Exception as e:
        logger.error(f"Image gen error: {e}")
        return None

# QR Generator
def generate_qr(data: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.getvalue()

# Password Generator
def generate_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(chars) for _ in range(length))

# URL Shortener
async def shorten_url(url: str) -> str:
    try:
        api = f"https://tinyurl.com/api-create.php?url={url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.text()
        return url
    except:
        return url

# Translation
async def translate_text(text: str, target: str) -> str:
    try:
        url = f"https://api.mymemory.translated.net/get?q={text}&langpair=en|{target}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("responseData", {}).get("translatedText", text)
        return text
    except:
        return text

# Lyrics
async def get_lyrics(song: str) -> str:
    try:
        url = f"https://api.lyrics.ovh/v1/{song}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    lyrics = data.get('lyrics', 'Not found')
                    if len(lyrics) > 4000:
                        lyrics = lyrics[:4000] + "\n\n... (truncated)"
                    return lyrics
        return "❌ Lyrics not found"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# AI Response
async def get_ai_response(chat_id: int, text: str, user_id: int) -> str:
    try:
        if not client:
            fallbacks = [
                "Main yahan hu! 😊", "Kya haal hai? ✨", "Boliye! 💫",
                "Sun rahi hu! 👂", "Haan ji! 🌟"
            ]
            return f"{get_emotion()} {random.choice(fallbacks)}"
        
        if chat_id not in chat_memory:
            chat_memory[chat_id] = deque(maxlen=50)
        
        update_user_emotion(user_id, text)
        
        # Quick responses
        text_lower = text.lower()
        if any(g in text_lower for g in ['hi', 'hello', 'hey']):
            return f"{get_emotion('happy')} Hii! Kaise ho? 😊"
        if 'good morning' in text_lower:
            return f"{get_emotion('happy')} Good Morning! 🌅 Have a great day!"
        if 'good night' in text_lower:
            return f"{get_emotion('sleepy')} Good Night! 🌙 Sweet dreams!"
        
        # AI completion
        messages = [{
            "role": "system",
            "content": ("You are Alita, a friendly Indian girl. Reply in Hinglish. "
                       "Keep it short (1-2 lines). Be casual, use emojis. "
                       "Developer: @a6h1ii | Home: @abhi0w0")
        }]
        
        for msg in list(chat_memory[chat_id])[-5:]:
            messages.append(msg)
        
        messages.append({"role": "user", "content": text})
        
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=150
        )
        
        reply = completion.choices[0].message.content.strip()
        chat_memory[chat_id].append({"role": "user", "content": text})
        chat_memory[chat_id].append({"role": "assistant", "content": reply})
        
        return f"{get_emotion(user_emotions.get(user_id, 'happy'))} {reply}"
        
    except Exception as e:
        logger.error(f"AI error: {e}")
        return f"{get_emotion()} Thoda busy hu, baad mein baat karein? 😅"
# ========== BASIC COMMANDS ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    started_users.add(user_id)
    
    # Save user to DB
    try:
        cursor.execute(
            """INSERT OR REPLACE INTO users 
               (user_id, username, first_name, last_name) 
               VALUES (?, ?, ?, ?)""",
            (user_id, message.from_user.username, 
             message.from_user.first_name, message.from_user.last_name)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"DB error: {e}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📋 All Commands", callback_data="show_help")],
        [InlineKeyboardButton("🎨 Generate Image", callback_data="gen_image")],
        [InlineKeyboardButton("🌟 Join Channel", url="https://t.me/abhi0w0")]
    ])
    
    welcome_text = (
        f"{get_emotion('love')} <b>Hey! I'm Alita 🎀</b>\n\n"
        f"<i>Your personal AI assistant with superpowers!</i>\n\n"
        f"<b>✨ What I can do:</b>\n"
        f"🧠 <b>AI Chat</b> - Smart conversations\n"
        f"🎨 <b>Image Gen</b> - Create any image\n"
        f"🌤️ <b>Weather</b> - Real-time updates\n"
        f"🛡️ <b>Admin Tools</b> - Group management\n"
        f"🎭 <b>Fun</b> - Jokes, memes, facts\n"
        f"🔧 <b>Utilities</b> - QR, password, calc\n\n"
        f"<b>💬 How to use:</b>\n"
        f"• In <b>Private</b>: Just message me anything!\n"
        f"• In <b>Groups</b>: Mention me or reply to my message\n\n"
        f"<b>🏠 My Home:</b> @abhi0w0\n"
        f"<b>👨‍💻 Developer:</b> @a6h1ii\n\n"
        f"Type /help for all commands! 💕"
    )
    
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=keyboard)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        f"{get_emotion('happy')} <b>🎀 ALITA COMMAND CENTER 🎀</b>\n\n"
        
        f"<b>🧠 AI & CHAT</b>\n"
        f"<code>/start</code> - Start the bot\n"
        f"<code>/ask [question]</code> - Ask AI anything\n"
        f"<code>/clear</code> - Clear chat memory\n\n"
        
        f"<b>🎨 CREATIVE</b>\n"
        f"<code>/imagine [prompt]</code> - AI image generation\n"
        f"<code>/meme</code> - Random meme text\n"
        f"<code>/joke</code> - Random joke\n"
        f"<code>/fact</code> - Daily fact\n"
        f"<code>/roast</code> - Roast someone (reply)\n"
        f"<code>/horoscope [sign]</code> - Daily horoscope\n\n"
        
        f"<b>🌤️ UTILITIES</b>\n"
        f"<code>/weather [city]</code> - Weather info\n"
        f"<code>/time</code> - Indian time\n"
        f"<code>/date</code> - Today's date\n"
        f"<code>/qr [text]</code> - Generate QR code\n"
        f"<code>/password [len]</code> - Secure password\n"
        f"<code>/short [url]</code> - Shorten URL\n"
        f"<code>/calc [expr]</code> - Calculator\n"
        f"<code>/translate [lang] [text]</code> - Translate\n\n"
        
        f"<b>📝 PERSONAL</b>\n"
        f"<code>/note [text]</code> - Save a note\n"
        f"<code>/notes</code> - View your notes\n"
        f"<code>/remind [time] [text]</code> - Set reminder\n"
        f"<code>/reminders</code> - View reminders\n"
        f"<code>/afk [reason]</code> - Set AFK status\n"
        f"<code>/id</code> - Get your info\n"
        f"<code>/info</code> - Get user info (reply)\n\n"
        
        f"<b>🎵 MUSIC</b>\n"
        f"<code>/lyrics [song]</code> - Get song lyrics\n"
        f"<code>/song [name]</code> - Search song info\n\n"
        
        f"<b>🛡️ ADMIN COMMANDS</b>\n"
        f"<code>/adminlist</code> - List all admins\n"
        f"<code>/warn [reason]</code> - Warn user (reply)\n"
        f"<code>/kick</code> - Kick user (reply)\n"
        f"<code>/ban</code> - Ban user permanently (reply)\n"
        f"<code>/unban</code> - Unban user (reply)\n"
        f"<code>/mute [time]</code> - Mute user (reply)\n"
        f"<code>/unmute</code> - Unmute user (reply)\n"
        f"<code>/purge [n]</code> - Delete messages\n"
        f"<code>/pin</code> - Pin message (reply)\n"
        f"<code>/unpin</code> - Unpin last message\n"
        f"<code>/slowmode [sec]</code> - Set slow mode\n"
        f"<code>/lock</code> - Lock group chat\n"
        f"<code>/unlock</code> - Unlock group chat\n"
        f"<code>/setwelcome [text]</code> - Custom welcome\n"
        f"<code>/setgoodbye [text]</code> - Custom goodbye\n"
        f"<code>/tagall</code> - Mention all members\n"
        f"<code>/rules</code> - Show group rules\n\n"
        
        f"<b>👑 OWNER ONLY</b>\n"
        f"<code>/sendall</code> - Broadcast message (reply)\n"
        f"<code>/savesticker</code> - Save sticker (reply)\n"
        f"<code>/stickerstatus</code> - Sticker database info\n"
        f"<code>/broadcast</code> - Send to all users\n\n"
        
        f"<b>🔒 AUTO-MODERATION</b>\n"
        f"• Bad word filtering\n"
        f"• Adult content detection & auto-ban\n"
        f"• Group link blocking\n"
        f"• Spam detection\n"
        f"• Fake link detection\n"
        f"• Auto-warn (3 = mute, adult = ban)\n\n"
        
        f"<b>⏰ SCHEDULED FEATURES</b>\n"
        f"• Morning/Afternoon/Evening/Night greetings\n"
        f"• Daily facts & reminders\n"
        f"• Random sticker sending\n\n"
        
        f"━━〘 <b>@abhi0w0</b> 〙━━"
    )
    await message.answer(help_text, parse_mode="HTML")

@dp.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("❓ Usage: <code>/ask [your question]</code>\nExample: <code>/ask What is AI?</code>", parse_mode="HTML")
        return
    
    await bot.send_chat_action(message.chat.id, "typing")
    response = await get_ai_response(message.chat.id, command.args, message.from_user.id)
    await message.reply(response)

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    chat_id = message.chat.id
    if chat_id in chat_memory:
        chat_memory[chat_id].clear()
    await message.reply(f"{get_emotion('happy')} <b>Memory cleared!</b> 🧹\nChat history has been reset!", parse_mode="HTML")

# ========== CREATIVE COMMANDS ==========

@dp.message(Command("imagine"))
async def cmd_imagine(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            "🎨 <b>Image Generation</b>\n\n"
            "Usage: <code>/imagine [description]</code>\n\n"
            "Examples:\n"
            "• <code>/imagine sunset over mountains</code>\n"
            "• <code>/imagine cute puppy with glasses</code>\n"
            "• <code>/imagine futuristic cyberpunk city</code>\n\n"
            "Powered by Pollinations AI",
            parse_mode="HTML"
        )
        return
    
    status_msg = await message.reply(f"{get_emotion('happy')} <b>Creating your image...</b> 🎨\n<i>{command.args[:50]}{'...' if len(command.args) > 50 else ''}</i>")
    
    try:
        image_data = await generate_image(command.args)
        
        if image_data:
            await status_msg.delete()
            await message.reply_photo(
                BufferedInputFile(image_data, filename="generated.png"),
                caption=(
                    f"🎨 <b>Generated Image</b>\n"
                    f"📝 <i>{command.args}</i>\n\n"
                    f"⚡ Powered by Alita AI"
                ),
                parse_mode="HTML"
            )
        else:
            await status_msg.edit_text("❌ <b>Failed to generate image.</b>\nTry a different prompt!", parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Imagine error: {e}")
        await status_msg.edit_text(f"❌ <b>Error:</b> {str(e)}", parse_mode="HTML")

@dp.message(Command("meme"))
async def cmd_meme(message: Message):
    template = random.choice(MEME_TEMPLATES)
    await message.reply(
        f"{get_emotion('funny')} <b>{template['emoji']} Random Meme</b>\n\n"
        f"<i>\"{template['text']}\"</i>\n\n"
        f"Relatable? 😂",
        parse_mode="HTML"
    )

@dp.message(Command("joke"))
async def cmd_joke(message: Message):
    await message.reply(f"{get_emotion('funny')} <b>Random Joke</b>\n\n{random.choice(JOKES)}")

@dp.message(Command("fact"))
async def cmd_fact(message: Message):
    await message.reply(f"{get_emotion('thinking')} <b>Did You Know?</b>\n\n{random.choice(DAILY_FACTS)}")

@dp.message(Command("roast"))
async def cmd_roast(message: Message):
    if message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
        roast = random.choice(ROAST_RESPONSES)
        await message.reply(
            f"{get_emotion('sassy')} <b>Roasting {target}</b> 🔥\n\n"
            f"<i>{roast}</i>\n\n"
            f"<b>Burn level:</b> {'🔥' * random.randint(3, 5)}",
            parse_mode="HTML"
        )
    else:
        await message.reply(
            f"{get_emotion('sassy')} <b>Self-Roast Mode</b> 😂\n\n"
            f"<i>{random.choice(ROAST_RESPONSES)}</i>\n\n"
            f"Reply to someone's message to roast them specifically!",
            parse_mode="HTML"
        )

@dp.message(Command("horoscope"))
async def cmd_horoscope(message: Message, command: CommandObject):
    signs = {
        "aries": "♈", "taurus": "♉", "gemini": "♊", "cancer": "♋",
        "leo": "♌", "virgo": "♍", "libra": "♎", "scorpio": "♏",
        "sagittarius": "♐", "capricorn": "♑", "aquarius": "♒", "pisces": "♓"
    }
    
    if not command.args:
        # Show buttons
        kb = []
        row = []
        for sign, emoji in list(signs.items())[:6]:
            row.append(InlineKeyboardButton(f"{emoji} {sign.title()}", callback_data=f"horo_{sign}"))
        kb.append(row)
        row = []
        for sign, emoji in list(signs.items())[6:]:
            row.append(InlineKeyboardButton(f"{emoji} {sign.title()}", callback_data=f"horo_{sign}"))
        kb.append(row)
        
        await message.reply(
            f"{get_emotion('love')} <b>Choose Your Zodiac Sign</b> ♈\n\n"
            f"Or use: <code>/horoscope [sign]</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
        return
    
    sign = command.args.lower()
    if sign not in signs:
        await message.reply("❌ Invalid sign! Use: aries, taurus, gemini, etc.")
        return
    
    horoscopes = {
        "aries": "Energy and passion fill your day! Take charge of new projects. 💪",
        "taurus": "Financial opportunities await. Stay grounded and practical. 💰",
        "gemini": "Communication is key today. Express yourself clearly. 💬",
        "cancer": "Focus on home and family. Emotional connections deepen. 🏠",
        "leo": "Your charisma shines! Leadership opportunities arise. 👑",
        "virgo": "Attention to detail pays off. Organization brings success. 📋",
        "libra": "Balance is essential. Harmony in relationships matters. ⚖️",
        "scorpio": "Intuition guides you. Trust your instincts today. 🔮",
        "sagittarius": "Adventure calls! Explore new horizons and ideas. 🌍",
        "capricorn": "Hard work yields results. Stay disciplined and focused. 🏔️",
        "aquarius": "Innovation flows. Think outside the box today. 💡",
        "pisces": "Creativity blooms. Express your artistic side freely. 🎨"
    }
    
    await message.reply(
        f"{get_emotion('love')} {signs[sign]} <b>{sign.title()} Horoscope</b>\n\n"
        f"<i>{horoscopes[sign]}</i>\n\n"
        f"✨ Stars are aligned for you today!",
        parse_mode="HTML"
    )

# ========== UTILITY COMMANDS ==========

@dp.message(Command("weather"))
async def cmd_weather(message: Message, command: CommandObject):
    if not command.args:
        cities = "Mumbai, Delhi, Bangalore, Kolkata, Chennai, Hyderabad, Pune, Ahmedabad, Jaipur, Lucknow"
        await message.reply(
            f"{get_emotion('thinking')} <b>Weather Command</b>\n\n"
            f"Usage: <code>/weather [city]</code>\n\n"
            f"<b>Popular Indian cities:</b>\n{cities}\n\n"
            f"<i>Or any city worldwide!</i> 🌍",
            parse_mode="HTML"
        )
        return
    
    await bot.send_chat_action(message.chat.id, "typing")
    weather = await get_weather(command.args)
    await message.reply(weather, parse_mode="Markdown")

@dp.message(Command("time"))
async def cmd_time(message: Message):
    now = get_indian_time()
    hour = now.hour
    
    if 5 <= hour < 12:
        greeting = "Good Morning! 🌅"
    elif 12 <= hour < 17:
        greeting = "Good Afternoon! ☀️"
    elif 17 <= hour < 21:
        greeting = "Good Evening! 🌇"
    else:
        greeting = "Good Night! 🌙"
    
    await message.reply(
        f"🕐 <b>Indian Standard Time (IST)</b>\n"
        f"━━〘 ⏰ 〙━━\n"
        f"<b>Time:</b> {now.strftime('%I:%M %p')}\n"
        f"<b>Date:</b> {now.strftime('%A, %d %B %Y')}\n"
        f"<b>Zone:</b> UTC+5:30 🇮🇳\n\n"
        f"{greeting}",
        parse_mode="HTML"
    )

@dp.message(Command("date"))
async def cmd_date(message: Message):
    now = get_indian_time()
    await message.reply(
        f"📅 <b>Today's Date</b>\n\n"
        f"{now.strftime('%A, %d %B %Y')}\n"
        f"Day {now.timetuple().tm_yday} of 365\n\n"
        f"{get_emotion('happy')} Have a great day!",
        parse_mode="HTML"
    )

@dp.message(Command("qr"))
async def cmd_qr(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            "📱 <b>QR Code Generator</b>\n\n"
            "Usage: <code>/qr [text or URL]</code>\n\n"
            "Examples:\n"
            "• <code>/qr https://t.me/abhi0w0</code>\n"
            "• <code>/qr My WiFi: abhi123</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        qr_bytes = generate_qr(command.args)
        await message.reply_photo(
            BufferedInputFile(qr_bytes, filename="qr.png"),
            caption=(
                f"📱 <b>QR Code Generated</b>\n\n"
                f"Data: <code>{command.args[:100]}{'...' if len(command.args) > 100 else ''}</code>\n\n"
                f"Scan karo! 📲"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("password"))
async def cmd_password(message: Message, command: CommandObject):
    try:
        length = int(command.args) if command.args else 12
        if length < 4 or length > 50:
            await message.reply("❌ Length must be between 4 and 50!")
            return
        
        pwd = generate_password(length)
        await message.reply(
            f"🔐 <b>Secure Password Generated</b>\n\n"
            f"<code>{pwd}</code>\n\n"
            f"📊 Length: {length} characters\n"
            f"🔒 Contains: Upper, Lower, Numbers, Symbols\n\n"
            f"<i>Copy and store safely! 🤫</i>",
            parse_mode="HTML"
        )
    except ValueError:
        await message.reply("❌ Usage: <code>/password [length]</code>\nExample: <code>/password 16</code>", parse_mode="HTML")

@dp.message(Command("short"))
async def cmd_short(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            "🔗 <b>URL Shortener</b>\n\n"
            "Usage: <code>/short [long URL]</code>\n\n"
            "Powered by TinyURL",
            parse_mode="HTML"
        )
        return
    
    url = command.args.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    status = await message.reply("🔗 <b>Shortening URL...</b>")
    
    try:
        short = await shorten_url(url)
        await status.edit_text(
            f"✅ <b>URL Shortened!</b>\n\n"
            f"🔗 <b>Short:</b> {short}\n"
            f"📝 <b>Original:</b> <code>{url[:50]}{'...' if len(url) > 50 else ''}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        await status.edit_text(f"❌ Error: {str(e)}")

@dp.message(Command("calc"))
async def cmd_calc(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            "🧮 <b>Calculator</b>\n\n"
            "Usage: <code>/calc [expression]</code>\n\n"
            "Examples:\n"
            "• <code>/calc 2 + 2</code>\n"
            "• <code>/calc (5 * 10) / 2</code>\n"
            "• <code>/calc 2 ** 8</code> (power)\n"
            "• <code>/calc sqrt(16)</code> (square root)",
            parse_mode="HTML"
        )
        return
    
    expr = command.args
    
    # Security check
    allowed = set('0123456789+-*/.() **sqrt ')
    if not all(c in allowed for c in expr):
        await message.reply("❌ Invalid characters! Only numbers and + - * / allowed.")
        return
    
    try:
        safe_expr = expr.replace('sqrt', '(__import__("math").sqrt)')
        result = eval(safe_expr, {"__builtins__": {}}, {"math": __import__('math')})
        
        await message.reply(
            f"🧮 <b>Calculator</b>\n\n"
            f"Expression: <code>{expr}</code>\n"
            f"Result: <b>{result}</b>\n\n"
            f"✅ Calculated by Alita",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Invalid expression! Error: {str(e)}")

@dp.message(Command("translate"))
async def cmd_translate(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            "🌍 <b>Translator</b>\n\n"
            "Usage: <code>/translate [language_code] [text]</code>\n\n"
            "Examples:\n"
            "• <code>/translate hi Hello, how are you?</code> (Hindi)\n"
            "• <code>/translate es I love this bot</code> (Spanish)\n"
            "• <code>/translate fr Good morning</code> (French)\n\n"
            "Codes: hi, es, fr, de, ja, ko, ru, ar, etc.",
            parse_mode="HTML"
        )
        return
    
    args = command.args.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Please provide both language code and text!")
        return
    
    target_lang, text = args[0], args[1]
    
    status = await message.reply("🌍 <b>Translating...</b>")
    
    try:
        translated = await translate_text(text, target_lang)
        await status.edit_text(
            f"✅ <b>Translation</b>\n\n"
            f"📝 <b>Original:</b> {text}\n"
            f"🔀 <b>Translated ({target_lang.upper()}):</b>\n<i>{translated}</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await status.edit_text(f"❌ Translation failed: {str(e)}")

# ========== PERSONAL COMMANDS ==========

@dp.message(Command("note"))
async def cmd_note(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            "📝 <b>Note Taker</b>\n\n"
            "Usage: <code>/note [your note]</code>\n\n"
            "Example: <code>/note Buy milk tomorrow</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        cursor.execute(
            "INSERT INTO notes (user_id, note_text) VALUES (?, ?)",
            (message.from_user.id, command.args)
        )
        conn.commit()
        
        # Update in-memory
        user_notes[message.from_user.id].append({
            "text": command.args,
            "time": datetime.now()
        })
        
        await message.reply(
            f"{get_emotion('happy')} <b>Note Saved!</b> 📝\n\n"
            f"<i>{command.args[:100]}{'...' if len(command.args) > 100 else ''}</i>\n\n"
            f"View all: <code>/notes</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Error saving note: {str(e)}")

@dp.message(Command("notes"))
async def cmd_notes(message: Message):
    try:
        cursor.execute(
            "SELECT note_text, created_at FROM notes WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (message.from_user.id,)
        )
        notes = cursor.fetchall()
        
        if not notes:
            await message.reply(
                f"{get_emotion('crying')} <b>No notes found!</b>\n\n"
                f"Save your first note with <code>/note [text]</code>",
                parse_mode="HTML"
            )
            return
        
        text = f"📝 <b>Your Notes</b> ({len(notes)} total)\n\n"
        for i, (note, created) in enumerate(notes, 1):
            time_str = datetime.fromisoformat(created).strftime('%d/%m %H:%M')
            text += f"{i}. {note[:50]}{'...' if len(note) > 50 else ''} <i>({time_str})</i>\n\n"
        
        await message.reply(text, parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("afk"))
async def cmd_afk(message: Message, command: CommandObject):
    reason = command.args or "Busy"
    
    afk_users[message.from_user.id] = {
        "reason": reason,
        "since": datetime.now()
    }
    
    await message.reply(
        f"😴 <b>AFK Mode Activated</b>\n\n"
        f"💤 <b>Reason:</b> {reason}\n"
        f"⏰ <b>Since:</b> {datetime.now().strftime('%I:%M %p')}\n\n"
        f"<i>I'll notify others when they mention you!</i>",
        parse_mode="HTML"
    )

@dp.message(Command("id"))
async def cmd_id(message: Message):
    user = message.from_user
    
    text = (
        f"👤 <b>Your Information</b>\n"
        f"━━〘 🆔 〙━━\n\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n"
        f"<b>Name:</b> {user.full_name}\n"
        f"<b>Username:</b> @{user.username or 'N/A'}\n"
        f"<b>Language:</b> {user.language_code or 'N/A'}\n"
        f"<b>Premium:</b> {'Yes ⭐' if user.is_premium else 'No'}\n\n"
        f"<b>Chat ID:</b> <code>{message.chat.id}</code>\n"
        f"<b>Chat Type:</b> {message.chat.type}"
    )
    
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        text += (
            f"\n\n👤 <b>Replied User</b>\n"
            f"<b>User ID:</b> <code>{target.id}</code>\n"
            f"<b>Name:</b> {target.full_name}\n"
            f"<b>Username:</b> @{target.username or 'N/A'}"
        )
    
    await message.reply(text, parse_mode="HTML")

@dp.message(Command("info"))
async def cmd_info(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    
    try:
        # Get chat member info if in group
        member_info = ""
        if message.chat.type in ["group", "supergroup"]:
            member = await bot.get_chat_member(message.chat.id, target.id)
            status = {
                "creator": "👑 Creator",
                "administrator": "🛡️ Admin",
                "member": "👤 Member",
                "restricted": "⚠️ Restricted",
                "left": "🚪 Left",
                "kicked": "🚫 Banned"
            }.get(member.status, "❓ Unknown")
            member_info = f"\n<b>Status:</b> {status}"
        
        await message.reply(
            f"👤 <b>User Information</b>\n"
            f"━━〘 📋 〙━━\n\n"
            f"<b>ID:</b> <code>{target.id}</code>\n"
            f"<b>Name:</b> {target.full_name}\n"
            f"<b>Username:</b> @{target.username or 'N/A'}\n"
            f"<b>Premium:</b> {'⭐ Yes' if target.is_premium else 'No'}"
            f"{member_info}\n\n"
            f"<i>Requested by {message.from_user.first_name}</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

# ========== MUSIC COMMANDS ==========

@dp.message(Command("lyrics"))
async def cmd_lyrics(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            "🎵 <b>Lyrics Finder</b>\n\n"
            "Usage: <code>/lyrics [song name]</code>\n\n"
            "Examples:\n"
            "• <code>/lyrics Shape of You</code>\n"
            "• <code>/lyrics Tujhe Kitna Chahne Lage</code>\n"
            "• <code>/lyrics Despacito</code>",
            parse_mode="HTML"
        )
        return
    
    status = await message.reply(f"{get_emotion('happy')} 🔍 <b>Searching lyrics...</b>")
    
    try:
        lyrics = await get_lyrics(command.args)
        
        # Truncate if too long
        if len(lyrics) > 4000:
            lyrics = lyrics[:4000] + "\n\n... (truncated)"
        
        await status.edit_text(
            f"🎵 <b>Lyrics: {command.args}</b>\n"
            f"━━〘 🎶 〙━━\n\n"
            f"<pre>{lyrics}</pre>\n\n"
            f"<i>Powered by lyrics.ovh</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await status.edit_text(f"❌ <b>Error:</b> {str(e)}")

@dp.message(Command("song"))
async def cmd_song(message: Message, command: CommandObject):
    await message.reply(
        f"{get_emotion('thinking')} <b>Song Search</b>\n\n"
        f"🎧 Feature coming soon!\n"
        f"For now, use <code>/lyrics [song name]</code> to get lyrics!",
        parse_mode="HTML"
    )
# ========== ADMIN COMMANDS ==========

@dp.message(Command("adminlist"))
async def cmd_adminlist(message: Message):
    if message.chat.type == "private":
        await message.reply("❌ This command works in groups only!")
        return
    
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        
        text = f"{get_emotion('protective')} <b>Group Administrators</b> 👑\n\n"
        
        for admin in admins:
            user = admin.user
            emoji = "👑" if admin.status == "creator" else "🛡️"
            name = f"{user.first_name} {user.last_name or ''}".strip()
            username = f"@{user.username}" if user.username else "No username"
            text += f"{emoji} <b>{name}</b>\n   ├ <code>{user.id}</code>\n   └ {username}\n\n"
        
        await message.reply(text, parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules = (
        f"{get_emotion('protective')} <b>📜 GROUP RULES</b> 🛡️\n\n"
        f"<b>✅ DO's:</b>\n"
        f"• Be respectful to everyone 🤝\n"
        f"• Keep chat friendly and positive 🌟\n"
        f"• Help each other grow 📚\n"
        f"• Follow admin instructions 👮\n"
        f"• Have fun and enjoy! 🎉\n\n"
        f"<b>🚫 DON'Ts:</b>\n"
        f"• No spam or flooding ⚠️\n"
        f"• No group links sharing 🔗\n"
        f"• No bad language 🚫\n"
        f"• No personal fights ⚔️\n"
        f"• No adult/NSFW content 🚷 (Auto-ban!)\n"
        f"• No self-promotion without permission 📢\n"
        f"• No fake/suspicious links 🚫\n\n"
        f"<b>⚡ Auto-Moderation:</b>\n"
        f"• 3 Warnings = Auto-mute 🔇\n"
        f"• Adult content = Instant ban 🚫\n"
        f"• Spam = Warning + Delete ⚠️\n\n"
        f"{get_emotion('love')} <i>I'm here to keep everyone safe!</i> 💪"
    )
    await message.reply(rules, parse_mode="HTML")

@dp.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only command!</b>")
        return
    
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a user to warn them!")
        return
    
    target = message.reply_to_message.from_user
    reason = command.args or "Rule violation"
    
    # Add to database
    cursor.execute(
        "INSERT INTO warnings (chat_id, user_id, reason, warned_by) VALUES (?, ?, ?, ?)",
        (message.chat.id, target.id, reason, message.from_user.id)
    )
    conn.commit()
    
    # Get count
    cursor.execute(
        "SELECT COUNT(*) FROM warnings WHERE chat_id = ? AND user_id = ?",
        (message.chat.id, target.id)
    )
    count = cursor.fetchone()[0]
    limit = group_settings[message.chat.id].get("warn_limit", 3)
    
    # Check if should mute
    if count >= limit:
        try:
            until = datetime.now() + timedelta(hours=24)
            await bot.restrict_chat_member(
                message.chat.id, target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            
            # Clear warnings
            cursor.execute(
                "DELETE FROM warnings WHERE chat_id = ? AND user_id = ?",
                (message.chat.id, target.id)
            )
            conn.commit()
            
            await message.reply(
                f"🚫 <b>User Muted!</b>\n\n"
                f"👤 <b>{target.first_name}</b>\n"
                f"⚠️ Warnings: {count}/{limit}\n"
                f"⏰ Duration: 24 hours\n"
                f"🔇 Reason: Too many warnings!",
                parse_mode="HTML"
            )
        except Exception as e:
            await message.reply(f"❌ Failed to mute: {str(e)}")
    else:
        await message.reply(
            f"⚠️ <b>Warning Issued!</b>\n\n"
            f"👤 <b>{target.first_name}</b>\n"
            f"📝 Reason: {reason}\n"
            f"📊 Count: {count}/{limit}\n\n"
            f"<i>{limit - count} more = 24h mute!</i>",
            parse_mode="HTML"
        )

@dp.message(Command("kick"))
async def cmd_kick(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a user to kick them!")
        return
    
    target = message.reply_to_message.from_user
    
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id)
        
        await message.reply(
            f"👢 <b>Kicked!</b>\n\n"
            f"👤 {target.first_name}\n"
            f"🆔 <code>{target.id}</code>\n\n"
            f"<i>They can rejoin using the invite link.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Failed to kick: {str(e)}")

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a user to ban them!")
        return
    
    target = message.reply_to_message.from_user
    
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        
        await message.reply(
            f"🚫 <b>Banned Permanently!</b>\n\n"
            f"👤 {target.first_name}\n"
            f"🆔 <code>{target.id}</code>\n\n"
            f"<i>Use /unban to remove the ban.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Failed to ban: {str(e)}")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a user's message to unban them!")
        return
    
    target = message.reply_to_message.from_user
    
    try:
        await bot.unban_chat_member(message.chat.id, target.id)
        
        await message.reply(
            f"✅ <b>Unbanned!</b>\n\n"
            f"👤 {target.first_name}\n"
            f"🆔 <code>{target.id}</code>\n\n"
            f"<i>They can now rejoin the group.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Failed to unban: {str(e)}")

@dp.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a user to mute them!")
        return
    
    target = message.reply_to_message.from_user
    
    # Parse duration
    duration_str = command.args or "1h"
    try:
        if duration_str.endswith('h'):
            hours = int(duration_str[:-1])
            until = datetime.now() + timedelta(hours=hours)
            duration_text = f"{hours} hour(s)"
        elif duration_str.endswith('m'):
            minutes = int(duration_str[:-1])
            until = datetime.now() + timedelta(minutes=minutes)
            duration_text = f"{minutes} minute(s)"
        elif duration_str.endswith('d'):
            days = int(duration_str[:-1])
            until = datetime.now() + timedelta(days=days)
            duration_text = f"{days} day(s)"
        else:
            until = datetime.now() + timedelta(hours=1)
            duration_text = "1 hour"
    except:
        until = datetime.now() + timedelta(hours=1)
        duration_text = "1 hour"
    
    try:
        await bot.restrict_chat_member(
            message.chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        
        await message.reply(
            f"🔇 <b>Muted!</b>\n\n"
            f"👤 {target.first_name}\n"
            f"⏰ Duration: {duration_text}\n"
            f"🔒 Cannot send messages until unmuted",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Failed to mute: {str(e)}")

@dp.message(Command("unmute"))
async def cmd_unmute(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a user to unmute them!")
        return
    
    target = message.reply_to_message.from_user
    
    try:
        await bot.restrict_chat_member(
            message.chat.id, target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_invite_users=True
            )
        )
        
        await message.reply(
            f"🔊 <b>Unmuted!</b>\n\n"
            f"👤 {target.first_name}\n"
            f"✅ Can speak again!",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Failed to unmute: {str(e)}")

@dp.message(Command("purge"))
async def cmd_purge(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to the oldest message you want to delete!")
        return
    
    try:
        count = int(command.args) if command.args else 10
        count = min(max(count, 1), 100)  # Between 1 and 100
        
        message_ids = []
        async for msg in bot.get_chat_history(message.chat.id, limit=count):
            if msg.message_id >= message.reply_to_message.message_id:
                message_ids.append(msg.message_id)
        
        if message_ids:
            # Delete in batches of 100
            for i in range(0, len(message_ids), 100):
                batch = message_ids[i:i+100]
                await bot.delete_messages(message.chat.id, batch)
            
            await message.reply(
                f"🗑️ <b>Purged!</b>\n\n"
                f"Deleted {len(message_ids)} messages!",
                parse_mode="HTML"
            )
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("pin"))
async def cmd_pin(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a message to pin it!")
        return
    
    try:
        await bot.pin_chat_message(
            message.chat.id,
            message.reply_to_message.message_id,
            disable_notification=False
        )
        await message.reply("📌 <b>Pinned!</b>")
    except Exception as e:
        await message.reply(f"❌ Failed to pin: {str(e)}")

@dp.message(Command("unpin"))
async def cmd_unpin(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    try:
        await bot.unpin_chat_message(message.chat.id)
        await message.reply("📍 <b>Unpinned!</b>")
    except Exception as e:
        await message.reply(f"❌ Failed to unpin: {str(e)}")

@dp.message(Command("slowmode"))
async def cmd_slowmode(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    try:
        delay = int(command.args) if command.args else 0
        delay = max(0, min(delay, 86400))  # 0 to 24 hours
        
        await bot.set_chat_slow_mode_delay(message.chat.id, delay)
        
        if delay == 0:
            await message.reply("🚀 <b>Slow mode disabled!</b>\nUsers can send messages freely.")
        else:
            await message.reply(
                f"⏱️ <b>Slow mode enabled!</b>\n\n"
                f"Users can send 1 message every {delay} seconds.",
                parse_mode="HTML"
            )
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("lock"))
async def cmd_lock(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    try:
        await bot.set_chat_permissions(
            message.chat.id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        
        await message.reply(
            "🔒 <b>Chat Locked!</b>\n\n"
            "Only admins can send messages now.\n"
            "Use /unlock to allow everyone.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("unlock"))
async def cmd_unlock(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
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
                can_invite_users=True
            )
        )
        
        await message.reply(
            "🔓 <b>Chat Unlocked!</b>\n\n"
            "Everyone can send messages now! 🎉",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("setwelcome"))
async def cmd_setwelcome(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if not command.args:
        await message.reply(
            "👋 <b>Set Custom Welcome</b>\n\n"
            "Usage: <code>/setwelcome [message]</code>\n\n"
            "Variables:\n"
            "• <code>{name}</code> - User's first name\n"
            "• <code>{username}</code> - Username\n"
            "• <code>{chat}</code> - Group name\n\n"
            "Example:\n"
            "<code>/setwelcome Welcome {name} to {chat}! Enjoy! 🎉</code>",
            parse_mode="HTML"
        )
        return
    
    group_settings[message.chat.id]["custom_welcome"] = command.args
    await message.reply(
        "✅ <b>Custom welcome message set!</b>\n\n"
        f"Preview:\n<i>{command.args}</i>",
        parse_mode="HTML"
    )

@dp.message(Command("setgoodbye"))
async def cmd_setgoodbye(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if not command.args:
        await message.reply(
            "👋 <b>Set Custom Goodbye</b>\n\n"
            "Usage: <code>/setgoodbye [message]</code>\n\n"
            "Variables: <code>{name}</code>, <code>{username}</code>\n\n"
            "Example:\n"
            "<code>/setgoodbye Goodbye {name}! We'll miss you! 👋</code>",
            parse_mode="HTML"
        )
        return
    
    group_settings[message.chat.id]["custom_goodbye"] = command.args
    await message.reply(
        "✅ <b>Custom goodbye message set!</b>\n\n"
        f"Preview:\n<i>{command.args}</i>",
        parse_mode="HTML"
    )

@dp.message(Command("tagall"))
async def cmd_tagall(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    
    if message.chat.type == "private":
        await message.reply("❌ Works in groups only!")
        return
    
    try:
        # Get members
        members = []
        async for member in bot.get_chat_members(message.chat.id):
            if not member.user.is_bot and member.user.id != bot.id:
                if member.user.username:
                    members.append(f"@{member.user.username}")
                else:
                    members.append(f"[{member.user.first_name}](tg://user?id={member.user.id})")
        
        if not members:
            await message.reply("No members found!")
            return
        
        # Send in batches of 5
        await message.reply(f"📢 <b>Tagging {len(members)} members...</b>")
        
        for i in range(0, len(members), 5):
            batch = members[i:i+5]
            await message.reply(" ".join(batch), parse_mode="Markdown")
            await asyncio.sleep(1)
            
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")
# ========== OWNER COMMANDS ==========

@dp.message(Command("sendall"))
async def cmd_sendall(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ <b>Owner only command!</b>")
        return
    
    if not message.reply_to_message:
        await message.reply("📢 Reply to a message to broadcast it!")
        return
    
    status = await message.reply("📤 <b>Broadcasting...</b>")
    
    # Get all users
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    
    # Get all groups
    cursor.execute("SELECT chat_id FROM groups")
    groups = cursor.fetchall()
    
    sent = 0
    failed = 0
    
    # Broadcast to users
    for (user_id,) in users:
        try:
            await bot.copy_message(
                user_id,
                message.chat.id,
                message.reply_to_message.message_id
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.error(f"Broadcast to user {user_id} failed: {e}")
    
    # Broadcast to groups
    for (chat_id,) in groups:
        try:
            await bot.copy_message(
                chat_id,
                message.chat.id,
                message.reply_to_message.message_id
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.error(f"Broadcast to group {chat_id} failed: {e}")
    
    await status.edit_text(
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"📤 Sent: {sent}\n"
        f"❌ Failed: {failed}\n"
        f"📊 Total: {sent + failed}",
        parse_mode="HTML"
    )

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ <b>Owner only!</b>")
        return
    
    if not command.args:
        await message.reply("Usage: /broadcast [message]")
        return
    
    status = await message.reply("📤 Broadcasting message...")
    
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    
    sent = 0
    failed = 0
    
    for (user_id,) in users:
        try:
            await bot.send_message(user_id, command.args, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await status.edit_text(f"✅ Broadcast: {sent} sent, {failed} failed")

@dp.message(Command("savesticker"))
async def cmd_savesticker(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ <b>Owner only!</b>")
        return
    
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply("⚠️ Reply to a sticker to save it!")
        return
    
    sticker = message.reply_to_message.sticker
    file_id = sticker.file_id
    
    if file_id in saved_stickers:
        await message.reply("ℹ️ Sticker already saved!")
        return
    
    try:
        cursor.execute(
            "INSERT INTO stickers (file_id, added_by) VALUES (?, ?)",
            (file_id, message.from_user.id)
        )
        conn.commit()
        saved_stickers.append(file_id)
        
        await message.reply(
            f"✅ <b>Sticker Saved!</b>\n\n"
            f"🎭 Total stickers: {len(saved_stickers)}\n"
            f"🆔 File ID: <code>{file_id[:30]}...</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("stickerstatus"))
async def cmd_stickerstatus(message: Message):
    total = len(saved_stickers)
    
    if total == 0:
        await message.reply(
            f"{get_emotion('crying')} <b>No stickers saved yet!</b>\n\n"
            f"Owner can save with <code>/savesticker</code> (reply to sticker)",
            parse_mode="HTML"
        )
        return
    
    cursor.execute("SELECT COUNT(*) FROM stickers WHERE date(added_at) = date('now')")
    today = cursor.fetchone()[0]
    
    await message.reply(
        f"📊 <b>Sticker Database</b>\n\n"
        f"🎯 Total: {total}\n"
        f"📅 Today: {today}\n"
        f"👑 Owner: @a6h1ii\n\n"
        f"<i>Auto-sends randomly in chats!</i>",
        parse_mode="HTML"
    )

# ========== CALLBACK HANDLERS ==========

@dp.callback_query(F.data == "show_help")
async def cb_show_help(callback: CallbackQuery):
    await cmd_help(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "gen_image")
async def cb_gen_image(callback: CallbackQuery):
    await callback.message.answer(
        "🎨 <b>Image Generation</b>\n\n"
        "Use: <code>/imagine [description]</code>\n\n"
        "Example: <code>/imagine sunset over mountains</code>",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("horo_"))
async def cb_horoscope(callback: CallbackQuery):
    sign = callback.data.split("_")[1]
    await cmd_horoscope(callback.message, type('obj', (object,), {'args': sign})())
    await callback.answer()

# ========== CHAT EVENTS ==========

@dp.chat_member()
async def handle_chat_member(update: ChatMemberUpdated):
    """Handle join/leave events"""
    if not update.new_chat_member:
        return
    
    chat_id = update.chat.id
    new_member = update.new_chat_member
    
    # Save group to DB
    if update.chat.type in ["group", "supergroup"]:
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO groups (chat_id, title, type) VALUES (?, ?, ?)",
                (chat_id, update.chat.title, update.chat.type)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Group save error: {e}")
    
    # Member joined
    if new_member.status == "member":
        user = new_member.user
        
        # Get welcome message
        custom = group_settings[chat_id].get("custom_welcome")
        if custom:
            text = custom.replace("{name}", user.first_name).replace("{username}", user.username or "").replace("{chat}", update.chat.title or "Group")
        else:
            text = random.choice(WELCOME_MESSAGES).format(name=user.first_name)
        
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Welcome error: {e}")
    
    # Member left/kicked/banned
    elif new_member.status in ["left", "kicked", "banned"]:
        user = new_member.user
        
        custom = group_settings[chat_id].get("custom_goodbye")
        if custom:
            text = custom.replace("{name}", user.first_name).replace("{username}", user.username or "")
        else:
            text = random.choice(GOODBYE_MESSAGES).format(name=user.first_name)
        
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Goodbye error: {e}")

# ========== MAIN MESSAGE HANDLER ==========

@dp.message()
async def handle_all_messages(message: Message):
    """Main message handler - responds in private and groups (mention/reply)"""
    if not message.from_user or not message.text:
        # Handle stickers/photos in groups
        if message.chat.type in ["group", "supergroup"]:
            if message.sticker and saved_stickers and random.random() < 0.1:
                try:
                    await bot.send_sticker(message.chat.id, random.choice(saved_stickers))
                except:
                    pass
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text
    
    # Save user
    started_users.add(user_id)
    
    # Check AFK and notify
    if user_id in afk_users:
        del afk_users[user_id]
        await message.reply(f"👋 Welcome back {message.from_user.first_name}! AFK removed!", parse_mode="HTML")
        return
    
    # Check if someone mentioned AFK user
    for uid, data in list(afk_users.items()):
        if f"[{uid}]" in text or f"@{uid}" in text:
            try:
                since = data['since'].strftime('%I:%M %p')
                await message.reply(
                    f"😴 <b>{data['name']}</b> is AFK!\n"
                    f"💤 Reason: {data['reason']}\n"
                    f"⏰ Since: {since}",
                    parse_mode="HTML"
                )
            except:
                pass
    
    # Auto-moderation for groups
    if message.chat.type in ["group", "supergroup"]:
        # Adult content - instant ban
        if contains_adult_content(text):
            try:
                await message.delete()
                await bot.ban_chat_member(chat_id, user_id)
                await message.answer(
                    f"🚫 <b>{message.from_user.first_name}</b> banned for adult content!",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ban error: {e}")
            return
        
        # Bad words
        if contains_bad_words(text):
            try:
                await message.delete()
                await message.answer(f"⚠️ {message.from_user.first_name}, watch your language!", parse_mode="HTML")
            except:
                pass
            return
        
        # Group links
        if contains_group_link(text):
            try:
                await message.delete()
                await message.answer(f"🔗 Links not allowed, {message.from_user.first_name}!", parse_mode="HTML")
            except:
                pass
            return
        
        # Spam check
        if await check_spam(message):
            try:
                await message.delete()
                await message.answer(f"⚠️ {message.from_user.first_name}, stop spamming!", parse_mode="HTML")
            except:
                pass
            return
    
    # Determine if should respond
    try:
        me = await bot.get_me()
        bot_username = me.username.lower()
        
        is_private = message.chat.type == "private"
        is_mention = f"@{bot_username}" in text.lower()
        is_reply = message.reply_to_message and message.reply_to_message.from_user.id == me.id
        
        should_respond = is_private or is_mention or is_reply
        
        if should_respond:
            # Clean text
            clean_text = text.replace(f"@{bot_username}", "").strip()
            
            # Show typing
            await bot.send_chat_action(chat_id, "typing")
            
            # Small delay for realism
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # Get AI response
            response = await get_ai_response(chat_id, clean_text, user_id)
            
            # Send reply
            await message.reply(response)
            
    except Exception as e:
        logger.error(f"Message handler error: {e}")
# ========== WEB SERVER & SCHEDULED TASKS ==========

async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(
        text="✅ Alita Bot is Running! 🎀\n\nStatus: Online\nVersion: 2.0\nDeveloper: @a6h1ii",
        content_type="text/plain"
    )

async def start_web_server():
    """Start aiohttp web server"""
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web server started on port {PORT}")

# Scheduled tasks
async def send_time_greetings():
    """Send scheduled greetings"""
    period = get_current_time_period()
    if period not in TIME_GREETINGS:
        return
    
    greeting = random.choice(TIME_GREETINGS[period]["templates"])
    
    # Send to groups
    cursor.execute("SELECT chat_id FROM groups")
    groups = cursor.fetchall()
    for (chat_id,) in groups:
        try:
            if group_settings[chat_id].get("greetings_enabled", True):
                await bot.send_message(chat_id, greeting, parse_mode="Markdown")
                await asyncio.sleep(0.5)
        except:
            pass
    
    # Send to active users
    for user_id in list(started_users):
        try:
            await bot.send_message(user_id, greeting, parse_mode="Markdown")
            await asyncio.sleep(0.5)
        except:
            pass

async def send_random_stickers():
    """Send random stickers to active chats"""
    if not saved_stickers:
        return
    
    # To groups
    cursor.execute("SELECT chat_id FROM groups")
    groups = cursor.fetchall()
    for (chat_id,) in groups:
        if random.random() < 0.15:  # 15% chance
            try:
                await bot.send_sticker(chat_id, random.choice(saved_stickers))
                await asyncio.sleep(1)
            except:
                pass
    
    # To users
    for user_id in list(started_users):
        if random.random() < 0.1:  # 10% chance
            try:
                await bot.send_sticker(user_id, random.choice(saved_stickers))
                await asyncio.sleep(1)
            except:
                pass

async def daily_reminders():
    """Send daily reminders"""
    reminders = [
        "🌅 Good morning! Have a productive day! 💪",
        "💧 Don't forget to drink water! Stay hydrated! 🥤",
        "🌟 You're amazing! Keep going! ✨",
        "😊 Smile! It looks good on you! 💕"
    ]
    
    for user_id in list(started_users):
        try:
            await bot.send_message(user_id, random.choice(reminders))
            await asyncio.sleep(0.5)
        except:
            pass

def setup_scheduler():
    """Setup scheduled jobs"""
    # Time-based greetings every 6 hours
    scheduler.add_job(send_time_greetings, 'interval', hours=6, id='greetings')
    
    # Random stickers every 4 hours
    scheduler.add_job(send_random_stickers, 'interval', hours=4, id='stickers')
    
    # Daily reminders at 9 AM
    scheduler.add_job(daily_reminders, CronTrigger(hour=9, minute=0, timezone=INDIAN_TIMEZONE), id='daily')
    
    scheduler.start()
    logger.info("⏰ Scheduler started")

# ========== MAIN ==========

async def main():
    """Main function"""
    logger.info("=" * 60)
    logger.info("🎀 ALITA BOT v2.0 - STARTING")
    logger.info("=" * 60)
    
    try:
        # Validate token
        if not TOKEN or TOKEN == "YOUR_BOT_TOKEN":
            logger.error("❌ BOT_TOKEN not set!")
            return
        
        # Start web server for Render
        asyncio.create_task(start_web_server())
        logger.info("✅ Web server started")
        
        # Setup scheduler
        setup_scheduler()
        logger.info("✅ Scheduler started")
        
        # Delete webhook
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook deleted")
        
        # Get bot info
        me = await bot.get_me()
        logger.info(f"🤖 Bot: @{me.username} (ID: {me.id})")
        logger.info(f"👑 Admin ID: {ADMIN_ID}")
        logger.info(f"🎭 Stickers: {len(saved_stickers)}")
        logger.info(f"📊 Database: {DB_PATH}")
        
        # Start polling
        logger.info("🚀 Starting polling...")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        # Keep alive
        while True:
            await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Critical error: {e}")
        import traceback
        traceback.print_exc()
