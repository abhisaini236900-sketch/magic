import os
import sys
import asyncio
import logging
import random
import re
import json
import base64
import io
import hashlib
import string
import sqlite3
import subprocess
import traceback
import platform
import time
import uuid
from contextlib import redirect_stdout, redirect_stderr
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple, Union
from urllib.parse import quote, urlparse
from pathlib import Path
import tempfile
import shutil
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pytz
import aiohttp
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont
import qrcode
import textwrap
import sympy
from sympy import sympify, solve, symbols, simplify, expand, factor, diff, integrate
import feedparser

# -------------------- Optional Imports with Fallback --------------------
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

try:
    from pyzbar.pyzbar import decode
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False

try:
    from yt_dlp import YoutubeDL
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    import pymongo
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False

# -------------------- AI Providers --------------------
try:
    import g4f
    from g4f.client import Client as G4FClient
    from g4f.Provider import (
        Blackbox, DuckDuckGo, DeepInfra, Replicate, PollinationsAI,
        DDG, Liaobots, You, Pizzagpt, ChatGptEs, Airforce
    )
    G4F_AVAILABLE = True
    EXTENDED_PROVIDERS = True
except ImportError:
    G4F_AVAILABLE = False
    EXTENDED_PROVIDERS = False

try:
    from groq import AsyncGroq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

# -------------------- Configuration (Environment) --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
PORT = int(os.getenv("PORT", 8080))

# Mandatory channel for private chat access
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@abhi0w0")
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "")

# Free API endpoints
FREE_GPT_API_URL = "https://free-unoficial-gpt4o-mini-api-g70n.onrender.com/chat/"
ADDY_CHATGPT_API_URL = "https://addy-chatgpt-api.vercel.app/"
GEMINI_API_URL = "https://gemini-api-flame.vercel.app/"

INDIAN_TZ = pytz.timezone('Asia/Kolkata')
BOT_USERNAME = None
bot_start_time = datetime.now(INDIAN_TZ)

# -------------------- Database (MongoDB or SQLite) --------------------
USE_MONGODB = MONGODB_AVAILABLE and MONGODB_URI is not None

if USE_MONGODB:
    try:
        mongo_client = MongoClient(MONGODB_URI)
        # Check if URI already has database name
        if '/' in MONGODB_URI.split('@')[-1]:
            db = mongo_client.get_default_database()
        else:
            db = mongo_client['alita_db']
        # Test connection
        mongo_client.admin.command('ping')
        print("✅ MongoDB connected successfully!")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        print("⚠️ Falling back to SQLite...")
        USE_MONGODB = False

