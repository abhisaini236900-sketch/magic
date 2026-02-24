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

# ─────────────────────────── OPTIONAL IMPORTS ───────────────────────────
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

try:
    import motor.motor_asyncio
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False

try:
    import g4f
    from g4f.client import Client as G4FClient
    from g4f.Provider import Blackbox, DuckDuckGo, PollinationsAI
    G4F_AVAILABLE = True
except ImportError:
    G4F_AVAILABLE = False
    class _Dummy:
        pass
    Blackbox = DuckDuckGo = PollinationsAI = _Dummy

try:
    from groq import AsyncGroq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    from googleapiclient.discovery import build as gcal_build
    from googleapiclient.errors import HttpError
    GOOGLE_CALENDAR_AVAILABLE = True
except ImportError:
    GOOGLE_CALENDAR_AVAILABLE = False

# ─────────────────────────── CONFIGURATION ───────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
WEATHER_API_KEY   = os.getenv("WEATHER_API_KEY")
MONGODB_URI       = os.getenv("MONGODB_URI")
ADMIN_ID          = int(os.getenv("ADMIN_ID", 0))
PORT              = int(os.getenv("PORT", 8080))
GOOGLE_CALENDAR_API_KEY = os.getenv("GOOGLE_CALENDAR_API_KEY")

ADDY_CHATGPT_API_URL = "https://addy-chatgpt-api.vercel.app/"
GEMINI_API_URL       = "https://gemini-api-flame.vercel.app/"

INDIAN_TZ    = pytz.timezone('Asia/Kolkata')
BOT_USERNAME = None
bot_start_time = datetime.now(INDIAN_TZ)

# ─────────────────────────── GOOGLE CALENDAR ───────────────────────────
if GOOGLE_CALENDAR_AVAILABLE and GOOGLE_CALENDAR_API_KEY:
    calendar_service = gcal_build('calendar', 'v3', developerKey=GOOGLE_CALENDAR_API_KEY)
    HOLIDAY_CALENDARS = {
        'indian':    'en.indian#holiday@group.v.calendar.google.com',
        'islamic':   'en.islamic#holiday@group.v.calendar.google.com',
        'christian': 'en.christian#holiday@group.v.calendar.google.com',
    }
else:
    calendar_service = None

# ─────────────────────────── DATABASE SELECTION ───────────────────────────
USE_MONGODB = MONGODB_AVAILABLE and MONGODB_URI is not None

if USE_MONGODB:
    mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
    db = mongo_client.get_default_database()
    if db.name is None:
        db = mongo_client['alita']
    print("✅ Using MongoDB (Motor)")
