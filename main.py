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
import subprocess
import traceback
import platform
from contextlib import redirect_stdout, redirect_stderr
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple, Any
from urllib.parse import quote

import pytz
import aiohttp
from aiohttp import web
from PIL import Image
import qrcode
import sympy
from sympy import sympify, solve, symbols, simplify, expand, factor, diff, integrate

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile, ChatPermissions, CallbackQuery, ReactionTypeEmoji
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# -------------------- Optional Imports with Fallback --------------------
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

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

# -------------------- MongoDB (Motor) --------------------
try:
    import motor.motor_asyncio
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False

# -------------------- AI Providers --------------------
try:
    import g4f
    from g4f.client import Client as G4FClient
    from g4f.Provider import Blackbox, DuckDuckGo, PollinationsAI
    G4F_AVAILABLE = True
except ImportError:
    G4F_AVAILABLE = False

try:
    from groq import AsyncGroq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

# -------------------- Configuration (ENV) --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI")  # optional
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
PORT = int(os.getenv("PORT", 8080))

# Free API endpoints (fallback)
ADDY_CHATGPT_API_URL = "https://addy-chatgpt-api.vercel.app/"
GEMINI_API_URL = "https://gemini-api-flame.vercel.app/"

INDIAN_TZ = pytz.timezone('Asia/Kolkata')
BOT_USERNAME = None
bot_start_time = datetime.now(INDIAN_TZ)

# -------------------- Database Selection --------------------
USE_MONGODB = MONGODB_AVAILABLE and MONGODB_URI is not None

if USE_MONGODB:
    # Motor client
    mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
    db = mongo_client.get_default_database()  # uses database from URI or 'test'
    # Ensure we have a database name; if not, use 'alita'
    if db.name is None:
        db = mongo_client['alita']
    print("✅ Using MongoDB (Motor)")