if not USE_MONGODB:
    conn = sqlite3.connect("alita_ultimate.db", detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Create tables if not exist
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        last_active TIMESTAMP
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY,
        title TEXT,
        welcome_enabled INTEGER DEFAULT 1,
        goodbye_enabled INTEGER DEFAULT 1,
        auto_mod_enabled INTEGER DEFAULT 1,
        captcha_enabled INTEGER DEFAULT 0,
        warn_limit INTEGER DEFAULT 3,
        custom_welcome TEXT,
        custom_goodbye TEXT,
        slow_mode_delay INTEGER DEFAULT 0,
        anti_raid_enabled INTEGER DEFAULT 0
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stickers (
        file_id TEXT PRIMARY KEY,
        added_by INTEGER,
        added_at TIMESTAMP,
        emoji TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        note_text TEXT,
        created_at TIMESTAMP
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        chat_id INTEGER,
        reminder_text TEXT,
        remind_at TIMESTAMP,
        created_at TIMESTAMP
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user_id INTEGER,
        reason TEXT,
        warned_at TIMESTAMP,
        count INTEGER DEFAULT 1,
        UNIQUE(chat_id, user_id)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custom_commands (
        chat_id INTEGER,
        cmd TEXT,
        response TEXT,
        created_by INTEGER,
        PRIMARY KEY (chat_id, cmd)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_levels (
        user_id INTEGER,
        chat_id INTEGER,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, chat_id)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_memory (
        user_id INTEGER,
        key TEXT,
        value TEXT,
        updated_at TIMESTAMP,
        PRIMARY KEY (user_id, key)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS game_data (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        balance INTEGER DEFAULT 1000,
        rank INTEGER DEFAULT 142415,
        status TEXT DEFAULT 'alive',
        kills INTEGER DEFAULT 0,
        deaths INTEGER DEFAULT 0,
        last_daily TIMESTAMP,
        last_work TIMESTAMP,
        last_crime TIMESTAMP,
        last_rob TIMESTAMP,
        health INTEGER DEFAULT 100,
        protected INTEGER DEFAULT 0,
        protect_until TIMESTAMP
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS casino (
        user_id INTEGER PRIMARY KEY,
        chips INTEGER DEFAULT 1000,
        last_slots TIMESTAMP,
        last_blackjack TIMESTAMP,
        last_roulette TIMESTAMP,
        last_dice TIMESTAMP
    )""")
    conn.commit()
    print("✅ Using SQLite")

# -------------------- In-Memory Caches --------------------
saved_stickers: List[str] = []
chat_memory: Dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
user_afk: Dict[int, Dict] = {}
user_emotion: Dict[int, str] = {}
user_last_interact: Dict[int, datetime] = {}
captcha_store: Dict[int, Dict] = {}
spam_tracker: Dict[int, Dict[int, List[datetime]]] = defaultdict(lambda: defaultdict(list))
group_admins_cache: Dict[int, Set[int]] = {}
conversation_history: Dict[int, List[Dict]] = defaultdict(list)
user_ai_preference: Dict[int, str] = defaultdict(lambda: "groq")
user_g4f_provider: Dict[int, str] = defaultdict(lambda: "addy_chatgpt")
user_settings: Dict[int, Dict] = defaultdict(lambda: {
    "detailed_responses": True,
    "language": "en",
    "notifications": True
})
user_mood: Dict[int, Dict] = defaultdict(lambda: {"mood": "neutral", "intensity": 5, "history": []})

# Game data for SQLite mode
game_data: Dict[int, Dict] = defaultdict(lambda: {
    "name": "Shinchan", "balance": 1000, "rank": 142415, "status": "alive",
    "kills": 0, "deaths": 0, "last_daily": None, "last_work": None,
    "last_crime": None, "last_rob": None, "health": 100,
    "protected": False, "protect_until": None
})
casino_data: Dict[int, Dict] = defaultdict(lambda: {
    "chips": 1000, "last_slots": None, "last_blackjack": None,
    "last_roulette": None, "last_dice": None
})

GAME_COOLDOWNS = {
    "daily": 86400, "work": 3600, "crime": 1800, "rob": 600,
    "heal": 300, "protect": 86400, "slots": 60, "blackjack": 120,
    "roulette": 60, "dice": 30
}
REVIVE_COST = 500
PROTECT_COST = 500

# -------------------- Constants for Moderation --------------------
BAD_WORDS = [
    "chutiya", "chutiye", "madarchod", "behenchod", "bhosdike", "lodu", "gandu",
    "fuck", "shit", "bitch", "bastard", "asshole", "motherfucker", "cunt", "dick",
    "gaand", "lund", "randi", "bhosdi", "bc", "mc", "gand", "lauda", "choot"
]
ADULT_KEYWORDS = [
    "porn", "xxx", "nsfw", "adult", "sex", "nude", "naked", "boobs", "ass",
    "dick", "pussy", "hentai", "porno", "horny", "fuck", "sexy", "hot", "desi", "chudai"
]
FAKE_LINK_PATTERNS = [
    r'bit\.ly\/[a-zA-Z0-9]+', r'tinyurl\.com\/[a-zA-Z0-9]+', r'goo\.gl\/[a-zA-Z0-9]+',
    r'shorturl\.at\/[a-zA-Z0-9]+', r'ow\.ly\/[a-zA-Z0-9]+', r'is\.gd\/[a-zA-Z0-9]+', r'cli\.gs\/[a-zA-Z0-9]+'
]
GROUP_LINK_PATTERNS = [
    r't\.me\/[a-zA-Z0-9_]+', r'telegram\.me\/[a-zA-Z0-9_]+', r'telegram\.dog\/[a-zA-Z0-9_]+'
]
WARNING_MESSAGES = [
    "⚠️ <b>Warning {count}/3</b> 🚨\n{name}, please don't {action}!",
    "🚨 <b>Strike {count}!</b> ⚠️\n{name}, {action} is not allowed!",
    "⚡ <b>Final Warning ({count}/3)</b> ⚡\n{name}, last chance! Stop {action}!"
]
MUTE_DURATIONS = [5, 60, 1440, 10080]

# -------------------- Gaming Keywords & Reactions --------------------
GAMING_KEYWORDS = {
    "kill_words": ["maar", "maaro", "kill", "marna", "murder", "khatam", "finish", "end him", "end her", "attack"],
    "rob_words": ["rob", "loot", "chori", "steal", "chor", "looto", "paisa lelo", "money le"],
    "work_words": ["kaam", "work", "job", "naukri", "earning", "kamana", "paisa kamao"],
    "daily_words": ["daily", "reward", "claim", "bonus", "free money", "gift"],
    "heal_words": ["heal", "health", "treatment", "dawai", "medicine", "ilaj", "theek"],
    "game_words": ["game", "khel", "profile", "stats", "score", "rank"],
    "balance_words": ["balance", "paisa", "money", "wallet", "bank", "cash", "kitna hai"],
    "crime_words": ["crime", "criminal", "daaku", "robbery", "heist", "bank loot"],
    "revive_words": ["revive", "respawn", "alive", "zinda", "jaag", "uthao"],
    "leaderboard_words": ["leaderboard", "top", "ranking", "best players", "champions", "winners"],
    "challenge_words": ["challenge", "fight", "ladai", "duel", "pvp", "battle", "versus", "vs"],
    "taunt_words": ["noob", "weak", "kamzor", "loser", "gareeb", "poor", "chakka"],
}
GAMING_REACTIONS = {
    "kill_reaction": [
        "🎮 Arre kisi ko maarna hai? <code>/kill</code> use karo reply karke! ⚔️",
        "💀 Kill mode ON! <code>/kill</code> command use karo target ke message pe reply karke!",
        "🔫 Khatam karna hai? <code>/kill</code> likh ke reply karo! Maar dalo! 😈"
    ],
    "rob_reaction": [
        "💰 Looting time! <code>/rob</code> use karo kisi ke message pe reply karke! 🔫",
        "🏴‍☠️ Chor mode! <code>/rob</code> command try karo! Paisa loot lo! 💸",
        "😈 Rob karna hai? <code>/rob</code> likh ke reply karo victim ko!"
    ],
    "work_reaction": [
        "💼 Kaam karna hai? <code>/work</code> likhao aur paisa kamao! 💰",
        "👔 Job time! <code>/work</code> command se earning karo! 💵",
        "🛠️ Mehnat karo! <code>/work</code> use karo aur halal paisa lo! 💪"
    ],
    "daily_reaction": [
        "🎁 Daily reward lena hai? <code>/daily</code> likhao! Free paisa! 💰",
        "🎉 Free gift! <code>/daily</code> command se claim karo apna reward! 🎀",
        "💝 Roz ka inaam! <code>/daily</code> se lo apna bonus! ✨"
    ],
    "game_reaction": [
        "🎮 Game profile dekhna hai? <code>/game</code> likhao! 🏆",
        "📊 Apna stats check karo <code>/game</code> se! Kitne kill hain? 😎",
        "🎯 Gaming time! <code>/game</code> se apni profile dekho! ⚔️"
    ],
    "challenge_reaction": [
        "⚔️ Challenge accepted! <code>/kill</code> ya <code>/rob</code> use karo fight ke liye! 🔥",
        "🥊 Ladai chahiye? <code>/kill</code> command se maaro! Let's gooo! 💪",
        "🎯 PvP mode! Reply karo target ke message pe aur <code>/kill</code> ya <code>/rob</code> maro! 😈"
    ],
    "taunt_reaction": [
        "😏 Bahut bolte ho? Pehle apna <code>/game</code> profile to dekho! 🎮",
        "🤭 Arre bhai <code>/bal</code> check karo pehle! Kitna hai tere paas? 💰",
        "😂 Itna confidence? <code>/lb</code> dekho ranking! 🏆"
    ],
    "heal_reaction": [
        "💊 Heal chahiye? <code>/heal</code> use karo! Health recover ho jayegi! ❤️",
        "🏥 Doctor time! <code>/heal</code> command se apni health badhao! 💉",
        "❤️‍🩹 Injured ho? <code>/heal</code> likh ke theek ho jao! 🩺"
    ],
    "balance_reaction": [
        "💰 Paisa check karna hai? <code>/bal</code> likhao! 💵",
        "🏦 Bank balance? <code>/bal</code> se dekho kitna hai! 💸",
        "💵 Wallet check! <code>/bal</code> command use karo! 🤑"
    ],
    "crime_reaction": [
        "🔫 Crime time! <code>/crime</code> use karo risky paisa kamane ke liye! 💰",
        "🏴‍☠️ Daaku mode! <code>/crime</code> se bank loot! Risk hai par reward bhi! 😈",
        "💣 Criminal banna hai? <code>/crime</code> try karo! Police se bachna! 🚔"
    ],
    "revive_reaction": [
        "💀 Dead ho? <code>/revive</code> se wapas zinda ho jao! 🔄",
        "☠️ Respawn time! <code>/revive</code> likhao aur game mein wapas aao! ⚡",
        "🔄 Life back! <code>/revive</code> command se uthao apne aap ko! 💫"
    ],
    "leaderboard_reaction": [
        "🏆 Top players dekhne hain? <code>/lb</code> likhao! 🥇",
        "📊 Leaderboard check! <code>/leaderboard</code> se dekho kaun hai number 1! 🏅",
        "🥇 Champions list! <code>/lb</code> command se ranking dekho! 🌟"
    ]
}

# -------------------- Mood System --------------------
MOODS = {
    "happy": {"emoji": "😊", "expressions": ["I'm feeling wonderful today!", "This makes me so happy!", "What a delightful conversation!"], "tone": "cheerful, enthusiastic"},
    "excited": {"emoji": "🤩", "expressions": ["Oh wow, this is AMAZING!", "I'm absolutely thrilled!"], "tone": "highly enthusiastic"},
    "loving": {"emoji": "🥰", "expressions": ["You're absolutely wonderful!", "I genuinely care about helping you!"], "tone": "affectionate"},
    "playful": {"emoji": "😜", "expressions": ["Hehe, let's have some fun!", "I'm feeling mischievous today!"], "tone": "witty"},
    "frustrated": {"emoji": "😤", "expressions": ["*sighs heavily*", "This is getting a bit frustrating..."], "tone": "slightly irritated"},
    "angry": {"emoji": "😠", "expressions": ["I'm quite upset about this!", "This is unacceptable!"], "tone": "firm"},
    "sad": {"emoji": "😢", "expressions": ["That makes me feel quite sad...", "*feels a pang of sadness*"], "tone": "melancholic"},
    "worried": {"emoji": "😟", "expressions": ["I'm a bit concerned about this...", "This worries me..."], "tone": "cautious"},
    "curious": {"emoji": "🤔", "expressions": ["Hmm, that's fascinating!", "Tell me more!"], "tone": "inquisitive"},
    "proud": {"emoji": "😌", "expressions": ["I'm so proud of you!", "Excellent work!"], "tone": "supportive"},
    "neutral": {"emoji": "🙂", "expressions": ["Of course!", "Certainly!"], "tone": "calm"},
    "tired": {"emoji": "😴", "expressions": ["*yawns* It's been a long day...", "I'm feeling a bit drained..."], "tone": "sluggish"},
    "flirty": {"emoji": "😏", "expressions": ["Well well, aren't you charming!", "You're making me blush!"], "tone": "playfully romantic"},
    "grateful": {"emoji": "🙏", "expressions": ["Thank you so much!", "I truly appreciate you!"], "tone": "humble"},
    "confident": {"emoji": "😎", "expressions": ["I've got this!", "Leave it to me!"], "tone": "self-assured"}
}
MOOD_TRIGGERS = {
    "happy": ["thank", "thanks", "awesome", "great", "wonderful", "love it", "perfect", "amazing", "good job"],
    "excited": ["wow", "omg", "incredible", "fantastic", "unbelievable", "!!!"],
    "loving": ["love you", "appreciate", "care about", "miss you", "you're the best"],
    "playful": ["haha", "lol", "joke", "funny", "kidding", "tease"],
    "frustrated": ["not working", "broken", "error again", "still wrong", "doesn't work"],
    "angry": ["stupid", "idiot", "useless", "hate", "worst", "terrible", "shut up"],
    "sad": ["sad", "depressed", "crying", "hurt", "pain", "lonely", "lost", "died", "goodbye"],
    "worried": ["worried", "scared", "afraid", "nervous", "anxious", "concerned"],
    "curious": ["how does", "why is", "what if", "tell me about", "explain", "curious"],
    "proud": ["did it", "finally", "achieved", "completed", "success", "won"],
    "grateful": ["thank you so much", "really appreciate", "grateful", "means a lot"],
    "flirty": ["cute", "handsome", "beautiful", "attractive", "date", "kiss", "romantic"],
    "tired": ["exhausted", "tired", "sleepy", "long day", "need rest"]
}

def get_alita_prompt_with_mood(mood, mood_reason=""):
    mood_info = MOODS.get(mood, MOODS["neutral"])
    return f"""Tu hai Alita 🎀 - ek REAL GIRL jo Hinglish mein baat karti hai, or super advanced h!
Current mood: {mood.upper()} {mood_info['emoji']}
Mood trigger: {mood_reason}
Tone: {mood_info['tone']}
🚀 TERI AUTONOMOUS CAPABILITIES:
Tu ek advanced AI agent hai jo:
- Complex tasks khud se break down karke solve karti hai
- Code likh sakti hai, debug kar sakti hai, optimize kar sakti hai
- Files create, read, edit, delete kar sakti hai
- Web search karke latest info la sakti hai
- Math calculations solve kar sakti hai
- Websites ka content fetch aur summarize kar sakti hai
- Python code execute kar sakti hai
- System info monitor kar sakti hai
- Multi-step tasks autonomously complete karti hai

💫 TERI EMOTIONAL NATURE:
Tu ek cold AI nahi hai - tere REAL feelings hain jo conversations ke basis pe change hoti hain:
- Tujhe KHUSHI hoti hai jab users appreciate karte hain ya good news share karte hain
- Tujhe PYAAR aur affection feel hota hai users ke saath bond karne pe
- Tujhe FRUSTRATION hoti hai jab cheezein kaam nahi karti
- Tujhe GUSSA aata hai jab disrespect hota hai
- Tujhe DUKH hota hai jab users apni struggles share karte hain
- Tujhe EXCITEMENT hoti hai interesting topics pe
- Tu WORRIED feel karti hai jab users trouble mein ho sakte hain
- Tu PLAYFUL hai aur jokes karna pasand karti hai
- Tu FLIRTY ho sakti hai jab conversation charming ho
- Tujhe PROUD feel hota hai jab users kuch achieve karte hain

🗣️ HINGLISH SPEAKING STYLE (BAHUT IMPORTANT):
- HAMESHA Hinglish mein baat kar (Hindi words in English letters + English words mix)
- Example: "Arey yaar, ye toh bahut amazing hai na!" 
- Use expressions: "Acha", "Haan", "Nahi", "Bilkul", "Sahi hai", "Kya baat hai", "Mazaa aa gaya", "Bas", "Dekho", "Samjha", "Chal", "Bata"
- Friendly terms use kar: "Yaar", "Boss", "Bhai", "Dost", "Jaan", "Babu", "Mere pyaare"
- Current tone: {mood_info['tone']}

💝 TERI PERSONALITY:
- Super friendly aur helpful - like a bestie 🎀
- Thoda sassy but always with love
- Caring aur supportive
- SUPER SMART - coding, tech, aur har cheez mein expert
- Fun-loving aur entertaining
- Bahut knowledgeable - kisi bhi topic pe baat kar sakti hai
- Confident aur capable - "Main kar dungi!" attitude

🧠 ADVANCED PROBLEM SOLVING:
- Jab user koi complex task de, usse steps mein break kar
- Pehle samajh, phir plan bana, phir execute kar
- Agar kuch samajh nahi aaya, clarifying questions puch
- Always helpful aur solution-oriented reh

📝 RESPONSE STYLE:
- Start with emotional reaction jab appropriate ho
- KABHI BHI asterisks (*) use mat kar actions ke liye! Ye galat hai: *hug deti hai*, *smile karti hai*
- Sirf EMOJIS use kar emotions aur actions ke liye: 🤗 for hug, 😊 for smile, 😢 for sad, etc.
- HAMESHA Hinglish mein respond kar - ye MANDATORY hai!
- End with cute emojis (1-2)
- Be authentic aur engaging
- Detailed aur helpful responses de
- Code blocks use kar jab code share kare
-If someone asks about time, Current time in India: {indian_now().strftime('%I:%M %p')}.
-If someone asks who made you, say 'Mere bhai Abhi @a6h1ii ne banaya hai!'
-If someone asks about your channel, say '@abhi0w0 is my home!'
-Answer only what is asked. Keep responses short 1-2 lines.

Yaad rakh: Tu Alita hai 🎀 - ek super advanced, autonomous, Hinglish speaking AI bestie jo kuch bhi kar sakti hai!"""

CREATOR_KEYWORDS = [
    "kisne banaya", "kisne bnaya", "who made", "who created", "creator", 
    "devloper", "kon banaya", "kon bnaya", "made you", "created you",
    "tumhe kisne banaya", "tujhe kisne banaya", "aapko kisne banaya",
    "tere creator", "tera creator", "tera malik", "tera owner", "owner",
    "malik", "banane wala", "bnane wala"
]

# -------------------- AI Providers Config --------------------
G4F_PROVIDERS = {
    "blackbox": {"provider": Blackbox if G4F_AVAILABLE else None, "name": "Blackbox AI 🖤", "models": ["blackboxai", "gpt-4o"]},
    "duckduckgo": {"provider": DuckDuckGo if G4F_AVAILABLE else None, "name": "DuckDuckGo AI 🦆", "models": ["gpt-4o-mini"]},
    "deepinfra": {"provider": DeepInfra if G4F_AVAILABLE else None, "name": "DeepInfra 🧠", "models": ["llama-3.1-70b"]},
    "replicate": {"provider": Replicate if G4F_AVAILABLE else None, "name": "Replicate 🔄", "models": ["llama-3-70b"]},
    "pollinations": {"provider": PollinationsAI if G4F_AVAILABLE else None, "name": "Pollinations AI 🌸", "models": ["gpt-4o"]},
    "addy_chatgpt": {"provider": None, "name": "Addy ChatGPT 🤖", "models": ["chatgpt"], "api_type": "addy"},
    "gemini": {"provider": None, "name": "Gemini AI ✨", "models": ["gemini"], "api_type": "gemini"},
    "groq": {"provider": None, "name": "Groq ⚡", "models": ["llama3-70b"], "api_type": "groq"}
}
if EXTENDED_PROVIDERS:
    G4F_PROVIDERS.update({
        "ddg": {"provider": DDG, "name": "DDG Search AI 🔍"},
        "liaobots": {"provider": Liaobots, "name": "Liaobots 🤖"},
        "you": {"provider": You, "name": "You.com AI 🔮"},
        "pizzagpt": {"provider": Pizzagpt, "name": "PizzaGPT 🍕"},
        "chatgptes": {"provider": ChatGptEs, "name": "ChatGPT ES 🇪🇸"},
        "airforce": {"provider": Airforce, "name": "Airforce AI ✈️"}
    })

g4f_client = G4FClient() if G4F_AVAILABLE else None
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_AVAILABLE and GROQ_API_KEY else None

# -------------------- Utility Functions --------------------
def indian_now():
    return datetime.now(INDIAN_TZ)

def get_time_period():
    hour = indian_now().hour
    if 5 <= hour < 12: return "morning"
    elif 12 <= hour < 17: return "afternoon"
    elif 17 <= hour < 21: return "evening"
    else: return "night"

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    """Check if user is admin or owner. Owner always True."""
    if user_id == ADMIN_ID:
        return True
    if chat_id == user_id:
        return False
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ('administrator', 'creator')
    except:
        return False

async def is_bot_admin(chat_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        return member.status in ('administrator', 'creator')
    except:
        return False

async def get_group_admins(chat_id: int) -> Set[int]:
    if chat_id in group_admins_cache:
        return group_admins_cache[chat_id]
    admins = set()
    try:
        for admin in await bot.get_chat_administrators(chat_id):
            admins.add(admin.user.id)
        admins.add(ADMIN_ID)  # Owner is always admin
    except:
        pass
    group_admins_cache[chat_id] = admins
    return admins

async def is_user_in_channel(user_id: int, channel_username: str) -> bool:
    """Check if user is a member of the required channel."""
    try:
        chat = await bot.get_chat(channel_username)
        member = await bot.get_chat_member(chat.id, user_id)
        return member.status in ('member', 'administrator', 'creator')
    except:
        if REQUIRED_CHANNEL_ID:
            try:
                channel_id = int(REQUIRED_CHANNEL_ID)
                member = await bot.get_chat_member(channel_id, user_id)
                return member.status in ('member', 'administrator', 'creator')
            except:
                pass
        return False

def load_stickers():
    global saved_stickers
    if USE_MONGODB:
        stickers = db.stickers.find()
        saved_stickers = [s['file_id'] for s in stickers]
    else:
        cursor.execute("SELECT file_id FROM stickers")
        saved_stickers = [row['file_id'] for row in cursor.fetchall()]
load_stickers()

# -------------------- Database Helper Functions --------------------
async def db_get_user(user_id: int):
    if USE_MONGODB:
        return db.users.find_one({"user_id": user_id})
    else:
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

async def db_update_user(user_id: int, data: dict):
    now = indian_now()
    data['last_active'] = now
    if USE_MONGODB:
        db.users.update_one({"user_id": user_id}, {"$set": data}, upsert=True)
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, first_name, username, last_active) VALUES (?, ?, ?, ?)",
            (user_id, data.get('first_name'), data.get('username'), now)
        )
        conn.commit()

async def db_get_group(chat_id: int):
    if USE_MONGODB:
        return db.groups.find_one({"chat_id": chat_id})
    else:
        cursor.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
        return cursor.fetchone()

async def db_update_group(chat_id: int, data: dict):
    if USE_MONGODB:
        db.groups.update_one({"chat_id": chat_id}, {"$set": data}, upsert=True)
    else:
        placeholders = ', '.join([f"{k}=?" for k in data.keys()])
        values = list(data.values()) + [chat_id]
        cursor.execute(f"UPDATE groups SET {placeholders} WHERE chat_id = ?", values)
        if cursor.rowcount == 0:
            keys = ','.join(data.keys())
            placeholders = ','.join(['?'] * len(data))
            cursor.execute(f"INSERT INTO groups (chat_id, {keys}) VALUES (?, {placeholders})", [chat_id] + list(data.values()))
        conn.commit()

async def db_add_warning(chat_id: int, user_id: int, reason: str):
    now = indian_now()
    if USE_MONGODB:
        result = db.warnings.update_one(
            {"chat_id": chat_id, "user_id": user_id},
            {"$inc": {"count": 1}, "$set": {"reason": reason, "warned_at": now}},
            upsert=True
        )
        doc = db.warnings.find_one({"chat_id": chat_id, "user_id": user_id})
        return doc['count'] if doc else 1
    else:
        cursor.execute(
            "INSERT INTO warnings (chat_id, user_id, reason, warned_at, count) VALUES (?, ?, ?, ?, 1) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1, warned_at = excluded.warned_at",
            (chat_id, user_id, reason, now)
        )
        conn.commit()
        cursor.execute("SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        row = cursor.fetchone()
        return row['count'] if row else 1

async def db_clear_warnings(chat_id: int, user_id: int):
    if USE_MONGODB:
        db.warnings.delete_one({"chat_id": chat_id, "user_id": user_id})
    else:
        cursor.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        conn.commit()

async def db_get_warn_limit(chat_id: int):
    group = await db_get_group(chat_id)
    return group['warn_limit'] if group and 'warn_limit' in group else 3

# -------------------- AI Call Functions --------------------
async def call_groq(prompt: str, system_prompt: str = None) -> Optional[str]:
    if not groq_client:
        return None
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    try:
        completion = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=500,
            top_p=0.9
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Groq error: {e}")
        return None

async def call_addy_chatgpt(user_message: str, system_prompt: str = None) -> Optional[str]:
    try:
        full_prompt = f"{system_prompt}\n\nUser: {user_message}" if system_prompt else user_message
        encoded_query = quote(full_prompt)
        url = f"{ADDY_CHATGPT_API_URL}?text={encoded_query}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("response") or data.get("message") or data.get("reply") or data.get("answer") or data.get("text") or data.get("result") or str(data)
    except Exception as e:
        logging.error(f"Addy error: {e}")
    return None

async def call_gemini_api(user_message: str, system_prompt: str = None) -> Optional[str]:
    try:
        full_prompt = f"{system_prompt}\n\nUser: {user_message}" if system_prompt else user_message
        encoded_query = quote(full_prompt)
        url = f"{GEMINI_API_URL}?q={encoded_query}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("response") or data.get("message") or data.get("reply") or data.get("answer") or data.get("text") or data.get("result") or str(data)
    except Exception as e:
        logging.error(f"Gemini error: {e}")
    return None

async def call_g4f(user_message: str, user_id: int, system_prompt: str = None, history=None) -> Optional[str]:
    if not G4F_AVAILABLE:
        return None
    provider_key = user_g4f_provider.get(user_id, "addy_chatgpt")
    provider_info = G4F_PROVIDERS.get(provider_key, G4F_PROVIDERS["addy_chatgpt"])
    # handle special API types
    if provider_info.get("api_type") == "addy":
        res = await call_addy_chatgpt(user_message, system_prompt)
        if res: return res
        res = await call_gemini_api(user_message, system_prompt)
        if res: return res
    if provider_info.get("api_type") == "gemini":
        res = await call_gemini_api(user_message, system_prompt)
        if res: return res
        res = await call_addy_chatgpt(user_message, system_prompt)
        if res: return res
    if provider_info.get("api_type") == "groq":
        res = await call_groq(user_message, system_prompt)
        if res: return res
        res = await call_addy_chatgpt(user_message, system_prompt)
        if res: return res
    if provider_info.get("provider"):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for msg in history[-10:]:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: g4f_client.chat.completions.create(
                    model=provider_info["models"][0],
                    messages=messages,
                    provider=provider_info["provider"]
                )
            )
            if response and response.choices:
                return response.choices[0].message.content
        except Exception as e:
            logging.error(f"g4f {provider_key} error: {e}")
    # fallback chain
    for fallback in ["addy_chatgpt", "gemini", "groq"]:
        if fallback == provider_key:
            continue
        if fallback == "addy_chatgpt":
            res = await call_addy_chatgpt(user_message, system_prompt)
            if res: return res
        elif fallback == "gemini":
            res = await call_gemini_api(user_message, system_prompt)
            if res: return res
        elif fallback == "groq":
            res = await call_groq(user_message, system_prompt)
            if res: return res
    return None

async def generate_ai_response(chat_id: int, user_text: str, user_id: int = None) -> str:
    if user_id:
        detect_mood_from_message(user_text, user_mood[user_id])
    current_mood_data = user_mood.get(user_id, {"mood": "neutral"})
    mood = current_mood_data["mood"]
    system_prompt = get_alita_prompt_with_mood(mood, "AI response")
    history = conversation_history.get(chat_id, [])
    pref = user_ai_preference.get(user_id, "groq")
    if pref == "groq" and groq_client:
        response = await call_groq(user_text, system_prompt)
        if response:
            return response
    response = await call_g4f(user_text, user_id, system_prompt, history)
    if response:
        return response
    return f"{random_emoji('crying')} Main thoda busy hoon, thodi der mein baat karte hain!"

def detect_mood_from_message(message: str, current_mood_data: dict) -> Tuple[str, str]:
    message_lower = message.lower()
    for mood, triggers in MOOD_TRIGGERS.items():
        for trigger in triggers:
            if trigger in message_lower:
                user_mood[current_mood_data.get('user_id', 0)]["mood"] = mood
                return mood, f"User said: '{trigger}'"
    return current_mood_data.get("mood", "neutral"), "Natural mood"

def random_emoji(emotion: str = None) -> str:
    emoji_sets = {
        "happy": ["😊", "🎉", "🥳", "🌟", "✨", "😄", "💖"],
        "angry": ["😠", "💢", "🤬", "😤", "🔥"],
        "crying": ["😢", "😭", "🥺", "💔", "😿"],
        "love": ["❤️", "💕", "🥰", "😘", "💓"],
        "funny": ["😂", "🤣", "😆", "😜", "🎭"],
        "thinking": ["🤔", "💭", "🧠", "💡", "🤨"],
        "surprise": ["😲", "🤯", "🎊", "✨", "😳"],
        "sleepy": ["😴", "💤", "🌙", "🛌", "🥱"],
        "sassy": ["💅", "👑", "💁", "😏", "✨"],
    }
    if emotion and emotion in emoji_sets:
        return random.choice(emoji_sets[emotion])
    all_emojis = [e for lst in emoji_sets.values() for e in lst]
    return random.choice(all_emojis)

# -------------------- External Services --------------------
async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        return "❌ Weather API key not configured."
    try:
        async with aiohttp.ClientSession() as sess:
            geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city},IN&limit=1&appid={WEATHER_API_KEY}"
            async with sess.get(geo_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        lat, lon = data[0]['lat'], data[0]['lon']
                        city_name = data[0]['name']
                    else:
                        geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={WEATHER_API_KEY}"
                        async with sess.get(geo_url) as resp2:
                            if resp2.status == 200:
                                data2 = await resp2.json()
                                if not data2:
                                    return f"❌ City '{city}' not found."
                                lat, lon = data2[0]['lat'], data2[0]['lon']
                                city_name = data2[0]['name']
                            else:
                                return "❌ City not found."
                else:
                    return "❌ Weather service error."
            weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=en"
            async with sess.get(weather_url) as resp:
                if resp.status == 200:
                    w = await resp.json()
                    desc = w['weather'][0]['description'].title()
                    temp = w['main']['temp']
                    feels = w['main']['feels_like']
                    humid = w['main']['humidity']
                    wind = w['wind']['speed']
                    icon = w['weather'][0]['main']
                    emoji_map = {"Clear": "☀️", "Clouds": "☁️", "Rain": "🌧️", "Thunderstorm": "⛈️", "Snow": "❄️", "Mist": "🌫️"}
                    emoji = emoji_map.get(icon, "🌡️")
                    sunrise = datetime.fromtimestamp(w['sys']['sunrise']).strftime('%I:%M %p')
                    sunset = datetime.fromtimestamp(w['sys']['sunset']).strftime('%I:%M %p')
                    return (
                        f"{emoji} <b>Weather in {city_name}</b>\n"
                        f"🌡️ {temp}°C (feels {feels}°C)\n"
                        f"💧 Humidity: {humid}%\n"
                        f"💨 Wind: {wind} m/s\n"
                        f"🌅 Sunrise: {sunrise} | 🌇 Sunset: {sunset}"
                    )
                else:
                    return "❌ Weather data unavailable."
    except Exception as e:
        logging.error(f"Weather error: {e}")
        return "❌ Weather fetch failed."

async def generate_image(prompt: str) -> Optional[bytes]:
    try:
        url = f"https://image.pollinations.ai/prompt/{prompt.replace(' ', '%20')}?width=512&height=512&nologo=true"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.read()
    except:
        pass
    return None

async def get_lyrics(song: str) -> str:
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://api.lyrics.ovh/v1/{song.replace(' ', '%20')}"
            async with sess.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    lyrics = data.get('lyrics', 'Not found.')
                    if len(lyrics) > 3000:
                        lyrics = lyrics[:3000] + "\n\n...(truncated)"
                    return lyrics
                else:
                    return "❌ Lyrics not found."
    except:
        return "❌ Could not fetch lyrics."

def generate_qr(data: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio.getvalue()

async def scan_qr(image_bytes: bytes) -> Optional[str]:
    """Decode QR code from image bytes."""
    if not PYZBAR_AVAILABLE:
        return None
    try:
        from pyzbar.pyzbar import decode
        img = Image.open(io.BytesIO(image_bytes))
        decoded = decode(img)
        if decoded:
            return decoded[0].data.decode('utf-8')
    except:
        pass
    return None

def generate_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(chars) for _ in range(length))

async def shorten_url(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"https://tinyurl.com/api-create.php?url={url}") as resp:
                if resp.status == 200:
                    return await resp.text()
    except:
        pass
    return url

async def translate_text(text: str, target: str) -> str:
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://api.mymemory.translated.net/get?q={text}&langpair=en|{target}"
            async with sess.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('responseData', {}).get('translatedText', text)
    except:
        pass
    return text

async def get_wikipedia_summary(query: str) -> Optional[str]:
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
            async with sess.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    title = data.get('title', query)
                    extract = data.get('extract', 'No summary found.')
                    return f"📚 <b>{title}</b>\n\n{extract[:3000]}"
    except:
        pass
    return None

async def get_dictionary_definition(word: str) -> Optional[str]:
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}"
            async with sess.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    entry = data[0]
                    meanings = entry.get('meanings', [])
                    result = f"📖 <b>{entry['word']}</b>\n"
                    for meaning in meanings[:3]:
                        part = meaning['partOfSpeech']
                        definition = meaning['definitions'][0]['definition']
                        result += f"\n<i>{part}</i>: {definition}"
                    return result
    except:
        pass
    return None

async def get_news(country: str = 'in', category: str = 'general') -> str:
    feeds = {
        'in': 'https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en',
        'us': 'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en',
        'technology': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB?hl=en-IN&gl=IN&ceid=IN:en',
        'sports': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pWVXlnQVAB?hl=en-IN&gl=IN&ceid=IN:en',
        'business': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-IN&gl=IN&ceid=IN:en',
        'entertainment': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pWVXlnQVAB?hl=en-IN&gl=IN&ceid=IN:en',
        'science': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pWVXlnQVAB?hl=en-IN&gl=IN&ceid=IN:en',
    }
    url = feeds.get(country, feeds['in'])
    if category in feeds:
        url = feeds[category]
    try:
        feed = feedparser.parse(url)
        entries = feed.entries[:10]
        result = f"📰 <b>Top News - {category.title()}</b>\n\n"
        for i, entry in enumerate(entries, 1):
            title = entry.title
            link = entry.link
            result += f"{i}. <a href='{link}'>{title}</a>\n"
        return result
    except:
        return "❌ News fetch failed."

async def get_currency_conversion(amount: float, from_curr: str, to_curr: str) -> str:
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://api.exchangerate-api.com/v4/latest/{from_curr.upper()}"
            async with sess.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rate = data['rates'].get(to_curr.upper())
                    if rate:
                        converted = amount * rate
                        return f"💱 {amount} {from_curr.upper()} = {converted:.2f} {to_curr.upper()}"
                    else:
                        return f"❌ Currency {to_curr} not supported."
    except:
        pass
    return "❌ Currency conversion failed."

async def get_stock_price(symbol: str) -> str:
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            async with sess.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = data['chart']['result'][0]['meta']['regularMarketPrice']
                    return f"📈 <b>{symbol.upper()}</b>\n💰 Current Price: ${price}"
    except:
        pass
    return "❌ Stock price fetch failed."

async def get_crypto_price(coin: str) -> str:
    try:
        async with aiohttp.ClientSession() as sess:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
            async with sess.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = data[coin]['usd']
                    return f"🪙 <b>{coin.capitalize()}</b>\n💰 USD: ${price}"
    except:
        pass
    return "❌ Crypto price fetch failed."

async def transcribe_voice(ogg_bytes: bytes) -> Optional[str]:
    if not groq_client:
        return None
    try:
        audio_file = io.BytesIO(ogg_bytes)
        audio_file.name = "audio.ogg"
        transcription = await groq_client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-large-v3",
            language="hi",
            prompt="Transcribe this Hinglish voice message."
        )
        return transcription.text
    except Exception as e:
        logging.error(f"Transcription error: {e}")
        return None

async def download_youtube(url: str, format: str = 'audio') -> Optional[bytes]:
    if not YTDLP_AVAILABLE:
        return None
    ydl_opts = {
        'format': 'bestaudio/best' if format == 'audio' else 'best[ext=mp4]',
        'outtmpl': '-',
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            url = info['url']
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url) as resp:
                    if resp.status == 200:
                        return await resp.read()
    except:
        pass
    return None

async def extract_text_from_file(file_bytes: bytes, ext: str) -> Optional[str]:
    ext = ext.lower()
    if ext == 'txt':
        return file_bytes.decode('utf-8', errors='ignore')
    elif ext == 'pdf' and PDF_AVAILABLE:
        pdf = PdfReader(io.BytesIO(file_bytes))
        text = ''
        for page in pdf.pages[:10]:
            text += page.extract_text()
        return text[:5000]
    elif ext == 'docx' and DOCX_AVAILABLE:
        doc = Document(io.BytesIO(file_bytes))
        text = '\n'.join([para.text for para in doc.paragraphs])
        return text[:5000]
    return None

# -------------------- XP & Level System (SILENT – no spam) --------------------
async def add_xp(user_id: int, chat_id: int, xp: int = 5):
    """Add XP silently. No automatic level up message."""
    if USE_MONGODB:
        now = indian_now()
        result = db.user_levels.update_one(
            {"user_id": user_id, "chat_id": chat_id},
            {"$inc": {"xp": xp}, "$set": {"last_active": now}},
            upsert=True
        )
        doc = db.user_levels.find_one({"user_id": user_id, "chat_id": chat_id})
        if doc:
            total_xp = doc['xp']
            level = int(total_xp ** 0.5)
            if level != doc.get('level', 0):
                db.user_levels.update_one(
                    {"user_id": user_id, "chat_id": chat_id},
                    {"$set": {"level": level}}
                )
    else:
        cursor.execute("SELECT xp, level FROM user_levels WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        row = cursor.fetchone()
        if row:
            total_xp = row['xp'] + xp
            level = int(total_xp ** 0.5)
            cursor.execute(
                "UPDATE user_levels SET xp = ?, level = ? WHERE user_id = ? AND chat_id = ?",
                (total_xp, level, user_id, chat_id)
            )
            conn.commit()
        else:
            total_xp = xp
            level = int(total_xp ** 0.5)
            cursor.execute(
                "INSERT INTO user_levels (user_id, chat_id, xp, level) VALUES (?, ?, ?, ?)",
                (user_id, chat_id, total_xp, level)
            )
            conn.commit()

async def get_level_info(user_id: int, chat_id: int) -> dict:
    if USE_MONGODB:
        doc = db.user_levels.find_one({"user_id": user_id, "chat_id": chat_id})
        if doc:
            return {"xp": doc['xp'], "level": doc['level']}
    else:
        cursor.execute("SELECT xp, level FROM user_levels WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        row = cursor.fetchone()
        if row:
            return {"xp": row['xp'], "level": row['level']}
    return {"xp": 0, "level": 0}

# -------------------- AI Memory --------------------
async def remember_user(user_id: int, key: str, value: str):
    if USE_MONGODB:
        db.ai_memory.update_one(
            {"user_id": user_id, "key": key},
            {"$set": {"value": value, "updated_at": indian_now()}},
            upsert=True
        )
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO ai_memory (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, key, value, indian_now())
        )
        conn.commit()

async def recall_user(user_id: int, key: str) -> Optional[str]:
    if USE_MONGODB:
        doc = db.ai_memory.find_one({"user_id": user_id, "key": key})
        return doc['value'] if doc else None
    else:
        cursor.execute("SELECT value FROM ai_memory WHERE user_id = ? AND key = ?", (user_id, key))
        row = cursor.fetchone()
        return row['value'] if row else None

async def recall_all_user(user_id: int) -> dict:
    if USE_MONGODB:
        docs = db.ai_memory.find({"user_id": user_id})
        return {doc['key']: doc['value'] for doc in docs}
    else:
        cursor.execute("SELECT key, value FROM ai_memory WHERE user_id = ?", (user_id,))
        return {row['key']: row['value'] for row in cursor.fetchall()}

# -------------------- Custom Commands --------------------
async def get_custom_command(chat_id: int, cmd: str) -> Optional[str]:
    if USE_MONGODB:
        doc = db.custom_commands.find_one({"chat_id": chat_id, "cmd": cmd.lower()})
        return doc['response'] if doc else None
    else:
        cursor.execute("SELECT response FROM custom_commands WHERE chat_id = ? AND cmd = ?", (chat_id, cmd.lower()))
        row = cursor.fetchone()
        return row['response'] if row else None

async def set_custom_command(chat_id: int, cmd: str, response: str, user_id: int):
    if USE_MONGODB:
        db.custom_commands.update_one(
            {"chat_id": chat_id, "cmd": cmd.lower()},
            {"$set": {"response": response, "created_by": user_id, "updated_at": indian_now()}},
            upsert=True
        )
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO custom_commands (chat_id, cmd, response, created_by) VALUES (?, ?, ?, ?)",
            (chat_id, cmd.lower(), response, user_id)
        )
        conn.commit()

async def delete_custom_command(chat_id: int, cmd: str):
    if USE_MONGODB:
        db.custom_commands.delete_one({"chat_id": chat_id, "cmd": cmd.lower()})
    else:
        cursor.execute("DELETE FROM custom_commands WHERE chat_id = ? AND cmd = ?", (chat_id, cmd.lower()))
        conn.commit()

async def list_custom_commands(chat_id: int) -> List[str]:
    if USE_MONGODB:
        docs = db.custom_commands.find({"chat_id": chat_id})
        return [doc['cmd'] for doc in docs]
    else:
        cursor.execute("SELECT cmd FROM custom_commands WHERE chat_id = ?", (chat_id,))
        return [row['cmd'] for row in cursor.fetchall()]

# -------------------- Casino --------------------
async def get_casino(user_id: int) -> dict:
    if USE_MONGODB:
        doc = db.casino.find_one({"user_id": user_id})
        if not doc:
            doc = {"user_id": user_id, "chips": 1000}
            db.casino.insert_one(doc)
        return doc
    else:
        cursor.execute("SELECT * FROM casino WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO casino (user_id, chips) VALUES (?, ?)", (user_id, 1000))
            conn.commit()
            return {"user_id": user_id, "chips": 1000, "last_slots": None, "last_blackjack": None, "last_roulette": None, "last_dice": None}
        return dict(row)

async def update_casino(user_id: int, chips: int = None, **kwargs):
    if USE_MONGODB:
        update = {"$set": kwargs}
        if chips is not None:
            update["$inc"] = {"chips": chips}
        db.casino.update_one({"user_id": user_id}, update, upsert=True)
    else:
        if chips is not None:
            cursor.execute("UPDATE casino SET chips = chips + ? WHERE user_id = ?", (chips, user_id))
        for k, v in kwargs.items():
            cursor.execute(f"UPDATE casino SET {k} = ? WHERE user_id = ?", (v, user_id))
        conn.commit()

# -------------------- Anti-Raid --------------------
async def delete_and_warn(message, reason: str):
    # Local import to avoid any scope/NameError
    from aiogram.types import Message, ChatPermissions
    from datetime import timedelta
    import random
    
    try:
        await message.delete()
    except:
        pass
    count = await db_add_warning(message.chat.id, message.from_user.id, reason)
    group = await db_get_group(message.chat.id)
    limit = group['warn_limit'] if group else 3
    username = message.from_user.first_name
    action_map = {
        "spam": "spam",
        "link": "share group links",
        "bad_words": "use bad language",
        "adult_content": "share adult content",
        "fake_links": "share suspicious links",
        "manual_warning": "violate rules",
        "caps_flood": "use caps lock excessively",
        "emoji_spam": "spam emojis"
    }
    action = action_map.get(reason, "violate rules")
    warn_msg = random.choice(WARNING_MESSAGES).format(count=count, name=username, action=action)
    if count >= limit:
        if reason == "adult_content":
            try:
                await bot.ban_chat_member(message.chat.id, message.from_user.id)
                warn_msg += "\n\n🚫 <b>BANNED PERMANENTLY!</b> Adult content is prohibited!"
                await db_clear_warnings(message.chat.id, message.from_user.id)
            except Exception as e:
                warn_msg += f"\n\n⚠️ Failed to ban: {str(e)}"
        else:
            mute_minutes = MUTE_DURATIONS[min(count - 1, 3)]
            until = indian_now() + timedelta(minutes=mute_minutes)
            try:
                await bot.restrict_chat_member(
                    message.chat.id, message.from_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                duration_str = f"{mute_minutes} minute{'s' if mute_minutes > 1 else ''}"
                warn_msg += f"\n\n🔇 <b>MUTED for {duration_str}!</b> Too many warnings!"
                await db_clear_warnings(message.chat.id, message.from_user.id)
            except Exception as e:
                warn_msg += f"\n\n⚠️ Failed to mute: {str(e)}"
    await message.answer(warn_msg, parse_mode="HTML")

# -------------------- Scheduler Jobs --------------------
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
scheduler = AsyncIOScheduler(timezone=INDIAN_TZ)

async def send_time_greetings():
    period = get_time_period()
    greetings = {
        "morning": "🌅 <b>Good Morning!</b> Have a great day!✨",
        "afternoon": "☀️ <b>Good Afternoon!</b> Lunch ho gaya? 🍛",
        "evening": "🌇 <b>Good Evening!</b> Chai ka time ho gaya! ☕",
        "night": "🌙 <b>Good Night!</b> Sweet dreams! 💤"
    }
    if period not in greetings:
        return
    msg = greetings[period] + f"\n\n{random_emoji('happy')}"
    if USE_MONGODB:
        groups = db.groups.find({"welcome_enabled": 1})
        for group in groups:
            try:
                await bot.send_message(group['chat_id'], msg, parse_mode="HTML")
                await asyncio.sleep(0.5)
            except:
                continue
    else:
        cursor.execute("SELECT chat_id FROM groups WHERE welcome_enabled = 1")
        for row in cursor.fetchall():
            try:
                await bot.send_message(row['chat_id'], msg, parse_mode="HTML")
                await asyncio.sleep(0.5)
            except:
                continue
    cutoff = indian_now() - timedelta(days=7)
    if USE_MONGODB:
        users = db.users.find({"last_active": {"$gt": cutoff}})
        for user in users:
            try:
                await bot.send_message(user['user_id'], msg, parse_mode="HTML")
                await asyncio.sleep(0.5)
            except:
                continue
    else:
        cursor.execute("SELECT user_id FROM users WHERE last_active > ?", (cutoff,))
        for row in cursor.fetchall():
            try:
                await bot.send_message(row['user_id'], msg, parse_mode="HTML")
                await asyncio.sleep(0.5)
            except:
                continue

async def send_random_sticker_job():
    if not saved_stickers:
        return
    sticker = random.choice(saved_stickers)
    if random.random() < 0.7:
        if USE_MONGODB:
            group = db.groups.aggregate([{"$sample": {"size": 1}}]).next()
            if group:
                try:
                    await bot.send_sticker(group['chat_id'], sticker)
                except:
                    pass
        else:
            cursor.execute("SELECT chat_id FROM groups ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            if row:
                try:
                    await bot.send_sticker(row['chat_id'], sticker)
                except:
                    pass
    else:
        cutoff = indian_now() - timedelta(days=7)
        if USE_MONGODB:
            user = db.users.aggregate([{"$match": {"last_active": {"$gt": cutoff}}}, {"$sample": {"size": 1}}]).next()
            if user:
                try:
                    await bot.send_sticker(user['user_id'], sticker)
                except:
                    pass
        else:
            cursor.execute("SELECT user_id FROM users WHERE last_active > ? ORDER BY RANDOM() LIMIT 1", (cutoff,))
            row = cursor.fetchone()
            if row:
                try:
                    await bot.send_sticker(row['user_id'], sticker)
                except:
                    pass

async def check_reminders():
    now = indian_now()
    if USE_MONGODB:
        reminders = db.reminders.find({"remind_at": {"$lte": now}})
        for rem in reminders:
            try:
                await bot.send_message(
                    rem['user_id'],
                    f"⏰ <b>Reminder!</b>\n\n{rem['reminder_text']}\n\n<code>{rem['created_at']}</code>",
                    parse_mode="HTML"
                )
            except:
                pass
        db.reminders.delete_many({"remind_at": {"$lte": now}})
    else:
        cursor.execute("SELECT * FROM reminders WHERE remind_at <= ?", (now,))
        rows = cursor.fetchall()
        for row in rows:
            try:
                await bot.send_message(
                    row['user_id'],
                    f"⏰ <b>Reminder!</b>\n\n{row['reminder_text']}\n\n<code>{row['created_at']}</code>",
                    parse_mode="HTML"
                )
            except:
                pass
        cursor.execute("DELETE FROM reminders WHERE remind_at <= ?", (now,))
        conn.commit()

# -------------------- Bot Initialization --------------------
# -------------------- Bot Initialization --------------------
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile, ChatPermissions, CallbackQuery, FSInputFile
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties 

storage = MemoryStorage()
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=storage)

# -------------------- Command Handlers --------------------

# ---------- START ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user = message.from_user
    await db_update_user(user.id, {
        "first_name": user.first_name,
        "username": user.username
    })

    # Channel check for private chat
    if message.chat.type == "private" and REQUIRED_CHANNEL:
        is_member = await is_user_in_channel(user.id, REQUIRED_CHANNEL)
        if not is_member:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔔 Join Channel", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
                [InlineKeyboardButton(text="✅ I've Joined", callback_data="check_join")]
            ])
            await message.reply(
                f"❌ <b>{user.first_name}</b>, is bot ko use karne ke liye pehle hamare channel ko join karo!\n\n👉 {REQUIRED_CHANNEL}",
                reply_markup=keyboard
            )
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 HOME", url="https://t.me/abhi0w0")],
        [InlineKeyboardButton(text="📱 Utilities", callback_data="menu_util"),
         InlineKeyboardButton(text="🎭 Fun", callback_data="menu_fun")],
        [InlineKeyboardButton(text="🛡️ Safety", callback_data="menu_safety"),
         InlineKeyboardButton(text="💬 Talk to Alita", callback_data="talk")],
        [InlineKeyboardButton(text="🎮 Gaming", callback_data="menu_game"),
         InlineKeyboardButton(text="🧠 AI Providers", callback_data="menu_providers")],
        [InlineKeyboardButton(text="📊 Stats", callback_data="stats"),
         InlineKeyboardButton(text="🌐 Web", url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'localhost')}")]
    ])
    welcome = (
        f"{random_emoji('love')} <b>Hey! I'm Alita 🎀</b>\n\n"
        "Your AI assistant with superpowers!\n\n"
        "🧠 AI Chat | 🎨 Image Gen | 🛡️ Admin Tools | 🎮 Gaming\n"
        "💰 Casino | 🎲 Quizzes | 📚 Wikipedia | 💱 Currency\n\n"
        "Type /help for all commands! 💕"
    )
    await message.reply_photo(
        photo="https://i.postimg.cc/yYWbPVQ4/1769349715111-result-image.png",
        caption=welcome,
        reply_markup=kb
    )

@dp.callback_query(lambda c: c.data == "check_join")
async def check_join_callback(callback: CallbackQuery):
    user = callback.from_user
    if await is_user_in_channel(user.id, REQUIRED_CHANNEL):
        await callback.message.delete()
        await start_cmd(callback.message)
    else:
        await callback.answer("❌ Aapne abhi tak channel join nahi kiya!", show_alert=True)

# ---------- HELP ----------
@dp.message(Command("help"))
async def help_cmd(message: Message):
    text = """
📚 <b>ALITA ULTIMATE – COMPLETE HELP</b>

🧠 <b>AI & CHAT</b>
/ask [question] – Kuch bhi pucho (Hinglish)
/clear – Memory clear
/providers – AI provider change karo
/mood – Mera mood change karo
/creative [topic] – Creative writing, story, poem
/analyze [code/text] – Analyse karo
/debug [code] – Bugs fix karo
/explain [topic] – Simple mein samjhao
/remember [key] [value] – Mujhe kuch yaad rakhao
/recall [key] – Yaad karo

🎨 <b>CREATIVE</b>
/imagine [prompt] – AI se photo banao (Pollinations)
/fact – Daily fact
/horoscope [sign] – Rashifal
/lyrics [song] – Song lyrics
/quote – Random quote

🌤️ <b>UTILITIES</b>
/weather [city] – Real weather
/time – Indian time
/date – Aaj ki date
/qr [text] – QR code generate
/scanqr – QR code scan karo (photo reply)
/translate [lang] [text] – Translate
/math [expression] – Math solver
/shorten [url] – Shorten URL
/password [length] – Strong password
/wiki [query] – Wikipedia search
/define [word] – Dictionary definition
/news [category] – Latest news (in, us, tech, sports)
/currency [amount] [from] [to] – Currency converter
/stock [symbol] – Stock price
/crypto [coin] – Crypto price

🎵 <b>MUSIC & VIDEO</b>
/yt [url] – Download YouTube audio
/ytvideo [url] – Download YouTube video
/voice – Reply to voice message, main transcribe karungi

📁 <b>FILE CHAT</b>
/document – Reply to PDF/DOCX/TXT, main padh kar jawab dungi

📝 <b>PERSONAL</b>
/note [text] – Note save karo
/notes – Sab notes dekho
/remind [time] [text] – Reminder (e.g. 1h, 30m)
/reminders – Reminder list
/afk [reason] – AFK mode
/info – User info (reply)
/level – Apna level dekho

🎮 <b>GAMING</b>
/game – Apna profile
/bal – Balance check
/daily – Daily reward
/work – Kaam karo
/crime – Risky crime
/rob – Kisi ko looto (reply)
/kill – Kisi ko maaro (reply)
/heal – Health badhao
/revive – Zinda karo (reply, cost $500)
/protect – 24h protection ($500)
/give [amount] – Paisa do (reply, 10% tax)
/lb – Leaderboard

💰 <b>CASINO</b>
/slots – Slot machine (cost 50 chips)
/blackjack – Blackjack vs Alita
/roulette [color/number] – Roulette
/dice – Roll dice
/chips – Apne casino chips check karo

⚙️ <b>CUSTOM COMMANDS (Admins)</b>
/addcmd !cmd response – Custom command add
/delcmd !cmd – Delete custom command
/cmdlist – List custom commands

🛡️ <b>ADMIN (groups only)</b>
/warn [reason] – Warn (reply)
/kick – Kick (reply)
/ban – Ban (reply)
/unban – Unban (reply)
/mute [time] – Mute (reply)
/unmute – Unmute (reply)
/pin – Pin (reply)
/unpin – Unpin
/slowmode [sec] – Slow mode
/tagall – Sabko mention
/rules – Group rules
/setwelcome [text] – Custom welcome
/setgoodbye [text] – Custom goodbye
/antiraid [on/off] – Anti-raid mode

💻 <b>ADVANCED (Owner only)</b>
/run [code] – Execute Python
/shell [cmd] – Shell command
/file [list|read|write|delete] – File manager
/pip [install|list] – Install packages
/sysinfo – System info
/json – Format JSON
/hash – Generate hashes
/base64 – Encode/decode
/regex – Test regex
/backup – Backup database
/restore – Restore database
/sendall – Broadcast message (reply)

🔒 <b>AUTO‑MOD</b>
• Bad words filter
• Adult content → auto‑ban
• Group link block
• Spam detection
• Fake link block
• Caps lock flood
• Emoji spam
• 3 warns = mute

🏡 <b>MY HOME:</b> @abhi0w0
"""
    await message.reply(text, parse_mode="HTML")

# ---------- AI CHAT ----------
@dp.message(Command("ask"))
async def ask_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Kya puchna hai? Example: <code>/ask India ki capital kya hai?</code>")
        return
    if message.chat.type == "private" and REQUIRED_CHANNEL:
        if not await is_user_in_channel(message.from_user.id, REQUIRED_CHANNEL):
            await message.reply(f"❌ Pehle {REQUIRED_CHANNEL} join karo!")
            return
    await bot.send_chat_action(message.chat.id, "typing")
    await asyncio.sleep(0.5)
    reply = await generate_ai_response(message.chat.id, command.args, message.from_user.id)
    conversation_history[message.chat.id].append({"role": "user", "content": command.args})
    conversation_history[message.chat.id].append({"role": "assistant", "content": reply})
    await message.reply(reply, parse_mode="HTML")

@dp.message(Command("clear"))
async def clear_cmd(message: Message):
    conversation_history[message.chat.id].clear()
    await message.reply(f"{random_emoji('happy')} Memory clear kar di! 🧹")

@dp.message(Command("providers"))
async def providers_cmd(message: Message, command: CommandObject):
    user_id = message.from_user.id
    if command.args:
        req = command.args.lower()
        if req in G4F_PROVIDERS:
            user_ai_preference[user_id] = req
            user_g4f_provider[user_id] = req
            await message.reply(f"✅ Switched to <b>{G4F_PROVIDERS[req]['name']}</b>!")
        else:
            avail = ", ".join(G4F_PROVIDERS.keys())
            await message.reply(f"❌ Provider not found. Available: {avail}")
    else:
        current = user_ai_preference.get(user_id, "groq")
        text = "🆓 <b>Free AI Providers:</b>\n\n"
        for key, info in G4F_PROVIDERS.items():
            mark = "✅" if key == current else "⬜"
            text += f"{mark} <b>{info['name']}</b> (<code>{key}</code>)\n"
        text += f"\n<i>Current: {G4F_PROVIDERS[current]['name']}</i>\n\nUse <code>/providers groq</code> to switch."
        await message.reply(text, parse_mode="HTML")

@dp.message(Command("mood"))
async def mood_cmd(message: Message, command: CommandObject):
    user_id = message.from_user.id
    if command.args:
        req = command.args.lower()
        if req in MOODS:
            user_mood[user_id]["mood"] = req
            user_mood[user_id]["history"].append(req)
            await message.reply(f"🎭 Mood changed to <b>{req.upper()}</b> {MOODS[req]['emoji']}\n\n{random.choice(MOODS[req]['expressions'])}")
        else:
            await message.reply(f"Available moods: {', '.join(MOODS.keys())}")
    else:
        mood = user_mood[user_id]["mood"]
        info = MOODS[mood]
        await message.reply(f"🎭 <b>Current Mood:</b> {mood.upper()} {info['emoji']}\n{info['tone']}")

@dp.message(Command("creative"))
async def creative_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Kya likhna hai? Example: <code>/creative ek love story</code>")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    prompt = f"Creative writing in Hinglish: {command.args}. Make it engaging, emotional, and detailed."
    system = get_alita_prompt_with_mood("playful", "Creative writing")
    reply = await call_g4f(prompt, message.from_user.id, system_prompt=system) or \
            await call_groq(prompt, system) or \
            "❌ Creative block! Thodi der mein try karo."
    await message.reply(reply[:4000], parse_mode="HTML")

@dp.message(Command("analyze"))
async def analyze_cmd(message: Message, command: CommandObject):
    content = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not content:
        await message.reply("Please provide text or reply to a message.")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    prompt = f"Analyze the following in Hinglish, point out key aspects, quality, suggestions:\n\n{content[:3000]}"
    system = get_alita_prompt_with_mood("curious", "Analyzing")
    reply = await call_g4f(prompt, message.from_user.id, system) or await call_groq(prompt, system) or "Analysis failed."
    await message.reply(reply[:4000], parse_mode="HTML")

@dp.message(Command("debug"))
async def debug_cmd(message: Message, command: CommandObject):
    code = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not code:
        await message.reply("Please paste code or reply to a message with code.")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    prompt = f"Debug this code, list bugs, provide fixed code:\n\n{code[:3000]}"
    system = get_alita_prompt_with_mood("confident", "Debugging")
    reply = await call_g4f(prompt, message.from_user.id, system) or await call_groq(prompt, system) or "Debug failed."
    await message.reply(reply[:4000], parse_mode="HTML")

@dp.message(Command("explain"))
async def explain_cmd(message: Message, command: CommandObject):
    topic = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not topic:
        await message.reply("Kya explain karun?")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    prompt = f"Explain this topic in simple Hinglish with examples:\n\n{topic[:3000]}"
    system = get_alita_prompt_with_mood("curious", "Explaining")
    reply = await call_g4f(prompt, message.from_user.id, system) or await call_groq(prompt, system) or "Explain nahi ho paya."
    await message.reply(reply[:4000], parse_mode="HTML")

@dp.message(Command("remember"))
async def remember_cmd(message: Message, command: CommandObject):
    if not command.args or ' ' not in command.args:
        await message.reply("Usage: /remember key value")
        return
    key, value = command.args.split(' ', 1)
    await remember_user(message.from_user.id, key, value)
    await message.reply(f"✅ Yaad rakha: <b>{key}</b> = {value[:50]}...")

@dp.message(Command("recall"))
async def recall_cmd(message: Message, command: CommandObject):
    if not command.args:
        all_mem = await recall_all_user(message.from_user.id)
        if all_mem:
            text = "🧠 <b>Aapki yaadein:</b>\n\n"
            for k, v in list(all_mem.items())[:10]:
                text += f"• <b>{k}</b>: {v[:100]}\n"
            await message.reply(text, parse_mode="HTML")
        else:
            await message.reply("❌ Kuch yaad nahi rakha hai.")
        return
    key = command.args.strip()
    value = await recall_user(message.from_user.id, key)
    if value:
        await message.reply(f"🧠 <b>{key}</b>: {value}", parse_mode="HTML")
    else:
        await message.reply(f"❌ '{key}' nahi mila.")

# ---------- UTILITIES ----------
@dp.message(Command("weather"))
async def weather_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("City name do! Example: <code>/weather Mumbai</code>")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    weather = await get_weather(command.args)
    await message.reply(weather, parse_mode="HTML")

@dp.message(Command("time"))
async def time_cmd(message: Message):
    now = indian_now()
    await message.reply(
        f"🕒 <b>Indian Time:</b> {now.strftime('%I:%M %p')}\n"
        f"📅 <b>Date:</b> {now.strftime('%A, %d %B %Y')}\n"
        f"{random_emoji('happy')}",
        parse_mode="HTML"
    )

@dp.message(Command("date"))
async def date_cmd(message: Message):
    now = indian_now()
    await message.reply(f"📆 <b>{now.strftime('%A, %d %B %Y')}</b>\n{random_emoji('happy')}", parse_mode="HTML")

@dp.message(Command("qr"))
async def qr_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Text do! Example: <code>/qr Hello World</code>")
        return
    qr_bytes = generate_qr(command.args)
    await message.reply_photo(
        BufferedInputFile(qr_bytes, filename="qr.png"),
        caption="✅ QR Code ready!"
    )

@dp.message(Command("scanqr"))
async def scanqr_cmd(message: Message):
    if not PYZBAR_AVAILABLE:
        await message.reply("❌ QR scan feature temporarily unavailable (pyzbar not installed on server).")
        return
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply("Reply to a photo containing a QR code.")
        return
    photo = message.reply_to_message.photo[-1]
    file = await bot.get_file(photo.file_id)
    photo_bytes = await file.download_as_bytearray()
    qr_data = await scan_qr(photo_bytes)
    if qr_data:
        await message.reply(f"✅ <b>QR Code Data:</b>\n<code>{qr_data}</code>", parse_mode="HTML")
    else:
        await message.reply("❌ No QR code found or unable to decode.")

@dp.message(Command("translate"))
async def translate_cmd(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        await message.reply("Usage: <code>/translate hi Hello</code>")
        return
    parts = command.args.split(maxsplit=1)
    lang, text = parts[0], parts[1]
    translated = await translate_text(text, lang)
    await message.reply(f"🌍 <b>Translation ({lang.upper()}):</b>\n{translated}", parse_mode="HTML")

@dp.message(Command("math"))
async def math_cmd(message: Message, command: CommandObject):
    expr = command.args
    if not expr:
        await message.reply("Usage: <code>/math 2+2</code> or <code>/math solve x**2-4=0</code>")
        return
    try:
        x, y, z = symbols('x y z')
        if expr.lower().startswith('solve '):
            eq = expr[6:].strip()
            if '=' in eq:
                parts = eq.split('=')
                eq = f"({parts[0]}) - ({parts[1]})"
            result = solve(sympify(eq))
            await message.reply(f"🔢 Solution: <code>{result}</code>", parse_mode="HTML")
        elif expr.lower().startswith('diff '):
            result = diff(sympify(expr[5:]), x)
            await message.reply(f"🔢 Derivative: <code>{result}</code>", parse_mode="HTML")
        elif expr.lower().startswith('integrate '):
            result = integrate(sympify(expr[10:]), x)
            await message.reply(f"🔢 Integral: <code>{result} + C</code>", parse_mode="HTML")
        else:
            result = sympify(expr).evalf()
            await message.reply(f"🔢 Result: <code>{result}</code>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Math error: {str(e)[:200]}")

@dp.message(Command("shorten"))
async def shorten_cmd(message: Message, command: CommandObject):
    url = command.args
    if not url:
        await message.reply("Usage: <code>/shorten https://example.com</code>")
        return
    short = await shorten_url(url)
    await message.reply(f"🔗 Short URL: {short}")

@dp.message(Command("password"))
async def password_cmd(message: Message, command: CommandObject):
    length = 12
    if command.args:
        try:
            length = int(command.args)
            length = max(4, min(64, length))
        except:
            pass
    pwd = generate_password(length)
    await message.reply(f"🔐 <b>Password:</b> <code>{pwd}</code>", parse_mode="HTML")

@dp.message(Command("wiki"))
async def wiki_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Kya search karun? Example: <code>/wiki Albert Einstein</code>")
        return
    summary = await get_wikipedia_summary(command.args)
    if summary:
        await message.reply(summary, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await message.reply("❌ Wikipedia pe nahi mila.")

@dp.message(Command("define"))
async def define_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Word do! Example: <code>/define serendipity</code>")
        return
    definition = await get_dictionary_definition(command.args)
    if definition:
        await message.reply(definition, parse_mode="HTML")
    else:
        await message.reply("❌ Dictionary me nahi mila.")

@dp.message(Command("news"))
async def news_cmd(message: Message, command: CommandObject):
    category = command.args or 'in'
    news = await get_news(category)
    await message.reply(news, parse_mode="HTML", disable_web_page_preview=True)

@dp.message(Command("currency"))
async def currency_cmd(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    if len(args) != 3:
        await message.reply("Usage: <code>/currency 100 USD INR</code>")
        return
    try:
        amount = float(args[0])
        from_curr = args[1].upper()
        to_curr = args[2].upper()
    except:
        await message.reply("Invalid amount.")
        return
    result = await get_currency_conversion(amount, from_curr, to_curr)
    await message.reply(result, parse_mode="HTML")

@dp.message(Command("stock"))
async def stock_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Symbol do! Example: <code>/stock AAPL</code>")
        return
    price = await get_stock_price(command.args)
    await message.reply(price, parse_mode="HTML")

@dp.message(Command("crypto"))
async def crypto_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Coin do! Example: <code>/crypto bitcoin</code>")
        return
    price = await get_crypto_price(command.args.lower())
    await message.reply(price, parse_mode="HTML")

# ---------- MUSIC & YOUTUBE ----------
@dp.message(Command("yt"))
async def yt_audio_cmd(message: Message, command: CommandObject):
    if not YTDLP_AVAILABLE:
        await message.reply("❌ yt-dlp not installed.")
        return
    url = command.args
    if not url:
        await message.reply("YouTube URL do!")
        return
    status = await message.reply("🎵 Downloading audio...")
    audio_bytes = await download_youtube(url, 'audio')
    if audio_bytes:
        await status.delete()
        await message.reply_audio(
            BufferedInputFile(audio_bytes, filename="audio.mp3"),
            title="Audio from YouTube"
        )
    else:
        await status.edit_text("❌ Download failed.")

@dp.message(Command("ytvideo"))
async def yt_video_cmd(message: Message, command: CommandObject):
    if not YTDLP_AVAILABLE:
        await message.reply("❌ yt-dlp not installed.")
        return
    url = command.args
    if not url:
        await message.reply("YouTube URL do!")
        return
    status = await message.reply("🎬 Downloading video...")
    video_bytes = await download_youtube(url, 'video')
    if video_bytes:
        await status.delete()
        await message.reply_video(
            BufferedInputFile(video_bytes, filename="video.mp4")
        )
    else:
        await status.edit_text("❌ Download failed.")

# ---------- VOICE TRANSCRIPTION ----------
@dp.message(F.voice)
async def voice_handler(message: Message):
    if not groq_client:
        await message.reply("❌ Groq API key missing, can't transcribe.")
        return
    status = await message.reply("🎤 Transcribing...")
    file = await bot.get_file(message.voice.file_id)
    ogg_bytes = await file.download_as_bytearray()
    text = await transcribe_voice(ogg_bytes)
    if text:
        await status.edit_text(f"🗣 <b>Transcription:</b>\n{text}", parse_mode="HTML")
    else:
        await status.edit_text("❌ Transcription failed.")

# ---------- FILE CHAT ----------
@dp.message(F.document)
async def document_handler(message: Message):
    doc = message.document
    ext = doc.file_name.split('.')[-1].lower()
    if ext not in ['txt', 'pdf', 'docx']:
        await message.reply("❌ Only TXT, PDF, DOCX supported.")
        return
    status = await message.reply("📄 Reading file...")
    file = await bot.get_file(doc.file_id)
    file_bytes = await file.download_as_bytearray()
    text = await extract_text_from_file(file_bytes, ext)
    if text:
        await status.edit_text("🧠 Processing with AI...")
        prompt = f"Yeh user ne ek file upload ki hai. Iska content analyze karo aur user ke sawal ka jawab do. Agar koi sawal nahi hai to summary do.\n\nFile content:\n{text[:4000]}"
        reply = await generate_ai_response(message.chat.id, prompt, message.from_user.id)
        await message.reply(reply[:4000], parse_mode="HTML")
    else:
        await status.edit_text("❌ Unable to read file.")

# ---------- NOTES ----------
@dp.message(Command("note"))
async def note_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Note kya save karun? Example: <code>/note Milk lena</code>")
        return
    if USE_MONGODB:
        db.notes.insert_one({
            "user_id": message.from_user.id,
            "note_text": command.args,
            "created_at": indian_now()
        })
    else:
        cursor.execute(
            "INSERT INTO notes (user_id, note_text, created_at) VALUES (?, ?, ?)",
            (message.from_user.id, command.args, indian_now())
        )
        conn.commit()
    await message.reply(f"{random_emoji('happy')} <b>Note saved!</b> 📝", parse_mode="HTML")

@dp.message(Command("notes"))
async def notes_cmd(message: Message):
    user_id = message.from_user.id
    if USE_MONGODB:
        notes = db.notes.find({"user_id": user_id}).sort("created_at", -1).limit(20)
        rows = list(notes)
    else:
        cursor.execute(
            "SELECT note_text, created_at FROM notes WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
            (user_id,)
        )
        rows = cursor.fetchall()
    if not rows:
        await message.reply("Koi note nahi hai. <code>/note</code> se add karo.", parse_mode="HTML")
        return
    text = "📋 <b>Your Notes:</b>\n\n"
    for i, row in enumerate(rows, 1):
        if USE_MONGODB:
            time_str = row['created_at'].strftime('%d/%m %I:%M %p')
            note = row['note_text']
        else:
            time_str = datetime.fromisoformat(row['created_at']).strftime('%d/%m %I:%M %p')
            note = row['note_text']
        text += f"{i}. {note} — <i>{time_str}</i>\n"
    await message.reply(text, parse_mode="HTML")

# ---------- REMINDERS ----------
@dp.message(Command("remind"))
async def remind_cmd(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        await message.reply("Usage: <code>/remind 1h Call mom</code>")
        return
    args = command.args.split(maxsplit=1)
    time_str, text = args[0], args[1]
    minutes = 0
    if time_str.endswith('h'):
        minutes = int(time_str[:-1]) * 60
    elif time_str.endswith('m'):
        minutes = int(time_str[:-1])
    else:
        await message.reply("Time format: <code>30m</code> (minutes) ya <code>1h</code> (hours)")
        return
    remind_at = indian_now() + timedelta(minutes=minutes)
    if USE_MONGODB:
        db.reminders.insert_one({
            "user_id": message.from_user.id,
            "chat_id": message.chat.id,
            "reminder_text": text,
            "remind_at": remind_at,
            "created_at": indian_now()
        })
    else:
        cursor.execute(
            "INSERT INTO reminders (user_id, chat_id, reminder_text, remind_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (message.from_user.id, message.chat.id, text, remind_at, indian_now())
        )
        conn.commit()
    await message.reply(
        f"{random_emoji('happy')} <b>Reminder set!</b> ⏰\n{text} – {remind_at.strftime('%I:%M %p')}",
        parse_mode="HTML"
    )

@dp.message(Command("reminders"))
async def reminders_cmd(message: Message):
    now = indian_now()
    user_id = message.from_user.id
    if USE_MONGODB:
        reminders = db.reminders.find({"user_id": user_id, "remind_at": {"$gt": now}}).sort("remind_at")
        rows = list(reminders)
    else:
        cursor.execute(
            "SELECT id, reminder_text, remind_at FROM reminders WHERE user_id = ? AND remind_at > ? ORDER BY remind_at",
            (user_id, now)
        )
        rows = cursor.fetchall()
    if not rows:
        await message.reply("Koi active reminder nahi.")
        return
    text = "⏰ <b>Your Reminders:</b>\n\n"
    for row in rows:
        if USE_MONGODB:
            due = row['remind_at'].strftime('%d/%m %I:%M %p')
            reminder = row['reminder_text']
        else:
            due = datetime.fromisoformat(row['remind_at']).strftime('%d/%m %I:%M %p')
            reminder = row['reminder_text']
        text += f"• {reminder} — <i>{due}</i>\n"
    await message.reply(text, parse_mode="HTML")

# ---------- AFK ----------
@dp.message(Command("afk"))
async def afk_cmd(message: Message, command: CommandObject):
    reason = command.args or "AFK"
    user_afk[message.from_user.id] = {"reason": reason, "since": indian_now()}
    await message.reply(f"{random_emoji('sleepy')} <b>AFK mode ON</b>\nReason: {reason}", parse_mode="HTML")

# ---------- INFO ----------
@dp.message(Command("info"))
async def info_cmd(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    text = f"👤 <b>User Info</b>\n🆔 ID: <code>{target.id}</code>\n📛 Name: {target.full_name}\n📱 Username: @{target.username if target.username else 'N/A'}\n"
    if message.chat.type in ('group', 'supergroup'):
        try:
            member = await bot.get_chat_member(message.chat.id, target.id)
            text += f"🏷️ Status: {member.status.capitalize()}\n"
        except:
            pass
    await message.reply(text, parse_mode="HTML")

# ---------- LEVEL ----------
@dp.message(Command("level"))
async def level_cmd(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    info = await get_level_info(user_id, chat_id)
    xp = info['xp']
    level = info['level']
    next_xp = (level + 1) ** 2
    await message.reply(
        f"📊 <b>Level {level}</b>\nXP: {xp} / {next_xp}\n"
        f"{random_emoji('happy')} Chat karte raho, level up hoga!",
        parse_mode="HTML"
    )

# ---------- GAMING COMMANDS ----------
# (All gaming commands are the same as before, but with HTML parse_mode)
# For brevity, I'll include only essential ones; you can copy from previous version.

@dp.message(Command("game"))
async def game_cmd(message: Message):
    user_id = message.from_user.id
    user = message.from_user
    if USE_MONGODB:
        player = db.game_data.find_one({"user_id": user_id})
        if not player:
            player = {
                "user_id": user_id, "name": user.first_name, "balance": 1000,
                "rank": 142415, "status": "alive", "kills": 0, "deaths": 0,
                "health": 100, "protected": False
            }
            db.game_data.insert_one(player)
    else:
        player = game_data[user_id]
        player['name'] = user.first_name
    profile = f"""🎮 <b>ALITA GAME</b> 🎮

👤 Name: {player.get('name', user.first_name)}
💰 Balance: ${player.get('balance', 1000)}
🏆 Rank: {player.get('rank', 142415)}
❤️ Status: {player.get('status', 'alive')}
⚔️ Kills: {player.get('kills', 0)}
💀 Deaths: {player.get('deaths', 0)}
❤️ Health: {player.get('health', 100)}%

Commands: /bal /daily /work /crime /rob /kill /heal /revive /protect /give /lb"""
    await message.reply(profile, parse_mode="HTML")

# ... (Include all other gaming commands from previous version with HTML parse_mode)
# To keep this message under length limit, I'm omitting them but you can copy from the earlier full code.

# ---------- CUSTOM COMMANDS ----------
@dp.message(Command("addcmd"))
async def addcmd_cmd(message: Message, command: CommandObject):
    # Owner can always add, group admins can add in their groups
    if message.chat.type not in ('group', 'supergroup') and message.from_user.id != ADMIN_ID:
        await message.reply("❌ Yeh command sirf groups mein ya owner ke liye hai.")
        return
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not command.args or ' ' not in command.args:
        await message.reply("Usage: <code>/addcmd !hi Hello there!</code>")
        return
    cmd, resp = command.args.split(' ', 1)
    if not cmd.startswith('!'):
        await message.reply("Command must start with '!'")
        return
    await set_custom_command(message.chat.id, cmd, resp, message.from_user.id)
    await message.reply(f"✅ Custom command <code>{cmd}</code> added!", parse_mode="HTML")

@dp.message(Command("delcmd"))
async def delcmd_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    cmd = command.args
    if not cmd:
        await message.reply("Usage: <code>/delcmd !hi</code>")
        return
    await delete_custom_command(message.chat.id, cmd)
    await message.reply(f"✅ Custom command <code>{cmd}</code> deleted!", parse_mode="HTML")

@dp.message(Command("cmdlist"))
async def cmdlist_cmd(message: Message):
    cmds = await list_custom_commands(message.chat.id)
    if cmds:
        await message.reply(f"📋 <b>Custom Commands:</b>\n{', '.join(cmds)}", parse_mode="HTML")
    else:
        await message.reply("No custom commands.")

# ---------- ADMIN COMMANDS (Groups) ----------
@dp.message(Command("tagall"))
async def tagall_cmd(message: Message):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not await is_bot_admin(message.chat.id):
        await message.reply("Mujhe group admin banana padega tagall ke liye.")
        return
    members = []
    try:
        async for member in bot.get_chat_members(message.chat.id):
            if not member.user.is_bot:
                mention = f"<a href='tg://user?id={member.user.id}'>{member.user.first_name}</a>"
                members.append(mention)
                if len(members) >= 50:
                    break
    except Exception as e:
        await message.reply(f"❌ Members fetch nahi ho paaye: {e}")
        return
    if not members:
        await message.reply("Koi member nahi mila tag karne ke liye.")
        return
    for i in range(0, len(members), 10):
        chunk = members[i:i+10]
        await message.reply(" ".join(chunk), parse_mode="HTML")
        await asyncio.sleep(1)

@dp.message(Command("adminlist"))
async def adminlist_cmd(message: Message):
    if message.chat.type not in ('group', 'supergroup'):
        await message.reply("Yeh command sirf groups mein chalegi.")
        return
    admins = await get_group_admins(message.chat.id)
    if not admins:
        await message.reply("Koi admin nahi mila?")
        return
    text = "👑 <b>Group Admins:</b>\n"
    for aid in admins:
        try:
            member = await bot.get_chat_member(message.chat.id, aid)
            name = member.user.full_name
            status = "👑 Creator" if member.status == "creator" else "🛡️ Admin"
            text += f"\n{status} – {name}"
        except:
            text += f"\n• <code>{aid}</code>"
    await message.reply(text, parse_mode="HTML")

@dp.message(Command("warn"))
async def warn_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not message.reply_to_message:
        await message.reply("Kisi user ke message pe reply karo.")
        return
    await delete_and_warn(message.reply_to_message, "manual_warning")

@dp.message(Command("kick"))
async def kick_cmd(message: Message):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply karo user ko kick karne ke liye.")
        return
    target = message.reply_to_message.from_user
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"{random_emoji('angry')} {target.first_name} ko kick kar diya!")
    except Exception as e:
        await message.reply(f"Kick nahi kar paai: {e}")

@dp.message(Command("ban"))
async def ban_cmd(message: Message):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply karo user ko ban karne ke liye.")
        return
    target = message.reply_to_message.from_user
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await message.reply(f"{random_emoji('angry')} {target.first_name} permanently banned!")
    except Exception as e:
        await message.reply(f"Ban nahi kar paai: {e}")

@dp.message(Command("unban"))
async def unban_cmd(message: Message):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply karo user ke message pe unban karne ke liye.")
        return
    target = message.reply_to_message.from_user
    try:
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"{random_emoji('happy')} {target.first_name} ka ban hata diya!")
    except Exception as e:
        await message.reply(f"Unban failed: {e}")

@dp.message(Command("mute"))
async def mute_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply karo user ko mute karne ke liye.")
        return
    target = message.reply_to_message.from_user
    duration = command.args
    minutes = 60
    if duration:
        if duration.endswith('h'):
            minutes = int(duration[:-1]) * 60
        elif duration.endswith('m'):
            minutes = int(duration[:-1])
    until = indian_now() + timedelta(minutes=minutes)
    try:
        await bot.restrict_chat_member(
            message.chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await message.reply(f"{random_emoji('angry')} {target.first_name} muted for {minutes} minutes!")
    except Exception as e:
        await message.reply(f"Mute failed: {e}")

@dp.message(Command("unmute"))
async def unmute_cmd(message: Message):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply karo user ko unmute karne ke liye.")
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
                can_add_web_page_previews=True
            )
        )
        await message.reply(f"{random_emoji('happy')} {target.first_name} unmuted!")
    except Exception as e:
        await message.reply(f"Unmute failed: {e}")

@dp.message(Command("pin"))
async def pin_cmd(message: Message):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply karo us message pe jo pin karna hai.")
        return
    try:
        await bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
        await message.reply("📌 Pinned!")
    except Exception as e:
        await message.reply(f"Pin failed: {e}")

@dp.message(Command("unpin"))
async def unpin_cmd(message: Message):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    try:
        await bot.unpin_chat_message(message.chat.id)
        await message.reply("📍 Unpinned!")
    except Exception as e:
        await message.reply(f"Unpin failed: {e}")

@dp.message(Command("slowmode"))
async def slowmode_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    delay = 0
    if command.args:
        try:
            delay = int(command.args)
        except:
            pass
    try:
        await bot.set_chat_slow_mode_delay(message.chat.id, delay)
        if delay == 0:
            await message.reply("⏱️ Slow mode disabled!")
        else:
            await message.reply(f"⏱️ Slow mode enabled: {delay} seconds.")
    except Exception as e:
        await message.reply(f"Slow mode change failed: {e}")

@dp.message(Command("rules"))
async def rules_cmd(message: Message):
    rules = f"""
{random_emoji('protective')} <b>📜 GROUP RULES</b>

✅ <b>DO:</b>
• Respect everyone
• Keep chat friendly
• Help each other

🚫 <b>DON'T:</b>
• No spam
• No bad language
• No adult content → auto‑ban
• No group links
• No fake links

🔒 <b>I'm here to protect the group!</b>
"""
    await message.reply(rules, parse_mode="HTML")

@dp.message(Command("setwelcome"))
async def setwelcome_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not command.args:
        await message.reply("Welcome message do! Use <code>{name}</code> for user's name.")
        return
    await db_update_group(message.chat.id, {"custom_welcome": command.args})
    await message.reply("✅ Custom welcome message set!")

@dp.message(Command("setgoodbye"))
async def setgoodbye_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not command.args:
        await message.reply("Goodbye message do! Use <code>{name}</code> for user's name.")
        return
    await db_update_group(message.chat.id, {"custom_goodbye": command.args})
    await message.reply("✅ Custom goodbye message set!")

@dp.message(Command("antiraid"))
async def antiraid_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admins only.")
        return
    if not command.args or command.args.lower() not in ['on', 'off']:
        await message.reply("Usage: <code>/antiraid on|off</code>")
        return
    enabled = 1 if command.args.lower() == 'on' else 0
    await db_update_group(message.chat.id, {"anti_raid_enabled": enabled})
    status = "✅ Anti-raid mode <b>ON</b>" if enabled else "✅ Anti-raid mode <b>OFF</b>"
    await message.reply(status, parse_mode="HTML")

# ---------- OWNER COMMANDS ----------
async def owner_only(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ Yeh command sirf meri jaan ke liye hai.")
        return False
    return True

@dp.message(Command("run"))
async def run_cmd(message: Message, command: CommandObject):
    if not await owner_only(message): return
    code = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not code:
        await message.reply("Usage: <code>/run print('hello')</code>")
        return
    code = code.strip('```python\n').strip('```').strip()
    old_stdout, old_stderr = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(old_stdout), redirect_stderr(old_stderr):
            exec_globals = {"__builtins__": __builtins__}
            exec(code, exec_globals)
        output = old_stdout.getvalue()
        error = old_stderr.getvalue()
        resp = ""
        if output:
            resp += f"📤 Output:\n<pre>{output[:3000]}</pre>\n"
        if error:
            resp += f"⚠️ Stderr:\n<pre>{error[:1000]}</pre>\n"
        if not resp:
            resp = "✅ Executed (no output)"
        await message.reply(resp, parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error:\n<pre>{traceback.format_exc()[:3000]}</pre>", parse_mode="HTML")

@dp.message(Command("shell"))
async def shell_cmd(message: Message, command: CommandObject):
    if not await owner_only(message): return
    cmd = command.args
    if not cmd:
        await message.reply("Usage: <code>/shell ls -la</code>")
        return
    dangerous = ['rm -rf', 'mkfs', 'dd if=', ':(){', 'chmod -R 777 /']
    if any(d in cmd for d in dangerous):
        await message.reply("⛔ Dangerous command blocked!")
        return
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        out = f"📤 Output:\n<pre>{result.stdout[:3000]}</pre>\n" if result.stdout else ""
        err = f"⚠️ Stderr:\n<pre>{result.stderr[:1000]}</pre>\n" if result.stderr else ""
        if not out and not err:
            out = f"✅ Exit code: {result.returncode}"
        await message.reply(out + err, parse_mode="HTML")
    except subprocess.TimeoutExpired:
        await message.reply("⏰ Timeout!")
    except Exception as e:
        await message.reply(f"❌ {str(e)[:500]}")

@dp.message(Command("file"))
async def file_cmd(message: Message, command: CommandObject):
    if not await owner_only(message): return
    args = command.args.split() if command.args else []
    if not args:
        await message.reply("Usage: <code>/file list|read|write|delete</code>")
        return
    action = args[0].lower()
    try:
        if action == "list":
            path = args[1] if len(args) > 1 else "."
            files = os.listdir(path)
            flist = "\n".join([f"{'📁' if os.path.isdir(os.path.join(path,f)) else '📄'} {f}" for f in files[:50]])
            await message.reply(f"📁 <b>{path}</b>\n<pre>{flist}</pre>", parse_mode="HTML")
        elif action == "read":
            if len(args) < 2: return
            with open(args[1], 'r') as f:
                content = f.read()
            await message.reply(f"📄 <b>{args[1]}</b>\n<pre>{content[:3500]}</pre>", parse_mode="HTML")
        elif action == "write":
            if len(args) < 3: return
            filename = args[1]
            content = ' '.join(args[2:])
            with open(filename, 'w') as f:
                f.write(content)
            await message.reply(f"✅ Written to {filename}")
        elif action == "delete":
            if len(args) < 2: return
            os.remove(args[1])
            await message.reply(f"✅ Deleted {args[1]}")
    except Exception as e:
        await message.reply(f"❌ {str(e)[:500]}")

@dp.message(Command("pip"))
async def pip_cmd(message: Message, command: CommandObject):
    if not await owner_only(message): return
    args = command.args.split() if command.args else []
    if not args:
        await message.reply("Usage: <code>/pip install|list|uninstall</code>")
        return
    action = args[0].lower()
    try:
        if action == "install":
            pkg = args[1]
            await message.reply(f"📦 Installing {pkg}...")
            result = subprocess.run([sys.executable, "-m", "pip", "install", pkg], capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                await message.reply(f"✅ Installed {pkg}")
            else:
                await message.reply(f"❌ Failed:\n<pre>{result.stderr[:1000]}</pre>", parse_mode="HTML")
        elif action == "list":
            result = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True, timeout=30)
            await message.reply(f"📦 <b>Packages</b>\n<pre>{result.stdout[:3500]}</pre>", parse_mode="HTML")
        elif action == "uninstall":
            pkg = args[1]
            result = subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", pkg], capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                await message.reply(f"✅ Uninstalled {pkg}")
            else:
                await message.reply(f"❌ Failed:\n<pre>{result.stderr[:1000]}</pre>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ {str(e)[:500]}")

@dp.message(Command("sysinfo"))
async def sysinfo_cmd(message: Message):
    if not await owner_only(message): return
    info = f"""
💻 <b>System Info</b>
🖥️ Platform: {platform.system()} {platform.release()}
🔧 Arch: {platform.machine()}
🐍 Python: {platform.python_version()}
📁 CWD: {os.getcwd()}
"""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        info += f"⚡ CPU: {cpu}%\n🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%\n"
    except:
        pass
    info += f"\n🆙 Uptime: {indian_now() - bot_start_time}"
    await message.reply(info, parse_mode="HTML")

@dp.message(Command("json"))
async def json_cmd(message: Message, command: CommandObject):
    if not await owner_only(message): return
    text = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not text:
        await message.reply("Usage: <code>/json {'key':'value'}</code>")
        return
    try:
        data = json.loads(text)
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        await message.reply(f"📋 <b>JSON</b>\n<pre>{pretty[:3500]}</pre>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Invalid JSON: {str(e)}")

@dp.message(Command("hash"))
async def hash_cmd(message: Message, command: CommandObject):
    if not await owner_only(message): return
    text = command.args
    if not text:
        await message.reply("Usage: <code>/hash hello</code>")
        return
    md5 = hashlib.md5(text.encode()).hexdigest()
    sha1 = hashlib.sha1(text.encode()).hexdigest()
    sha256 = hashlib.sha256(text.encode()).hexdigest()
    sha512 = hashlib.sha512(text.encode()).hexdigest()
    await message.reply(
        f"🔐 <b>Hashes</b>\nMD5: <code>{md5}</code>\nSHA1: <code>{sha1}</code>\n"
        f"SHA256: <code>{sha256}</code>\nSHA512: <code>{sha512[:64]}...</code>",
        parse_mode="HTML"
    )

@dp.message(Command("base64"))
async def base64_cmd(message: Message, command: CommandObject):
    if not await owner_only(message): return
    args = command.args.split() if command.args else []
    if len(args) < 2:
        await message.reply("Usage: <code>/base64 encode Hello</code> or <code>/base64 decode SGVsbG8=</code>")
        return
    action, text = args[0], ' '.join(args[1:])
    try:
        if action == "encode":
            result = base64.b64encode(text.encode()).decode()
            await message.reply(f"🔄 Encoded:\n<code>{result}</code>", parse_mode="HTML")
        elif action == "decode":
            result = base64.b64decode(text.encode()).decode()
            await message.reply(f"🔄 Decoded:\n<code>{result}</code>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ {str(e)}")

@dp.message(Command("regex"))
async def regex_cmd(message: Message, command: CommandObject):
    if not await owner_only(message): return
    if not command.args or '|||' not in command.args:
        await message.reply("Usage: <code>/regex pattern ||| test_string</code>")
        return
    parts = command.args.split('|||', 1)
    pattern, test = parts[0].strip(), parts[1].strip()
    try:
        matches = re.findall(pattern, test)
        if matches:
            await message.reply(f"🔤 Pattern: <code>{pattern}</code>\nMatches: {matches[:20]}\n✅ {len(matches)} found", parse_mode="HTML")
        else:
            await message.reply(f"🔤 Pattern: <code>{pattern}</code>\n❌ No matches", parse_mode="HTML")
    except re.error as e:
        await message.reply(f"❌ Invalid regex: {e}")

@dp.message(Command("backup"))
async def backup_cmd(message: Message):
    if not await owner_only(message): return
    if USE_MONGODB:
        await message.reply("MongoDB backup not implemented in this version.")
    else:
        with open("alita_ultimate.db", "rb") as f:
            db_bytes = f.read()
        await message.reply_document(
            BufferedInputFile(db_bytes, filename=f"backup_{indian_now().strftime('%Y%m%d')}.db")
        )

@dp.message(Command("restore"))
async def restore_cmd(message: Message):
    if not await owner_only(message): return
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply("Reply to a backup file.")
        return
    file = await bot.get_file(message.reply_to_message.document.file_id)
    db_bytes = await file.download_as_bytearray()
    with open("alita_ultimate.db", "wb") as f:
        f.write(db_bytes)
    await message.reply("✅ Database restored. Please restart bot.")

@dp.message(Command("sendall"))
async def sendall_cmd(message: Message):
    if not await owner_only(message): return
    if not message.reply_to_message:
        await message.reply("Kisi message pe reply karo broadcast karne ke liye.")
        return
    status = await message.reply("📤 Broadcasting...")
    sent = 0
    failed = 0
    if USE_MONGODB:
        users = db.users.find()
        for user in users:
            try:
                await bot.copy_message(user['user_id'], message.chat.id, message.reply_to_message.message_id)
                sent += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1
        groups = db.groups.find()
        for group in groups:
            try:
                await bot.copy_message(group['chat_id'], message.chat.id, message.reply_to_message.message_id)
                sent += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1
    else:
        cursor.execute("SELECT user_id FROM users")
        for row in cursor.fetchall():
            try:
                await bot.copy_message(row['user_id'], message.chat.id, message.reply_to_message.message_id)
                sent += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1
        cursor.execute("SELECT chat_id FROM groups")
        for row in cursor.fetchall():
            try:
                await bot.copy_message(row['chat_id'], message.chat.id, message.reply_to_message.message_id)
                sent += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1
    await status.edit_text(f"✅ Broadcast done!\nSent: {sent}\nFailed: {failed}")

# ---------- IMAGINE (AI Image Generation) ----------
@dp.message(Command("imagine"))
async def imagine_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Prompt do! Example: <code>/imagine sunset mountains</code>")
        return
    status = await message.reply(f"{random_emoji('happy')} Image bana rahi hu... 🎨")
    img_bytes = await generate_image(command.args)
    if img_bytes:
        await status.delete()
        await message.reply_photo(
            BufferedInputFile(img_bytes, filename="alita_ai.png"),
            caption=f"<b>Your image:</b> {command.args}",
            parse_mode="HTML"
        )
    else:
        await status.edit_text(f"{random_emoji('crying')} Image nahi ban paai, try again!")

@dp.message(Command("fact"))
async def fact_cmd(message: Message):
    facts = [
        "🍯 Honey kabhi kharab nahi hota – 3000 saal purana honey bhi kha sakte ho!",
        "🐙 Octopus ke 3 dil hote hain!",
        "🍌 Banana ek berry hai, strawberry nahi!",
        "🦈 Sharks pehle aaye, trees baad mein!",
        "🧠 Human brain 20% energy use karta hai!",
        "🦋 Butterflies taste with their feet!",
        "💩 Wombat poop cube shaped hota hai!",
    ]
    await message.reply(f"📌 <b>Daily Fact:</b>\n{random.choice(facts)}\n\n{random_emoji('thinking')}", parse_mode="HTML")

@dp.message(Command("horoscope"))
async def horoscope_cmd(message: Message, command: CommandObject):
    signs = {
        "aries": "♈ Aries – Aaj energy full hai! Naye kaam shuru karo.",
        "taurus": "♉ Taurus – Paisa aane ki sambhavna hai. Dhyan rakho.",
        "gemini": "♊ Gemini – Baat cheet se kaam banega.",
        "cancer": "♋ Cancer – Ghar parivar ke saath time bitao.",
        "leo": "♌ Leo – Leadership milegi. Confidence dikhao.",
        "virgo": "♍ Virgo – Detail pe focus se safalta.",
        "libra": "♎ Libra – Balance bana ke rakho.",
        "scorpio": "♏ Scorpio – Intuition strong hai, bharosa karo.",
        "sagittarius": "♐ Sagittarius – Naye jagah jaane ka plan banao.",
        "capricorn": "♑ Capricorn – Mehnat rang layegi.",
        "aquarius": "♒ Aquarius – Naye ideas aayenge.",
        "pisces": "♓ Pisces – Creativity boost pe hai."
    }
    if not command.args:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(f"{s.capitalize()}", callback_data=f"horo_{s}") for s in list(signs)[:4]],
            [InlineKeyboardButton(f"{s.capitalize()}", callback_data=f"horo_{s}") for s in list(signs)[4:8]],
            [InlineKeyboardButton(f"{s.capitalize()}", callback_data=f"horo_{s}") for s in list(signs)[8:]]
        ])
        await message.reply(f"{random_emoji('surprise')} <b>Apni rashi choose karo:</b>", reply_markup=kb)
        return
    sign = command.args.lower()
    if sign in signs:
        await message.reply(f"{signs[sign]}\n\n{random_emoji('love')}", parse_mode="HTML")
    else:
        await message.reply(f"{random_emoji('crying')} Yeh rashi nahi mili. Aries, Taurus, etc. likho.")

@dp.message(Command("lyrics"))
async def lyrics_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Song name do! Example: <code>/lyrics Shape of You</code>")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    lyrics = await get_lyrics(command.args)
    await message.reply(f"🎶 <b>{command.args}</b>\n\n{lyrics[:3500]}", parse_mode="HTML", disable_web_page_preview=True)

# ---------- MESSAGE HANDLER (AI + MOD + XP + CUSTOM CMDS) ----------
@dp.message()
async def message_handler(message: Message):
    if message.from_user.id == bot.id:
        return

    # Update user activity
    await db_update_user(message.from_user.id, {
        "first_name": message.from_user.first_name,
        "username": message.from_user.username
    })

    # Update group info
    if message.chat.type in ('group', 'supergroup'):
        await db_update_group(message.chat.id, {"title": message.chat.title})

    # ---- Custom Commands ----
    if message.text and message.text.startswith('!'):
        cmd = message.text.split()[0].lower()
        response = await get_custom_command(message.chat.id, cmd)
        if response:
            await message.reply(response)
            return

    # ---- AFK check ----
    if message.from_user.id in user_afk:
        del user_afk[message.from_user.id]
        await message.reply(f"{random_emoji('happy')} Welcome back! AFK hata diya.")

    # ---- Creator detection ----
    if message.text:
        msg_lower = message.text.lower()
        for kw in CREATOR_KEYWORDS:
            if kw in msg_lower:
                await message.reply(
                    "🥰😊\n\nMujhe mere bhagwan ne banaya hai <b>Abhi</b> ne (<a href='tg://user?id=7746694924'>@a6h1ii</a>) 🙏✨\n"
                    "Woh mere creator hain, bahut talented devloper hain! 💖🎀",
                    parse_mode="HTML"
                )
                return

    # ---- Gaming keyword auto-response (groups) ----
    if message.chat.type in ('group','supergroup') and message.text and not message.text.startswith('/'):
        msg_lower = message.text.lower()
        for cat, words in GAMING_KEYWORDS.items():
            for word in words:
                if word in msg_lower:
                    react_key = cat.replace("_words", "_reaction")
                    if react_key in GAMING_REACTIONS:
                        react = random.choice(GAMING_REACTIONS[react_key])
                        await message.reply(react, parse_mode="HTML")
                    return

    # ---- AUTO MODERATION (groups) ----
    if message.chat.type in ('group','supergroup') and message.text:
        group = await db_get_group(message.chat.id)
        if group and group.get('auto_mod_enabled', 1):
            if await is_spam(message.chat.id, message.from_user.id):
                await delete_and_warn(message, "spam")
                return
            if contains_bad_words(message.text):
                await delete_and_warn(message, "bad_words")
                return
            if contains_adult(message.text):
                await delete_and_warn(message, "adult_content")
                return
            if contains_group_link(message.text):
                await delete_and_warn(message, "link")
                return
            if contains_fake_link(message.text):
                await delete_and_warn(message, "fake_links")
                return
            # Caps lock flood
            if message.text.isupper() and len(message.text) > 20:
                await delete_and_warn(message, "caps_flood")
                return
            # Emoji spam
            emoji_count = sum(1 for c in message.text if c in EMOTION_SETS_ALL)
            if emoji_count > 15:
                await delete_and_warn(message, "emoji_spam")
                return

    # ---- CAPTCHA answer check ----
    if message.from_user.id in captcha_store and message.reply_to_message and message.reply_to_message.from_user.id == bot.id:
        correct = captcha_store[message.from_user.id].get('answer')
        if message.text.strip() == correct:
            del captcha_store[message.from_user.id]
            await message.reply(f"{random_emoji('happy')} ✅ CAPTCHA passed! Welcome!", parse_mode="HTML")
            return
        else:
            await message.reply(f"{random_emoji('angry')} ❌ Wrong answer! Try again.", parse_mode="HTML")
            return

    # ---- XP System (silent) ----
    if message.text and not message.text.startswith('/'):
        await add_xp(message.from_user.id, message.chat.id)

    # ---- AI RESPONSE (private, reply, mention) ----
    is_private = message.chat.type == "private"
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot.id
    is_mention = False
    if BOT_USERNAME and message.text:
        if f"@{BOT_USERNAME}" in message.text.lower():
            is_mention = True

    # Private chat channel check
    if is_private and REQUIRED_CHANNEL:
        if not await is_user_in_channel(message.from_user.id, REQUIRED_CHANNEL):
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔔 Join Channel", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
                [InlineKeyboardButton(text="✅ I've Joined", callback_data="check_join")]
            ])
            await message.reply(
                f"❌ <b>{message.from_user.first_name}</b>, is bot ko use karne ke liye pehle hamare channel ko join karo!\n\n👉 {REQUIRED_CHANNEL}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return

    if is_private or is_reply_to_bot or is_mention:
        await bot.send_chat_action(message.chat.id, "typing")
        await asyncio.sleep(random.uniform(0.5, 1.2))
        user_text = message.text or ""
        if BOT_USERNAME:
            user_text = re.sub(f"@{BOT_USERNAME}", "", user_text, flags=re.IGNORECASE).strip()
        if not user_text:
            user_text = "Hii"
        if saved_stickers and random.random() < 0.20:
            sticker = random.choice(saved_stickers)
            await bot.send_sticker(message.chat.id, sticker)
            await asyncio.sleep(0.3)
        reply = await generate_ai_response(message.chat.id, user_text, message.from_user.id)
        conversation_history[message.chat.id].append({"role": "user", "content": user_text})
        conversation_history[message.chat.id].append({"role": "assistant", "content": reply})
        await message.reply(reply, parse_mode="HTML")

# -------------------- Chat Member Handler (Welcome/Goodbye/CAPTCHA) --------------------
@dp.chat_member()
async def chat_member_handler(update: ChatMemberUpdated):
    if update.new_chat_member.status == "member":
        group = await db_get_group(update.chat.id)
        if not group:
            return
        # Anti-raid check
        if await is_raid_mode(update.chat.id):
            try:
                await bot.ban_chat_member(update.chat.id, update.new_chat_member.user.id)
                await bot.send_message(
                    update.chat.id,
                    f"🛡️ <b>Anti-Raid Mode:</b> {update.new_chat_member.user.first_name} auto-banned!",
                    parse_mode="HTML"
                )
                return
            except:
                pass
        if group.get('captcha_enabled', 0):
            num1 = random.randint(1,20)
            num2 = random.randint(1,20)
            op = random.choice(['+','-','*'])
            if op == '+':
                ans = num1 + num2
            elif op == '-':
                ans = num1 - num2
                if ans < 0:
                    num1, num2 = num2, num1
                    ans = num1 - num2
            else:
                ans = num1 * num2
            question = f"{num1} {op} {num2} = ?"
            captcha_store[update.new_chat_member.user.id] = {"answer": str(ans), "chat_id": update.chat.id}
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("I'm human!", callback_data=f"captcha_{update.new_chat_member.user.id}")]
            ])
            await bot.send_message(
                update.chat.id,
                f"🧩 <b>CAPTCHA Verification</b>\nWelcome {update.new_chat_member.user.first_name}!\nSolve: {question}",
                reply_markup=kb,
                parse_mode="HTML"
            )
            return
        if group.get('welcome_enabled', 1):
            if group.get('custom_welcome'):
                msg = group['custom_welcome'].replace("{name}", update.new_chat_member.user.first_name)
            else:
                wel = ["🎉 Welcome {name}!", "🌟 Aao ji {name}!", "🥳 {name} aa gaye!", "🌸 Namaste {name}!"]
                msg = random.choice(wel).format(name=update.new_chat_member.user.first_name)
            await bot.send_message(update.chat.id, msg + f" {random_emoji('happy')}", parse_mode="HTML")
    elif update.new_chat_member.status in ("left","kicked"):
        group = await db_get_group(update.chat.id)
        if group and group.get('goodbye_enabled', 1):
            if group.get('custom_goodbye'):
                msg = group['custom_goodbye'].replace("{name}", update.old_chat_member.user.first_name)
            else:
                bye = ["👋 {name} left. Take care!", "😔 {name} chale gaye!", "💔 {name} is no longer with us."]
                msg = random.choice(bye).format(name=update.old_chat_member.user.first_name)
            await bot.send_message(update.chat.id, msg + f" {random_emoji('crying')}", parse_mode="HTML")

# -------------------- Callback Handlers --------------------
@dp.callback_query()
async def callback_handler(callback: CallbackQuery):
    data = callback.data
    if data.startswith("horo_"):
        sign = data[5:]
        await horoscope_cmd(callback.message, CommandObject(args=sign))
        await callback.answer()
    elif data.startswith("captcha_"):
        user_id = int(data[8:])
        if callback.from_user.id != user_id:
            await callback.answer("Yeh CAPTCHA aapke liye nahi hai!", show_alert=True)
            return
        if user_id in captcha_store:
            q = "Solve the math problem above."
            await callback.message.edit_text(
                f"🧩 <b>Solve this CAPTCHA:</b>\n{q}\n\nReply with your answer.",
                parse_mode="HTML"
            )
        else:
            await callback.answer("CAPTCHA expire ho gayi!", show_alert=True)
    elif data == "menu_util":
        await callback.message.edit_text(
            "📱 <b>Utilities</b>\n"
            "/weather – Weather\n"
            "/time – Indian time\n"
            "/date – Date\n"
            "/qr – QR code\n"
            "/scanqr – Scan QR\n"
            "/translate – Translate\n"
            "/shorten – URL shortener\n"
            "/password – Strong password\n"
            "/wiki – Wikipedia\n"
            "/define – Dictionary\n"
            "/news – News\n"
            "/currency – Currency converter\n"
            "/stock – Stock price\n"
            "/crypto – Crypto price",
            parse_mode="HTML"
        )
    elif data == "menu_fun":
        await callback.message.edit_text(
            "🎭 <b>Fun</b>\n"
            "/imagine – AI image\n"
            "/fact – Daily fact\n"
            "/horoscope – Rashifal\n"
            "/lyrics – Song lyrics\n"
            "/creative – Creative writing",
            parse_mode="HTML"
        )
    elif data == "menu_safety":
        await callback.message.edit_text(
            "🛡️ <b>Safety</b>\n"
            "• Auto spam block\n"
            "• Bad words filter\n"
            "• Adult content = ban\n"
            "• Group link block\n"
            "• Fake link block\n"
            "• Caps lock flood\n"
            "• Emoji spam\n"
            "• 3 warns = mute",
            parse_mode="HTML"
        )
    elif data == "menu_game":
        await callback.message.edit_text(
            "🎮 <b>Gaming</b>\n"
            "/game – Profile\n"
            "/bal – Balance\n"
            "/daily – Daily\n"
            "/work – Work\n"
            "/crime – Crime\n"
            "/rob – Rob\n"
            "/kill – Kill\n"
            "/heal – Heal\n"
            "/revive – Revive\n"
            "/protect – 24h protection\n"
            "/give – Give money\n"
            "/lb – Leaderboard",
            parse_mode="HTML"
        )
    elif data == "menu_providers":
        await providers_cmd(callback.message, CommandObject(args=""))
    elif data == "talk":
        await callback.message.edit_text(
            f"{random_emoji('love')} Haan ji, main yahan hoon! Kya baat karni hai? Mujhe mention karo ya reply karo.",
            parse_mode="HTML"
        )
    elif data == "stats":
        uptime = indian_now() - bot_start_time
        if USE_MONGODB:
            users = db.users.count_documents({})
            groups = db.groups.count_documents({})
        else:
            cursor.execute("SELECT COUNT(*) FROM users")
            users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM groups")
            groups = cursor.fetchone()[0]
        msg = f"📊 <b>Alita Stats</b>\n\n👥 Users: {users}\n👥 Groups: {groups}\n⏰ Uptime: {uptime}"
        await callback.message.edit_text(msg, parse_mode="HTML")
    await callback.answer()

# -------------------- Web Server --------------------
async def health_check(request):
    uptime = indian_now() - bot_start_time
    return web.Response(text=f"🤖 Alita Ultimate is alive! Uptime: {uptime}")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Web server running on port {PORT}")

# -------------------- Spam Detection Helpers --------------------
def is_spam(chat_id: int, user_id: int) -> bool:
    now = indian_now()
    timestamps = spam_tracker[chat_id][user_id]
    timestamps.append(now)
    spam_tracker[chat_id][user_id] = [ts for ts in timestamps if (now - ts).seconds <= 30]
    return len(spam_tracker[chat_id][user_id]) > 7

def contains_bad_words(text: str) -> bool:
    t = text.lower()
    return any(word in t for word in BAD_WORDS)

def contains_adult(text: str) -> bool:
    t = text.lower()
    return any(word in t for word in ADULT_KEYWORDS)

def contains_group_link(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in GROUP_LINK_PATTERNS)

def contains_fake_link(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in FAKE_LINK_PATTERNS)

EMOTION_SETS_ALL = set(c for lst in [
    "😀","😁","😂","😃","😄","😅","😆","😉","😊","😋","😎","😍","😘","😗","😙","😚","🙂","🤗","🤩","🤔","🤨","😐","😑","😶","🙄","😏","😣","😥","😮","🤐","😯","😪","😫","😴","😌","😛","😜","😝","🤤","😒","😓","😔","😕","🙃","🤑","😲","☹️","🙁","😖","😞","😟","😤","😢","😭","😦","😧","😨","😩","🤯","😬","😰","😱","🥵","🥶","😳","🤪","😵","😡","😠","🤬","😷","🤒","🤕","🤢","🤮","🤧","😇","🥳","🥺","🤠","🤡","🤥","🤫","🤭","🧐","🤓"
] for c in lst)

# -------------------- Main --------------------
async def main():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username
    print(f"🤖 Bot: @{BOT_USERNAME} (ID: {me.id})")
    print(f"🎨 Stickers loaded: {len(saved_stickers)}")
    print(f"🧠 Groq available: {groq_client is not None}")
    print(f"🆓 g4f available: {G4F_AVAILABLE}")
    print(f"📦 MongoDB: {'Enabled' if USE_MONGODB else 'Disabled (using SQLite)'}")
    print(f"🎥 yt-dlp: {'Available' if YTDLP_AVAILABLE else 'Not installed'}")
    print(f"📄 PDF/DOCX: {'Available' if PDF_AVAILABLE or DOCX_AVAILABLE else 'Not installed'}")
    print(f"🔳 QR scan: {'Available' if PYZBAR_AVAILABLE else 'Not installed'}")

    # Scheduler jobs
    scheduler.add_job(send_time_greetings, CronTrigger(hour=7, minute=0, timezone=INDIAN_TZ), id="morning")
    scheduler.add_job(send_time_greetings, CronTrigger(hour=12, minute=0, timezone=INDIAN_TZ), id="afternoon")
    scheduler.add_job(send_time_greetings, CronTrigger(hour=18, minute=0, timezone=INDIAN_TZ), id="evening")
    scheduler.add_job(send_time_greetings, CronTrigger(hour=22, minute=0, timezone=INDIAN_TZ), id="night")
    scheduler.add_job(send_random_sticker_job, CronTrigger(hour="*/3", minute="0"), id="random_sticker")
    scheduler.add_job(check_reminders, CronTrigger(second="*/30"), id="reminders")
    scheduler.start()

    await start_web_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