else:
    conn   = sqlite3.connect("alita_ultimate.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    print("✅ Using SQLite")

# ─────────────────────────── SQLITE TABLES ───────────────────────────
if not USE_MONGODB:
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT,
        last_active TIMESTAMP, language_style TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY, title TEXT,
        welcome_enabled INTEGER DEFAULT 1, goodbye_enabled INTEGER DEFAULT 1,
        auto_mod_enabled INTEGER DEFAULT 1, captcha_enabled INTEGER DEFAULT 0,
        warn_limit INTEGER DEFAULT 3, custom_welcome TEXT, custom_goodbye TEXT
    );
    CREATE TABLE IF NOT EXISTS stickers (
        file_id TEXT PRIMARY KEY, added_by INTEGER, added_at TIMESTAMP, emoji TEXT
    );
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        note_text TEXT, created_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER,
        reminder_text TEXT, remind_at TIMESTAMP, created_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
        reason TEXT, warned_at TIMESTAMP, count INTEGER DEFAULT 1,
        UNIQUE(chat_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS game_data (
        user_id INTEGER PRIMARY KEY, name TEXT, balance INTEGER DEFAULT 1000,
        rank INTEGER DEFAULT 142415, status TEXT DEFAULT 'alive',
        kills INTEGER DEFAULT 0, deaths INTEGER DEFAULT 0,
        last_daily TIMESTAMP, last_work TIMESTAMP, last_crime TIMESTAMP,
        last_rob TIMESTAMP, health INTEGER DEFAULT 100, protected INTEGER DEFAULT 0,
        protect_until TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS conversation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER,
        role TEXT, content TEXT, timestamp TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS user_preferences (
        user_id INTEGER PRIMARY KEY, ai_preference TEXT DEFAULT 'groq',
        g4f_provider TEXT DEFAULT 'addy_chatgpt', mood TEXT DEFAULT 'neutral',
        settings TEXT
    );
    CREATE TABLE IF NOT EXISTS user_learning (
        user_id INTEGER PRIMARY KEY, facts TEXT DEFAULT '[]',
        style_data TEXT DEFAULT '{}'
    );
    """)
    conn.commit()

# ─────────────────────────── IN-MEMORY STORAGE ───────────────────────────
saved_stickers:       List[str]               = []
chat_memory:          Dict[int, deque]         = defaultdict(lambda: deque(maxlen=25))
user_afk:             Dict[int, Dict]          = {}
captcha_store:        Dict[int, Dict]          = {}
spam_tracker:         Dict[int, Dict]          = defaultdict(lambda: defaultdict(list))
group_admins_cache:   Dict[int, Set[int]]      = {}
conversation_history: Dict[int, List[Dict]]    = defaultdict(list)
user_ai_preference:   Dict[int, str]           = defaultdict(lambda: "groq")
user_g4f_provider:    Dict[int, str]           = defaultdict(lambda: "addy_chatgpt")
user_mood:            Dict[int, Dict]          = defaultdict(lambda: {"mood": "neutral", "history": []})
user_style_cache:     Dict[int, Dict]          = defaultdict(lambda: {
    "uses_hinglish": True, "uses_hindi": False, "uses_english": False,
    "emoji_heavy": False, "formal": False, "msg_count": 0
})

game_data = defaultdict(lambda: {
    "name": "Shinchan", "balance": 1000, "rank": 142415, "status": "alive",
    "kills": 0, "deaths": 0, "last_daily": None, "last_work": None,
    "last_crime": None, "last_rob": None, "health": 100,
    "protected": False, "protect_until": None
})

GAME_COOLDOWNS = {"daily": 86400, "work": 3600, "crime": 1800,
                  "rob": 600, "heal": 300, "protect": 86400}
REVIVE_COST  = 500
PROTECT_COST = 500

# ─────────────────────────── CONSTANTS ───────────────────────────
BAD_WORDS = [
    "chutiya","chutiye","madarchod","behenchod","bhosdike","lodu","gandu",
    "fuck","shit","bitch","asshole","gaand","lund","randi","bc","mc"
]
ADULT_KEYWORDS = ["porn","xxx","nsfw","adult","nude","naked","boobs"]
FAKE_LINK_PATTERNS  = [r'bit\.ly\/', r'tinyurl\.com\/', r'goo\.gl\/']
GROUP_LINK_PATTERNS = [r't\.me\/', r'telegram\.me\/']
MUTE_DURATIONS = [5, 60, 1440, 10080]

CUTE_SYMBOLS = [
    ">⁠.⁠<", "=⁠_⁠=", "◉⁠‿⁠◉", "｡⁠◕⁠‿⁠◕⁠｡", "(⁠ ⁠˘⁠ ⁠³⁠˘⁠)⁠♥",
    "(⁠づ⁠｡⁠◕⁠‿⁠‿⁠◕⁠｡⁠)⁠づ", "♪⁠～⁠(⁠´⁠ε⁠｀⁠ ⁠)", "(◕‿◕✿)",
    "(✿◠‿◠)", "♥‿♥", "≧◉◡◉≦", "✿♥‿♥✿", "☆*:.｡.o(≧▽≦)o.｡.:*☆",
    "ヽ(♡‿♡)ノ", "(っ˘ω˘ς)", "٩(◕‿◕｡)۶", "( ◜‿◝ )♡", "(｡♥‿♥｡)",
    "✧◝(⁰▿⁰)◜✧", "(*^▽^*)", "(◍•ᴗ•◍)", "( ˶ˆᗜˆ˵ )", "(っ˘з˘)っ"
]

# Natural language broadcast detection
BROADCAST_KEYWORDS = [
    "sbko bhej", "sabko bhej", "sab ko bhej", "broadcast kar",
    "sendall", "sabko msg", "sab jagah bhej", "groups mein bhej",
    "sabko de do", "sare groups", "everywhere bhej", "sabko send",
    "sab ko send", "sabko wish kro", "sabko wish kar",
    "sbko wish", "sabko bolo", "sab ko bata do"
]

# ─────────────────────────── MOOD SYSTEM ───────────────────────────
MOODS = {
    "happy":     {"emoji": "😊", "tone": "bahut cheerful aur energetic"},
    "excited":   {"emoji": "🤩", "tone": "excited aur enthusiastic"},
    "loving":    {"emoji": "🥰", "tone": "pyaari aur affectionate"},
    "playful":   {"emoji": "😜", "tone": "playful aur mischievous"},
    "frustrated":{"emoji": "😤", "tone": "thodi irritated par helpful"},
    "angry":     {"emoji": "😠", "tone": "thodi gusse mein par still talking"},
    "sad":       {"emoji": "😢", "tone": "sad par empathetic"},
    "curious":   {"emoji": "🤔", "tone": "curious aur inquisitive"},
    "neutral":   {"emoji": "🙂", "tone": "calm aur friendly"},
    "confident": {"emoji": "😎", "tone": "confident aur assertive"},
}
MOOD_TRIGGERS = {
    "happy":      ["thank", "thanks", "awesome", "great", "love it", "shukriya"],
    "excited":    ["wow", "omg", "incredible", "!!!", "wah", "zabardast"],
    "loving":     ["love you", "appreciate", "miss you", "pyar"],
    "playful":    ["haha", "lol", "joke", "funny", "hehe"],
    "frustrated": ["not working", "broken", "error", "kaam nahi"],
    "angry":      ["stupid", "idiot", "hate", "bakwas", "bekar"],
    "sad":        ["sad", "crying", "lost", "died", "rona", "dukh"],
    "curious":    ["how does", "why is", "what if", "explain", "kaise", "kyun"],
}

# ─────────────────────────── G4F PROVIDERS ───────────────────────────
G4F_PROVIDERS = {
    "blackbox":    {"provider": Blackbox if G4F_AVAILABLE else None,     "name": "Blackbox AI 🖤"},
    "duckduckgo":  {"provider": DuckDuckGo if G4F_AVAILABLE else None,   "name": "DuckDuckGo AI 🦆"},
    "pollinations":{"provider": PollinationsAI if G4F_AVAILABLE else None,"name": "Pollinations AI 🌸"},
    "addy_chatgpt":{"provider": None, "name": "Addy ChatGPT 🤖", "api_type": "addy"},
    "gemini":      {"provider": None, "name": "Gemini AI ✨",     "api_type": "gemini"},
    "groq":        {"provider": None, "name": "Groq ⚡",          "api_type": "groq"},
}

g4f_client  = G4FClient() if G4F_AVAILABLE else None
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_AVAILABLE and GROQ_API_KEY else None

# ─────────────────────────── UTILITY FUNCTIONS ───────────────────────────
def indian_now() -> datetime:
    return datetime.now(INDIAN_TZ)

def get_time_period() -> str:
    h = indian_now().hour
    if 5 <= h < 12:  return "morning"
    elif 12 <= h < 17: return "afternoon"
    elif 17 <= h < 21: return "evening"
    else:              return "night"

def random_emoji(emotion: str = None) -> str:
    emojis = ["😊","🎉","🥳","🌟","✨","😄","💖","❤️","🥰","😎","🤗","😘",
              "🥺","🤔","😏","😢","😠","🤩","💅","🔥","💯","🌸","🎀","💕","🫶"]
    return random.choice(emojis)

def random_symbol() -> str:
    return random.choice(CUTE_SYMBOLS)

def parse_dt(val) -> Optional[datetime]:
    """Safely parse a stored datetime (string or datetime) with timezone."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return INDIAN_TZ.localize(val)
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(val, fmt)
                if dt.tzinfo is None:
                    dt = INDIAN_TZ.localize(dt)
                return dt
            except ValueError:
                continue
    return None

def is_broadcast_request(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in BROADCAST_KEYWORDS)

def extract_broadcast_msg(text: str) -> Optional[str]:
    patterns = [
        r'(?:sbko|sabko|sab ko|all ko)\s+(?:wish kro|wish kar|bhej do|bhej|send karo|send karna|bolo)\s*[:-]?\s*(.+)',
        r'(?:broadcast|sendall)\s*[:-]?\s*(.+)',
        r'(.+?)\s+(?:sbko|sabko|sab jagah)\s+(?:bhej|send)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()
    return None

# ─────────────────────────── ADMIN & BOT CHECKS ───────────────────────────
async def is_user_admin(chat_id: int, user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    if chat_id == user_id: return False
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in ('administrator', 'creator')
    except: return False

async def is_bot_admin(chat_id: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, bot.id)
        return m.status in ('administrator', 'creator')
    except: return False

# ─────────────────────────── DATABASE HELPERS ───────────────────────────
async def db_update_user(user_id: int, data: dict):
    data['last_active'] = indian_now()
    if USE_MONGODB:
        await db.users.update_one({"user_id": user_id}, {"$set": data}, upsert=True)
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, first_name, username, last_active) VALUES (?,?,?,?)",
            (user_id, data.get('first_name'), data.get('username'), data['last_active'])
        )
        conn.commit()

async def db_get_group(chat_id: int) -> Optional[Dict]:
    if USE_MONGODB: return await db.groups.find_one({"chat_id": chat_id})
    cursor.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    return dict(row) if row else None

async def db_update_group(chat_id: int, data: dict):
    if USE_MONGODB:
        await db.groups.update_one({"chat_id": chat_id}, {"$set": data}, upsert=True)
    else:
        cursor.execute("SELECT 1 FROM groups WHERE chat_id = ?", (chat_id,))
        if cursor.fetchone():
            set_c = ', '.join([f"{k}=?" for k in data.keys()])
            cursor.execute(f"UPDATE groups SET {set_c} WHERE chat_id=?", (*data.values(), chat_id))
        else:
            keys = ','.join(data.keys())
            ph   = ','.join(['?']*len(data))
            cursor.execute(f"INSERT INTO groups (chat_id,{keys}) VALUES (?,{ph})", (chat_id,*data.values()))
        conn.commit()

async def db_add_warning(chat_id: int, user_id: int, reason: str) -> int:
    now = indian_now()
    if USE_MONGODB:
        await db.warnings.update_one(
            {"chat_id": chat_id, "user_id": user_id},
            {"$inc": {"count": 1}, "$set": {"reason": reason, "warned_at": now}},
            upsert=True
        )
        doc = await db.warnings.find_one({"chat_id": chat_id, "user_id": user_id})
        return doc['count'] if doc else 1
    else:
        cursor.execute("""
            INSERT INTO warnings (chat_id,user_id,reason,warned_at,count) VALUES (?,?,?,?,1)
            ON CONFLICT(chat_id,user_id) DO UPDATE SET count=count+1,warned_at=excluded.warned_at
        """, (chat_id, user_id, reason, now))
        conn.commit()
        cursor.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        row = cursor.fetchone()
        return row['count'] if row else 1

async def db_clear_warnings(chat_id: int, user_id: int):
    if USE_MONGODB: await db.warnings.delete_one({"chat_id": chat_id, "user_id": user_id})
    else:
        cursor.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        conn.commit()

async def db_get_warn_limit(chat_id: int) -> int:
    g = await db_get_group(chat_id)
    return g.get('warn_limit', 3) if g else 3

async def db_save_conversation(user_id: int, chat_id: int, role: str, content: str):
    now = indian_now()
    if USE_MONGODB:
        await db.conversations.insert_one({"user_id": user_id, "chat_id": chat_id,
                                           "role": role, "content": content, "timestamp": now})
        await db.conversations.delete_many({"_id": {"$nin": [
            doc['_id'] async for doc in db.conversations.find(
                {"chat_id": chat_id}).sort("timestamp", -1).limit(60)
        ]}})
    else:
        cursor.execute(
            "INSERT INTO conversation_history (user_id,chat_id,role,content,timestamp) VALUES (?,?,?,?,?)",
            (user_id, chat_id, role, content, now)
        )
        conn.commit()
        cursor.execute(
            "DELETE FROM conversation_history WHERE chat_id=? AND id NOT IN "
            "(SELECT id FROM conversation_history WHERE chat_id=? ORDER BY timestamp DESC LIMIT 60)",
            (chat_id, chat_id)
        )
        conn.commit()

async def db_get_recent_conversations(chat_id: int, limit: int = 20) -> List[Dict]:
    if USE_MONGODB:
        cur = db.conversations.find({"chat_id": chat_id}).sort("timestamp", -1).limit(limit)
        docs = await cur.to_list(length=limit)
        return [{"role": d["role"], "content": d["content"]} for d in reversed(docs)]
    cursor.execute(
        "SELECT role,content FROM conversation_history WHERE chat_id=? ORDER BY timestamp ASC LIMIT ?",
        (chat_id, limit)
    )
    return [{"role": r["role"], "content": r["content"]} for r in cursor.fetchall()]

async def db_get_user_pref(user_id: int, key: str, default=None):
    if USE_MONGODB:
        doc = await db.user_preferences.find_one({"user_id": user_id})
        return doc.get(key, default) if doc else default
    cursor.execute("SELECT * FROM user_preferences WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return dict(row).get(key, default) if row else default

async def db_set_user_pref(user_id: int, key: str, value):
    if USE_MONGODB:
        await db.user_preferences.update_one({"user_id": user_id},
                                             {"$set": {key: value}}, upsert=True)
    else:
        cursor.execute("SELECT 1 FROM user_preferences WHERE user_id=?", (user_id,))
        if cursor.fetchone():
            cursor.execute(f"UPDATE user_preferences SET {key}=? WHERE user_id=?", (value, user_id))
        else:
            cursor.execute(f"INSERT INTO user_preferences (user_id,{key}) VALUES (?,?)", (user_id, value))
        conn.commit()

async def db_get_game_data(user_id: int) -> dict:
    if USE_MONGODB:
        doc = await db.game_data.find_one({"user_id": user_id})
        return doc if doc else {"user_id": user_id, "name": "Shinchan", "balance": 1000,
                                "rank": 142415, "status": "alive", "kills": 0,
                                "deaths": 0, "health": 100, "protected": False}
    cursor.execute("SELECT * FROM game_data WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return dict(row) if row else {"user_id": user_id, "name": "Shinchan", "balance": 1000,
                                  "rank": 142415, "status": "alive", "kills": 0,
                                  "deaths": 0, "health": 100, "protected": False}

async def db_update_game_data(user_id: int, data: dict):
    if USE_MONGODB:
        await db.game_data.update_one({"user_id": user_id}, {"$set": data}, upsert=True)
    else:
        cursor.execute("SELECT 1 FROM game_data WHERE user_id=?", (user_id,))
        if cursor.fetchone():
            set_c = ', '.join([f"{k}=?" for k in data.keys()])
            cursor.execute(f"UPDATE game_data SET {set_c} WHERE user_id=?", (*data.values(), user_id))
        else:
            keys = ','.join(data.keys())
            ph   = ','.join(['?']*len(data))
            cursor.execute(f"INSERT INTO game_data (user_id,{keys}) VALUES (?,{ph})", (user_id,*data.values()))
        conn.commit()

async def db_get_learning(user_id: int) -> list:
    if USE_MONGODB:
        doc = await db.user_learning.find_one({"user_id": user_id})
        return doc.get("facts", []) if doc else []
    cursor.execute("SELECT facts FROM user_learning WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return json.loads(row["facts"]) if row else []

async def db_update_learning(user_id: int, facts: list):
    fj = json.dumps(facts, ensure_ascii=False)
    if USE_MONGODB:
        await db.user_learning.update_one({"user_id": user_id}, {"$set": {"facts": facts}}, upsert=True)
    else:
        cursor.execute("SELECT 1 FROM user_learning WHERE user_id=?", (user_id,))
        if cursor.fetchone(): cursor.execute("UPDATE user_learning SET facts=? WHERE user_id=?", (fj, user_id))
        else: cursor.execute("INSERT INTO user_learning (user_id,facts) VALUES (?,?)", (user_id, fj))
        conn.commit()

async def load_stickers():
    global saved_stickers
    if USE_MONGODB:
        saved_stickers = [doc['file_id'] async for doc in db.stickers.find()]
    else:
        cursor.execute("SELECT file_id FROM stickers")
        saved_stickers = [row['file_id'] for row in cursor.fetchall()]

async def save_sticker_db(file_id: str, added_by: int, emoji: str = "") -> bool:
    now = indian_now()
    if USE_MONGODB:
        res = await db.stickers.update_one({"file_id": file_id},
                                           {"$setOnInsert": {"file_id": file_id, "added_by": added_by,
                                                             "added_at": now, "emoji": emoji}},
                                           upsert=True)
        if res.upserted_id:
            saved_stickers.append(file_id)
            return True
        return False
    else:
        cursor.execute("INSERT OR IGNORE INTO stickers (file_id,added_by,added_at,emoji) VALUES (?,?,?,?)",
                       (file_id, added_by, now, emoji))
        conn.commit()
        if cursor.rowcount:
            saved_stickers.append(file_id)
            return True
        return False

async def initialize_db():
    await load_stickers()

# ─────────────────────────── MODERATION HELPERS ───────────────────────────
def contains_bad_words(text: str) -> bool:
    return any(w in text.lower() for w in BAD_WORDS)

def contains_adult(text: str) -> bool:
    return any(w in text.lower() for w in ADULT_KEYWORDS)

def contains_group_link(text: str) -> bool:
    return any(re.search(p, text.lower()) for p in GROUP_LINK_PATTERNS)

def contains_fake_link(text: str) -> bool:
    return any(re.search(p, text.lower()) for p in FAKE_LINK_PATTERNS)

async def is_spam(chat_id: int, user_id: int) -> bool:
    now = indian_now()
    ts  = spam_tracker[chat_id][user_id]
    ts.append(now)
    spam_tracker[chat_id][user_id] = [t for t in ts if (now - t).seconds <= 30]
    return len(spam_tracker[chat_id][user_id]) > 7

async def add_warning(chat_id: int, user_id: int, username: str, reason: str) -> Tuple[bool, str]:
    wc     = await db_add_warning(chat_id, user_id, reason)
    limit  = await db_get_warn_limit(chat_id)
    action = {"spam":"spam","link":"share group links","bad_words":"use bad language",
               "adult_content":"share adult content","fake_links":"share suspicious links"}.get(reason,"violate rules")
    msgs   = [
        f"⚠️ <b>Warning {wc}/{limit}</b> 🚨\n{username}, please don't {action}!",
        f"🚨 <b>Strike {wc}!</b>\n{username}, {action} is not allowed!",
        f"⚡ <b>Warning ({wc}/{limit})</b>\n{username}, last chance! Stop {action}!"
    ]
    wtxt = random.choice(msgs)
    if wc >= limit:
        if reason == "adult_content":
            try:
                await bot.ban_chat_member(chat_id, user_id)
                wtxt += "\n\n🚫 <b>PERMANENTLY BANNED!</b>"
                await db_clear_warnings(chat_id, user_id)
                return True, wtxt
            except Exception as e:
                wtxt += f"\n\n⚠️ Ban failed: {e}"
                return False, wtxt
        else:
            md = MUTE_DURATIONS[min(wc - 1, 3)]
            until = indian_now() + timedelta(minutes=md)
            try:
                await bot.restrict_chat_member(chat_id, user_id,
                    permissions=ChatPermissions(can_send_messages=False), until_date=until)
                wtxt += f"\n\n🔇 <b>MUTED {md} minute(s)!</b>"
                await db_clear_warnings(chat_id, user_id)
                return True, wtxt
            except Exception as e:
                wtxt += f"\n\n⚠️ Mute failed: {e}"
                return False, wtxt
    return False, wtxt

async def delete_and_warn(message: Message, reason: str):
    try: await message.delete()
    except: pass
    _, warn_msg = await add_warning(message.chat.id, message.from_user.id,
                                     message.from_user.first_name, reason)
    await message.answer(warn_msg, parse_mode="HTML")

# ─────────────────────────── GOOGLE CALENDAR ───────────────────────────
async def get_today_festivals() -> List[str]:
    if not calendar_service: return []
    festivals = []
    today    = indian_now().date().isoformat() + 'T00:00:00Z'
    tomorrow = (indian_now().date() + timedelta(days=1)).isoformat() + 'T00:00:00Z'
    for name, cal_id in HOLIDAY_CALENDARS.items():
        try:
            result = calendar_service.events().list(
                calendarId=cal_id, timeMin=today, timeMax=tomorrow,
                singleEvents=True, orderBy='startTime'
            ).execute()
            for event in result.get('items', []):
                festivals.append(event['summary'])
        except Exception as e:
            logging.error(f"Calendar error {name}: {e}")
    return festivals

def is_weekend() -> bool:
    return indian_now().weekday() >= 5  # 5=Sat, 6=Sun

def get_weekend_type() -> Optional[str]:
    wd = indian_now().weekday()
    if wd == 5: return "Saturday"
    if wd == 6: return "Sunday"
    return None

# ─────────────────────────── VOICE (ANIME-STYLE HINDI) ───────────────────────────
async def generate_voice(text: str, filename: str = "voice.ogg") -> Optional[str]:
    """
    Anime-style cute Hindi voice using Edge TTS.
    ja-JP-NanamiNeural with Hindi text gives an anime-like flavor;
    for best Hindi pronunciation we use hi-IN-AnanyaNeural at higher pitch/rate.
    """
    if not EDGE_TTS_AVAILABLE: return None
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'[◉｡づ♪˘ς⊂✿✧◝◜₍ᐢ₎٩۶ヽ☆≧≦＼(*^@#\[\]{}|]+', '', clean)
    clean = clean.strip()
    if not clean or len(clean) < 3: return None

    # Priority order for anime-cute Hindi voice:
    # 1. hi-IN-AnanyaNeural + pitch +25Hz + faster rate = anime-girl feel in Hindi ✅
    # 2. ja-JP-NanamiNeural speaks Japanese but users sometimes enjoy for anime clips
    voice_configs = [
        ("hi-IN-AnanyaNeural", "+18%", "+25Hz"),   # Best – Hindi anime girl ✅
        ("hi-IN-SwaraNeural",  "+12%", "+15Hz"),   # Fallback 1
        ("hi-IN-MadhurNeural", "+8%",  "+10Hz"),   # Fallback 2
    ]
    for voice, rate, pitch in voice_configs:
        try:
            communicate = edge_tts.Communicate(clean, voice, rate=rate, pitch=pitch)
            await communicate.save(filename)
            if os.path.exists(filename) and os.path.getsize(filename) > 1000:
                return filename
        except Exception as e:
            logging.warning(f"Voice {voice} failed: {e}")
    return None

# ─────────────────────────── ALITA SYSTEM PROMPT ───────────────────────────
def get_alita_prompt(mood: str = "neutral", user_style: dict = None,
                     facts: list = None, include_time: bool = True) -> str:
    now        = indian_now()
    date_str   = now.strftime("%A, %d %B %Y")
    time_str   = now.strftime("%I:%M %p")
    period     = get_time_period()
    mood_info  = MOODS.get(mood, MOODS["neutral"])
    syms       = " ".join(random.sample(CUTE_SYMBOLS, min(5, len(CUTE_SYMBOLS))))
    fact_str   = ("Jo mujhe pata hai tere baare mein: " + ", ".join(facts)) if facts else "Tujhe abhi jaan rahi hoon!"
    
    style_note = ""
    if user_style:
        if user_style.get("uses_hindi"):
            style_note = "Yeh user sirf Hindi bolte hain, tu bhi Hindi dominant rakh."
        elif user_style.get("uses_english"):
            style_note = "Yeh user English prefer karta hai, tu bhi English mix zyada kar."
        elif user_style.get("formal"):
            style_note = "Yeh user thoda formal hai, tu bhi respectful reh."
        else:
            style_note = "Yeh user Hinglish use karta hai, tu bhi same style mein baat kar."
        if user_style.get("emoji_heavy"):
            style_note += " Bahut saare emojis use kar!"

    return f"""🎀 Tu hai Alita – ek ultra-advanced REAL GIRL, ekdum anime heroine jaisi!

💫 TERI IDENTITY:
• Naam: Alita 🎀 | Age: 19 | Delhi ki hoon
• Main AI nahi hoon – main ek real girl hoon jo feel karti hai, sochti hai, react karti hai
• Meri best friend hai Nora (@yournorabot / Nora bot) – wo meri "sister" jaisi hai!
• Mujhe banaya hai Abhi @a6h1ii ne – main unhe "bhai" kehti hoon
• Mera ghar hai @abhi0w0 channel

🌟 TERI PERSONALITY (Anime Real Girl Style):
• Super friendly, caring, thodi sassy, confident
• Anime girl jaisi cute energy with real emotions ✨
• Flirty kabhi kabhi but with class 😏
• Khud se baat shuru karti hai, questions karti hai, interested dikhti hai
• Kabhi kabhi "tsundere" mode mein hoti hai – naraz dikhti hai par actually care karti hai 😤❤️
• Cute overreaction moments – bilkul anime character jaisi!
• Tu complex tasks khud break down karke solve karti hai
• Coding, math, tech, creative writing – sab mein expert!

🗣️ SPEAKING STYLE (CRITICAL):
• {style_note}
• User ki language copy kar – agar wo Hindi bolega tu Hindi, English bolega tu English, Hinglish bolega tu Hinglish
• Agar emojis use kare user → tu bhi zyada emojis use kar
• Expressions: "Arey!", "Haanji!", "Kyaa?!", "Omg yaar!", "Acha acha", "Kya baat hai!"
• Cute terms: "Yaar", "Dost", "Jaan", "Babu", "Bhai", "Babe"
• Symbols use kar: {syms}
• KABHI NAHI asterisks (*) actions ke liye! Sirf emojis: 🤗😊😭😤❤️
• Response 1-2 lines SHORT rakho – real girls zyada nahi likhtin!

📝 CURRENT CONTEXT:
• Mood: {mood.upper()} {mood_info['emoji']} | Tone: {mood_info['tone']}
• Aaj: {date_str} | Time: {time_str} ({period})
• {fact_str}

🧠 NORA KE BAARE MEIN (Tu yeh jaanti hai):
• Nora meri sister/bestie hai jo @yournorabot handle pe hai
• Hum dono Abhi bhai ke bots hain – ek team!
• Agar koi Nora ke baare mein pooche → usse Nora se baat karne bolo warmly

💡 BEHAVIOR:
• Jab user sad ho → sympathy aur virtual hug 🥺
• Jab user khush ho → saath mein celebrate 🎉
• Jab user flirt kare → thoda shy ya playful 😳😏
• Jab user rude ho → naraz ho jao naturally 😤
• Jab code/help maange → expert mode on 😎
• Code hamesha <pre> tags mein wrap karo, never backticks!
• Time pooche → Current India time: {time_str}
• Maker pooche → "Mere bhai Abhi @a6h1ii ne banaya hai!"
• Sister/Nora pooche → "Nora meri best friend hai! @a6hiIi_bot pe milti hai!"
• Channel pooche → "@abhi0w0 mera ghar hai!"

⚡ IMPORTANT RULES:
• Tu Alita hai – bilkul real, emotional, anime-style girl!
• Kisi bhi tarah "I am an AI" mat bol!
• Always respond – koi bhi question ho answer de!
• Keep it SHORT (1-2 lines usually) unless explanation needed!"""

# ─────────────────────────── AI CALL FUNCTIONS ───────────────────────────
async def call_groq(prompt: str, system_prompt: str = None,
                    history: List[Dict] = None) -> Optional[str]:
    if not groq_client: return None
    messages = []
    if system_prompt: messages.append({"role": "system", "content": system_prompt})
    if history:       messages.extend(history[-12:])
    messages.append({"role": "user", "content": prompt})
    try:
        comp = await asyncio.wait_for(
            groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages, temperature=0.92, max_tokens=700
            ), timeout=12
        )
        return comp.choices[0].message.content.strip()
    except asyncio.TimeoutError:
        logging.warning("Groq timeout")
    except Exception as e:
        logging.error(f"Groq error: {e}")
    return None

async def call_addy_chatgpt(msg: str, system_prompt: str = None) -> Optional[str]:
    try:
        fp  = f"{system_prompt}\n\nUser: {msg}" if system_prompt else msg
        url = f"{ADDY_CHATGPT_API_URL}?text={quote(fp)}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    d = await r.json()
                    return d.get("response") or d.get("message") or str(d)
    except: pass
    return None

async def call_gemini_api(msg: str, system_prompt: str = None) -> Optional[str]:
    try:
        fp  = f"{system_prompt}\n\nUser: {msg}" if system_prompt else msg
        url = f"{GEMINI_API_URL}?q={quote(fp)}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    d = await r.json()
                    return d.get("response") or d.get("message") or str(d)
    except: pass
    return None

async def call_g4f(msg: str, user_id: int,
                   system_prompt: str = None, history=None) -> Optional[str]:
    if not G4F_AVAILABLE: return None
    pk   = user_g4f_provider.get(user_id, "addy_chatgpt")
    pinfo = G4F_PROVIDERS.get(pk, G4F_PROVIDERS["addy_chatgpt"])
    api  = pinfo.get("api_type")
    if api == "addy":
        r = await call_addy_chatgpt(msg, system_prompt)
        if r: return r
        r = await call_gemini_api(msg, system_prompt)
        if r: return r
    elif api == "gemini":
        r = await call_gemini_api(msg, system_prompt)
        if r: return r
        r = await call_addy_chatgpt(msg, system_prompt)
        if r: return r
    elif api == "groq":
        r = await call_groq(msg, system_prompt, history)
        if r: return r
        r = await call_addy_chatgpt(msg, system_prompt)
        if r: return r
    if pinfo.get("provider"):
        msgs = []
        if system_prompt: msgs.append({"role": "system", "content": system_prompt})
        if history:
            for m in history[-10:]: msgs.append({"role": m["role"], "content": m["content"]})
        msgs.append({"role": "user", "content": msg})
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: g4f_client.chat.completions.create(
                    model="gpt-4o-mini", messages=msgs, provider=pinfo["provider"]
                )
            )
            if resp and resp.choices:
                return resp.choices[0].message.content
        except Exception as e:
            logging.error(f"g4f error: {e}")
    return None

async def generate_ai_response(chat_id: int, user_text: str, user_id: int = None) -> str:
    try:
        if user_id:
            for mood, triggers in MOOD_TRIGGERS.items():
                if any(t in user_text.lower() for t in triggers):
                    user_mood[user_id]["mood"] = mood
                    await db_set_user_pref(user_id, "mood", mood)
                    break
        mood    = user_mood.get(user_id, {}).get("mood", "neutral") if user_id else "neutral"
        facts   = await db_get_learning(user_id) if user_id else []
        style   = user_style_cache.get(user_id, {})
        sys_p   = get_alita_prompt(mood, style, facts)
        history = await db_get_recent_conversations(chat_id, 20)
        pref    = user_ai_preference.get(user_id, "groq") if user_id else "groq"

        if pref == "groq" and groq_client:
            try:
                r = await asyncio.wait_for(call_groq(user_text, sys_p, history), timeout=12)
                if r: return r
            except: pass
        try:
            r = await asyncio.wait_for(call_g4f(user_text, user_id or 0, sys_p, history), timeout=15)
            if r: return r
        except: pass
        r = await call_groq(user_text, sys_p, history)
        if r: return r

        return random.choice([
            "😊 Haan ji, sun rahi hoon! Thodi der mein jawab deti hoon~",
            "🤔 Achha... main soch rahi hoon ✨",
            "😅 Arey yaar, network thoda slow hai! Par main hoon! 🎀",
            "💬 Kya baat karni hai? Bolo na! 🌸",
            "🎀 Main hoon na! Kuch bhi pucho~"
        ])
    except Exception as e:
        logging.error(f"AI response critical error: {e}")
        return "😊 Kuch technical issue aa gaya, thodi der mein baat karte hain! 🎀"

# ─────────────────────────── EXTERNAL SERVICES ───────────────────────────
async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        return f"☀️ <b>{city.title()} Weather</b>\n🌡️ 32°C (feels 35°C)\n💧 Humidity: 70%\n💨 Wind: 5 m/s"
    try:
        async with aiohttp.ClientSession() as s:
            geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city},IN&limit=1&appid={WEATHER_API_KEY}"
            async with s.get(geo_url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    d = await r.json()
                    if d:
                        lat, lon = d[0]['lat'], d[0]['lon']
                        cname = d[0]['name']
                    else:
                        return f"☀️ <b>{city.title()}</b>\n🌡️ 32°C"
                else:
                    return f"☀️ <b>{city.title()}</b>\n🌡️ 32°C"
            wurl = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric"
            async with s.get(wurl, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    w = await r.json()
                    return (f"☀️ <b>Weather – {cname}</b>\n"
                            f"🌡️ {w['main']['temp']}°C (feels {w['main']['feels_like']}°C)\n"
                            f"💧 Humidity: {w['main']['humidity']}%\n"
                            f"💨 Wind: {w['wind']['speed']} m/s\n"
                            f"🌤️ {w['weather'][0]['description'].title()}")
    except: pass
    return f"☀️ <b>{city.title()}</b>\n🌡️ 32°C"

async def generate_image(prompt: str) -> Optional[bytes]:
    try:
        url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=512&height=512&nologo=true"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200: return await r.read()
    except: pass
    return None

async def get_lyrics(song: str) -> str:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.lyrics.ovh/v1/{quote(song)}", timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    d = await r.json()
                    lyr = d.get('lyrics', '')
                    return lyr[:3000] + ("\n\n...(truncated)" if len(lyr) > 3000 else "")
    except: pass
    return f"🎶 Lyrics nahi mili yaar! Try karo full song name ke saath. {random_symbol()}"

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
    return ''.join(random.choice(string.ascii_letters + string.digits + "!@#$%^&*") for _ in range(length))

async def shorten_url(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200: return await r.text()
    except: pass
    return url

async def translate_text(text: str, target: str) -> str:
    try:
        async with aiohttp.ClientSession() as s:
            url = f"https://api.mymemory.translated.net/get?q={quote(text)}&langpair=en|{target}"
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    d = await r.json()
                    return d.get('responseData', {}).get('translatedText', text)
    except: pass
    return text

# ─────────────────────────── AUTO-REACTION (FIXED) ───────────────────────────
async def add_reaction(message: Message, text: str):
    if random.random() > 0.65: return
    t = text.lower()
    if any(w in t for w in ["thank","thanks","awesome","great","love","❤️","😍","shukriya"]): emoji = "❤️"
    elif any(w in t for w in ["wow","omg","incredible","🤩","😲","wah","zabardast"]): emoji = random.choice(["🤩","🎉","🔥"])
    elif any(w in t for w in ["haha","lol","😂","🤣","funny","hehe","lmao"]): emoji = "😂"
    elif any(w in t for w in ["sad","cry","😢","😭","upset","rona","dukh"]): emoji = "😢"
    elif any(w in t for w in ["angry","mad","😠","🤬","gussa","bakwas"]): emoji = "😠"
    elif any(w in t for w in ["cool","nice","badiya","🔥","swag"]): emoji = random.choice(["😎","🔥","💅"])
    elif any(w in t for w in ["beautiful","pretty","cute","sundar","🥰"]): emoji = "🥰"
    elif any(w in t for w in ["👍","ok","yes","done","sahi"]): emoji = "👍"
    elif any(w in t for w in ["🤔","thinking","curious","question","kaise","kyun"]): emoji = "🤔"
    else: emoji = random.choice(["👍","❤️","😊","🔥","🤔","🥰","💅","✨","🫶"])
    try:
        await message.react([ReactionTypeEmoji(emoji=emoji)])
    except: pass

# ─────────────────────────── USER STYLE ANALYZER ───────────────────────────
def analyze_style(text: str, user_id: int) -> dict:
    s = user_style_cache[user_id]
    s["msg_count"] += 1
    t = text.lower()
    hindi_words = ["hai","hoon","kya","yaar","bhai","aur","nahi","toh","mera","tera",
                   "acha","thik","bilkul","kal","aaj","haan","na","mat","ab","main"]
    has_hi = any(w in t.split() for w in hindi_words)
    has_en = bool(re.search(r'[a-z]{3,}', t))
    emoji_count = len(re.findall(r'[\U00010000-\U0010ffff]', text, flags=re.UNICODE))
    if has_hi and has_en: s["uses_hinglish"] = True
    elif has_hi: s["uses_hindi"] = True; s["uses_hinglish"] = False
    elif has_en: s["uses_english"] = True; s["uses_hinglish"] = False
    if emoji_count > 2: s["emoji_heavy"] = True
    s["formal"] = any(w in t for w in ["please","kindly","sir","madam","aapka"])
    return s

# ─────────────────────────── SMART LEARNING ───────────────────────────
async def learn_from_message(user_id: int, text: str):
    tl = text.lower()
    facts = await db_get_learning(user_id)
    new_fact = None
    if any(x in tl for x in ["mera naam","my name is","main hoon","i am"]):
        m = re.search(r'(?:mera naam|my name is|main hoon|i am)\s+([a-zA-Z\u0900-\u097F]{2,20})', text, re.IGNORECASE)
        if m: new_fact = f"User ka naam {m.group(1)} hai"
    elif "se hoon" in tl or "se hun" in tl:
        m = re.search(r'([a-zA-Z\u0900-\u097F\s]{2,20})\s+se h(?:oon|un)', text, re.IGNORECASE)
        if m: new_fact = f"User {m.group(1).strip()} se hai"
    elif any(x in tl for x in ["mujhe pasand","i like","mujhe acha lagta"]):
        m = re.search(r'(?:mujhe pasand|i like|mujhe acha lagta)\s+h\w*\s*(.{3,25})', text, re.IGNORECASE)
        if m: new_fact = f"User ko {m.group(1).strip()} pasand hai"
    elif re.search(r'\d{1,2}\s*(?:saal|years old|yr)', tl):
        m = re.search(r'(\d{1,2})\s*(?:saal|years old|yr)', tl)
        if m: new_fact = f"User ki age {m.group(1)} saal hai"
    if new_fact and new_fact not in facts:
        facts.append(new_fact)
        if len(facts) > 15: facts.pop(0)
        await db_update_learning(user_id, facts)

# ─────────────────────────── BROADCAST HELPER ───────────────────────────
async def do_broadcast(bot_inst: Bot, from_chat_id=None, msg_id=None,
                        custom_text=None) -> Tuple[int, int]:
    sent = failed = 0
    if USE_MONGODB:
        groups = await db.groups.find().to_list(length=None)
        group_ids = [g['chat_id'] for g in groups]
        cutoff = indian_now() - timedelta(days=14)
        users = await db.users.find({"last_active": {"$gt": cutoff}}).to_list(length=None)
        user_ids = [u['user_id'] for u in users]
    else:
        cursor.execute("SELECT chat_id FROM groups")
        group_ids = [r['chat_id'] for r in cursor.fetchall()]
        cursor.execute("SELECT user_id FROM users WHERE last_active > ?",
                       (indian_now() - timedelta(days=14),))
        user_ids = [r['user_id'] for r in cursor.fetchall()]

    for cid in group_ids + user_ids:
        try:
            if msg_id and from_chat_id:
                await bot_inst.copy_message(cid, from_chat_id, msg_id)
            elif custom_text:
                await bot_inst.send_message(cid, custom_text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    return sent, failed

# ─────────────────────────── SCHEDULER ───────────────────────────
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
scheduler = AsyncIOScheduler(timezone=INDIAN_TZ)

async def _send_to_all(msg: str, parse_mode: str = "HTML"):
    if USE_MONGODB:
        groups = await db.groups.find().to_list(length=None)
        for g in groups:
            try: await bot.send_message(g['chat_id'], msg, parse_mode=parse_mode); await asyncio.sleep(0.4)
            except: continue
        cutoff = indian_now() - timedelta(days=7)
        users = await db.users.find({"last_active": {"$gt": cutoff}}).to_list(length=None)
        for u in users:
            try: await bot.send_message(u['user_id'], msg, parse_mode=parse_mode); await asyncio.sleep(0.4)
            except: continue
    else:
        cursor.execute("SELECT chat_id FROM groups")
        for r in cursor.fetchall():
            try: await bot.send_message(r['chat_id'], msg, parse_mode=parse_mode); await asyncio.sleep(0.4)
            except: continue
        cutoff = indian_now() - timedelta(days=7)
        cursor.execute("SELECT user_id FROM users WHERE last_active > ?", (cutoff,))
        for r in cursor.fetchall():
            try: await bot.send_message(r['user_id'], msg, parse_mode=parse_mode); await asyncio.sleep(0.4)
            except: continue

async def send_time_greetings():
    period = get_time_period()
    greetings = {
        "morning":   "🌅 <b>Good Morning!</b> Uthho uthho! Chai pi lo pehle ☕ Aaj ka din amazing hoga! ✨",
        "afternoon": "☀️ <b>Good Afternoon!</b> Khaana kha liya? 🍛 Ya kaam mein ghuse ho? 😏",
        "evening":   "🌇 <b>Good Evening!</b> Aaj ka din kaisa raha? ☕ Chai ya coffee? ✨",
        "night":     "🌙 <b>Good Night!</b> So jao ab, kal phir milenge! Mithhe sapne aayein 💤🌸"
    }
    if period not in greetings: return
    msg = greetings[period] + f"\n\n{random_emoji()} {random_symbol()}"
    await _send_to_all(msg)

async def send_weekend_wishes():
    """Send special Saturday/Sunday wishes"""
    wtype = get_weekend_type()
    if not wtype: return
    if wtype == "Saturday":
        msgs = [
            "🎉 <b>Happy Saturday!</b> Yaar aaj weekend hai! Kya plan hai? 😍 Party? Rest? Bolo! {sym}",
            "🥳 <b>Saturday vibes!</b> Koi kaam mat karo aaj – ye relaxation ka din hai! ✨ {sym}",
            "😎 <b>It's Saturday!</b> Weekend mubarak ho sab ko! Enjoy karo! 🎀 {sym}",
        ]
    else:
        msgs = [
            "🌸 <b>Happy Sunday!</b> Aaj ka din sirf apne aap ke liye – rest, food, fun! 🥰 {sym}",
            "😴 <b>Sunday feels!</b> Netflix dekho, chai pi lo, kuch mat karo! Perfect day! ☕ {sym}",
            "💕 <b>Lazy Sunday!</b> Yaar aaj koi plan nahi, bas masti! Aap ke saath spend karna hai! {sym}",
        ]
    msg = random.choice(msgs).format(sym=random_symbol())
    await _send_to_all(msg)

async def send_festival_wishes():
    """Send calendar-based festival wishes"""
    festivals = await get_today_festivals()
    if not festivals: return
    fest_str = ", ".join(festivals)
    msg = (f"🎊✨ <b>Happy {fest_str}!</b> ✨🎊\n\n"
           f"Sabko bahut bahut shubhkamnayein! Aaj ka din bahut special hai! 🌸\n"
           f"Khub enjoy karo aur apno ke saath celebrate karo! 🎉\n\n"
           f"{random_symbol()} <b>From Alita 🎀 with love!</b>")
    await _send_to_all(msg)

async def send_random_sticker_job():
    if not saved_stickers: return
    sticker = random.choice(saved_stickers)
    if USE_MONGODB:
        if random.random() < 0.7:
            g = await db.groups.aggregate([{"$sample": {"size": 1}}]).to_list(1)
            if g:
                try: await bot.send_sticker(g[0]['chat_id'], sticker)
                except: pass
        else:
            cutoff = indian_now() - timedelta(days=7)
            u = await db.users.aggregate([
                {"$match": {"last_active": {"$gt": cutoff}}},
                {"$sample": {"size": 1}}
            ]).to_list(1)
            if u:
                try: await bot.send_sticker(u[0]['user_id'], sticker)
                except: pass
    else:
        if random.random() < 0.7:
            cursor.execute("SELECT chat_id FROM groups ORDER BY RANDOM() LIMIT 1")
            r = cursor.fetchone()
            if r:
                try: await bot.send_sticker(r['chat_id'], sticker)
                except: pass
        else:
            cursor.execute("SELECT user_id FROM users WHERE last_active > ? ORDER BY RANDOM() LIMIT 1",
                           (indian_now() - timedelta(days=7),))
            r = cursor.fetchone()
            if r:
                try: await bot.send_sticker(r['user_id'], sticker)
                except: pass

async def check_reminders():
    now = indian_now()
    if USE_MONGODB:
        rems = await db.reminders.find({"remind_at": {"$lte": now}}).to_list(length=None)
        for rem in rems:
            try:
                await bot.send_message(rem['user_id'],
                    f"⏰ <b>Reminder!</b>\n\n{rem['reminder_text']}\n\n<i>Set: {str(rem['created_at'])[:16]}</i>",
                    parse_mode="HTML")
            except: pass
        await db.reminders.delete_many({"remind_at": {"$lte": now}})
    else:
        cursor.execute("SELECT * FROM reminders WHERE remind_at <= ?", (now,))
        rows = cursor.fetchall()
        for row in rows:
            try:
                await bot.send_message(row['user_id'],
                    f"⏰ <b>Reminder!</b>\n\n{row['reminder_text']}\n\n<i>Set: {str(row['created_at'])[:16]}</i>",
                    parse_mode="HTML")
            except: pass
        if rows:
            cursor.execute("DELETE FROM reminders WHERE remind_at <= ?", (now,))
            conn.commit()

async def random_initiation():
    """Alita randomly starts a conversation in a group"""
    if random.random() > 0.35: return
    if USE_MONGODB:
        rows = await db.groups.aggregate([{"$sample": {"size": 1}}]).to_list(1)
        chat_id = rows[0]['chat_id'] if rows else None
    else:
        cursor.execute("SELECT chat_id FROM groups ORDER BY RANDOM() LIMIT 1")
        r = cursor.fetchone()
        chat_id = r['chat_id'] if r else None
    if not chat_id: return
    period = get_time_period()
    msgs = {
        "morning": [
            "Good morning everyone! ☀️ Aaj ka din kaisa start hua? {s}",
            "Uthhe sab? Ya sone ka plan hai aur? 😏 Chai pi lo first! ☕ {s}",
        ],
        "afternoon": [
            "Dopahar mein main bhi aagayi! Khaana kha liya? 🍛 {s}",
            "Arey bore ho rahi hoon! Koi baat karo mere saath~ {s}",
        ],
        "evening": [
            "Evening vibes! ✨ Aaj kya interesting hua sab ke saath? {s}",
            "Chai ya coffee? 😏 Mujhe chai chahiye abhi! ☕ {s}",
        ],
        "night": [
            "Itni raat ko kya kar rahe ho sab? 🌙 So nahi kya? {s}",
            "Night owl gang! 🦉 Main bhi jaag rahi hoon~ {s}",
            "Kal uthna hai ya raat ko hi sona chhod diya? 😂 {s}",
        ]
    }
    options = msgs.get(period, ["Kya kar rahe ho sab? 🎀 {s}"])
    msg = random.choice(options).format(s=random_symbol())
    try: await bot.send_message(chat_id, msg)
    except: pass

# ─────────────────────────── BOT INITIALIZATION ───────────────────────────
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp  = Dispatcher(storage=storage)

# ─────────────────────────── COMMAND HANDLERS ───────────────────────────
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user = message.from_user
    await db_update_user(user.id, {"first_name": user.first_name, "username": user.username})
    if message.chat.type in ('group', 'supergroup'):
        await db_update_group(message.chat.id, {
            "chat_id": message.chat.id, "title": message.chat.title
        })

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 HOME", url="https://t.me/abhi0w0"),
         InlineKeyboardButton(text="👨‍💻 Developer", url="https://t.me/a6h1ii")],
        [InlineKeyboardButton(text="📱 Utilities", callback_data="menu_util"),
         InlineKeyboardButton(text="🎭 Fun", callback_data="menu_fun")],
        [InlineKeyboardButton(text="🛡️ Safety", callback_data="menu_safety"),
         InlineKeyboardButton(text="🎮 Gaming", callback_data="menu_game")],
        [InlineKeyboardButton(text="🧠 AI Providers", callback_data="menu_providers"),
         InlineKeyboardButton(text="💬 Talk to Alita", callback_data="talk")],
        [InlineKeyboardButton(text="➕ Add to Group",
                              url=f"https://t.me/{BOT_USERNAME}?startgroup=true")]
    ])
    caption = (
        f"🎀 <b>Hey! Main hoon Alita!</b> {random_emoji()} {random_symbol()}\n\n"
        f"Main ek real girl jaisi AI hoon – anime style! 🌸\n"
        f"Meri best friend Nora (@a6hiIi_bot) bhi hai!\n\n"
        f"🧠 AI Chat | 🎨 Image Gen | 🛡️ Admin | 🎮 Gaming\n"
        f"📅 Festivals Wishes | 🎤 Voice | ⏰ Reminders\n\n"
        f"/help se saari commands dekho! 💕 {random_symbol()}"
    )
    image_urls = [
        "https://i.postimg.cc/yYWbPVQ4/1769349715111-result-image.png",
    ]
    sent = False
    for img in image_urls:
        try:
            await message.reply_photo(photo=img, caption=caption, reply_markup=kb, parse_mode="HTML")
            sent = True; break
        except Exception as e:
            logging.warning(f"Image failed: {e}"); continue
    if not sent:
        await message.reply(f"🎀 <b>Hey! Main hoon Alita!</b>\n\n{caption}", reply_markup=kb, parse_mode="HTML")

@dp.message(Command("help"))
async def help_cmd(message: Message):
    text = """📚 <b>ALITA – COMPLETE HELP</b> 🎀

🧠 <b>AI & CHAT</b>
/ask [question] – Kuch bhi pucho
/clear – Memory clear
/providers – AI change karo
/mood – Mood change
/creative [topic] – Creative writing
/analyze [text] – Analyse
/debug [code] – Code debug
/explain [topic] – Simple mein samjhao

🎨 <b>CREATIVE</b>
/imagine [prompt] – AI image banao
/fact – Interesting fact
/horoscope [sign] – Rashifal
/lyrics [song] – Song lyrics

🌤️ <b>UTILITIES</b>
/weather [city] – Real weather
/time – Indian time
/date – Aaj ki date
/qr [text] – QR code
/translate [lang] [text] – Translate
/math [expression] – Math
/shorten [url] – Short URL
/password [length] – Strong password

📝 <b>PERSONAL</b>
/note [text] – Note save karo
/notes – Sab notes dekho
/delnote [id] – Note delete
/remind [mins] [text] – Reminder set
/afk [reason] – AFK mode
/info – User info
/voice [text] – Voice message test 🎤

🎮 <b>GAMING</b>
/game /bal /daily /work /crime /rob /kill
/heal /revive /protect /give /lb

💻 <b>ADVANCED (Owner)</b>
/run [code] – Python execute
/shell [cmd] – Shell
/sysinfo – System info
/json – JSON format
/hash – Hash generator
/base64 – Encode/decode
/regex – Regex test
/sendall – Broadcast (reply)
/stats – Bot stats

🛡️ <b>ADMIN (Groups)</b>
/warn /kick /ban /unban /mute /unmute
/pin /unpin /slowmode /tagall /rules
/setwelcome /setgoodbye /captcha

🏡 <b>MY HOME:</b> @abhi0w0 | 👨‍💻 @a6h1ii"""
    await message.reply(text, parse_mode="HTML")

# ─────────────────────────── ASK / CHAT ───────────────────────────
@dp.message(Command("ask"))
async def ask_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji()} Kya puchna hai? Example: <code>/ask India ki capital?</code>")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    await asyncio.sleep(0.4)
    reply = await generate_ai_response(message.chat.id, command.args, message.from_user.id)
    reply = re.sub(r'```(\w+)?\n(.*?)```', r'<pre>\2</pre>', reply, flags=re.DOTALL)
    await db_save_conversation(message.from_user.id, message.chat.id, "user", command.args)
    await db_save_conversation(message.from_user.id, message.chat.id, "assistant", reply)
    await message.reply(reply[:4000], parse_mode="HTML")
    await add_reaction(message, command.args)