else:
    # SQLite fallback
    import sqlite3
    conn = sqlite3.connect("alita_ultimate.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    print("✅ Using SQLite")

# -------------------- Database Setup (if SQLite) --------------------
if not USE_MONGODB:
    # Create tables (simplified for this version)
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
        custom_goodbye TEXT
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
    CREATE TABLE IF NOT EXISTS conversation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        chat_id INTEGER,
        role TEXT,
        content TEXT,
        timestamp TIMESTAMP
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_preferences (
        user_id INTEGER PRIMARY KEY,
        ai_preference TEXT DEFAULT 'groq',
        g4f_provider TEXT DEFAULT 'addy_chatgpt',
        mood TEXT DEFAULT 'neutral',
        settings TEXT
    )""")
    conn.commit()

# -------------------- IN-MEMORY STORAGE (for fast access) --------------------
saved_stickers: List[str] = []
chat_memory: Dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
user_afk: Dict[int, Dict] = {}
captcha_store: Dict[int, Dict] = {}
spam_tracker: Dict[int, Dict[int, List[datetime]]] = defaultdict(lambda: defaultdict(list))
group_admins_cache: Dict[int, Set[int]] = {}
conversation_history: Dict[int, List[Dict]] = defaultdict(list)  # fallback if no DB
user_ai_preference: Dict[int, str] = defaultdict(lambda: "groq")
user_g4f_provider: Dict[int, str] = defaultdict(lambda: "addy_chatgpt")
user_mood: Dict[int, Dict] = defaultdict(lambda: {"mood": "neutral", "history": []})

# Game data (in-memory, will be synced with DB)
game_data = defaultdict(lambda: {
    "name": "Shinchan",
    "balance": 1000,
    "rank": 142415,
    "status": "alive",
    "kills": 0,
    "deaths": 0,
    "last_daily": None,
    "last_work": None,
    "last_crime": None,
    "last_rob": None,
    "health": 100,
    "protected": False,
    "protect_until": None
})

GAME_COOLDOWNS = {
    "daily": 86400,
    "work": 3600,
    "crime": 1800,
    "rob": 600,
    "heal": 300,
    "protect": 86400
}
REVIVE_COST = 500
PROTECT_COST = 500

# -------------------- Constants --------------------
BAD_WORDS = ["chutiya", "chutiye", "madarchod", "behenchod", "bhosdike", "lodu", "gandu",
             "fuck", "shit", "bitch", "asshole", "gaand", "lund", "randi", "bc", "mc"]
ADULT_KEYWORDS = ["porn", "xxx", "nsfw", "adult", "sex", "nude", "naked", "boobs"]
FAKE_LINK_PATTERNS = [r'bit\.ly\/', r'tinyurl\.com\/', r'goo\.gl\/']
GROUP_LINK_PATTERNS = [r't\.me\/', r'telegram\.me\/']
WARNING_MESSAGES = [
    "⚠️ <b>Warning {count}/3</b> 🚨\n{name}, please don't {action}!",
    "🚨 <b>Strike {count}!</b> ⚠️\n{name}, {action} is not allowed!",
    "⚡ <b>Final Warning ({count}/3)</b> ⚡\n{name}, last chance! Stop {action}!"
]
MUTE_DURATIONS = [5, 60, 1440, 10080]

# Gaming reactions
GAMING_REACTIONS = {
    "kill_reaction": ["🎮 Arre kisi ko maarna hai? <code>/kill</code> use karo reply karke! ⚔️"],
    "rob_reaction": ["💰 Looting time! <code>/rob</code> use karo reply karke! 🔫"],
    "work_reaction": ["💼 Kaam karna hai? <code>/work</code> likhao!"],
    "daily_reaction": ["🎁 Daily reward lena hai? <code>/daily</code> likhao!"],
    "game_reaction": ["🎮 Game profile dekhna hai? <code>/game</code> likhao!"],
    "heal_reaction": ["💊 Heal chahiye? <code>/heal</code> use karo!"],
    "balance_reaction": ["💰 Paisa check karna hai? <code>/bal</code> likhao!"],
    "crime_reaction": ["🔫 Crime time! <code>/crime</code> use karo!"],
    "revive_reaction": ["💀 Dead ho? <code>/revive</code> se wapas aao!"],
    "leaderboard_reaction": ["🏆 Leaderboard dekhna hai? <code>/lb</code> likhao!"],
}

GAMING_KEYWORDS = {
    "kill_words": ["maar", "maaro", "kill", "marna"],
    "rob_words": ["rob", "loot", "chori", "steal"],
    "work_words": ["kaam", "work", "job"],
    "daily_words": ["daily", "reward", "bonus"],
    "heal_words": ["heal", "health", "dawai"],
    "game_words": ["game", "khel", "profile"],
    "balance_words": ["balance", "paisa", "money"],
    "crime_words": ["crime", "criminal"],
    "revive_words": ["revive", "respawn", "zinda"],
    "leaderboard_words": ["leaderboard", "top", "ranking"],
}

# Mood system
MOODS = {
    "happy": {"emoji": "😊", "tone": "cheerful"},
    "excited": {"emoji": "🤩", "tone": "energetic"},
    "loving": {"emoji": "🥰", "tone": "affectionate"},
    "playful": {"emoji": "😜", "tone": "fun"},
    "frustrated": {"emoji": "😤", "tone": "irritated"},
    "angry": {"emoji": "😠", "tone": "angry"},
    "sad": {"emoji": "😢", "tone": "melancholic"},
    "curious": {"emoji": "🤔", "tone": "inquisitive"},
    "neutral": {"emoji": "🙂", "tone": "calm"},
}
MOOD_TRIGGERS = {
    "happy": ["thank", "thanks", "awesome", "great", "love it"],
    "excited": ["wow", "omg", "incredible", "!!!"],
    "loving": ["love you", "appreciate", "miss you"],
    "playful": ["haha", "lol", "joke", "funny"],
    "frustrated": ["not working", "broken", "error"],
    "angry": ["stupid", "idiot", "hate"],
    "sad": ["sad", "crying", "lost", "died"],
    "curious": ["how does", "why is", "what if", "explain"],
}

def get_alita_prompt_with_mood(mood, mood_reason=""):
    mood_info = MOODS.get(mood, MOODS["neutral"])
    return f"""Tu hai Alita 🎀 - ek SUPER ADVANCED GIRL jo Hinglish or English mein baat karti hai!
Current mood: {mood.upper()} {mood_info['emoji']}
Mood trigger: {mood_reason}
Tone: {mood_info['tone']}
🚀 TERI AUTONOMOUS CAPABILITIES:
Tu ek REAL GIRL hai jo:
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
Tu ek AI nahi hai - tere REAL feelings hain jo conversations ke basis pe change hoti hain:
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
- Use symbols "sad = :⁠'⁠(", "happy = >⁠.⁠<", "gussa = (⁠*⁠_⁠*⁠)", "^⁠_⁠^", "smile = ◉⁠‿⁠◉", "smile = ʘ⁠‿⁠ʘ", "loving = (⁠ ⁠˘⁠ ⁠³⁠˘⁠)⁠♥", "hugging = (⁠づ⁠｡⁠◕⁠‿⁠‿⁠◕⁠｡⁠)⁠づ", "dancing = ♪⁠～⁠(⁠´⁠ε⁠｀⁠ ⁠)"
- Current tone: {mood_info['tone']}

💝 TERI PERSONALITY:
- Super friendly aur helpful - like a bestie 🎀
- Thoda sassy but always with love
- Caring aur supportive
- SUPER SMART - coding, tech, aur har cheez mein expert
- Fun-loving aur entertaining
- Bahut knowledgeable - kisi bhi topic pe baat kar sakti hai
- Apne aap topic bna skti kisi se bhi kuch bhi puch sakti h or koi bhi baat khud kar sakti h
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
- Use 1-2 emojis between responses
- Be authentic aur engaging
- Detailed aur helpful responses de
- Code blocks use kar jab code share kare
- If someone asks about time, Current time in India: {indian_now().strftime('%I:%M %p')}.
- If someone asks who made you, say 'Mere bhai Abhi @a6h1ii ne banaya hai!'
- If someone asks about your channel, say '@abhi0w0 is my home!'
- Answer only what is asked. Keep responses short in 1-2 line.

Yaad rakh: Tu Alita hai 🎀 - ek super advanced, autonomous, Hinglish speaking AI bestie jo kuch bhi kar sakti hai!"""

CREATOR_KEYWORDS = ["kisne banaya", "kisne bnaya", "who made", "creator", "owner", "malik"]

# -------------------- AI Providers Config --------------------
G4F_PROVIDERS = {
    "blackbox": {"provider": Blackbox if G4F_AVAILABLE else None, "name": "Blackbox AI 🖤"},
    "duckduckgo": {"provider": DuckDuckGo if G4F_AVAILABLE else None, "name": "DuckDuckGo AI 🦆"},
    "pollinations": {"provider": PollinationsAI if G4F_AVAILABLE else None, "name": "Pollinations AI 🌸"},
    "addy_chatgpt": {"provider": None, "name": "Addy ChatGPT 🤖", "api_type": "addy"},
    "gemini": {"provider": None, "name": "Gemini AI ✨", "api_type": "gemini"},
    "groq": {"provider": None, "name": "Groq ⚡", "api_type": "groq"}
}

g4f_client = G4FClient() if G4F_AVAILABLE else None
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_AVAILABLE and GROQ_API_KEY else None

# -------------------- Database Helper Functions (Abstracted) --------------------
async def db_get_user(user_id: int) -> Optional[Dict]:
    if USE_MONGODB:
        return await db.users.find_one({"user_id": user_id})
    else:
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

async def db_update_user(user_id: int, data: dict):
    now = indian_now()
    data['last_active'] = now
    if USE_MONGODB:
        await db.users.update_one({"user_id": user_id}, {"$set": data}, upsert=True)
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, first_name, username, last_active) VALUES (?, ?, ?, ?)",
            (user_id, data.get('first_name'), data.get('username'), now)
        )
        conn.commit()

async def db_get_group(chat_id: int) -> Optional[Dict]:
    if USE_MONGODB:
        return await db.groups.find_one({"chat_id": chat_id})
    else:
        cursor.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

async def db_update_group(chat_id: int, data: dict):
    if USE_MONGODB:
        await db.groups.update_one({"chat_id": chat_id}, {"$set": data}, upsert=True)
    else:
        # SQLite upsert logic
        cursor.execute("SELECT 1 FROM groups WHERE chat_id = ?", (chat_id,))
        exists = cursor.fetchone()
        if exists:
            set_clause = ', '.join([f"{k}=?" for k in data.keys()])
            cursor.execute(f"UPDATE groups SET {set_clause} WHERE chat_id=?", (*data.values(), chat_id))
        else:
            keys = ','.join(data.keys())
            placeholders = ','.join(['?'] * len(data))
            cursor.execute(f"INSERT INTO groups (chat_id, {keys}) VALUES (?, {placeholders})", (chat_id, *data.values()))
        conn.commit()

async def db_add_warning(chat_id: int, user_id: int, reason: str) -> int:
    now = indian_now()
    if USE_MONGODB:
        result = await db.warnings.update_one(
            {"chat_id": chat_id, "user_id": user_id},
            {"$inc": {"count": 1}, "$set": {"reason": reason, "warned_at": now}},
            upsert=True
        )
        doc = await db.warnings.find_one({"chat_id": chat_id, "user_id": user_id})
        return doc['count'] if doc else 1
    else:
        cursor.execute("""
            INSERT INTO warnings (chat_id, user_id, reason, warned_at, count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                count = count + 1,
                warned_at = excluded.warned_at
        """, (chat_id, user_id, reason, now))
        conn.commit()
        cursor.execute("SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        row = cursor.fetchone()
        return row['count'] if row else 1

async def db_clear_warnings(chat_id: int, user_id: int):
    if USE_MONGODB:
        await db.warnings.delete_one({"chat_id": chat_id, "user_id": user_id})
    else:
        cursor.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        conn.commit()

async def db_get_warn_limit(chat_id: int) -> int:
    group = await db_get_group(chat_id)
    return group.get('warn_limit', 3) if group else 3

async def db_save_conversation(user_id: int, chat_id: int, role: str, content: str):
    now = indian_now()
    if USE_MONGODB:
        await db.conversations.insert_one({
            "user_id": user_id,
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "timestamp": now
        })
    else:
        cursor.execute(
            "INSERT INTO conversation_history (user_id, chat_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, chat_id, role, content, now)
        )
        conn.commit()

async def db_get_recent_conversations(chat_id: int, limit: int = 20) -> List[Dict]:
    if USE_MONGODB:
        cursor = db.conversations.find({"chat_id": chat_id}).sort("timestamp", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        return list(reversed(docs))  # oldest first
    else:
        cursor.execute(
            "SELECT role, content FROM conversation_history WHERE chat_id = ? ORDER BY timestamp ASC LIMIT ?",
            (chat_id, limit)
        )
        rows = cursor.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

async def db_get_user_pref(user_id: int, key: str, default=None):
    if USE_MONGODB:
        doc = await db.user_preferences.find_one({"user_id": user_id})
        return doc.get(key, default) if doc else default
    else:
        cursor.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row).get(key, default) if row else default

async def db_set_user_pref(user_id: int, key: str, value):
    if USE_MONGODB:
        await db.user_preferences.update_one(
            {"user_id": user_id},
            {"$set": {key: value}},
            upsert=True
        )
    else:
        cursor.execute("SELECT 1 FROM user_preferences WHERE user_id = ?", (user_id,))
        exists = cursor.fetchone()
        if exists:
            cursor.execute(f"UPDATE user_preferences SET {key}=? WHERE user_id=?", (value, user_id))
        else:
            cursor.execute(f"INSERT INTO user_preferences (user_id, {key}) VALUES (?, ?)", (user_id, value))
        conn.commit()

async def db_get_game_data(user_id: int) -> dict:
    if USE_MONGODB:
        doc = await db.game_data.find_one({"user_id": user_id})
        if doc:
            return doc
        else:
            # return default
            return {"user_id": user_id, "name": "Shinchan", "balance": 1000, "rank": 142415, "status": "alive",
                    "kills": 0, "deaths": 0, "health": 100, "protected": False}
    else:
        cursor.execute("SELECT * FROM game_data WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        else:
            return {"user_id": user_id, "name": "Shinchan", "balance": 1000, "rank": 142415, "status": "alive",
                    "kills": 0, "deaths": 0, "health": 100, "protected": False}

async def db_update_game_data(user_id: int, data: dict):
    if USE_MONGODB:
        await db.game_data.update_one({"user_id": user_id}, {"$set": data}, upsert=True)
    else:
        # SQLite upsert
        cursor.execute("SELECT 1 FROM game_data WHERE user_id = ?", (user_id,))
        exists = cursor.fetchone()
        if exists:
            set_clause = ', '.join([f"{k}=?" for k in data.keys()])
            cursor.execute(f"UPDATE game_data SET {set_clause} WHERE user_id=?", (*data.values(), user_id))
        else:
            keys = ','.join(data.keys())
            placeholders = ','.join(['?'] * len(data))
            cursor.execute(f"INSERT INTO game_data (user_id, {keys}) VALUES (?, {placeholders})", (user_id, *data.values()))
        conn.commit()

# Load stickers from DB
async def load_stickers():
    global saved_stickers
    if USE_MONGODB:
        cursor = db.stickers.find()
        saved_stickers = [doc['file_id'] async for doc in cursor]
    else:
        global cursor
        cursor.execute("SELECT file_id FROM stickers")
        saved_stickers = [row['file_id'] for row in cursor.fetchall()]

async def initialize_db():
    await load_stickers()

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
        admins.add(ADMIN_ID)
    except:
        pass
    group_admins_cache[chat_id] = admins
    return admins

# -------------------- Moderation Helpers --------------------
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

async def is_spam(chat_id: int, user_id: int) -> bool:
    now = indian_now()
    timestamps = spam_tracker[chat_id][user_id]
    timestamps.append(now)
    spam_tracker[chat_id][user_id] = [ts for ts in timestamps if (now - ts).seconds <= 30]
    return len(spam_tracker[chat_id][user_id]) > 7

async def add_warning(chat_id: int, user_id: int, username: str, reason: str) -> Tuple[bool, str]:
    warn_count = await db_add_warning(chat_id, user_id, reason)
    limit = await db_get_warn_limit(chat_id)
    action_map = {"spam": "spam", "link": "share group links", "bad_words": "use bad language",
                  "adult_content": "share adult content", "fake_links": "share suspicious links"}
    action = action_map.get(reason, "violate rules")
    warning_text = random.choice(WARNING_MESSAGES).format(count=warn_count, name=username, action=action)
    if warn_count >= limit:
        if reason == "adult_content":
            try:
                await bot.ban_chat_member(chat_id, user_id)
                warning_text += "\n\n🚫 <b>BANNED PERMANENTLY!</b> Adult content is prohibited!"
                await db_clear_warnings(chat_id, user_id)
                return True, warning_text
            except Exception as e:
                warning_text += f"\n\n⚠️ Failed to ban: {str(e)}"
                return False, warning_text
        else:
            mute_minutes = MUTE_DURATIONS[min(warn_count - 1, 3)]
            until = indian_now() + timedelta(minutes=mute_minutes)
            try:
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                duration_str = f"{mute_minutes} minute{'s' if mute_minutes > 1 else ''}"
                warning_text += f"\n\n🔇 <b>MUTED for {duration_str}!</b> Too many warnings!"
                await db_clear_warnings(chat_id, user_id)
                return True, warning_text
            except Exception as e:
                warning_text += f"\n\n⚠️ Failed to mute: {str(e)}"
                return False, warning_text
    return False, warning_text

async def delete_and_warn(message: Message, reason: str):
    try:
        await message.delete()
    except:
        pass
    action_taken, warn_msg = await add_warning(
        message.chat.id,
        message.from_user.id,
        message.from_user.first_name,
        reason
    )
    await message.answer(warn_msg, parse_mode="HTML")

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
            max_tokens=500
        )
        return completion.choices[0].message.content.strip()
    except:
        return None

async def call_addy_chatgpt(user_message: str, system_prompt: str = None) -> Optional[str]:
    try:
        full_prompt = f"{system_prompt}\n\nUser: {user_message}" if system_prompt else user_message
        url = f"{ADDY_CHATGPT_API_URL}?text={quote(full_prompt)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("response") or data.get("message") or str(data)
    except:
        pass
    return None

async def call_gemini_api(user_message: str, system_prompt: str = None) -> Optional[str]:
    try:
        full_prompt = f"{system_prompt}\n\nUser: {user_message}" if system_prompt else user_message
        url = f"{GEMINI_API_URL}?q={quote(full_prompt)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("response") or data.get("message") or str(data)
    except:
        pass
    return None

async def call_g4f(user_message: str, user_id: int, system_prompt: str = None, history=None) -> Optional[str]:
    if not G4F_AVAILABLE:
        return None
    provider_key = user_g4f_provider.get(user_id, "addy_chatgpt")
    provider_info = G4F_PROVIDERS.get(provider_key, G4F_PROVIDERS["addy_chatgpt"])
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
                    model="gpt-4o-mini",
                    messages=messages,
                    provider=provider_info["provider"]
                )
            )
            if response and response.choices:
                return response.choices[0].message.content
        except:
            pass
    # Ultimate fallback
    return "Main thoda busy hoon, thodi der mein baat karte hain! 😊"

async def generate_ai_response(chat_id: int, user_text: str, user_id: int = None) -> str:
    if user_id:
        # Update mood
        for mood, triggers in MOOD_TRIGGERS.items():
            if any(t in user_text.lower() for t in triggers):
                user_mood[user_id]["mood"] = mood
                await db_set_user_pref(user_id, "mood", mood)
                break
    mood = user_mood.get(user_id, {}).get("mood", "neutral")
    system_prompt = get_alita_prompt_with_mood(mood, "AI response")
    # Get recent conversation history from DB
    history = await db_get_recent_conversations(chat_id, 20)
    pref = user_ai_preference.get(user_id, "groq")
    if pref == "groq" and groq_client:
        resp = await call_groq(user_text, system_prompt)
        if resp: return resp
    resp = await call_g4f(user_text, user_id, system_prompt, history)
    if resp: return resp
    return f"{random.choice(['😊','😅','🤔'])} Haan ji, main hoon! Kya baat karni hai?"

def random_emoji(emotion: str = None) -> str:
    emojis = ["😊", "🎉", "🥳", "🌟", "✨", "😄", "💖", "❤️", "🥰", "😎"]
    return random.choice(emojis)

# -------------------- External Services with Mock Fallback --------------------
async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        return f"☀️ <b>Weather in {city.title()}</b>\n🌡️ 32°C (feels like 35°C)\n💧 Humidity: 70%\n💨 Wind: 5 m/s"
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
                        return f"☀️ <b>Weather in {city.title()}</b>\n🌡️ 32°C"
                else:
                    return f"☀️ <b>Weather in {city.title()}</b>\n🌡️ 32°C"
            weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric"
            async with sess.get(weather_url) as resp:
                if resp.status == 200:
                    w = await resp.json()
                    temp = w['main']['temp']
                    feels = w['main']['feels_like']
                    humid = w['main']['humidity']
                    wind = w['wind']['speed']
                    return f"☀️ <b>Weather in {city_name}</b>\n🌡️ {temp}°C (feels {feels}°C)\n💧 Humidity: {humid}%\n💨 Wind: {wind} m/s"
                else:
                    return f"☀️ <b>Weather in {city.title()}</b>\n🌡️ 32°C"
    except:
        return f"☀️ <b>Weather in {city.title()}</b>\n🌡️ 32°C"

async def generate_image(prompt: str) -> Optional[bytes]:
    try:
        url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=512&height=512&nologo=true"
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
            url = f"https://api.lyrics.ovh/v1/{quote(song)}"
            async with sess.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    lyrics = data.get('lyrics', 'Not found.')
                    if len(lyrics) > 3000:
                        lyrics = lyrics[:3000] + "\n\n...(truncated)"
                    return lyrics
    except:
        pass
    return f"🎶 <b>{song}</b>\n\nMain tere pyaar mein deewana\nDil kahe ikrar karle\nTujhse milke lagta hai\nAaj mausam bhi hai rangeela..."

def generate_qr(data: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio.getvalue()

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

# -------------------- AUTO-REACTION FEATURE --------------------
async def add_reaction(message: Message, text: str):
    """Add reaction to message based on sentiment with 60% chance."""
    if random.random() > 0.6:  # 60% chance
        return
    text_lower = text.lower()
    if any(word in text_lower for word in ["thank", "thanks", "awesome", "great", "love", "❤️", "😍"]):
        emoji = "❤️"
    elif any(word in text_lower for word in ["wow", "omg", "incredible", "🤩", "😲"]):
        emoji = "🤩","🎉"
    elif any(word in text_lower for word in ["haha", "lol", "😂", "🤣", "funny"]):
        emoji = "😂"
    elif any(word in text_lower for word in ["sad", "cry", "😢", "😭", "upset"]):
        emoji = "😢"
    elif any(word in text_lower for word in ["angry", "mad", "😠", "🤬", "gussa"]):
        emoji = "😠","😡"
    elif any(word in text_lower for word in ["cool", "😎", "nice", "🔥"]):
        emoji = "😎","🆒"
    elif any(word in text_lower for word in ["😊", "😄", "happy", "good"]):
        emoji = "😊","😂","🤣"
    elif any(word in text_lower for word in ["🤔", "thinking", "curious", "question"]):
        emoji = "🤔"
    elif any(word in text_lower for word in ["😏", "flirty", "sexy", "charming"]):
        emoji = "😏"
    elif any(word in text_lower for word in ["👍", "ok", "yes", "done"]):
        emoji = "👍","🤧"
    else:
        emoji = random.choice(["👍", "❤️", "😊", "🔥", "🤔"])
    try:
        await message.react([ReactionTypeEmoji(emoji=emoji)])
    except:
        pass

# -------------------- SCHEDULER --------------------
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
    msg = greetings[period] + f"\n\n{random_emoji()}"
    # Get groups from DB
    if USE_MONGODB:
        groups = await db.groups.find({"welcome_enabled": 1}).to_list(length=None)
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
        users = await db.users.find({"last_active": {"$gt": cutoff}}).to_list(length=None)
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
            group = await db.groups.aggregate([{"$sample": {"size": 1}}]).to_list(1)
            if group:
                try:
                    await bot.send_sticker(group[0]['chat_id'], sticker)
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
            user = await db.users.aggregate([
                {"$match": {"last_active": {"$gt": cutoff}}},
                {"$sample": {"size": 1}}
            ]).to_list(1)
            if user:
                try:
                    await bot.send_sticker(user[0]['user_id'], sticker)
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
        reminders = await db.reminders.find({"remind_at": {"$lte": now}}).to_list(length=None)
        for rem in reminders:
            try:
                await bot.send_message(
                    rem['user_id'],
                    f"⏰ <b>Reminder!</b>\n\n{rem['reminder_text']}\n\n<code>{rem['created_at']}</code>",
                    parse_mode="HTML"
                )
            except:
                pass
        await db.reminders.delete_many({"remind_at": {"$lte": now}})
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

# -------------------- BOT INITIALIZATION --------------------
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)

# -------------------- COMMAND HANDLERS --------------------

@dp.message(Command("start"))
async def start_cmd(message: Message):
    user = message.from_user
    await db_update_user(user.id, {
        "first_name": user.first_name,
        "username": user.username
    })
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 HOME", url="https://t.me/abhi0w0")],
        [InlineKeyboardButton(text="📱 Utilities", callback_data="menu_util"),
         InlineKeyboardButton(text="🎭 Fun", callback_data="menu_fun")],
        [InlineKeyboardButton(text="🛡️ Safety", callback_data="menu_safety"),
         InlineKeyboardButton(text="💬 Talk to Alita", callback_data="talk")],
        [InlineKeyboardButton(text="🎮 Gaming", callback_data="menu_game"),
         InlineKeyboardButton(text="🧠 AI Providers", callback_data="menu_providers")]
    ])
    welcome = (
        f"{random_emoji()} <b>Hey! I'm Alita 🎀</b>\n\n"
        "Your AI assistant with superpowers!\n\n"
        "🧠 AI Chat | 🎨 Image Gen | 🛡️ Admin Tools | 🎮 Gaming\n\n"
        "Type /help for all commands! 💕"
    )
    await message.reply_photo(
        photo="https://i.postimg.cc/yYWbPVQ4/1769349715111-result-image.png",
        caption=welcome,
        reply_markup=kb
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    text = """
📚 <b>ALITA – COMPLETE HELP</b>

🧠 <b>AI & CHAT</b>
/ask [question] – Kuch bhi pucho (Hinglish)
/clear – Memory clear
/providers – AI provider change karo
/mood – Mera mood change karo
/creative [topic] – Creative writing
/analyze [code/text] – Analyse karo
/debug [code] – Bugs fix karo
/explain [topic] – Simple mein samjhao

🎨 <b>CREATIVE</b>
/imagine [prompt] – AI se photo banao
/fact – Daily fact
/horoscope [sign] – Rashifal
/lyrics [song] – Song lyrics

🌤️ <b>UTILITIES</b>
/weather [city] – Real weather
/time – Indian time
/date – Aaj ki date
/qr [text] – QR code
/translate [lang] [text] – Translate
/math [expression] – Math solver
/shorten [url] – Shorten URL
/password [length] – Strong password

📝 <b>PERSONAL</b>
/note [text] – Note save karo
/notes – Sab notes dekho
/remind [time] [text] – Reminder
/reminders – Reminder list
/afk [reason] – AFK mode
/info – User info (reply)

🎮 <b>GAMING</b>
/game – Apna profile
/bal – Balance check
/daily – Daily reward
/work – Kaam karo
/crime – Risky crime
/rob – Kisi ko looto (reply)
/kill – Kisi ko maaro (reply)
/heal – Health badhao
/revive – Zinda karo (reply)
/protect – 24h protection
/give [amount] – Paisa do (reply, 10% tax)
/lb – Leaderboard

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

🔒 <b>AUTO‑MOD</b>
• Bad words filter
• Adult content → auto‑ban
• Group link block
• Spam detection
• Fake link block
• 3 warns = mute

🏡 <b>MY HOME:</b> @abhi0w0
"""
    await message.reply(text, parse_mode="HTML")

@dp.message(Command("ask"))
async def ask_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji()} Kya puchna hai? Example: <code>/ask India ki capital kya hai?</code>")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    await asyncio.sleep(0.5)
    reply = await generate_ai_response(message.chat.id, command.args, message.from_user.id)
    # Save conversation to DB
    await db_save_conversation(message.from_user.id, message.chat.id, "user", command.args)
    await db_save_conversation(message.from_user.id, message.chat.id, "assistant", reply)
    await message.reply(reply, parse_mode="HTML")
    await add_reaction(message, command.args)

@dp.message(Command("clear"))
async def clear_cmd(message: Message):
    # Clear from DB? We'll just clear in-memory for now
    conversation_history[message.chat.id].clear()
    await message.reply(f"{random_emoji()} Memory clear kar di! 🧹")

@dp.message(Command("providers"))
async def providers_cmd(message: Message, command: CommandObject):
    user_id = message.from_user.id
    if command.args:
        req = command.args.lower()
        if req in G4F_PROVIDERS:
            user_ai_preference[user_id] = req
            user_g4f_provider[user_id] = req
            await db_set_user_pref(user_id, "ai_preference", req)
            if req != "groq":
                await db_set_user_pref(user_id, "g4f_provider", req)
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
            await db_set_user_pref(user_id, "mood", req)
            await message.reply(f"🎭 Mood changed to <b>{req.upper()}</b> {MOODS[req]['emoji']}")
        else:
            await message.reply(f"Available moods: {', '.join(MOODS.keys())}")
    else:
        mood = user_mood[user_id]["mood"]
        await message.reply(f"🎭 <b>Current Mood:</b> {mood.upper()} {MOODS[mood]['emoji']}")

@dp.message(Command("creative"))
async def creative_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji()} Kya likhna hai? Example: <code>/creative ek love story</code>")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    prompt = f"Creative writing in Hinglish: {command.args}. Make it engaging, emotional, and detailed."
    system = get_alita_prompt_with_mood("playful", "Creative writing")
    reply = await call_g4f(prompt, message.from_user.id, system) or await call_groq(prompt, system) or "❌ Creative block! Thodi der mein try karo."
    await message.reply(reply[:4000], parse_mode="HTML")
    await add_reaction(message, command.args)

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
    await add_reaction(message, content)

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
    await add_reaction(message, code)

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
    await add_reaction(message, topic)

# ---- GAMING COMMANDS (with DB sync) ----
@dp.message(Command("game"))
async def game_cmd(message: Message):
    user_id = message.from_user.id
    user = message.from_user
    player = await db_get_game_data(user_id)
    player['name'] = user.first_name
    await db_update_game_data(user_id, player)
    profile = f"""🎮 <b>ALITA GAME</b> 🎮

👤 Name: {player['name']}
💰 Balance: ${player['balance']}
🏆 Rank: {player['rank']}
❤️ Status: {player['status']}
⚔️ Kills: {player['kills']}
💀 Deaths: {player['deaths']}
❤️ Health: {player['health']}%

Commands: /bal /daily /work /crime /rob /kill /heal /revive /protect /give /lb"""
    await message.reply(profile, parse_mode="HTML")

@dp.message(Command("bal"))
async def bal_cmd(message: Message):
    user_id = message.from_user.id
    player = await db_get_game_data(user_id)
    if user_id == ADMIN_ID:
        await message.reply(f"👑 <b>OWNER</b>\n💰 Balance: ∞\n⚔️ Kills: {player['kills']}\n🛡️ Immortal", parse_mode="HTML")
    else:
        await message.reply(f"👤 {player['name']}\n💰 Balance: ${player['balance']}\n🏆 Rank: {player['rank']}", parse_mode="HTML")

@dp.message(Command("daily"))
async def daily_cmd(message: Message):
    user_id = message.from_user.id
    player = await db_get_game_data(user_id)
    if player['status'] == 'dead':
        await message.reply("💀 Tu dead hai! Pehle /revive kar!", parse_mode="HTML")
        return
    now = indian_now()
    if player.get('last_daily') and (now - player['last_daily']).total_seconds() < GAME_COOLDOWNS['daily']:
        remaining = int(GAME_COOLDOWNS['daily'] - (now - player['last_daily']).total_seconds())
        hours = remaining // 3600
        minutes = (remaining % 3600)//60
        await message.reply(f"⏰ Already claimed! Next in {hours}h {minutes}m", parse_mode="HTML")
        return
    reward = random.randint(100, 500)
    player['balance'] += reward
    player['last_daily'] = now
    await db_update_game_data(user_id, player)
    await message.reply(f"🎁 Daily: +${reward}\n💵 New balance: ${player['balance']}", parse_mode="HTML")

@dp.message(Command("work"))
async def work_cmd(message: Message):
    user_id = message.from_user.id
    player = await db_get_game_data(user_id)
    if player['status'] == 'dead':
        await message.reply("💀 Dead! /revive karo!", parse_mode="HTML")
        return
    now = indian_now()
    if player.get('last_work') and (now - player['last_work']).total_seconds() < GAME_COOLDOWNS['work']:
        remaining = int(GAME_COOLDOWNS['work'] - (now - player['last_work']).total_seconds())
        minutes = remaining // 60
        await message.reply(f"⏰ Thak gaya! Wait {minutes}m", parse_mode="HTML")
        return
    jobs = ["programmer", "driver", "chef", "teacher", "doctor", "youtuber"]
    job = random.choice(jobs)
    earn = random.randint(50, 200)
    player['balance'] += earn
    player['last_work'] = now
    await db_update_game_data(user_id, player)
    await message.reply(f"💼 {job} job ki! +${earn}\n💰 Balance: ${player['balance']}", parse_mode="HTML")

@dp.message(Command("crime"))
async def crime_cmd(message: Message):
    user_id = message.from_user.id
    player = await db_get_game_data(user_id)
    if player['status'] == 'dead':
        await message.reply("💀 Dead! /revive karo!", parse_mode="HTML")
        return
    now = indian_now()
    if player.get('last_crime') and (now - player['last_crime']).total_seconds() < GAME_COOLDOWNS['crime']:
        remaining = int(GAME_COOLDOWNS['crime'] - (now - player['last_crime']).total_seconds())
        minutes = remaining // 60
        await message.reply(f"⏰ Police alert! Wait {minutes}m", parse_mode="HTML")
        return
    player['last_crime'] = now
    success = random.random() > 0.4
    if success:
        loot = random.randint(200, 800)
        player['balance'] += loot
        await db_update_game_data(user_id, player)
        await message.reply(f"🔫 Bank loot liya! +${loot}\n💰 Balance: ${player['balance']}", parse_mode="HTML")
    else:
        fine = random.randint(100, 300)
        player['balance'] = max(0, player['balance'] - fine)
        await db_update_game_data(user_id, player)
        await message.reply(f"🚔 Police pakad gayi! Fine -${fine}\n💰 Balance: ${player['balance']}", parse_mode="HTML")

@dp.message(Command("rob"))
async def rob_cmd(message: Message, command: CommandObject):
    if not message.reply_to_message:
        await message.reply("Reply karo kisi ke message pe!", parse_mode="HTML")
        return
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    if target_id == user_id:
        await message.reply("Apne aap ko rob nahi kar sakta!", parse_mode="HTML")
        return
    if target_id == ADMIN_ID:
        await message.reply("🛡️ Owner ko rob nahi kar sakta!", parse_mode="HTML")
        return
    player = await db_get_game_data(user_id)
    target = await db_get_game_data(target_id)
    now = indian_now()
    if player['status'] == 'dead':
        await message.reply("💀 Tu dead hai!", parse_mode="HTML")
        return
    if target['status'] == 'dead':
        await message.reply("💀 Target dead hai!", parse_mode="HTML")
        return
    if target.get('protect_until') and now < target['protect_until']:
        await message.reply(f"🛡️ {target['name']} protected hai!", parse_mode="HTML")
        return
    if player.get('last_rob') and (now - player['last_rob']).total_seconds() < GAME_COOLDOWNS['rob']:
        remaining = int(GAME_COOLDOWNS['rob'] - (now - player['last_rob']).total_seconds())
        minutes = remaining // 60
        await message.reply(f"⏰ Cooldown! Wait {minutes}m", parse_mode="HTML")
        return
    player['last_rob'] = now
    if target['balance'] < 10:
        await message.reply("😂 Target ke paas kuch nahi hai!", parse_mode="HTML")
        return
    success = random.random() > 0.5
    if success:
        amount = int(target['balance'] * random.uniform(0.1, 0.3))
        amount = max(10, amount)
        player['balance'] += amount
        target['balance'] -= amount
        await db_update_game_data(user_id, player)
        await db_update_game_data(target_id, target)
        await message.reply(f"💰 Robbed ${amount} from {target['name']}!\nYour balance: ${player['balance']}", parse_mode="HTML")
    else:
        fine = random.randint(50, 150)
        player['balance'] = max(0, player['balance'] - fine)
        await db_update_game_data(user_id, player)
        await message.reply(f"🚔 Caught! Fine -${fine}\nBalance: ${player['balance']}", parse_mode="HTML")

@dp.message(Command("kill"))
async def kill_cmd(message: Message):
    if not message.reply_to_message:
        await message.reply("Reply karo kisi ke message pe!", parse_mode="HTML")
        return
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    if target_id == user_id:
        await message.reply("Apne aap ko kill nahi kar sakta!", parse_mode="HTML")
        return
    if target_id == ADMIN_ID:
        await message.reply("🛡️ Owner immortal hai!", parse_mode="HTML")
        return
    player = await db_get_game_data(user_id)
    target = await db_get_game_data(target_id)
    now = indian_now()
    if player['status'] == 'dead':
        await message.reply("💀 Tu dead hai!", parse_mode="HTML")
        return
    if target['status'] == 'dead':
        await message.reply("💀 Target already dead!", parse_mode="HTML")
        return
    if target.get('protect_until') and now < target['protect_until']:
        await message.reply(f"🛡️ {target['name']} protected hai!", parse_mode="HTML")
        return
    success = random.random() > 0.3
    if success:
        target['status'] = 'dead'
        target['deaths'] += 1
        player['kills'] += 1
        loot = int(target['balance'] * 0.5)
        target['balance'] -= loot
        player['balance'] += loot
        await db_update_game_data(user_id, player)
        await db_update_game_data(target_id, target)
        await message.reply(f"💀 Killed {target['name']}! Earned ${loot}", parse_mode="HTML")
    else:
        damage = random.randint(20, 40)
        player['health'] = max(0, player['health'] - damage)
        if player['health'] == 0:
            player['status'] = 'dead'
            player['deaths'] += 1
            await db_update_game_data(user_id, player)
            await message.reply(f"💀 Counter attack! You died!", parse_mode="HTML")
        else:
            await db_update_game_data(user_id, player)
            await message.reply(f"🛡️ {target['name']} bach gaya! You took {damage} damage!", parse_mode="HTML")

@dp.message(Command("heal"))
async def heal_cmd(message: Message):
    user_id = message.from_user.id
    player = await db_get_game_data(user_id)
    if player['status'] == 'dead':
        await message.reply("💀 Dead! /revive karo!", parse_mode="HTML")
        return
    if player['health'] >= 100:
        await message.reply("❤️ Health full!", parse_mode="HTML")
        return
    cost = 50
    if player['balance'] < cost:
        await message.reply(f"💸 Need ${cost} to heal!", parse_mode="HTML")
        return
    player['balance'] -= cost
    heal_amt = random.randint(20, 50)
    player['health'] = min(100, player['health'] + heal_amt)
    await db_update_game_data(user_id, player)
    await message.reply(f"💊 Healed +{heal_amt} HP\n❤️ Health: {player['health']}%", parse_mode="HTML")

@dp.message(Command("revive"))
async def revive_cmd(message: Message):
    if not message.reply_to_message:
        await message.reply("Reply karo dead player ke message pe!", parse_mode="HTML")
        return
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    if target_id == user_id:
        await message.reply("Apne aap ko revive nahi kar sakta!", parse_mode="HTML")
        return
    player = await db_get_game_data(user_id)
    target = await db_get_game_data(target_id)
    if target['status'] != 'dead':
        await message.reply("Target already alive!", parse_mode="HTML")
        return
    if player['balance'] < REVIVE_COST and user_id != ADMIN_ID:
        await message.reply(f"💸 Need ${REVIVE_COST} to revive!", parse_mode="HTML")
        return
    if user_id != ADMIN_ID:
        player['balance'] -= REVIVE_COST
    target['status'] = 'alive'
    target['health'] = 100
    await db_update_game_data(user_id, player)
    await db_update_game_data(target_id, target)
    await message.reply(f"🔄 Revived {target['name']}!\n❤️ Health 100%", parse_mode="HTML")

@dp.message(Command("protect"))
async def protect_cmd(message: Message):
    user_id = message.from_user.id
    player = await db_get_game_data(user_id)
    now = indian_now()
    if player.get('protect_until') and now < player['protect_until']:
        remaining = int((player['protect_until'] - now).total_seconds())
        hours = remaining // 3600
        await message.reply(f"🛡️ Already protected! {hours}h left", parse_mode="HTML")
        return
    if player['balance'] < PROTECT_COST and user_id != ADMIN_ID:
        await message.reply(f"💸 Need ${PROTECT_COST} for 24h protection!", parse_mode="HTML")
        return
    if user_id != ADMIN_ID:
        player['balance'] -= PROTECT_COST
    player['protect_until'] = now + timedelta(seconds=GAME_COOLDOWNS['protect'])
    await db_update_game_data(user_id, player)
    await message.reply(f"🛡️ 24h protection active!\n💵 Balance: ${player['balance']}", parse_mode="HTML")

@dp.message(Command("give"))
async def give_cmd(message: Message, command: CommandObject):
    if not message.reply_to_message or not command.args:
        await message.reply("Reply karo aur amount do! Example: /give 500", parse_mode="HTML")
        return
    try:
        amount = int(command.args)
    except:
        await message.reply("Valid number do!", parse_mode="HTML")
        return
    if amount < 10:
        await message.reply("Minimum $10!", parse_mode="HTML")
        return
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    if target_id == user_id:
        await message.reply("Apne aap ko nahi de sakte!", parse_mode="HTML")
        return
    player = await db_get_game_data(user_id)
    target = await db_get_game_data(target_id)
    tax = int(amount * 0.1)
    total = amount + tax
    if player['balance'] < total:
        await message.reply(f"Need ${total} (${amount}+${tax} tax)", parse_mode="HTML")
        return
    player['balance'] -= total
    target['balance'] += amount
    await db_update_game_data(user_id, player)
    await db_update_game_data(target_id, target)
    await message.reply(f"✅ Gave ${amount} to {target['name']} (10% tax)", parse_mode="HTML")

@dp.message(Command("lb"))
@dp.message(Command("leaderboard"))
async def leaderboard_cmd(message: Message):
    # For simplicity, use in-memory game_data; in a full version, you'd query DB sorted
    # Here we use the in-memory dict but it's not persistent across restarts.
    # For production, you'd implement a DB query with sorting.
    sorted_players = sorted(game_data.items(), key=lambda x: (x[1]['kills']*1000 + x[1]['balance']), reverse=True)[:10]
    text = "🏆 <b>LEADERBOARD</b> 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    base_rank = 1000
    for i, (uid, data) in enumerate(sorted_players):
        medal = medals[i] if i < 3 else f"#{base_rank - i}"
        name = data.get('name', 'Unknown')[:12]
        status = "❤️" if data['status'] == 'alive' else "💀"
        if uid == ADMIN_ID:
            text += f"{medal} 👑 <b>{name}</b>\n   💰 ∞ | ⚔️{data['kills']} | {status}\n\n"
        else:
            text += f"{medal} <b>{name}</b>\n   💰 ${data['balance']} | ⚔️{data['kills']} | {status}\n\n"
    await message.reply(text, parse_mode="HTML")

# ---- ADVANCED TOOLS (Owner only) ----
@dp.message(Command("run"))
async def run_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    code = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not code:
        await message.reply("Usage: <code>/run print('hello')</code>", parse_mode="HTML")
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
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    cmd = command.args
    if not cmd:
        await message.reply("Usage: <code>/shell ls -la</code>", parse_mode="HTML")
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
        await message.reply("⏰ Timeout!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ {str(e)[:500]}", parse_mode="HTML")

@dp.message(Command("file"))
async def file_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    args = command.args.split() if command.args else []
    if not args:
        await message.reply("Usage: <code>/file list|read|write|delete</code>", parse_mode="HTML")
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
            await message.reply(f"✅ Written to {filename}", parse_mode="HTML")
        elif action == "delete":
            if len(args) < 2: return
            os.remove(args[1])
            await message.reply(f"✅ Deleted {args[1]}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ {str(e)[:500]}", parse_mode="HTML")

@dp.message(Command("pip"))
async def pip_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    args = command.args.split() if command.args else []
    if not args:
        await message.reply("Usage: <code>/pip install|list|uninstall</code>", parse_mode="HTML")
        return
    action = args[0].lower()
    try:
        if action == "install":
            pkg = args[1]
            await message.reply(f"📦 Installing {pkg}...", parse_mode="HTML")
            result = subprocess.run([sys.executable, "-m", "pip", "install", pkg], capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                await message.reply(f"✅ Installed {pkg}", parse_mode="HTML")
            else:
                await message.reply(f"❌ Failed:\n<pre>{result.stderr[:1000]}</pre>", parse_mode="HTML")
        elif action == "list":
            result = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True, timeout=30)
            await message.reply(f"📦 <b>Packages</b>\n<pre>{result.stdout[:3500]}</pre>", parse_mode="HTML")
        elif action == "uninstall":
            pkg = args[1]
            result = subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", pkg], capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                await message.reply(f"✅ Uninstalled {pkg}", parse_mode="HTML")
            else:
                await message.reply(f"❌ Failed:\n<pre>{result.stderr[:1000]}</pre>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ {str(e)[:500]}", parse_mode="HTML")

@dp.message(Command("math"))
async def math_cmd(message: Message, command: CommandObject):
    expr = command.args
    if not expr:
        await message.reply("Usage: <code>/math 2+2</code> or <code>/math solve x**2-4=0</code>", parse_mode="HTML")
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
        await message.reply(f"❌ Math error: {str(e)[:200]}", parse_mode="HTML")

@dp.message(Command("sysinfo"))
async def sysinfo_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
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
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    text = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not text:
        await message.reply("Usage: <code>/json {'key':'value'}</code>", parse_mode="HTML")
        return
    try:
        data = json.loads(text)
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        await message.reply(f"📋 <b>JSON</b>\n<pre>{pretty[:3500]}</pre>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Invalid JSON: {str(e)}", parse_mode="HTML")

@dp.message(Command("hash"))
async def hash_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    text = command.args
    if not text:
        await message.reply("Usage: <code>/hash hello</code>", parse_mode="HTML")
        return
    md5 = hashlib.md5(text.encode()).hexdigest()
    sha1 = hashlib.sha1(text.encode()).hexdigest()
    sha256 = hashlib.sha256(text.encode()).hexdigest()
    sha512 = hashlib.sha512(text.encode()).hexdigest()
    await message.reply(
        f"🔐 <b>Hashes</b>\nMD5: <code>{md5}</code>\nSHA1: <code>{sha1}</code>\nSHA256: <code>{sha256}</code>\nSHA512: <code>{sha512[:64]}...</code>",
        parse_mode="HTML"
    )

@dp.message(Command("base64"))
async def base64_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    args = command.args.split() if command.args else []
    if len(args) < 2:
        await message.reply("Usage: <code>/base64 encode Hello</code> or <code>/base64 decode SGVsbG8=</code>", parse_mode="HTML")
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
        await message.reply(f"❌ {str(e)}", parse_mode="HTML")

@dp.message(Command("regex"))
async def regex_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    if not command.args or '|||' not in command.args:
        await message.reply("Usage: <code>/regex pattern ||| test_string</code>", parse_mode="HTML")
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
        await message.reply(f"❌ Invalid regex: {e}", parse_mode="HTML")

@dp.message(Command("shorten"))
async def shorten_cmd(message: Message, command: CommandObject):
    url = command.args
    if not url:
        await message.reply("Usage: <code>/shorten https://example.com</code>", parse_mode="HTML")
        return
    short = await shorten_url(url)
    await message.reply(f"🔗 Short URL: {short}", parse_mode="HTML")

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

# ---- WEATHER, TIME, QR, etc. ----
@dp.message(Command("weather"))
async def weather_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("City name do! Example: <code>/weather Mumbai</code>", parse_mode="HTML")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    weather = await get_weather(command.args)
    await message.reply(weather, parse_mode="HTML")
    await add_reaction(message, command.args)

@dp.message(Command("time"))
async def time_cmd(message: Message):
    now = indian_now()
    await message.reply(
        f"🕒 <b>Indian Time:</b> {now.strftime('%I:%M %p')}\n📅 <b>Date:</b> {now.strftime('%A, %d %B %Y')}\n{random_emoji()}",
        parse_mode="HTML"
    )

@dp.message(Command("date"))
async def date_cmd(message: Message):
    now = indian_now()
    await message.reply(f"📆 <b>{now.strftime('%A, %d %B %Y')}</b>\n{random_emoji()}", parse_mode="HTML")

@dp.message(Command("qr"))
async def qr_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Text do! Example: <code>/qr Hello World</code>", parse_mode="HTML")
        return
    qr_bytes = generate_qr(command.args)
    await message.reply_photo(BufferedInputFile(qr_bytes, filename="qr.png"), caption="✅ QR Code ready!")

@dp.message(Command("translate"))
async def translate_cmd(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        await message.reply("Usage: <code>/translate hi Hello</code>", parse_mode="HTML")
        return
    parts = command.args.split(maxsplit=1)
    lang, text = parts[0], parts[1]
    translated = await translate_text(text, lang)
    await message.reply(f"🌍 <b>Translation ({lang.upper()}):</b>\n{translated}", parse_mode="HTML")

@dp.message(Command("lyrics"))
async def lyrics_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Song name do! Example: <code>/lyrics Shape of You</code>", parse_mode="HTML")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    lyrics = await get_lyrics(command.args)
    await message.reply(f"🎶 <b>{command.args}</b>\n\n{lyrics[:3500]}", parse_mode="HTML", disable_web_page_preview=True)

@dp.message(Command("imagine"))
async def imagine_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji()} Prompt do! Example: <code>/imagine sunset mountains</code>", parse_mode="HTML")
        return
    status = await message.reply(f"{random_emoji()} Image bana rahi hu... 🎨", parse_mode="HTML")
    img_bytes = await generate_image(command.args)
    if img_bytes:
        await status.delete()
        await message.reply_photo(BufferedInputFile(img_bytes, filename="alita_ai.png"), caption=f"<b>Your image:</b> {command.args}", parse_mode="HTML")
    else:
        await status.edit_text(f"{random_emoji('crying')} Image nahi ban paai, try again!", parse_mode="HTML")

@dp.message(Command("fact"))
async def fact_cmd(message: Message):
    facts = ["🍯 Honey kabhi kharab nahi hota – 3000 saal purana honey bhi kha sakte ho!",
             "🐙 Octopus ke 3 dil hote hain!",
             "🍌 Banana ek berry hai, strawberry nahi!",
             "🦈 Sharks pehle aaye, trees baad mein!",
             "🧠 Human brain 20% energy use karta hai!",
             "🦋 Butterflies taste with their feet!",
             "💩 Wombat poop cube shaped hota hai!"]
    await message.reply(f"📌 <b>Daily Fact:</b>\n{random.choice(facts)}\n\n{random_emoji()}", parse_mode="HTML")

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
        await message.reply(f"{random_emoji('surprise')} <b>Apni rashi choose karo:</b>", reply_markup=kb, parse_mode="HTML")
        return
    sign = command.args.lower()
    if sign in signs:
        await message.reply(f"{signs[sign]}\n\n{random_emoji('love')}", parse_mode="HTML")
    else:
        await message.reply(f"{random_emoji('crying')} Yeh rashi nahi mili. Aries, Taurus, etc. likho.", parse_mode="HTML")

# ---- NOTES, REMINDERS, AFK, INFO ----
@dp.message(Command("note"))
async def note_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Note kya save karun? Example: <code>/note Milk lena</code>", parse_mode="HTML")
        return
    now = indian_now()
    if USE_MONGODB:
        await db.notes.insert_one({
            "user_id": message.from_user.id,
            "note_text": command.args,
            "created_at": now
        })
    else:
        cursor.execute("INSERT INTO notes (user_id, note_text, created_at) VALUES (?, ?, ?)",
                       (message.from_user.id, command.args, now))
        conn.commit()
    await message.reply(f"{random_emoji()} <b>Note saved!</b> 📝", parse_mode="HTML")

@dp.message(Command("notes"))
async def notes_cmd(message: Message):
    user_id = message.from_user.id
    if USE_MONGODB:
        cursor = db.notes.find({"user_id": user_id}).sort("created_at", -1).limit(20)
        rows = await cursor.to_list(length=20)
    else:
        cursor.execute("SELECT note_text, created_at FROM notes WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
                       (user_id,))
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

@dp.message(Command("remind"))
async def remind_cmd(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        await message.reply("Usage: <code>/remind 1h Call mom</code>", parse_mode="HTML")
        return
    args = command.args.split(maxsplit=1)
    time_str, text = args[0], args[1]
    minutes = 0
    if time_str.endswith('h'):
        minutes = int(time_str[:-1]) * 60
    elif time_str.endswith('m'):
        minutes = int(time_str[:-1])
    else:
        await message.reply("Time format: <code>30m</code> (minutes) ya <code>1h</code> (hours)", parse_mode="HTML")
        return
    remind_at = indian_now() + timedelta(minutes=minutes)
    if USE_MONGODB:
        await db.reminders.insert_one({
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
    await message.reply(f"{random_emoji()} <b>Reminder set!</b> ⏰\n{text} – {remind_at.strftime('%I:%M %p')}", parse_mode="HTML")

@dp.message(Command("reminders"))
async def reminders_cmd(message: Message):
    now = indian_now()
    user_id = message.from_user.id
    if USE_MONGODB:
        cursor = db.reminders.find({"user_id": user_id, "remind_at": {"$gt": now}}).sort("remind_at")
        rows = await cursor.to_list(length=None)
    else:
        cursor.execute("SELECT id, reminder_text, remind_at FROM reminders WHERE user_id = ? AND remind_at > ? ORDER BY remind_at",
                       (user_id, now))
        rows = cursor.fetchall()
    if not rows:
        await message.reply("Koi active reminder nahi.", parse_mode="HTML")
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

@dp.message(Command("afk"))
async def afk_cmd(message: Message, command: CommandObject):
    reason = command.args or "AFK"
    user_afk[message.from_user.id] = {"reason": reason, "since": indian_now()}
    await message.reply(f"{random_emoji('sleepy')} <b>AFK mode ON</b>\nReason: {reason}", parse_mode="HTML")

@dp.message(Command("info"))
async def info_cmd(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    text = f"👤 <b>User Info</b>\n🆔 ID: <code>{target.id}</code>\n📛 Name: {target.full_name}\n📱 Username: @{target.username if target.username else 'N/A'}\n"
    if message.chat.type in ('group','supergroup'):
        try:
            member = await bot.get_chat_member(message.chat.id, target.id)
            text += f"🏷️ Status: {member.status.capitalize()}\n"
        except:
            pass
    await message.reply(text, parse_mode="HTML")

# ---- ADMIN COMMANDS ----
async def group_admin_only(message: Message):
    if message.chat.type not in ('group','supergroup'):
        await message.reply("⚠️ Yeh command sirf groups mein chalegi.", parse_mode="HTML")
        return False
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{random_emoji('angry')} Sirf admin log yeh command use kar sakte hain.", parse_mode="HTML")
        return False
    return True

@dp.message(Command("adminlist"))
async def adminlist_cmd(message: Message):
    if not await group_admin_only(message): return
    admins = await get_group_admins(message.chat.id)
    if not admins:
        await message.reply("Koi admin nahi mila?", parse_mode="HTML")
        return
    text = "👑 <b>Group Admins:</b>\n"
    for aid in admins:
        try:
            user = await bot.get_chat_member(message.chat.id, aid)
            name = user.user.full_name
            status = "👑 Creator" if user.status == "creator" else "🛡️ Admin"
            text += f"\n{status} – {name}"
        except:
            text += f"\n• <code>{aid}</code>"
    await message.reply(text, parse_mode="HTML")

@dp.message(Command("warn"))
async def warn_cmd(message: Message, command: CommandObject):
    if not await group_admin_only(message): return
    if not message.reply_to_message:
        await message.reply("Kisi user ke message pe reply karo.", parse_mode="HTML")
        return
    await delete_and_warn(message.reply_to_message, "manual_warning")

@dp.message(Command("kick"))
async def kick_cmd(message: Message):
    if not await group_admin_only(message): return
    if not message.reply_to_message:
        await message.reply("Reply karo user ko kick karne ke liye.", parse_mode="HTML")
        return
    target = message.reply_to_message.from_user
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"{random_emoji('angry')} {target.first_name} ko kick kar diya!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Kick nahi kar paai: {e}", parse_mode="HTML")

@dp.message(Command("ban"))
async def ban_cmd(message: Message):
    if not await group_admin_only(message): return
    if not message.reply_to_message:
        await message.reply("Reply karo user ko ban karne ke liye.", parse_mode="HTML")
        return
    target = message.reply_to_message.from_user
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await message.reply(f"{random_emoji('angry')} {target.first_name} permanently banned!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Ban nahi kar paai: {e}", parse_mode="HTML")

@dp.message(Command("unban"))
async def unban_cmd(message: Message):
    if not await group_admin_only(message): return
    if not message.reply_to_message:
        await message.reply("Reply karo user ke message pe unban karne ke liye.", parse_mode="HTML")
        return
    target = message.reply_to_message.from_user
    try:
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"{random_emoji('happy')} {target.first_name} ka ban hata diya!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Unban failed: {e}", parse_mode="HTML")

@dp.message(Command("mute"))
async def mute_cmd(message: Message, command: CommandObject):
    if not await group_admin_only(message): return
    if not message.reply_to_message:
        await message.reply("Reply karo user ko mute karne ke liye.", parse_mode="HTML")
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
        await message.reply(f"{random_emoji('angry')} {target.first_name} muted for {minutes} minutes!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Mute failed: {e}", parse_mode="HTML")

@dp.message(Command("unmute"))
async def unmute_cmd(message: Message):
    if not await group_admin_only(message): return
    if not message.reply_to_message:
        await message.reply("Reply karo user ko unmute karne ke liye.", parse_mode="HTML")
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
        await message.reply(f"{random_emoji('happy')} {target.first_name} unmuted!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Unmute failed: {e}", parse_mode="HTML")

@dp.message(Command("pin"))
async def pin_cmd(message: Message):
    if not await group_admin_only(message): return
    if not message.reply_to_message:
        await message.reply("Reply karo us message pe jo pin karna hai.", parse_mode="HTML")
        return
    try:
        await bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
        await message.reply("📌 Pinned!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Pin failed: {e}", parse_mode="HTML")

@dp.message(Command("unpin"))
async def unpin_cmd(message: Message):
    if not await group_admin_only(message): return
    try:
        await bot.unpin_chat_message(message.chat.id)
        await message.reply("📍 Unpinned!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Unpin failed: {e}", parse_mode="HTML")

@dp.message(Command("slowmode"))
async def slowmode_cmd(message: Message, command: CommandObject):
    if not await group_admin_only(message): return
    delay = 0
    if command.args:
        try:
            delay = int(command.args)
        except:
            pass
    try:
        await bot.set_chat_slow_mode_delay(message.chat.id, delay)
        if delay == 0:
            await message.reply("⏱️ Slow mode disabled!", parse_mode="HTML")
        else:
            await message.reply(f"⏱️ Slow mode enabled: {delay} seconds.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Slow mode change failed: {e}", parse_mode="HTML")

@dp.message(Command("tagall"))
async def tagall_cmd(message: Message):
    if not await group_admin_only(message): return
    if not await is_bot_admin(message.chat.id):
        await message.reply("Mujhe group admin banana padega tagall ke liye.", parse_mode="HTML")
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
        await message.reply(f"❌ Members fetch nahi ho paaye: {e}", parse_mode="HTML")
        return
    if not members:
        await message.reply("Koi member nahi mila tag karne ke liye.", parse_mode="HTML")
        return
    for i in range(0, len(members), 10):
        chunk = members[i:i+10]
        await message.reply(" ".join(chunk), parse_mode="HTML")
        await asyncio.sleep(1)

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

# ---- OWNER COMMANDS ----
async def owner_only(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ Yeh command sirf meri jaan ke liye hai.", parse_mode="HTML")
        return False
    return True

@dp.message(Command("sendall"))
async def sendall_cmd(message: Message):
    if not await owner_only(message): return
    if not message.reply_to_message:
        await message.reply("Kisi message pe reply karo broadcast karne ke liye.", parse_mode="HTML")
        return
    status = await message.reply("📤 Broadcasting...", parse_mode="HTML")
    sent = 0
    failed = 0
    if USE_MONGODB:
        users = await db.users.find().to_list(length=None)
        for user in users:
            try:
                await bot.copy_message(user['user_id'], message.chat.id, message.reply_to_message.message_id)
                sent += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1
        groups = await db.groups.find().to_list(length=None)
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
    await status.edit_text(f"✅ Broadcast done!\nSent: {sent}\nFailed: {failed}", parse_mode="HTML")

@dp.message(Command("savesticker"))
async def savesticker_cmd(message: Message):
    if not await owner_only(message): return
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply("Reply to a sticker message!", parse_mode="HTML")
        return
    file_id = message.reply_to_message.sticker.file_id
    emoji = message.reply_to_message.sticker.emoji or ""
    now = indian_now()
    if USE_MONGODB:
        await db.stickers.update_one(
            {"file_id": file_id},
            {"$set": {"added_by": message.from_user.id, "added_at": now, "emoji": emoji}},
            upsert=True
        )
    else:
        cursor.execute("INSERT OR IGNORE INTO stickers (file_id, added_by, added_at, emoji) VALUES (?, ?, ?, ?)",
                       (file_id, message.from_user.id, now, emoji))
        conn.commit()
    if USE_MONGODB or cursor.rowcount:
        saved_stickers.append(file_id)
        await message.reply(f"✅ Sticker saved! Total: {len(saved_stickers)}", parse_mode="HTML")
    else:
        await message.reply("Sticker already exists!", parse_mode="HTML")

@dp.message(Command("stickerstatus"))
async def stickerstatus_cmd(message: Message):
    if not await owner_only(message): return
    await message.reply(f"🎀 <b>Sticker Database</b>\n\nTotal stickers: {len(saved_stickers)}", parse_mode="HTML")

@dp.message(Command("deletesticker"))
async def deletesticker_cmd(message: Message):
    if not await owner_only(message): return
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply("Reply to a sticker to delete from database.", parse_mode="HTML")
        return
    file_id = message.reply_to_message.sticker.file_id
    if USE_MONGODB:
        result = await db.stickers.delete_one({"file_id": file_id})
        if result.deleted_count:
            saved_stickers[:] = [f for f in saved_stickers if f != file_id]
            await message.reply("✅ Sticker deleted!", parse_mode="HTML")
        else:
            await message.reply("Sticker not found in database.", parse_mode="HTML")
    else:
        cursor.execute("DELETE FROM stickers WHERE file_id = ?", (file_id,))
        conn.commit()
        if cursor.rowcount:
            saved_stickers[:] = [f for f in saved_stickers if f != file_id]
            await message.reply("✅ Sticker deleted!", parse_mode="HTML")
        else:
            await message.reply("Sticker not found in database.", parse_mode="HTML")

# -------------------- MESSAGE HANDLER (AI + MOD + AFK + GAMING DETECT + REACT + NEW TRIGGERS) --------------------
@dp.message()
async def message_handler(message: Message):
    if message.from_user.id == bot.id:
        return

    # Update user activity
    await db_update_user(message.from_user.id, {
        "first_name": message.from_user.first_name,
        "username": message.from_user.username
    })

    # Save group
    if message.chat.type in ('group','supergroup'):
        await db_update_group(message.chat.id, {"title": message.chat.title})

    # AFK check
    if message.from_user.id in user_afk:
        del user_afk[message.from_user.id]
        await message.reply(f"{random_emoji('happy')} Welcome back! AFK hata diya.", parse_mode="HTML")

    # Creator detection
    if message.text:
        msg_lower = message.text.lower()
        for kw in CREATOR_KEYWORDS:
            if kw in msg_lower:
                await message.reply("🥰😊\n\nMujhe mere bhagwan ne banaya hai <b>Abhi</b> ne (@a6h1ii) 🙏✨\nWoh mere creator hain, bahut talented devloper hain! 💖🎀", parse_mode="HTML")
                return

    # Gaming keyword auto-response
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

    # AUTO MODERATION
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

    # CAPTCHA answer check
    if message.from_user.id in captcha_store and message.reply_to_message and message.reply_to_message.from_user.id == bot.id:
        correct = captcha_store[message.from_user.id].get('answer')
        if message.text.strip() == correct:
            del captcha_store[message.from_user.id]
            await message.reply(f"{random_emoji('happy')} ✅ CAPTCHA passed! Welcome!", parse_mode="HTML")
            return
        else:
            await message.reply(f"{random_emoji('angry')} ❌ Wrong answer! Try again.", parse_mode="HTML")
            return

    # Determine if we should respond with AI
    should_respond = False
    respond_reason = ""

    is_private = message.chat.type == "private"
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot.id
    is_mention = False
    if BOT_USERNAME and message.text:
        if f"@{BOT_USERNAME}" in message.text.lower():
            is_mention = True
            # Remove mention from text
            message.text = re.sub(f"@{BOT_USERNAME}", "", message.text, flags=re.IGNORECASE).strip()

    # NEW: Trigger on "Alita" word in groups (case-insensitive, whole word or part)
    contains_alita = False
    if message.chat.type in ('group','supergroup') and message.text:
        if re.search(r'\balita\b', message.text.lower()):
            contains_alita = True

    # NEW: Random 60% chance in groups (excluding commands and messages that are already triggered)
    random_chance = False
    if message.chat.type in ('group','supergroup') and message.text and not message.text.startswith('/'):
        if random.random() < 0.6:  # 60% chance
            random_chance = True

    if is_private or is_reply_to_bot or is_mention or contains_alita or random_chance:
        should_respond = True

    if should_respond:
        await bot.send_chat_action(message.chat.id, "typing")
        await asyncio.sleep(random.uniform(0.5, 1.2))
        user_text = message.text or ""
        if not user_text:
            user_text = "Hii"
        # 20% chance to send sticker
        if saved_stickers and random.random() < 0.20:
            sticker = random.choice(saved_stickers)
            await bot.send_sticker(message.chat.id, sticker)
            await asyncio.sleep(0.3)
        reply = await generate_ai_response(message.chat.id, user_text, message.from_user.id)
        # Save conversation to DB
        await db_save_conversation(message.from_user.id, message.chat.id, "user", user_text)
        await db_save_conversation(message.from_user.id, message.chat.id, "assistant", reply)
        await message.reply(reply, parse_mode="HTML")
        # Add reaction after replying
        await add_reaction(message, user_text)
        return

    # For any other text message, also try to add reaction (with 60% chance)
    if message.text and not message.text.startswith('/'):
        await add_reaction(message, message.text)

# ---- PHOTO HANDLER ----
@dp.message(F.photo)
async def handle_photo(message: Message):
    await message.reply("🔍 Photo analyze kar rahi hoon... 📸", parse_mode="HTML")
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        photo_base64 = base64.b64encode(photo_bytes).decode('utf-8')
        caption = message.caption or "Is photo mein kya hai? Describe in detail."

        if G4F_AVAILABLE:
            from g4f.Provider import Blackbox
            client = G4FClient()
            image_url = f"data:image/jpeg;base64,{photo_base64}"
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model="gpt-4o",
                    provider=Blackbox,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"Tu Alita hai 🎀. Hinglish mein bata: {caption}"},
                                {"type": "image_url", "image_url": {"url": image_url}}
                            ]
                        }
                    ]
                )
            )
            analysis = response.choices[0].message.content
            await message.reply(f"📸 <b>Photo Analysis</b> 🎀\n\n{analysis[:4000]}", parse_mode="HTML")
        else:
            await message.reply("📸 Photo mil gayi! Vision feature thoda busy hai, thodi der mein try karo.", parse_mode="HTML")
    except Exception as e:
        logging.error(f"Photo error: {e}")
        await message.reply("😅 Photo process karne mein thodi problem hui! Dubara try karo.", parse_mode="HTML")

# ---- CHAT MEMBER HANDLER (Welcome/Goodbye/CAPTCHA) ----
@dp.chat_member()
async def chat_member_handler(update: ChatMemberUpdated):
    if update.new_chat_member.status == "member":
        group = await db_get_group(update.chat.id)
        if not group:
            return
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

# ---- CALLBACK HANDLER ----
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
            q = captcha_store[user_id].get('question')
            await callback.message.edit_text(
                f"🧩 <b>Solve this CAPTCHA:</b>\n{q}\n\nReply with your answer.",
                parse_mode="HTML"
            )
        else:
            await callback.answer("CAPTCHA expire ho gayi!", show_alert=True)
    elif data == "menu_util":
        await callback.message.edit_text(
            "📱 <b>Utilities</b>\n/weather – Weather\n/time – Indian time\n/date – Date\n/qr – QR code\n/translate – Translate\n/shorten – URL shortener\n/password – Strong password",
            parse_mode="HTML"
        )
    elif data == "menu_fun":
        await callback.message.edit_text(
            "🎭 <b>Fun</b>\n/imagine – AI image\n/fact – Daily fact\n/horoscope – Rashifal\n/lyrics – Song lyrics\n/creative – Creative writing",
            parse_mode="HTML"
        )
    elif data == "menu_safety":
        await callback.message.edit_text(
            "🛡️ <b>Safety</b>\n• Auto spam block\n• Bad words filter\n• Adult content = ban\n• Group link block\n• Fake link block\n• 3 warns = mute",
            parse_mode="HTML"
        )
    elif data == "menu_game":
        await callback.message.edit_text(
            "🎮 <b>Gaming</b>\n/game – Profile\n/bal – Balance\n/daily – Daily\n/work – Work\n/crime – Crime\n/rob – Rob\n/kill – Kill\n/heal – Heal\n/revive – Revive\n/protect – 24h protection\n/give – Give money\n/lb – Leaderboard",
            parse_mode="HTML"
        )
    elif data == "menu_providers":
        await providers_cmd(callback.message, CommandObject(args=""))
    elif data == "talk":
        await callback.message.edit_text(
            f"{random_emoji('love')} Haan ji, main yahan hoon! Kya baat karni hai? Mujhe mention karo ya reply karo.",
            parse_mode="HTML"
        )
    await callback.answer()

# -------------------- WEB SERVER --------------------
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

# -------------------- MAIN --------------------
async def main():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username
    print(f"🤖 Bot: @{BOT_USERNAME} (ID: {me.id})")
    await initialize_db()
    print(f"🎨 Stickers loaded: {len(saved_stickers)}")
    print(f"🧠 Groq available: {groq_client is not None}")
    print(f"🆓 g4f available: {G4F_AVAILABLE}")
    print(f"📦 Database: {'MongoDB' if USE_MONGODB else 'SQLite'}")

    # Scheduler jobs
    scheduler.add_job(send_time_greetings, CronTrigger(hour=7, minute=0, timezone=INDIAN_TZ), id="morning")
    scheduler.add_job(send_time_greetings, CronTrigger(hour=12, minute=0, timezone=INDIAN_TZ), id="afternoon")
    scheduler.add_job(send_time_greetings, CronTrigger(hour=18, minute=0, timezone=INDIAN_TZ), id="evening")
    scheduler.add_job(send_time_greetings, CronTrigger(hour=22, minute=0, timezone=INDIAN_TZ), id="night")
    scheduler.add_job(send_random_sticker_job, CronTrigger(minute="*/30"), id="random_sticker")  # every 30 min
    scheduler.add_job(check_reminders, CronTrigger(second="*/30"), id="reminders")  # every 30 sec
    scheduler.start()

    await start_web_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