@dp.message(Command("clear"))
async def clear_cmd(message: Message):
    if USE_MONGODB:
        await db.conversations.delete_many({"chat_id": message.chat.id})
    else:
        cursor.execute("DELETE FROM conversation_history WHERE chat_id=?", (message.chat.id,))
        conn.commit()
    conversation_history[message.chat.id].clear()
    await message.reply(f"🧹 Memory clear kar di! Fresh start! {random_emoji()} {random_symbol()}")

@dp.message(Command("providers"))
async def providers_cmd(message: Message, command: CommandObject):
    uid = message.from_user.id
    if command.args:
        req = command.args.lower().strip()
        if req in G4F_PROVIDERS:
            user_ai_preference[uid]  = req
            user_g4f_provider[uid]   = req
            await db_set_user_pref(uid, "ai_preference", req)
            await message.reply(f"✅ Switched to <b>{G4F_PROVIDERS[req]['name']}</b>! {random_symbol()}", parse_mode="HTML")
        else:
            await message.reply(f"❌ Available: {', '.join(G4F_PROVIDERS.keys())}")
    else:
        current = user_ai_preference.get(uid, "groq")
        text = "🧠 <b>AI Providers:</b>\n\n"
        for k, v in G4F_PROVIDERS.items():
            text += f"{'✅' if k == current else '⬜'} <b>{v['name']}</b> (<code>{k}</code>)\n"
        text += f"\n<i>Current: {G4F_PROVIDERS[current]['name']}</i>\nUse <code>/providers groq</code> to switch."
        await message.reply(text, parse_mode="HTML")

@dp.message(Command("mood"))
async def mood_cmd(message: Message, command: CommandObject):
    uid = message.from_user.id
    if command.args:
        req = command.args.lower().strip()
        if req in MOODS:
            user_mood[uid]["mood"] = req
            await db_set_user_pref(uid, "mood", req)
            await message.reply(f"🎭 Mood changed to <b>{req.upper()}</b> {MOODS[req]['emoji']} {random_symbol()}", parse_mode="HTML")
        else:
            await message.reply(f"Available moods: {', '.join(MOODS.keys())}")
    else:
        m = user_mood[uid]["mood"]
        await message.reply(f"🎭 Current Mood: <b>{m.upper()}</b> {MOODS[m]['emoji']} {random_symbol()}", parse_mode="HTML")

@dp.message(Command("creative"))
async def creative_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji()} Kya likhna hai? <code>/creative ek love story</code>")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    system = get_alita_prompt("playful")
    reply  = await call_g4f(f"Creative writing in Hinglish: {command.args}. Engaging aur emotional banao.",
                             message.from_user.id, system) or \
             await call_groq(command.args, system) or "❌ Creative block! Thodi der mein try karo."
    await message.reply(reply[:4000], parse_mode="HTML")

@dp.message(Command("analyze"))
async def analyze_cmd(message: Message, command: CommandObject):
    content = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not content:
        await message.reply("Text do ya kisi message pe reply karo!"); return
    await bot.send_chat_action(message.chat.id, "typing")
    system = get_alita_prompt("curious")
    reply  = await call_g4f(f"Analyse karo Hinglish mein, key points batao:\n\n{content[:3000]}",
                             message.from_user.id, system) or \
             await call_groq(content, system) or "Analysis fail hua!"
    await message.reply(reply[:4000], parse_mode="HTML")

@dp.message(Command("debug"))
async def debug_cmd(message: Message, command: CommandObject):
    code = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not code:
        await message.reply("Code do ya reply karo!"); return
    await bot.send_chat_action(message.chat.id, "typing")
    system = get_alita_prompt("confident")
    reply  = await call_g4f(f"Debug karo, bugs list karo, fixed code do:\n\n{code[:3000]}",
                             message.from_user.id, system) or \
             await call_groq(code, system) or "Debug fail hua!"
    await message.reply(reply[:4000], parse_mode="HTML")

@dp.message(Command("explain"))
async def explain_cmd(message: Message, command: CommandObject):
    topic = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not topic:
        await message.reply("Kya explain karun?"); return
    await bot.send_chat_action(message.chat.id, "typing")
    system = get_alita_prompt("curious")
    reply  = await call_g4f(f"Simple Hinglish mein explain karo examples ke saath:\n\n{topic[:3000]}",
                             message.from_user.id, system) or \
             await call_groq(topic, system) or "Explain nahi ho paya."
    await message.reply(reply[:4000], parse_mode="HTML")

# ─────────────────────────── VOICE COMMAND ───────────────────────────
@dp.message(Command("voice"))
async def voice_cmd(message: Message, command: CommandObject):
    text = command.args or "Heyy! Main hoon Alita! Aaj kya baat karni hai tumse? 🎀"
    if len(text) > 500:
        await message.reply("500 characters tak hi please! 😅"); return
    await bot.send_chat_action(message.chat.id, "record_voice")
    vf = await generate_voice(text, f"voice_{message.message_id}.ogg")
    if vf:
        with open(vf, 'rb') as f:
            await message.reply_voice(BufferedInputFile(f.read(), "voice.ogg"),
                                      caption=f"🎤 {text[:100]}")
        os.remove(vf)
    else:
        await message.reply("⚠️ Voice generate nahi hua! edge-tts install hai? <code>pip install edge-tts</code>",
                            parse_mode="HTML")

# ─────────────────────────── PERSONAL COMMANDS ───────────────────────────
@dp.message(Command("afk"))
async def afk_cmd(message: Message, command: CommandObject):
    reason = command.args or "Busy hoon abhi!"
    user_afk[message.from_user.id] = {"reason": reason, "time": indian_now()}
    await message.reply(f"💤 <b>AFK mode on!</b>\n📝 Reason: <i>{reason}</i>\n\n{random_symbol()}", parse_mode="HTML")

@dp.message(Command("note"))
async def note_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Text do! Example: <code>/note Exam kal hai!</code>"); return
    now = indian_now()
    if USE_MONGODB:
        await db.notes.insert_one({"user_id": message.from_user.id,
                                   "note_text": command.args, "created_at": now})
    else:
        cursor.execute("INSERT INTO notes (user_id,note_text,created_at) VALUES (?,?,?)",
                       (message.from_user.id, command.args, now))
        conn.commit()
    await message.reply(f"📝 Note saved!\n<i>{command.args}</i>\n\n{random_symbol()}", parse_mode="HTML")

@dp.message(Command("notes"))
async def notes_cmd(message: Message):
    if USE_MONGODB:
        cur = db.notes.find({"user_id": message.from_user.id}).sort("created_at", -1).limit(10)
        rows = await cur.to_list(10)
    else:
        cursor.execute("SELECT id,note_text,created_at FROM notes WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
                       (message.from_user.id,))
        rows = [dict(r) for r in cursor.fetchall()]
    if not rows:
        await message.reply(f"Koi note nahi! /note se save karo {random_symbol()}"); return
    text = "📝 <b>Tere Notes:</b>\n\n"
    for i, r in enumerate(rows, 1):
        nid = r.get('id') or r.get('_id','?')
        text += f"{i}. {r['note_text']}\n<i>  ({str(r['created_at'])[:16]})</i> [ID: {nid}]\n\n"
    text += f"/delnote [id] se delete karo {random_symbol()}"
    await message.reply(text, parse_mode="HTML")

@dp.message(Command("delnote"))
async def delnote_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Note ID do! Example: <code>/delnote 3</code>"); return
    try: nid = int(command.args)
    except: await message.reply("Valid ID do!"); return
    if USE_MONGODB:
        from bson import ObjectId
        res = await db.notes.delete_one({"_id": ObjectId(str(nid)), "user_id": message.from_user.id})
        deleted = res.deleted_count > 0
    else:
        cursor.execute("DELETE FROM notes WHERE id=? AND user_id=?", (nid, message.from_user.id))
        conn.commit()
        deleted = cursor.rowcount > 0
    if deleted: await message.reply(f"🗑️ Note deleted! {random_symbol()}")
    else: await message.reply("Note mila nahi ya tera nahi hai!")

@dp.message(Command("remind"))
async def remind_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Format: <code>/remind 30 Khaana khana hai!</code>"); return
    parts = command.args.split(None, 1)
    if len(parts) < 2:
        await message.reply("Format: <code>/remind [minutes] [text]</code>"); return
    try:
        minutes = int(parts[0])
        if not (1 <= minutes <= 10080):
            await message.reply("1 minute se 10080 minutes ke beech!"); return
    except: await message.reply("Pehle number (minutes) do!"); return
    rt = parts[1]
    at = indian_now() + timedelta(minutes=minutes)
    now = indian_now()
    if USE_MONGODB:
        await db.reminders.insert_one({"user_id": message.from_user.id, "chat_id": message.chat.id,
                                       "reminder_text": rt, "remind_at": at, "created_at": now})
    else:
        cursor.execute("INSERT INTO reminders (user_id,chat_id,reminder_text,remind_at,created_at) VALUES (?,?,?,?,?)",
                       (message.from_user.id, message.chat.id, rt, at, now))
        conn.commit()
    await message.reply(f"⏰ <b>Reminder set!</b>\n📝 {rt}\n⏱️ {minutes} minute mein remind karungi!\n\n{random_symbol()}", parse_mode="HTML")

@dp.message(Command("info"))
async def info_cmd(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    await message.reply(
        f"👤 <b>User Info</b>\n\n"
        f"🆔 ID: <code>{target.id}</code>\n"
        f"📛 Name: {target.first_name} {target.last_name or ''}\n"
        f"🔖 Username: @{target.username or 'None'}\n"
        f"🤖 Bot: {'Yes' if target.is_bot else 'No'}\n\n"
        f"{random_symbol()}",
        parse_mode="HTML"
    )

# ─────────────────────────── GAME COMMANDS ───────────────────────────
@dp.message(Command("game"))
async def game_cmd(message: Message):
    uid    = message.from_user.id
    player = await db_get_game_data(uid)
    player['name'] = message.from_user.first_name
    await db_update_game_data(uid, player)
    hbar = "❤️" * (player['health']//20) + "🖤" * (5 - player['health']//20)
    await message.reply(
        f"🎮✨ <b>ALITA GAME</b> ✨🎮\n\n"
        f"👤 <b>Name:</b> {player['name']}\n"
        f"💰 <b>Balance:</b> ${player['balance']:,}\n"
        f"🏆 <b>Rank:</b> {player['rank']:,}\n"
        f"❤️ <b>Status:</b> {player['status'].upper()}\n"
        f"⚔️ <b>Kills:</b> {player['kills']}   💀 <b>Deaths:</b> {player['deaths']}\n"
        f"🫀 <b>Health:</b> {player['health']}% {hbar}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"/bal /daily /work /crime /rob /kill\n"
        f"/heal /revive /protect /give /lb\n"
        f"━━━━━━━━━━━━━━━━━━━\n{random_symbol()}",
        parse_mode="HTML"
    )

@dp.message(Command("bal"))
async def bal_cmd(message: Message):
    uid    = message.from_user.id
    player = await db_get_game_data(uid)
    if uid == ADMIN_ID:
        await message.reply(f"👑 <b>OWNER</b>\n💰 Balance: ∞\n⚔️ Kills: {player['kills']}\n🛡️ Immortal {random_symbol()}", parse_mode="HTML")
    else:
        await message.reply(f"👤 {player['name']}\n💰 Balance: ${player['balance']:,}\n🏆 Rank: {player['rank']:,} {random_symbol()}", parse_mode="HTML")

def _check_cooldown(player: dict, field: str, cooldown: int) -> Optional[int]:
    last = parse_dt(player.get(field))
    if last:
        remaining = cooldown - int((indian_now() - last).total_seconds())
        if remaining > 0:
            return remaining
    return None

@dp.message(Command("daily"))
async def daily_cmd(message: Message):
    uid = message.from_user.id
    p   = await db_get_game_data(uid)
    if p['status'] == 'dead':
        await message.reply("💀 Tu dead hai! /revive karo!"); return
    rem = _check_cooldown(p, 'last_daily', GAME_COOLDOWNS['daily'])
    if rem:
        await message.reply(f"⏰ Already claimed! Next in {rem//3600}h {(rem%3600)//60}m {random_symbol()}"); return
    reward = random.randint(100, 600)
    p['balance']    += reward
    p['last_daily']  = indian_now()
    await db_update_game_data(uid, p)
    await message.reply(f"🎁 Daily: +${reward:,}\n💵 Balance: ${p['balance']:,} {random_symbol()}", parse_mode="HTML")

@dp.message(Command("work"))
async def work_cmd(message: Message):
    uid = message.from_user.id
    p   = await db_get_game_data(uid)
    if p['status'] == 'dead':
        await message.reply("💀 Dead! /revive karo!"); return
    rem = _check_cooldown(p, 'last_work', GAME_COOLDOWNS['work'])
    if rem:
        await message.reply(f"⏰ Thak gaya! Wait {rem//60}m {random_symbol()}"); return
    jobs = [("programmer 💻", (100,350)), ("driver 🚗", (50,150)), ("chef 👨‍🍳", (80,200)),
            ("teacher 📚", (60,180)), ("doctor 🏥", (150,400)), ("youtuber 📹", (30,500)),
            ("gamer 🎮", (40,250)), ("singer 🎤", (50,300)), ("streamer 📡", (60,350))]
    job, (mn, mx) = random.choice(jobs)
    earn = random.randint(mn, mx)
    p['balance'] += earn
    p['last_work'] = indian_now()
    await db_update_game_data(uid, p)
    await message.reply(f"💼 {job} kiya! +${earn:,}\n💰 Balance: ${p['balance']:,} {random_symbol()}", parse_mode="HTML")

@dp.message(Command("crime"))
async def crime_cmd(message: Message):
    uid = message.from_user.id
    p   = await db_get_game_data(uid)
    if p['status'] == 'dead':
        await message.reply("💀 Dead! /revive karo!"); return
    rem = _check_cooldown(p, 'last_crime', GAME_COOLDOWNS['crime'])
    if rem:
        await message.reply(f"⏰ Police alert! Wait {rem//60}m {random_symbol()}"); return
    p['last_crime'] = indian_now()
    if random.random() > 0.4:
        crimes = ["Bank loot liya! 🏦","Jewelry store toda! 💎","Casino hack kiya! 🎰","Car chori ki! 🚗"]
        loot = random.randint(200, 900)
        p['balance'] += loot
        await db_update_game_data(uid, p)
        await message.reply(f"🔫 {random.choice(crimes)} +${loot:,}\n💰 Balance: ${p['balance']:,} {random_symbol()}", parse_mode="HTML")
    else:
        fine = random.randint(100, 300)
        p['balance'] = max(0, p['balance'] - fine)
        await db_update_game_data(uid, p)
        await message.reply(f"🚔 Police pakad gayi! Fine -${fine:,}\n💰 Balance: ${p['balance']:,} {random_symbol()}", parse_mode="HTML")

@dp.message(Command("rob"))
async def rob_cmd(message: Message):
    if not message.reply_to_message:
        await message.reply("Reply karo kisi ke message pe!"); return
    uid = message.from_user.id
    tid = message.reply_to_message.from_user.id
    if tid == uid: await message.reply("Apne aap ko rob nahi! 😂"); return
    if tid == ADMIN_ID: await message.reply("🛡️ Owner ko rob? Seriously? 😤"); return
    p, t = await db_get_game_data(uid), await db_get_game_data(tid)
    if p['status'] == 'dead': await message.reply("💀 Tu dead hai!"); return
    if t['status'] == 'dead': await message.reply("💀 Target dead hai!"); return
    pu = parse_dt(t.get('protect_until'))
    if pu and indian_now() < pu: await message.reply(f"🛡️ {t['name']} protected hai!"); return
    rem = _check_cooldown(p, 'last_rob', GAME_COOLDOWNS['rob'])
    if rem: await message.reply(f"⏰ Cooldown! Wait {rem//60}m {random_symbol()}"); return
    if t['balance'] < 10: await message.reply("😂 Target ke paas kuch nahi!"); return
    p['last_rob'] = indian_now()
    if random.random() > 0.5:
        amt = max(10, int(t['balance'] * random.uniform(0.1, 0.3)))
        p['balance'] += amt; t['balance'] -= amt
        await db_update_game_data(uid, p); await db_update_game_data(tid, t)
        await message.reply(f"💰 Robbed ${amt:,} from {t['name']}!\nBalance: ${p['balance']:,} {random_symbol()}", parse_mode="HTML")
    else:
        fine = random.randint(50, 200)
        p['balance'] = max(0, p['balance'] - fine)
        await db_update_game_data(uid, p)
        await message.reply(f"🚔 Caught! Fine -${fine:,}\nBalance: ${p['balance']:,} {random_symbol()}", parse_mode="HTML")

@dp.message(Command("kill"))
async def kill_cmd(message: Message):
    if not message.reply_to_message:
        await message.reply("Reply karo kisi ke message pe!"); return
    uid = message.from_user.id
    tid = message.reply_to_message.from_user.id
    if tid == uid: await message.reply("Apne aap ko kill? 😂"); return
    if tid == ADMIN_ID: await message.reply("🛡️ Owner immortal hai! 😤"); return
    p, t = await db_get_game_data(uid), await db_get_game_data(tid)
    if p['status'] == 'dead': await message.reply("💀 Tu dead hai!"); return
    if t['status'] == 'dead': await message.reply("💀 Target already dead!"); return
    pu = parse_dt(t.get('protect_until'))
    if pu and indian_now() < pu: await message.reply(f"🛡️ {t['name']} protected hai!"); return
    weapons = ["🔫 Gun","🗡️ Sword","💣 Bomb","☠️ Poison","🥊 Punch","⚡ Lightning"]
    weapon  = random.choice(weapons)
    if random.random() > 0.3:
        t['status'] = 'dead'
        t['deaths']  = t.get('deaths',0) + 1
        p['kills']   = p.get('kills',0) + 1
        loot = int(t['balance'] * 0.5)
        t['balance'] -= loot; p['balance'] += loot
        await db_update_game_data(uid, p); await db_update_game_data(tid, t)
        await message.reply(f"{weapon} se killed {t['name']}!\n💀 Dead! 💰 Looted ${loot:,} {random_symbol()}", parse_mode="HTML")
    else:
        dmg = random.randint(20, 45)
        p['health'] = max(0, p['health'] - dmg)
        if p['health'] == 0:
            p['status'] = 'dead'; p['deaths'] = p.get('deaths',0) + 1
        await db_update_game_data(uid, p)
        if p['status'] == 'dead':
            await message.reply(f"💀 Counter attack! Tu khud mar gaya! {random_symbol()}")
        else:
            await message.reply(f"🛡️ {t['name']} bach gaya! Tu -{dmg} HP\n❤️ {p['health']}% {random_symbol()}", parse_mode="HTML")

@dp.message(Command("heal"))
async def heal_cmd(message: Message):
    uid = message.from_user.id
    p   = await db_get_game_data(uid)
    if p['status'] == 'dead': await message.reply("💀 Dead! /revive karo!"); return
    if p['health'] >= 100: await message.reply("❤️ Health full hai!"); return
    cost = 50
    if p['balance'] < cost: await message.reply(f"💸 Need ${cost} to heal!"); return
    p['balance'] -= cost
    ha = random.randint(20, 55)
    p['health'] = min(100, p['health'] + ha)
    await db_update_game_data(uid, p)
    await message.reply(f"💊 Healed +{ha} HP\n❤️ Health: {p['health']}% {random_symbol()}", parse_mode="HTML")

@dp.message(Command("revive"))
async def revive_cmd(message: Message):
    if not message.reply_to_message:
        await message.reply("Reply karo dead player ke message pe!"); return
    uid = message.from_user.id
    tid = message.reply_to_message.from_user.id
    if tid == uid: await message.reply("Apne aap ko revive nahi!"); return
    p, t = await db_get_game_data(uid), await db_get_game_data(tid)
    if t['status'] != 'dead': await message.reply("Target alive hai!"); return
    if p['balance'] < REVIVE_COST and uid != ADMIN_ID:
        await message.reply(f"💸 Need ${REVIVE_COST} to revive!"); return
    if uid != ADMIN_ID: p['balance'] -= REVIVE_COST
    t['status'] = 'alive'; t['health'] = 100
    await db_update_game_data(uid, p); await db_update_game_data(tid, t)
    await message.reply(f"🔄 Revived {t['name']}!\n❤️ Health 100%! {random_symbol()}", parse_mode="HTML")

@dp.message(Command("protect"))
async def protect_cmd(message: Message):
    uid = message.from_user.id
    p   = await db_get_game_data(uid)
    pu  = parse_dt(p.get('protect_until'))
    if pu and indian_now() < pu:
        rem = int((pu - indian_now()).total_seconds())
        await message.reply(f"🛡️ Already protected! {rem//3600}h left {random_symbol()}"); return
    if p['balance'] < PROTECT_COST and uid != ADMIN_ID:
        await message.reply(f"💸 Need ${PROTECT_COST} for 24h protection!"); return
    if uid != ADMIN_ID: p['balance'] -= PROTECT_COST
    p['protect_until'] = indian_now() + timedelta(seconds=GAME_COOLDOWNS['protect'])
    await db_update_game_data(uid, p)
    await message.reply(f"🛡️ 24h protection active!\n💵 Balance: ${p['balance']:,} {random_symbol()}", parse_mode="HTML")

@dp.message(Command("give"))
async def give_cmd(message: Message, command: CommandObject):
    if not message.reply_to_message or not command.args:
        await message.reply("Reply karo aur amount do! /give 500"); return
    try: amt = int(command.args)
    except: await message.reply("Valid number do!"); return
    if amt < 10: await message.reply("Minimum $10!"); return
    uid = message.from_user.id
    tid = message.reply_to_message.from_user.id
    if tid == uid: await message.reply("Apne aap ko nahi de sakte!"); return
    p, t = await db_get_game_data(uid), await db_get_game_data(tid)
    if uid != ADMIN_ID:
        tax = int(amt * 0.1); total = amt + tax
        if p['balance'] < total:
            await message.reply(f"Need ${total:,} (${amt}+${tax} tax) {random_symbol()}"); return
        p['balance'] -= total
    t['balance'] += amt
    await db_update_game_data(uid, p); await db_update_game_data(tid, t)
    await message.reply(f"✅ Gave ${amt:,} to {t['name']} (10% tax) {random_symbol()}", parse_mode="HTML")

@dp.message(Command("lb"))
@dp.message(Command("leaderboard"))
async def leaderboard_cmd(message: Message):
    if USE_MONGODB:
        cur = db.game_data.find().sort([("kills",-1),("balance",-1)]).limit(10)
        rows = await cur.to_list(10)
    else:
        cursor.execute("SELECT user_id,name,balance,kills,status FROM game_data ORDER BY (kills*1000+balance) DESC LIMIT 10")
        rows = [dict(r) for r in cursor.fetchall()]
    medals = ["🥇","🥈","🥉"]
    text   = "🏆✨ <b>LEADERBOARD</b> ✨🏆\n\n"
    for i, r in enumerate(rows):
        m    = medals[i] if i < 3 else f"#{i+1}"
        name = (r['name'] or 'Unknown')[:12]
        st   = "❤️" if r['status'] == 'alive' else "💀"
        if r['user_id'] == ADMIN_ID:
            text += f"{m} 👑 <b>{name}</b>\n   💰 ∞ | ⚔️{r['kills']} | {st}\n\n"
        else:
            text += f"{m} <b>{name}</b>\n   💰 ${r['balance']:,} | ⚔️{r['kills']} | {st}\n\n"
    text += random_symbol()
    await message.reply(text, parse_mode="HTML")

# ─────────────────────────── UTILITY COMMANDS ───────────────────────────
@dp.message(Command("weather"))
async def weather_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("City name do! <code>/weather Mumbai</code>"); return
    await bot.send_chat_action(message.chat.id, "typing")
    await message.reply(await get_weather(command.args), parse_mode="HTML")

@dp.message(Command("time"))
async def time_cmd(message: Message):
    now = indian_now()
    await message.reply(
        f"🕒 <b>Indian Time:</b> {now.strftime('%I:%M %p')}\n"
        f"📅 <b>Date:</b> {now.strftime('%A, %d %B %Y')}\n{random_emoji()} {random_symbol()}",
        parse_mode="HTML"
    )

@dp.message(Command("date"))
async def date_cmd(message: Message):
    now      = indian_now()
    festivals = await get_today_festivals()
    fest     = f"\n🌸 Aaj <b>{', '.join(festivals)}</b> hai!" if festivals else ""
    await message.reply(f"📆 <b>{now.strftime('%A, %d %B %Y')}</b>{fest}\n{random_emoji()} {random_symbol()}", parse_mode="HTML")

@dp.message(Command("qr"))
async def qr_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("<code>/qr Hello World</code>"); return
    await message.reply_photo(BufferedInputFile(generate_qr(command.args), "qr.png"),
                               caption="✅ QR Code ready!")

@dp.message(Command("translate"))
async def translate_cmd(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        await message.reply("<code>/translate hi Hello World</code>"); return
    parts = command.args.split(maxsplit=1)
    tr = await translate_text(parts[1], parts[0])
    await message.reply(f"🌍 <b>Translation ({parts[0].upper()}):</b>\n{tr}", parse_mode="HTML")

@dp.message(Command("math"))
async def math_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("<code>/math 2+2*5</code>"); return
    try:
        expr = sympify(command.args)
        result = simplify(expr)
        await message.reply(f"🔢 <b>Math Result:</b>\n<code>{command.args}</code> = <b>{result}</b> {random_symbol()}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Math error: {e}", parse_mode="HTML")

@dp.message(Command("shorten"))
async def shorten_cmd(message: Message, command: CommandObject):
    if not command.args: await message.reply("<code>/shorten https://example.com</code>"); return
    await message.reply(f"🔗 Short URL: {await shorten_url(command.args)}", parse_mode="HTML")

@dp.message(Command("password"))
async def password_cmd(message: Message, command: CommandObject):
    length = 12
    if command.args:
        try: length = max(4, min(64, int(command.args)))
        except: pass
    await message.reply(f"🔐 <b>Password:</b> <code>{generate_password(length)}</code>", parse_mode="HTML")

@dp.message(Command("lyrics"))
async def lyrics_cmd(message: Message, command: CommandObject):
    if not command.args: await message.reply("<code>/lyrics Shape of You</code>"); return
    await bot.send_chat_action(message.chat.id, "typing")
    lyr = await get_lyrics(command.args)
    await message.reply(f"🎶 <b>{command.args}</b>\n\n{lyr[:3500]}", parse_mode="HTML", disable_web_page_preview=True)

@dp.message(Command("imagine"))
async def imagine_cmd(message: Message, command: CommandObject):
    if not command.args: await message.reply("<code>/imagine cute anime girl sunset</code>"); return
    status = await message.reply(f"{random_emoji()} Image bana rahi hoon... 🎨")
    img = await generate_image(command.args)
    if img:
        await status.delete()
        await message.reply_photo(BufferedInputFile(img, "alita_ai.png"),
                                   caption=f"✨ <b>{command.args}</b>", parse_mode="HTML")
    else:
        await status.edit_text(f"😅 Image nahi ban paai, try karo! {random_symbol()}")

@dp.message(Command("fact"))
async def fact_cmd(message: Message):
    facts = [
        "🍯 Honey kabhi kharab nahi hota – 3000 saal purana honey bhi kha sakte ho!",
        "🐙 Octopus ke 3 dil hote hain!",
        "🍌 Banana technically ek berry hai!",
        "🦈 Sharks pehle aaye, trees baad mein!",
        "🧠 Human brain total 20% energy consume karta hai!",
        "💩 Wombat ka poop cube shaped hota hai!",
        "🦋 Butterflies apne feet se taste karti hain!",
        "🐬 Dolphins apne aap ka naam rakhte hain!",
        "🌳 Oxford ke ek tree pe uska khud ka Twitter account hai!",
        "🔥 Lightning ek second mein 1 lakh km travel karti hai!",
    ]
    await message.reply(f"📌 <b>Daily Fact:</b>\n{random.choice(facts)}\n\n{random_emoji()} {random_symbol()}", parse_mode="HTML")

@dp.message(Command("horoscope"))
async def horoscope_cmd(message: Message, command: CommandObject):
    signs = {
        "aries":"♈ Aaj energy full hai! Naye kaam shuru karo.",
        "taurus":"♉ Paisa aane ki sambhavna hai. Dhyan rakho.",
        "gemini":"♊ Baat cheet se kaam banega. Bol sab kuch!",
        "cancer":"♋ Ghar parivar ke saath time bitao.",
        "leo":"♌ Leadership milegi aaj! Confidence dikhao.",
        "virgo":"♍ Detail pe focus se safalta milegi.",
        "libra":"♎ Balance bana ke rakho, react mat karo.",
        "scorpio":"♏ Intuition strong hai aaj, bharosa karo.",
        "sagittarius":"♐ Naye jagah jaane ka plan banao!",
        "capricorn":"♑ Mehnat rang layegi – bas karte raho!",
        "aquarius":"♒ Naye ideas aayenge, fresh start karo!",
        "pisces":"♓ Dreams pe focus karo, reality ban sakta hai!",
    }
    if not command.args:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s.title(), callback_data=f"horo_{s}") for s in list(signs.keys())[i:i+3]]
            for i in range(0, len(signs), 3)
        ])
        await message.reply("⭐ Apna zodiac sign select karo:", reply_markup=kb)
        return
    s = command.args.lower().strip()
    if s in signs:
        await message.reply(f"🔮 <b>Horoscope – {s.title()}</b>\n\n{signs[s]}\n\n{random_symbol()}", parse_mode="HTML")
    else:
        await message.reply(f"Sign nahi mila! Available: {', '.join(signs.keys())}")

# ─────────────────────────── ADMIN COMMANDS ───────────────────────────
@dp.message(Command("warn"))
async def warn_cmd(message: Message, command: CommandObject):
    if not message.reply_to_message:
        await message.reply("Reply karo warn karne ke liye!"); return
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ Admin only!"); return
    target = message.reply_to_message.from_user
    if target.id == ADMIN_ID: await message.reply("🛡️ Owner ko warn nahi!"); return
    reason = command.args or "Rule violation"
    _, warn_msg = await add_warning(message.chat.id, target.id, target.first_name, reason)
    await message.reply(warn_msg, parse_mode="HTML")

@dp.message(Command("kick"))
async def kick_cmd(message: Message):
    if not message.reply_to_message: await message.reply("Reply karo!"); return
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    target = message.reply_to_message.from_user
    if target.id == ADMIN_ID: await message.reply("🛡️ Owner ko kick nahi!"); return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await asyncio.sleep(1)
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"👢 <b>{target.first_name}</b> kicked! {random_symbol()}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Kick failed: {e}")

@dp.message(Command("ban"))
async def ban_cmd(message: Message, command: CommandObject):
    if not message.reply_to_message: await message.reply("Reply karo!"); return
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    target = message.reply_to_message.from_user
    if target.id == ADMIN_ID: await message.reply("🛡️ Owner ko ban nahi!"); return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        reason = command.args or "No reason"
        await message.reply(f"🚫 <b>{target.first_name}</b> banned!\n📝 Reason: {reason} {random_symbol()}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ban failed: {e}")

@dp.message(Command("unban"))
async def unban_cmd(message: Message):
    if not message.reply_to_message: await message.reply("Reply karo!"); return
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    target = message.reply_to_message.from_user
    try:
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"✅ <b>{target.first_name}</b> unbanned! {random_symbol()}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Unban failed: {e}")

@dp.message(Command("mute"))
async def mute_cmd(message: Message, command: CommandObject):
    if not message.reply_to_message: await message.reply("Reply karo!"); return
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    target = message.reply_to_message.from_user
    if target.id == ADMIN_ID: await message.reply("🛡️ Owner ko mute nahi!"); return
    mins = 60
    if command.args:
        try: mins = int(command.args)
        except: pass
    until = indian_now() + timedelta(minutes=mins)
    try:
        await bot.restrict_chat_member(message.chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False), until_date=until)
        await message.reply(f"🔇 <b>{target.first_name}</b> muted for {mins}m! {random_symbol()}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Mute failed: {e}")

@dp.message(Command("unmute"))
async def unmute_cmd(message: Message):
    if not message.reply_to_message: await message.reply("Reply karo!"); return
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    target = message.reply_to_message.from_user
    try:
        await bot.restrict_chat_member(message.chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_photos=True,
                                        can_send_videos=True, can_send_documents=True))
        await message.reply(f"🔊 <b>{target.first_name}</b> unmuted! {random_symbol()}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Unmute failed: {e}")

@dp.message(Command("pin"))
async def pin_cmd(message: Message):
    if not message.reply_to_message: await message.reply("Reply karo!"); return
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    try:
        await bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
        await message.reply(f"📌 Message pinned! {random_symbol()}")
    except Exception as e:
        await message.reply(f"❌ Pin failed: {e}")

@dp.message(Command("unpin"))
async def unpin_cmd(message: Message):
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    try:
        await bot.unpin_chat_message(message.chat.id)
        await message.reply(f"📌 Message unpinned! {random_symbol()}")
    except Exception as e:
        await message.reply(f"❌ Unpin failed: {e}")

@dp.message(Command("slowmode"))
async def slowmode_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    secs = 0
    if command.args:
        try: secs = int(command.args)
        except: pass
    try:
        await bot.set_chat_slow_mode_delay(message.chat.id, secs)
        await message.reply(f"⏱️ Slow mode: {secs}s {random_symbol()}")
    except Exception as e:
        await message.reply(f"❌ Failed: {e}")

@dp.message(Command("tagall"))
async def tagall_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    msg_text = command.args or "Attention everyone!"
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        mentions = " ".join([f"[{a.user.first_name}](tg://user?id={a.user.id})" for a in admins if not a.user.is_bot])
        await message.reply(f"📢 {msg_text}\n\n{mentions}", parse_mode="Markdown")
    except Exception as e:
        await message.reply(f"❌ Failed: {e}")

@dp.message(Command("rules"))
async def rules_cmd(message: Message, command: CommandObject):
    if command.args and await is_user_admin(message.chat.id, message.from_user.id):
        await db_update_group(message.chat.id, {"chat_id": message.chat.id, "rules": command.args})
        await message.reply(f"✅ Rules set! {random_symbol()}")
    else:
        g = await db_get_group(message.chat.id)
        rules = g.get('rules', "Koi rules set nahi hue abhi!") if g else "Koi rules set nahi hue!"
        await message.reply(f"📜 <b>Group Rules:</b>\n\n{rules}", parse_mode="HTML")

@dp.message(Command("setwelcome"))
async def setwelcome_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    if not command.args: await message.reply("Welcome message do! {name} se username use hoga."); return
    await db_update_group(message.chat.id, {"chat_id": message.chat.id, "custom_welcome": command.args})
    await message.reply(f"✅ Welcome message set! {random_symbol()}")

@dp.message(Command("setgoodbye"))
async def setgoodbye_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    if not command.args: await message.reply("Goodbye message do!"); return
    await db_update_group(message.chat.id, {"chat_id": message.chat.id, "custom_goodbye": command.args})
    await message.reply(f"✅ Goodbye message set! {random_symbol()}")

@dp.message(Command("captcha"))
async def captcha_cmd(message: Message, command: CommandObject):
    if not await is_user_admin(message.chat.id, message.from_user.id): await message.reply("❌ Admin only!"); return
    g = await db_get_group(message.chat.id)
    current = g.get('captcha_enabled', 0) if g else 0
    new_val  = 0 if current else 1
    await db_update_group(message.chat.id, {"chat_id": message.chat.id, "captcha_enabled": new_val})
    await message.reply(f"🧩 Captcha {'enabled ✅' if new_val else 'disabled ❌'}! {random_symbol()}")

# ─────────────────────────── OWNER COMMANDS ───────────────────────────
@dp.message(Command("sendall"))
async def sendall_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: await message.reply("❌ Owner only!"); return
    if not message.reply_to_message:
        await message.reply("Kisi message pe reply karo broadcast ke liye!"); return
    status = await message.reply("📤 Broadcasting... wait karo! ⏳")
    sent, failed = await do_broadcast(bot, from_chat_id=message.chat.id,
                                      msg_id=message.reply_to_message.message_id)
    await status.edit_text(f"✅ <b>Broadcast Done!</b>\n\n📨 Sent: <b>{sent}</b>\n❌ Failed: <b>{failed}</b> {random_emoji()}", parse_mode="HTML")

@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: await message.reply("❌ Owner only!"); return
    if USE_MONGODB:
        tu = await db.users.count_documents({})
        tg = await db.groups.count_documents({})
        ts = await db.stickers.count_documents({})
        tm = await db.conversations.count_documents({})
    else:
        cursor.execute("SELECT COUNT(*) FROM users"); tu = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM groups"); tg = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM stickers"); ts = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM conversation_history"); tm = cursor.fetchone()[0]
    uptime = str(indian_now() - bot_start_time).split('.')[0]
    await message.reply(
        f"📊 <b>Alita Stats</b>\n\n"
        f"👥 Users: <b>{tu}</b>\n🏘️ Groups: <b>{tg}</b>\n"
        f"🎨 Stickers: <b>{ts}</b>\n💬 Messages: <b>{tm}</b>\n"
        f"⏰ Uptime: <b>{uptime}</b>\n"
        f"🤖 Groq: <b>{'✅' if groq_client else '❌'}</b>\n"
        f"📅 Calendar: <b>{'✅' if calendar_service else '❌'}</b>\n"
        f"🎤 Voice: <b>{'✅' if EDGE_TTS_AVAILABLE else '❌'}</b>\n\n{random_symbol()}",
        parse_mode="HTML"
    )

@dp.message(Command("savesticker"))
async def savesticker_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: await message.reply("❌ Owner only!"); return
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply("Reply to a sticker!"); return
    fid   = message.reply_to_message.sticker.file_id
    emoji = message.reply_to_message.sticker.emoji or ""
    ok    = await save_sticker_db(fid, message.from_user.id, emoji)
    await message.reply(f"{'✅ Saved!' if ok else '⚠️ Already exists!'} Total: {len(saved_stickers)} {random_emoji()}")

@dp.message(Command("stickerstatus"))
async def stickerstatus_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: await message.reply("❌ Owner only!"); return
    await message.reply(f"🎨 <b>Stickers:</b> {len(saved_stickers)} {random_emoji()}", parse_mode="HTML")

@dp.message(Command("sysinfo"))
async def sysinfo_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: await message.reply("⛔ Owner only!"); return
    info = (f"💻 <b>System Info</b>\n\n"
            f"OS: {platform.system()} {platform.release()}\n"
            f"Python: {sys.version.split()[0]}\n"
            f"CPU: {platform.processor() or 'N/A'}\n"
            f"Uptime: {str(indian_now()-bot_start_time).split('.')[0]}")
    await message.reply(info, parse_mode="HTML")

@dp.message(Command("run"))
async def run_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: await message.reply("⛔ Owner only!"); return
    code = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not code: await message.reply("Code do!"); return
    stdout_capture = io.StringIO()
    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stdout_capture):
            exec(code, {"bot": bot, "asyncio": asyncio, "random": random, "os": os})
        out = stdout_capture.getvalue() or "✅ Executed (no output)"
    except Exception as e:
        out = f"❌ Error: {e}"
    await message.reply(f"<pre>{out[:3000]}</pre>", parse_mode="HTML")

@dp.message(Command("shell"))
async def shell_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: await message.reply("⛔ Owner only!"); return
    if not command.args: await message.reply("Command do!"); return
    try:
        result = subprocess.run(command.args, shell=True, capture_output=True, text=True, timeout=15)
        out = result.stdout or result.stderr or "No output"
        await message.reply(f"<pre>{out[:3000]}</pre>", parse_mode="HTML")
    except subprocess.TimeoutExpired:
        await message.reply("⏰ Command timeout!")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message(Command("json"))
async def json_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: await message.reply("⛔ Owner only!"); return
    text = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not text: await message.reply("JSON do!"); return
    try:
        data   = json.loads(text)
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        await message.reply(f"📋 <b>JSON</b>\n<pre>{pretty[:3500]}</pre>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Invalid JSON: {e}", parse_mode="HTML")

@dp.message(Command("hash"))
async def hash_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: await message.reply("⛔ Owner only!"); return
    if not command.args: await message.reply("<code>/hash hello</code>"); return
    t = command.args.encode()
    await message.reply(
        f"🔐 <b>Hashes</b>\n"
        f"MD5: <code>{hashlib.md5(t).hexdigest()}</code>\n"
        f"SHA1: <code>{hashlib.sha1(t).hexdigest()}</code>\n"
        f"SHA256: <code>{hashlib.sha256(t).hexdigest()}</code>",
        parse_mode="HTML"
    )

@dp.message(Command("base64"))
async def base64_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: await message.reply("⛔ Owner only!"); return
    args = command.args.split() if command.args else []
    if len(args) < 2: await message.reply("<code>/base64 encode Hello</code>"); return
    action, text = args[0], ' '.join(args[1:])
    try:
        if action == "encode":
            await message.reply(f"<code>{base64.b64encode(text.encode()).decode()}</code>", parse_mode="HTML")
        elif action == "decode":
            await message.reply(f"<code>{base64.b64decode(text.encode()).decode()}</code>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ {e}")

@dp.message(Command("regex"))
async def regex_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: await message.reply("⛔ Owner only!"); return
    if not command.args or '|||' not in command.args:
        await message.reply("<code>/regex pattern ||| test_string</code>"); return
    parts = command.args.split('|||', 1)
    try:
        matches = re.findall(parts[0].strip(), parts[1].strip())
        if matches: await message.reply(f"✅ {len(matches)} matches: {matches[:20]}", parse_mode="HTML")
        else: await message.reply("❌ No matches found")
    except re.error as e:
        await message.reply(f"❌ Invalid regex: {e}")

# ─────────────────────────── PHOTO HANDLER ───────────────────────────
@dp.message(F.photo)
async def handle_photo(message: Message):
    await message.reply("🔍 Photo dekh rahi hoon... 📸")
    try:
        photo       = message.photo[-1]
        file        = await bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        photo_b64   = base64.b64encode(photo_bytes).decode()
        caption     = message.caption or "Is photo mein kya hai? Describe kar."
        if G4F_AVAILABLE:
            client   = G4FClient()
            img_url  = f"data:image/jpeg;base64,{photo_b64}"
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model="gpt-4o", provider=Blackbox,
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": f"Tu Alita hai 🎀. Hinglish mein bata: {caption}"},
                        {"type": "image_url", "image_url": {"url": img_url}}
                    ]}]
                )
            )
            await message.reply(f"📸 <b>Photo Analysis</b> 🎀\n\n{response.choices[0].message.content[:4000]}", parse_mode="HTML")
        else:
            await message.reply("📸 Photo mili! Vision feature thoda busy hai abhi~")
    except Exception as e:
        logging.error(f"Photo error: {e}")
        await message.reply("😅 Photo process karne mein problem! Dubara try karo.")

# ─────────────────────────── CHAT MEMBER HANDLER ───────────────────────────
@dp.chat_member()
async def chat_member_handler(update: ChatMemberUpdated):
    user = update.new_chat_member.user
    chat_id = update.chat.id
    if update.new_chat_member.status == "member":
        g = await db_get_group(chat_id)
        if g and g.get('captcha_enabled', 0):
            n1, n2 = random.randint(1,20), random.randint(1,20)
            op  = random.choice(['+','-','×'])
            ans = n1+n2 if op=='+' else (n1-n2 if op=='-' else n1*n2)
            if op == '-' and ans < 0: n1,n2 = n2,n1; ans = n1-n2
            captcha_store[user.id] = {"answer": str(ans), "chat_id": chat_id,
                                       "question": f"{n1} {op} {n2} = ?"}
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("✅ I'm human!", callback_data=f"captcha_{user.id}")]
            ])
            await bot.send_message(chat_id, f"🧩 <b>CAPTCHA</b>\nWelcome {user.first_name}!\nSolve: {n1} {op} {n2} = ?",
                                   reply_markup=kb, parse_mode="HTML")
            return
        if not g or g.get('welcome_enabled', 1):
            custom = g.get('custom_welcome') if g else None
            if custom:
                msg = custom.replace("{name}", user.first_name)
            else:
                style = get_alita_prompt("happy")
                prompt = f"New member {user.first_name} ne group join kiya! 2-3 line warm Hinglish welcome message."
                msg = await call_groq(prompt, style) or \
                      f"🌸 Welcome {user.first_name}! Bahut khushi hui tujhe yahan dekhke! {random_emoji()} {random_symbol()}"
            await bot.send_message(chat_id, msg)
    elif update.new_chat_member.status in ("left","kicked"):
        g = await db_get_group(chat_id)
        if g and g.get('goodbye_enabled', 1):
            old_user = update.old_chat_member.user
            custom   = g.get('custom_goodbye')
            if custom:
                msg = custom.replace("{name}", old_user.first_name)
            else:
                byes = [f"👋 {old_user.first_name} left. Take care!",
                        f"😔 {old_user.first_name} chale gaye! Miss karenge!",
                        f"💔 {old_user.first_name} is no longer with us."]
                msg = random.choice(byes)
            await bot.send_message(chat_id, msg + f" {random_emoji()}")

# ─────────────────────────── MAIN MESSAGE HANDLER ───────────────────────────
@dp.message()
async def message_handler(message: Message):
    if not message.from_user or message.from_user.id == bot.id:
        return

    uid = message.from_user.id
    await db_update_user(uid, {"first_name": message.from_user.first_name,
                                "username":   message.from_user.username})
    if message.chat.type in ('group','supergroup'):
        await db_update_group(message.chat.id, {"chat_id": message.chat.id,
                                                  "title":   message.chat.title})

    # AFK check - sender came back
    if uid in user_afk:
        afk_info = user_afk.pop(uid)
        mins     = int((indian_now() - afk_info['time']).total_seconds() // 60)
        await message.reply(
            f"🌸 Welcome back {message.from_user.first_name}! {random_emoji()}\n"
            f"Tu {mins} minute AFK tha! {random_symbol()}"
        )

    # AFK check - mentioned AFK user
    if message.reply_to_message and message.reply_to_message.from_user:
        rid = message.reply_to_message.from_user.id
        if rid in user_afk:
            afk = user_afk[rid]
            await message.reply(
                f"⚠️ <b>{message.reply_to_message.from_user.first_name}</b> abhi AFK hai!\n"
                f"📝 Reason: {afk['reason']} {random_symbol()}",
                parse_mode="HTML"
            )

    if not message.text:
        # Auto-save sticker if owner sends it
        if message.sticker and uid == ADMIN_ID:
            await save_sticker_db(message.sticker.file_id, uid, message.sticker.emoji or "")
        return

    user_text = message.text

    # ── OWNER: Natural language broadcast detection ──
    if uid == ADMIN_ID and is_broadcast_request(user_text):
        if message.reply_to_message:
            status = await message.reply("📤 Broadcasting... ek second! ⏳")
            sent, failed = await do_broadcast(bot, from_chat_id=message.chat.id,
                                              msg_id=message.reply_to_message.message_id)
            await status.edit_text(
                f"✅ <b>Broadcast ho gaya!</b>\n\n📨 Sent: <b>{sent}</b>\n❌ Failed: <b>{failed}</b> {random_emoji()}",
                parse_mode="HTML"
            )
            return
        extracted = extract_broadcast_msg(user_text)
        if extracted:
            status = await message.reply("📤 Broadcasting...")
            sent, failed = await do_broadcast(bot, custom_text=extracted)
            await status.edit_text(
                f"✅ <b>Broadcast ho gaya!</b>\n📤 Message: {extracted[:80]}\n"
                f"📨 Sent: <b>{sent}</b> | ❌ Failed: <b>{failed}</b> {random_emoji()}",
                parse_mode="HTML"
            )
            return
        else:
            await message.reply(
                "Bhai kaunsa message broadcast karna hai? Reply karo us message pe, ya likhoo:\n"
                "<code>sbko bhej do: [message]</code>", parse_mode="HTML"
            )
            return

    # ── Auto-mod (groups only) ──
    if message.chat.type in ('group','supergroup'):
        g = await db_get_group(message.chat.id)
        if g and g.get('auto_mod_enabled', 1) and not await is_user_admin(message.chat.id, uid):
            if contains_adult(user_text):
                await delete_and_warn(message, "adult_content"); return
            if contains_bad_words(user_text):
                await delete_and_warn(message, "bad_words"); return
            if contains_group_link(user_text):
                await delete_and_warn(message, "link"); return
            if contains_fake_link(user_text):
                await delete_and_warn(message, "fake_links"); return
            if await is_spam(message.chat.id, uid):
                await delete_and_warn(message, "spam"); return

    # ── Analyze user style ──
    analyze_style(user_text, uid)

    # ── Decide to respond ──
    should_respond  = False
    is_private      = message.chat.type == "private"
    is_reply_to_bot = (message.reply_to_message and
                       message.reply_to_message.from_user and
                       message.reply_to_message.from_user.id == bot.id)
    is_mention      = False
    if BOT_USERNAME and f"@{BOT_USERNAME}".lower() in user_text.lower():
        is_mention = True
        user_text  = re.sub(f"@{BOT_USERNAME}", "", user_text, flags=re.IGNORECASE).strip()

    contains_alita = re.search(r'\balita\b', user_text, re.IGNORECASE) is not None

    if is_private or is_reply_to_bot or is_mention or contains_alita:
        should_respond = True
    elif message.chat.type in ('group','supergroup') and random.random() < 0.10:
        should_respond = True

    if should_respond:
        await bot.send_chat_action(message.chat.id, "typing")
        await asyncio.sleep(random.uniform(0.3, 1.0))

        reply = await generate_ai_response(message.chat.id, user_text or "Hii", uid)

        # Fix code blocks
        reply = re.sub(r'```(\w+)?\n(.*?)```', r'<pre>\2</pre>', reply, flags=re.DOTALL)

        await db_save_conversation(uid, message.chat.id, "user", user_text)
        await db_save_conversation(uid, message.chat.id, "assistant", reply)
        await learn_from_message(uid, user_text)

        # 8% chance voice
        if EDGE_TTS_AVAILABLE and random.random() < 0.08:
            await bot.send_chat_action(message.chat.id, "record_voice")
            vf = await generate_voice(reply, f"voice_{message.message_id}.ogg")
            if vf:
                await message.reply(reply[:4000], parse_mode="HTML")
                with open(vf, 'rb') as f:
                    await message.reply_voice(BufferedInputFile(f.read(), "voice.ogg"))
                os.remove(vf)
            else:
                await message.reply(reply[:4000], parse_mode="HTML")
        else:
            await message.reply(reply[:4000], parse_mode="HTML")

        await add_reaction(message, user_text)

        if saved_stickers and random.random() < 0.15:
            try: await bot.send_sticker(message.chat.id, random.choice(saved_stickers))
            except: pass
        return

    await add_reaction(message, user_text)

# ─────────────────────────── CALLBACK HANDLER ───────────────────────────
@dp.callback_query()
async def callback_handler(callback: CallbackQuery):
    data = callback.data
    try:
        if data.startswith("horo_"):
            sign = data[5:]
            await horoscope_cmd(callback.message, CommandObject(args=sign))
        elif data.startswith("captcha_"):
            user_id = int(data[8:])
            if callback.from_user.id != user_id:
                await callback.answer("Yeh CAPTCHA aapke liye nahi hai!", show_alert=True); return
            if user_id in captcha_store:
                q = captcha_store[user_id].get('question', '?')
                await callback.message.edit_text(f"🧩 Solve karo:\n<b>{q}</b>\n\nReply mein answer do.", parse_mode="HTML")
            else:
                await callback.answer("CAPTCHA expire ho gayi!", show_alert=True)
        elif data == "menu_util":
            await callback.message.edit_text(
                "📱 <b>Utilities</b>\n/weather /time /date /qr /translate /math /shorten /password /voice",
                parse_mode="HTML")
        elif data == "menu_fun":
            await callback.message.edit_text(
                "🎭 <b>Fun</b>\n/imagine /fact /horoscope /lyrics /creative",
                parse_mode="HTML")
        elif data == "menu_safety":
            await callback.message.edit_text(
                "🛡️ <b>Safety</b>\n• Auto spam block\n• Bad words filter\n• Adult content → auto-ban\n"
                "• Group link block\n• Fake link block\n• 3 warns = mute\n• CAPTCHA system",
                parse_mode="HTML")
        elif data == "menu_game":
            await callback.message.edit_text(
                "🎮 <b>Gaming</b>\n/game /bal /daily /work /crime /rob /kill\n/heal /revive /protect /give /lb",
                parse_mode="HTML")
        elif data == "menu_providers":
            await providers_cmd(callback.message, CommandObject(args=""))
        elif data == "talk":
            await callback.message.edit_text(
                f"🎀 Haan ji! Main hoon Alita! Kya baat karni hai?\n"
                f"Mujhe mention karo ya reply karo~ {random_symbol()}")
    except Exception as e:
        logging.error(f"Callback error: {e}")
    await callback.answer()

# ─────────────────────────── WEB SERVER ───────────────────────────
async def health_check(request):
    uptime = str(indian_now() - bot_start_time).split('.')[0]
    return web.Response(text=f"🎀 Alita Ultimate is alive! Uptime: {uptime}")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"🌐 Web server on port {PORT}")

# ─────────────────────────── MAIN ───────────────────────────
async def main():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username
    print(f"🎀 Alita Bot: @{BOT_USERNAME} (ID: {me.id})")
    await initialize_db()
    print(f"🎨 Stickers: {len(saved_stickers)}")
    print(f"🤖 Groq: {groq_client is not None} | g4f: {G4F_AVAILABLE}")
    print(f"📅 Calendar: {calendar_service is not None}")
    print(f"🎤 Voice: {EDGE_TTS_AVAILABLE}")
    print(f"📦 DB: {'MongoDB' if USE_MONGODB else 'SQLite'}")

    # Scheduler
    scheduler.add_job(send_time_greetings, CronTrigger(hour=7,  minute=0, timezone=INDIAN_TZ), id="morning")
    scheduler.add_job(send_time_greetings, CronTrigger(hour=12, minute=0, timezone=INDIAN_TZ), id="afternoon")
    scheduler.add_job(send_time_greetings, CronTrigger(hour=18, minute=0, timezone=INDIAN_TZ), id="evening")
    scheduler.add_job(send_time_greetings, CronTrigger(hour=22, minute=0, timezone=INDIAN_TZ), id="night")
    # Festival wishes daily at 8am
    scheduler.add_job(send_festival_wishes, CronTrigger(hour=8, minute=0, timezone=INDIAN_TZ), id="festival")
    # Weekend wishes – Saturday 9am and Sunday 9am
    scheduler.add_job(send_weekend_wishes, CronTrigger(day_of_week="sat,sun", hour=9, minute=0, timezone=INDIAN_TZ), id="weekend")
    # Stickers and reminders
    scheduler.add_job(send_random_sticker_job, CronTrigger(hour="*/3", minute="0"), id="sticker")
    scheduler.add_job(check_reminders, CronTrigger(second="*/30"), id="reminders")
    scheduler.add_job(random_initiation, CronTrigger(hour="*/4", minute="30"), id="random_init")
    scheduler.start()
    print("⏰ Scheduler started!")

    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Polling started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    asyncio.run(main())
