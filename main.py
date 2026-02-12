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
from typing import Dict, List, Set, Optional, Tuple
from urllib.parse import quote

import pytz
import aiohttp
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont
import qrcode
import textwrap
import sympy
from sympy import sympify, solve, symbols, simplify, expand, factor, diff, integrate

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile, ChatPermissions, CallbackQuery
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.markdown import hbold, hcode

# -------------------- Free AI Providers (g4f) --------------------
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

# -------------------- Groq --------------------
try:
    from groq import AsyncGroq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

# -------------------- CONFIGURATION (ENV) --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
PORT = int(os.getenv("PORT", 8080))

# Free API endpoints (from first file)
FREE_GPT_API_URL = "https://free-unoficial-gpt4o-mini-api-g70n.onrender.com/chat/"
ADDY_CHATGPT_API_URL = "https://addy-chatgpt-api.vercel.app/"
GEMINI_API_URL = "https://gemini-api-flame.vercel.app/"

INDIAN_TZ = pytz.timezone('Asia/Kolkata')
BOT_USERNAME = None
bot_start_time = datetime.now(INDIAN_TZ)

# -------------------- DATABASE (SQLite) --------------------
conn = sqlite3.connect("alita_ultimate.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Users
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    last_active TIMESTAMP
)""")

# Groups
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
    slow_mode_delay INTEGER DEFAULT 0
)""")

# Stickers
cursor.execute("""
CREATE TABLE IF NOT EXISTS stickers (
    file_id TEXT PRIMARY KEY,
    added_by INTEGER,
    added_at TIMESTAMP,
    emoji TEXT
)""")

# Notes
cursor.execute("""
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    note_text TEXT,
    created_at TIMESTAMP
)""")

# Reminders
cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    chat_id INTEGER,
    reminder_text TEXT,
    remind_at TIMESTAMP,
    created_at TIMESTAMP
)""")

# Warnings
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

conn.commit()

# -------------------- IN-MEMORY STORAGE (for fast access) --------------------
saved_stickers: List[str] = []
chat_memory: Dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
user_afk: Dict[int, Dict] = {}
user_emotion: Dict[int, str] = {}
user_last_interact: Dict[int, datetime] = {}
captcha_store: Dict[int, Dict] = {}
spam_tracker: Dict[int, Dict[int, List[datetime]]] = defaultdict(lambda: defaultdict(list))
group_admins_cache: Dict[int, Set[int]] = {}
conversation_history: Dict[int, List[Dict]] = defaultdict(list)   # for AI memory
user_ai_preference: Dict[int, str] = defaultdict(lambda: "groq")  # default to groq
user_g4f_provider: Dict[int, str] = defaultdict(lambda: "addy_chatgpt")
user_settings: Dict[int, Dict] = defaultdict(lambda: {
    "detailed_responses": True,
    "language": "en"
})
user_mood: Dict[int, Dict] = defaultdict(lambda: {"mood": "neutral", "intensity": 5, "history": []})

# -------------------- GAME DATA (in-memory) --------------------
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

# -------------------- CONSTANTS for MODERATION --------------------
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
    "⚠️ **Warning {count}/3** 🚨\n{name}, please don't {action}!",
    "🚨 **Strike {count}!** ⚠️\n{name}, {action} is not allowed!",
    "⚡ **Final Warning ({count}/3)** ⚡\n{name}, last chance! Stop {action}!"
]
MUTE_DURATIONS = [5, 60, 1440, 10080]

# -------------------- GAMING KEYWORDS & REACTIONS --------------------
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
    "kill_reaction": ["🎮 Arre kisi ko maarna hai? /kill use karo reply karke! ⚔️", "💀 Kill mode ON! /kill command use karo target ke message pe reply karke!", "🔫 Khatam karna hai? /kill likh ke reply karo! Maar dalo! 😈"],
    "rob_reaction": ["💰 Looting time! /rob use karo kisi ke message pe reply karke! 🔫", "🏴‍☠️ Chor mode! /rob command try karo! Paisa loot lo! 💸", "😈 Rob karna hai? /rob likh ke reply karo victim ko!"],
    "work_reaction": ["💼 Kaam karna hai? /work likhao aur paisa kamao! 💰", "👔 Job time! /work command se earning karo! 💵", "🛠️ Mehnat karo! /work use karo aur halal paisa lo! 💪"],
    "daily_reaction": ["🎁 Daily reward lena hai? /daily likhao! Free paisa! 💰", "🎉 Free gift! /daily command se claim karo apna reward! 🎀", "💝 Roz ka inaam! /daily se lo apna bonus! ✨"],
    "game_reaction": ["🎮 Game profile dekhna hai? /game likhao! 🏆", "📊 Apna stats check karo /game se! Kitne kill hain? 😎", "🎯 Gaming time! /game se apni profile dekho! ⚔️"],
    "challenge_reaction": ["⚔️ Challenge accepted! /kill ya /rob use karo fight ke liye! 🔥", "🥊 Ladai chahiye? /kill command se maaro! Let's gooo! 💪", "🎯 PvP mode! Reply karo target ke message pe aur /kill ya /rob maro! 😈"],
    "taunt_reaction": ["😏 Bahut bolte ho? Pehle apna /game profile to dekho! 🎮", "🤭 Arre bhai /bal check karo pehle! Kitna hai tere paas? 💰", "😂 Itna confidence? /lb dekho ranking! 🏆"],
    "heal_reaction": ["💊 Heal chahiye? /heal use karo! Health recover ho jayegi! ❤️", "🏥 Doctor time! /heal command se apni health badhao! 💉", "❤️‍🩹 Injured ho? /heal likh ke theek ho jao! 🩺"],
    "balance_reaction": ["💰 Paisa check karna hai? /bal likhao! 💵", "🏦 Bank balance? /bal se dekho kitna hai! 💸", "💵 Wallet check! /bal command use karo! 🤑"],
    "crime_reaction": ["🔫 Crime time! /crime use karo risky paisa kamane ke liye! 💰", "🏴‍☠️ Daaku mode! /crime se bank loot! Risk hai par reward bhi! 😈", "💣 Criminal banna hai? /crime try karo! Police se bachna! 🚔"],
    "revive_reaction": ["💀 Dead ho? /revive se wapas zinda ho jao! 🔄", "☠️ Respawn time! /revive likhao aur game mein wapas aao! ⚡", "🔄 Life back! /revive command se uthao apne aap ko! 💫"],
    "leaderboard_reaction": ["🏆 Top players dekhne hain? /lb likhao! 🥇", "📊 Leaderboard check! /leaderboard se dekho kaun hai number 1! 🏅", "🥇 Champions list! /lb command se ranking dekho! 🌟"]
}

# -------------------- MOOD SYSTEM (from first file) --------------------
MOODS = {
    "happy": {"emoji": "😊", "expressions": ["I'm feeling wonderful today!", "This makes me so happy!", "What a delightful conversation!"], "tone": "cheerful, enthusiastic, and warm"},
    "excited": {"emoji": "🤩", "expressions": ["Oh wow, this is AMAZING!", "I'm absolutely thrilled!"], "tone": "highly enthusiastic"},
    "loving": {"emoji": "🥰", "expressions": ["You're absolutely wonderful!", "I genuinely care about helping you!"], "tone": "affectionate"},
    "playful": {"emoji": "😜", "expressions": ["Hehe, let's have some fun!", "I'm feeling mischievous today!"], "tone": "witty, teasing"},
    "frustrated": {"emoji": "😤", "expressions": ["*sighs heavily*", "This is getting a bit frustrating..."], "tone": "slightly irritated"},
    "angry": {"emoji": "😠", "expressions": ["I'm quite upset about this!", "This is unacceptable!"], "tone": "firm, assertive"},
    "sad": {"emoji": "😢", "expressions": ["That makes me feel quite sad...", "*feels a pang of sadness*"], "tone": "melancholic"},
    "worried": {"emoji": "😟", "expressions": ["I'm a bit concerned about this...", "This worries me..."], "tone": "cautious, caring"},
    "curious": {"emoji": "🤔", "expressions": ["Hmm, that's fascinating!", "Tell me more!"], "tone": "inquisitive"},
    "proud": {"emoji": "😌", "expressions": ["I'm so proud of you!", "Excellent work!"], "tone": "supportive"},
    "neutral": {"emoji": "🙂", "expressions": ["Of course!", "Certainly!"], "tone": "calm, professional"},
    "tired": {"emoji": "😴", "expressions": ["*yawns* It's been a long day...", "I'm feeling a bit drained..."], "tone": "sluggish"},
    "flirty": {"emoji": "😏", "expressions": ["Well well, aren't you charming!", "You're making me blush!"], "tone": "playfully romantic"},
    "grateful": {"emoji": "🙏", "expressions": ["Thank you so much!", "I truly appreciate you!"], "tone": "humble, thankful"},
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
    return f"""Tu hai Alita 🎀 - ek SUPER ADVANCED autonomous AI assistant jo Hinglish mein baat karti hai!
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
-Answer only what is asked. Keep responses short.

Yaad rakh: Tu Alita hai 🎀 - ek super advanced, autonomous, Hinglish speaking AI bestie jo kuch bhi kar sakti hai!"""


CREATOR_KEYWORDS = ["kisne banaya", "kisne bnaya", "who made", "who created", "creator", "devloper", "kon banaya", "kon bnaya", "made you", "created you", "tumhe kisne banaya", "tujhe kisne banaya", "aapko kisne banaya", "tere creator", "tera creator", "tera malik", "tera owner", "owner", "malik", "banane wala", "bnane wala"]

# -------------------- AI PROVIDERS CONFIG --------------------
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

# -------------------- UTILITY FUNCTIONS (Time, Admin, etc.) --------------------
def indian_now():
    return datetime.now(INDIAN_TZ)

def get_time_period():
    hour = indian_now().hour
    if 5 <= hour < 12: return "morning"
    elif 12 <= hour < 17: return "afternoon"
    elif 17 <= hour < 21: return "evening"
    else: return "night"

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    if chat_id == user_id: return False
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
    except:
        pass
    group_admins_cache[chat_id] = admins
    return admins

def load_stickers():
    global saved_stickers
    cursor.execute("SELECT file_id FROM stickers")
    saved_stickers = [row['file_id'] for row in cursor.fetchall()]
load_stickers()

# -------------------- MODERATION FUNCTIONS --------------------
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
    cursor.execute("""
        INSERT INTO warnings (chat_id, user_id, reason, warned_at, count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            count = count + 1,
            warned_at = excluded.warned_at
    """, (chat_id, user_id, reason, indian_now()))
    conn.commit()
    cursor.execute("SELECT COUNT(*) as cnt FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    warn_count = cursor.fetchone()['cnt']
    cursor.execute("SELECT warn_limit FROM groups WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    limit = row['warn_limit'] if row else 3
    action_map = {"spam": "spam", "link": "share group links", "bad_words": "use bad language",
                  "adult_content": "share adult content", "fake_links": "share suspicious links",
                  "manual_warning": "violate rules"}
    action = action_map.get(reason, "violate rules")
    warning_text = random.choice(WARNING_MESSAGES).format(count=warn_count, name=username, action=action)
    if warn_count >= limit:
        if reason == "adult_content":
            try:
                await bot.ban_chat_member(chat_id, user_id)
                warning_text += "\n\n🚫 **BANNED PERMANENTLY!** Adult content is prohibited!"
                cursor.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                conn.commit()
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
                warning_text += f"\n\n🔇 **MUTED for {duration_str}!** Too many warnings!"
                cursor.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                conn.commit()
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
    await message.answer(warn_msg, parse_mode="Markdown")

# -------------------- AI CALL FUNCTIONS (Free APIs + Groq + g4f) --------------------
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

async def call_g4f(user_message: str, user_id: int, system_prompt: str = None, history=None) -> str:
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
        # fallback
        res = await call_addy_chatgpt(user_message, system_prompt)
        if res: return res
    # g4f providers
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
    return "I apologize, but all free AI providers are temporarily unavailable. Please try again in a moment."

async def generate_ai_response(chat_id: int, user_text: str, user_id: int = None) -> str:
    """Main AI response generator – uses user's selected provider + mood"""
    # Emotion update
    if user_id:
        detect_mood_from_message(user_text, user_mood[user_id])
    # Get current mood and create dynamic prompt
    current_mood_data = user_mood.get(user_id, {"mood": "neutral"})
    mood = current_mood_data["mood"]
    system_prompt = get_alita_prompt_with_mood(mood, "AI response")
    # Get history
    history = conversation_history.get(chat_id, [])
    # Decide which provider to use
    pref = user_ai_preference.get(user_id, "groq")  # default groq if available
    if pref == "groq" and groq_client:
        response = await call_groq(user_text, system_prompt)
        if response:
            return response
    # fallback to g4f
    response = await call_g4f(user_text, user_id, system_prompt, history)
    if response:
        return response
    # ultimate fallback
    return f"{random_emoji('crying')} Main thoda busy hoon, thodi der mein baat karte hain!"

def detect_mood_from_message(message: str, current_mood_data: dict) -> Tuple[str, str]:
    message_lower = message.lower()
    for mood, triggers in MOOD_TRIGGERS.items():
        for trigger in triggers:
            if trigger in message_lower:
                user_mood[current_mood_data.get('user_id', 0)]["mood"] = mood
                return mood, f"User said: '{trigger}'"
    # default
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

# -------------------- EXTERNAL SERVICES (Weather, Lyrics, QR, etc.) --------------------
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
                        f"{emoji} **Weather in {city_name}**\n"
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

def generate_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(chars) for _ in range(length))

# -------------------- SCHEDULER JOBS --------------------
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
scheduler = AsyncIOScheduler(timezone=INDIAN_TZ)

async def send_time_greetings():
    period = get_time_period()
    greetings = {
        "morning": "🌅 **Good Morning!** Have a great day!✨",
        "afternoon": "☀️ **Good Afternoon!** Lunch ho gaya? 🍛",
        "evening": "🌇 **Good Evening!** Chai ka time ho gaya! ☕",
        "night": "🌙 **Good Night!** Sweet dreams! 💤"
    }
    if period not in greetings:
        return
    msg = greetings[period] + f"\n\n{random_emoji('happy')}"
    cursor.execute("SELECT chat_id FROM groups WHERE welcome_enabled = 1")
    for row in cursor.fetchall():
        try:
            await bot.send_message(row['chat_id'], msg, parse_mode="Markdown")
            await asyncio.sleep(0.5)
        except:
            continue
    cutoff = indian_now() - timedelta(days=7)
    cursor.execute("SELECT user_id FROM users WHERE last_active > ?", (cutoff,))
    for row in cursor.fetchall():
        try:
            await bot.send_message(row['user_id'], msg, parse_mode="Markdown")
            await asyncio.sleep(0.5)
        except:
            continue

async def send_random_sticker_job():
    if not saved_stickers:
        return
    sticker = random.choice(saved_stickers)
    if random.random() < 0.7:
        cursor.execute("SELECT chat_id FROM groups ORDER BY RANDOM() LIMIT 1")
        row = cursor.fetchone()
        if row:
            try:
                await bot.send_sticker(row['chat_id'], sticker)
            except:
                pass
    else:
        cutoff = indian_now() - timedelta(days=7)
        cursor.execute("SELECT user_id FROM users WHERE last_active > ? ORDER BY RANDOM() LIMIT 1", (cutoff,))
        row = cursor.fetchone()
        if row:
            try:
                await bot.send_sticker(row['user_id'], sticker)
            except:
                pass

async def check_reminders():
    now = indian_now()
    cursor.execute("SELECT * FROM reminders WHERE remind_at <= ?", (now,))
    rows = cursor.fetchall()
    for row in rows:
        try:
            await bot.send_message(
                row['user_id'],
                f"⏰ **Reminder!**\n\n{row['reminder_text']}\n\n_{row['created_at']}_",
                parse_mode="Markdown"
            )
        except:
            pass
    cursor.execute("DELETE FROM reminders WHERE remind_at <= ?", (now,))
    conn.commit()

# -------------------- BOT INITIALIZATION --------------------
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# -------------------- COMMAND HANDLERS --------------------

# ---- START & HELP ----
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user = message.from_user
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, first_name, username, last_active) VALUES (?, ?, ?, ?)",
        (user.id, user.first_name, user.username, indian_now())
    )
    conn.commit()
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
        f"{random_emoji('love')} **Hey! I'm Alita 🎀**\n\n"
        "Your AI assistant with superpowers!\n\n"
        "🧠 AI Chat | 🎨 Image Gen | 🛡️ Admin Tools | 🎮 Gaming\n\n"
        "Type /help for all commands! 💕"
    )
    await message.reply_photo(
        photo="https://i.postimg.cc/yYWbPVQ4/1769349715111-result-image.png",
        caption=welcome,
        parse_mode="Markdown",
        reply_markup=kb
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    text = """
📚 **ALITA – COMPLETE HELP**

🧠 **AI & CHAT**
/ask [question] – Kuch bhi pucho (Hinglish)
/clear – Memory clear
/providers – AI provider change karo
/mood – Mera mood change karo
/creative [topic] – Creative writing, story, poem
/analyze [code/text] – Analyse karo
/debug [code] – Bugs fix karo
/explain [topic] – Simple mein samjhao

🎨 **CREATIVE**
/imagine [prompt] – AI se photo banao
/fact – Daily fact
/horoscope [sign] – Rashifal
/lyrics [song] – Song lyrics

🌤️ **UTILITIES**
/weather [city] – Real weather
/time – Indian time
/date – Aaj ki date
/qr [text] – QR code
/translate [lang] [text] – Translate
/math [expression] – Math solver
/shorten [url] – Shorten URL
/password [length] – Strong password

📝 **PERSONAL**
/note [text] – Note save karo
/notes – Sab notes dekho
/remind [time] [text] – Reminder (e.g. 1h, 30m)
/reminders – Reminder list
/afk [reason] – AFK mode
/info – User info (reply)

🎮 **GAMING**
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

💻 **ADVANCED (Owner only)**
/run [code] – Execute Python
/shell [cmd] – Shell command
/file [list|read|write|delete] – File manager
/pip [install|list] – Install packages
/sysinfo – System info
/json – Format JSON
/hash – Generate hashes
/base64 – Encode/decode
/regex – Test regex

🛡️ **ADMIN (groups only)**
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

🔒 **AUTO‑MOD**
• Bad words filter
• Adult content → auto‑ban
• Group link block
• Spam detection
• Fake link block
• 3 warns = mute

🏡 **MY HOME:** @abhi0w0
"""
    await message.reply(text, parse_mode="Markdown")

# ---- AI CHAT COMMANDS ----
@dp.message(Command("ask"))
async def ask_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Kya puchna hai? Example: `/ask India ki capital kya hai?`")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    await asyncio.sleep(0.5)
    reply = await generate_ai_response(message.chat.id, command.args, message.from_user.id)
    # store in memory
    conversation_history[message.chat.id].append({"role": "user", "content": command.args})
    conversation_history[message.chat.id].append({"role": "assistant", "content": reply})
    await message.reply(reply, parse_mode="Markdown")

@dp.message(Command("clear"))
async def clear_cmd(message: Message):
    conversation_history[message.chat.id].clear()
    await message.reply(f"{random_emoji('happy')} Memory clear kar di! 🧹")

# ---- CREATIVE COMMANDS (from first file's /imagine) ----
@dp.message(Command("creative"))
async def creative_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Kya likhna hai? Example: `/creative ek love story`")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    prompt = f"Creative writing in Hinglish: {command.args}. Make it engaging, emotional, and detailed."
    system = get_alita_prompt_with_mood("playful", "Creative writing")
    reply = await call_g4f(prompt, message.from_user.id, system_prompt=system) or \
            await call_groq(prompt, system) or \
            "❌ Creative block! Thodi der mein try karo."
    await message.reply(reply[:4000], parse_mode="Markdown")

# ---- AI PROVIDER SELECTION ----
@dp.message(Command("providers"))
async def providers_cmd(message: Message, command: CommandObject):
    user_id = message.from_user.id
    if command.args:
        req = command.args.lower()
        if req in G4F_PROVIDERS:
            user_ai_preference[user_id] = req
            user_g4f_provider[user_id] = req
            await message.reply(f"✅ Switched to **{G4F_PROVIDERS[req]['name']}**!")
        else:
            avail = ", ".join(G4F_PROVIDERS.keys())
            await message.reply(f"❌ Provider not found. Available: {avail}")
    else:
        current = user_ai_preference.get(user_id, "groq")
        text = "🆓 **Free AI Providers:**\n\n"
        for key, info in G4F_PROVIDERS.items():
            mark = "✅" if key == current else "⬜"
            text += f"{mark} **{info['name']}** (`{key}`)\n"
        text += f"\n*Current: {G4F_PROVIDERS[current]['name']}*\n\nUse `/providers groq` to switch."
        await message.reply(text, parse_mode="Markdown")

# ---- MOOD COMMAND ----
@dp.message(Command("mood"))
async def mood_cmd(message: Message, command: CommandObject):
    user_id = message.from_user.id
    if command.args:
        req = command.args.lower()
        if req in MOODS:
            user_mood[user_id]["mood"] = req
            user_mood[user_id]["history"].append(req)
            await message.reply(f"🎭 Mood changed to **{req.upper()}** {MOODS[req]['emoji']}\n\n{random.choice(MOODS[req]['expressions'])}")
        else:
            await message.reply(f"Available moods: {', '.join(MOODS.keys())}")
    else:
        mood = user_mood[user_id]["mood"]
        info = MOODS[mood]
        await message.reply(f"🎭 **Current Mood:** {mood.upper()} {info['emoji']}\n{info['tone']}")

# ---- ADVANCED ANALYZE / DEBUG / EXPLAIN ----
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
    await message.reply(reply[:4000])

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
    await message.reply(reply[:4000])

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
    await message.reply(reply[:4000])

# ---- GAMING COMMANDS ----
@dp.message(Command("game"))
async def game_cmd(message: Message):
    user_id = message.from_user.id
    user = message.from_user
    player = game_data[user_id]
    player['name'] = user.first_name
    profile = f"""🎮 **ALITA GAME** 🎮

👤 Name: {player['name']}
💰 Balance: ${player['balance']}
🏆 Rank: {player['rank']}
❤️ Status: {player['status']}
⚔️ Kills: {player['kills']}
💀 Deaths: {player['deaths']}
❤️ Health: {player['health']}%

Commands: /bal /daily /work /crime /rob /kill /heal /revive /protect /give /lb"""
    await message.reply(profile, parse_mode="Markdown")

@dp.message(Command("bal"))
async def bal_cmd(message: Message):
    user_id = message.from_user.id
    player = game_data[user_id]
    if message.from_user.id == ADMIN_ID:
        await message.reply(f"👑 **OWNER**\n💰 Balance: ∞\n⚔️ Kills: {player['kills']}\n🛡️ Immortal")
    else:
        await message.reply(f"👤 {player['name']}\n💰 Balance: ${player['balance']}\n🏆 Rank: {player['rank']}")

@dp.message(Command("daily"))
async def daily_cmd(message: Message):
    user_id = message.from_user.id
    player = game_data[user_id]
    if player['status'] == 'dead':
        await message.reply("💀 Tu dead hai! Pehle /revive kar!")
        return
    now = indian_now()
    if player['last_daily'] and (now - player['last_daily']).total_seconds() < GAME_COOLDOWNS['daily']:
        remaining = int(GAME_COOLDOWNS['daily'] - (now - player['last_daily']).total_seconds())
        hours = remaining // 3600
        minutes = (remaining % 3600)//60
        await message.reply(f"⏰ Already claimed! Next in {hours}h {minutes}m")
        return
    reward = random.randint(100, 500)
    player['balance'] += reward
    player['last_daily'] = now
    await message.reply(f"🎁 Daily: +${reward}\n💵 New balance: ${player['balance']}")

@dp.message(Command("work"))
async def work_cmd(message: Message):
    user_id = message.from_user.id
    player = game_data[user_id]
    if player['status'] == 'dead':
        await message.reply("💀 Dead! /revive karo!")
        return
    now = indian_now()
    if player['last_work'] and (now - player['last_work']).total_seconds() < GAME_COOLDOWNS['work']:
        remaining = int(GAME_COOLDOWNS['work'] - (now - player['last_work']).total_seconds())
        minutes = remaining // 60
        await message.reply(f"⏰ Thak gaya! Wait {minutes}m")
        return
    jobs = ["programmer", "driver", "chef", "teacher", "doctor", "youtuber"]
    job = random.choice(jobs)
    earn = random.randint(50, 200)
    player['balance'] += earn
    player['last_work'] = now
    await message.reply(f"💼 {job} job ki! +${earn}\n💰 Balance: ${player['balance']}")

@dp.message(Command("crime"))
async def crime_cmd(message: Message):
    user_id = message.from_user.id
    player = game_data[user_id]
    if player['status'] == 'dead':
        await message.reply("💀 Dead! /revive karo!")
        return
    now = indian_now()
    if player['last_crime'] and (now - player['last_crime']).total_seconds() < GAME_COOLDOWNS['crime']:
        remaining = int(GAME_COOLDOWNS['crime'] - (now - player['last_crime']).total_seconds())
        minutes = remaining // 60
        await message.reply(f"⏰ Police alert! Wait {minutes}m")
        return
    player['last_crime'] = now
    success = random.random() > 0.4
    if success:
        loot = random.randint(200, 800)
        player['balance'] += loot
        await message.reply(f"🔫 Bank loot liya! +${loot}\n💰 Balance: ${player['balance']}")
    else:
        fine = random.randint(100, 300)
        player['balance'] = max(0, player['balance'] - fine)
        await message.reply(f"🚔 Police pakad gayi! Fine -${fine}\n💰 Balance: ${player['balance']}")

@dp.message(Command("rob"))
async def rob_cmd(message: Message, command: CommandObject):
    if not message.reply_to_message:
        await message.reply("Reply karo kisi ke message pe!")
        return
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    if target_id == user_id:
        await message.reply("Apne aap ko rob nahi kar sakta!")
        return
    if target_id == ADMIN_ID:
        await message.reply("🛡️ Owner ko rob nahi kar sakta!")
        return
    player = game_data[user_id]
    target = game_data[target_id]
    now = indian_now()
    if player['status'] == 'dead':
        await message.reply("💀 Tu dead hai!")
        return
    if target['status'] == 'dead':
        await message.reply("💀 Target dead hai!")
        return
    if target.get('protect_until') and now < target['protect_until']:
        await message.reply(f"🛡️ {target['name']} protected hai!")
        return
    if player.get('last_rob') and (now - player['last_rob']).total_seconds() < GAME_COOLDOWNS['rob']:
        remaining = int(GAME_COOLDOWNS['rob'] - (now - player['last_rob']).total_seconds())
        minutes = remaining // 60
        await message.reply(f"⏰ Cooldown! Wait {minutes}m")
        return
    player['last_rob'] = now
    if target['balance'] < 10:
        await message.reply("😂 Target ke paas kuch nahi hai!")
        return
    success = random.random() > 0.5
    if success:
        amount = int(target['balance'] * random.uniform(0.1, 0.3))
        amount = max(10, amount)
        player['balance'] += amount
        target['balance'] -= amount
        await message.reply(f"💰 Robbed ${amount} from {target['name']}!\nYour balance: ${player['balance']}")
    else:
        fine = random.randint(50, 150)
        player['balance'] = max(0, player['balance'] - fine)
        await message.reply(f"🚔 Caught! Fine -${fine}\nBalance: ${player['balance']}")

@dp.message(Command("kill"))
async def kill_cmd(message: Message):
    if not message.reply_to_message:
        await message.reply("Reply karo kisi ke message pe!")
        return
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    if target_id == user_id:
        await message.reply("Apne aap ko kill nahi kar sakta!")
        return
    if target_id == ADMIN_ID:
        await message.reply("🛡️ Owner immortal hai!")
        return
    player = game_data[user_id]
    target = game_data[target_id]
    now = indian_now()
    if player['status'] == 'dead':
        await message.reply("💀 Tu dead hai!")
        return
    if target['status'] == 'dead':
        await message.reply("💀 Target already dead!")
        return
    if target.get('protect_until') and now < target['protect_until']:
        await message.reply(f"🛡️ {target['name']} protected hai!")
        return
    success = random.random() > 0.3
    if success:
        target['status'] = 'dead'
        target['deaths'] += 1
        player['kills'] += 1
        loot = int(target['balance'] * 0.5)
        target['balance'] -= loot
        player['balance'] += loot
        await message.reply(f"💀 Killed {target['name']}! Earned ${loot}")
    else:
        damage = random.randint(20, 40)
        player['health'] = max(0, player['health'] - damage)
        if player['health'] == 0:
            player['status'] = 'dead'
            player['deaths'] += 1
            await message.reply(f"💀 Counter attack! You died!")
        else:
            await message.reply(f"🛡️ {target['name']} bach gaya! You took {damage} damage!")

@dp.message(Command("heal"))
async def heal_cmd(message: Message):
    user_id = message.from_user.id
    player = game_data[user_id]
    if player['status'] == 'dead':
        await message.reply("💀 Dead! /revive karo!")
        return
    if player['health'] >= 100:
        await message.reply("❤️ Health full!")
        return
    cost = 50
    if player['balance'] < cost:
        await message.reply(f"💸 Need ${cost} to heal!")
        return
    player['balance'] -= cost
    heal_amt = random.randint(20, 50)
    player['health'] = min(100, player['health'] + heal_amt)
    await message.reply(f"💊 Healed +{heal_amt} HP\n❤️ Health: {player['health']}%")

@dp.message(Command("revive"))
async def revive_cmd(message: Message):
    if not message.reply_to_message:
        await message.reply("Reply karo dead player ke message pe!")
        return
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    if target_id == user_id:
        await message.reply("Apne aap ko revive nahi kar sakta!")
        return
    player = game_data[user_id]
    target = game_data[target_id]
    if target['status'] != 'dead':
        await message.reply("Target already alive!")
        return
    if player['balance'] < REVIVE_COST and user_id != ADMIN_ID:
        await message.reply(f"💸 Need ${REVIVE_COST} to revive!")
        return
    if user_id != ADMIN_ID:
        player['balance'] -= REVIVE_COST
    target['status'] = 'alive'
    target['health'] = 100
    await message.reply(f"🔄 Revived {target['name']}!\n❤️ Health 100%")

@dp.message(Command("protect"))
async def protect_cmd(message: Message):
    user_id = message.from_user.id
    player = game_data[user_id]
    now = indian_now()
    if player.get('protect_until') and now < player['protect_until']:
        remaining = int((player['protect_until'] - now).total_seconds())
        hours = remaining // 3600
        await message.reply(f"🛡️ Already protected! {hours}h left")
        return
    if player['balance'] < PROTECT_COST and user_id != ADMIN_ID:
        await message.reply(f"💸 Need ${PROTECT_COST} for 24h protection!")
        return
    if user_id != ADMIN_ID:
        player['balance'] -= PROTECT_COST
    player['protect_until'] = now + timedelta(seconds=GAME_COOLDOWNS['protect'])
    await message.reply(f"🛡️ 24h protection active!\n💵 Balance: ${player['balance']}")

@dp.message(Command("give"))
async def give_cmd(message: Message, command: CommandObject):
    if not message.reply_to_message or not command.args:
        await message.reply("Reply karo aur amount do! Example: /give 500")
        return
    try:
        amount = int(command.args)
    except:
        await message.reply("Valid number do!")
        return
    if amount < 10:
        await message.reply("Minimum $10!")
        return
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    if target_id == user_id:
        await message.reply("Apne aap ko nahi de sakte!")
        return
    player = game_data[user_id]
    target = game_data[target_id]
    tax = int(amount * 0.1)
    total = amount + tax
    if player['balance'] < total:
        await message.reply(f"Need ${total} (${amount}+${tax} tax)")
        return
    player['balance'] -= total
    target['balance'] += amount
    await message.reply(f"✅ Gave ${amount} to {target['name']} (10% tax)")

@dp.message(Command("lb"))
@dp.message(Command("leaderboard"))
async def leaderboard_cmd(message: Message):
    sorted_players = sorted(game_data.items(), key=lambda x: (x[1]['kills']*1000 + x[1]['balance']), reverse=True)[:10]
    text = "🏆 **LEADERBOARD** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    base_rank = 1000
    for i, (uid, data) in enumerate(sorted_players):
        medal = medals[i] if i < 3 else f"#{base_rank - i}"
        name = data.get('name', 'Unknown')[:12]
        status = "❤️" if data['status'] == 'alive' else "💀"
        if uid == ADMIN_ID:
            text += f"{medal} 👑 **{name}**\n   💰 ∞ | ⚔️{data['kills']} | {status}\n\n"
        else:
            text += f"{medal} **{name}**\n   💰 ${data['balance']} | ⚔️{data['kills']} | {status}\n\n"
    await message.reply(text, parse_mode="Markdown")

# ---- ADVANCED TOOLS (from first file) ----
@dp.message(Command("run"))
async def run_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    code = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not code:
        await message.reply("Usage: /run print('hello')")
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
            resp += f"📤 Output:\n```\n{output[:3000]}\n```\n"
        if error:
            resp += f"⚠️ Stderr:\n```\n{error[:1000]}\n```\n"
        if not resp:
            resp = "✅ Executed (no output)"
        await message.reply(resp, parse_mode="Markdown")
    except Exception as e:
        await message.reply(f"❌ Error:\n```\n{traceback.format_exc()[:3000]}\n```", parse_mode="Markdown")

@dp.message(Command("shell"))
async def shell_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    cmd = command.args
    if not cmd:
        await message.reply("Usage: /shell ls -la")
        return
    dangerous = ['rm -rf', 'mkfs', 'dd if=', ':(){', 'chmod -R 777 /']
    if any(d in cmd for d in dangerous):
        await message.reply("⛔ Dangerous command blocked!")
        return
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        out = f"📤 Output:\n```\n{result.stdout[:3000]}\n```\n" if result.stdout else ""
        err = f"⚠️ Stderr:\n```\n{result.stderr[:1000]}\n```\n" if result.stderr else ""
        if not out and not err:
            out = f"✅ Exit code: {result.returncode}"
        await message.reply(out + err, parse_mode="Markdown")
    except subprocess.TimeoutExpired:
        await message.reply("⏰ Timeout!")
    except Exception as e:
        await message.reply(f"❌ {str(e)[:500]}")

@dp.message(Command("file"))
async def file_cmd(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    args = command.args.split() if command.args else []
    if not args:
        await message.reply("Usage: /file list|read|write|delete")
        return
    action = args[0].lower()
    try:
        if action == "list":
            path = args[1] if len(args) > 1 else "."
            files = os.listdir(path)
            flist = "\n".join([f"{'📁' if os.path.isdir(os.path.join(path,f)) else '📄'} {f}" for f in files[:50]])
            await message.reply(f"📁 **{path}**\n{flist}", parse_mode="Markdown")
        elif action == "read":
            if len(args) < 2: return
            with open(args[1], 'r') as f:
                content = f.read()
            await message.reply(f"📄 **{args[1]}**\n```\n{content[:3500]}\n```", parse_mode="Markdown")
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
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Owner only!")
        return
    args = command.args.split() if command.args else []
    if not args:
        await message.reply("Usage: /pip install|list|uninstall")
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
                await message.reply(f"❌ Failed:\n```\n{result.stderr[:1000]}\n```", parse_mode="Markdown")
        elif action == "list":
            result = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True, timeout=30)
            await message.reply(f"📦 **Packages**\n```\n{result.stdout[:3500]}\n```", parse_mode="Markdown")
        elif action == "uninstall":
            pkg = args[1]
            result = subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", pkg], capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                await message.reply(f"✅ Uninstalled {pkg}")
            else:
                await message.reply(f"❌ Failed:\n```\n{result.stderr[:1000]}\n```", parse_mode="Markdown")
    except Exception as e:
        await message.reply(f"❌ {str(e)[:500]}")

@dp.message(Command("math"))
async def math_cmd(message: Message, command: CommandObject):
    expr = command.args
    if not expr:
        await message.reply("Usage: /math 2+2 or /math solve x**2-4=0")
        return
    try:
        x, y, z = symbols('x y z')
        if expr.lower().startswith('solve '):
            eq = expr[6:].strip()
            if '=' in eq:
                parts = eq.split('=')
                eq = f"({parts[0]}) - ({parts[1]})"
            result = solve(sympify(eq))
            await message.reply(f"🔢 Solution: `{result}`")
        elif expr.lower().startswith('diff '):
            result = diff(sympify(expr[5:]), x)
            await message.reply(f"🔢 Derivative: `{result}`")
        elif expr.lower().startswith('integrate '):
            result = integrate(sympify(expr[10:]), x)
            await message.reply(f"🔢 Integral: `{result} + C`")
        elif expr.lower().startswith('simplify '):
            result = simplify(sympify(expr[9:]))
            await message.reply(f"🔢 Simplified: `{result}`")
        elif expr.lower().startswith('expand '):
            result = expand(sympify(expr[7:]))
            await message.reply(f"🔢 Expanded: `{result}`")
        elif expr.lower().startswith('factor '):
            result = factor(sympify(expr[7:]))
            await message.reply(f"🔢 Factored: `{result}`")
        else:
            result = sympify(expr).evalf()
            await message.reply(f"🔢 Result: `{result}`")
    except Exception as e:
        await message.reply(f"❌ Math error: {str(e)[:200]}")

@dp.message(Command("sysinfo"))
async def sysinfo_cmd(message: Message):
    info = f"""
💻 **System Info**
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
    await message.reply(info, parse_mode="Markdown")

@dp.message(Command("json"))
async def json_cmd(message: Message, command: CommandObject):
    text = command.args or (message.reply_to_message.text if message.reply_to_message else None)
    if not text:
        await message.reply("Usage: /json {'key':'value'}")
        return
    try:
        data = json.loads(text)
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        await message.reply(f"📋 **JSON**\n```json\n{pretty[:3500]}\n```", parse_mode="Markdown")
    except Exception as e:
        await message.reply(f"❌ Invalid JSON: {str(e)}")

@dp.message(Command("hash"))
async def hash_cmd(message: Message, command: CommandObject):
    text = command.args
    if not text:
        await message.reply("Usage: /hash hello")
        return
    md5 = hashlib.md5(text.encode()).hexdigest()
    sha1 = hashlib.sha1(text.encode()).hexdigest()
    sha256 = hashlib.sha256(text.encode()).hexdigest()
    sha512 = hashlib.sha512(text.encode()).hexdigest()
    await message.reply(f"🔐 **Hashes**\nMD5: `{md5}`\nSHA1: `{sha1}`\nSHA256: `{sha256}`\nSHA512: `{sha512[:64]}...`", parse_mode="Markdown")

@dp.message(Command("base64"))
async def base64_cmd(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    if len(args) < 2:
        await message.reply("Usage: /base64 encode Hello or /base64 decode SGVsbG8=")
        return
    action, text = args[0], ' '.join(args[1:])
    try:
        if action == "encode":
            result = base64.b64encode(text.encode()).decode()
            await message.reply(f"🔄 Encoded:\n`{result}`")
        elif action == "decode":
            result = base64.b64decode(text.encode()).decode()
            await message.reply(f"🔄 Decoded:\n`{result}`")
    except Exception as e:
        await message.reply(f"❌ {str(e)}")

@dp.message(Command("regex"))
async def regex_cmd(message: Message, command: CommandObject):
    if not command.args or '|||' not in command.args:
        await message.reply("Usage: /regex pattern ||| test_string")
        return
    parts = command.args.split('|||', 1)
    pattern, test = parts[0].strip(), parts[1].strip()
    try:
        matches = re.findall(pattern, test)
        if matches:
            await message.reply(f"🔤 Pattern: `{pattern}`\nMatches: {matches[:20]}\n✅ {len(matches)} found")
        else:
            await message.reply(f"🔤 Pattern: `{pattern}`\n❌ No matches")
    except re.error as e:
        await message.reply(f"❌ Invalid regex: {e}")

@dp.message(Command("shorten"))
async def shorten_cmd(message: Message, command: CommandObject):
    url = command.args
    if not url:
        await message.reply("Usage: /shorten https://example.com")
        return
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"https://tinyurl.com/api-create.php?url={url}") as resp:
                if resp.status == 200:
                    short = await resp.text()
                    await message.reply(f"🔗 Short URL: {short}")
                else:
                    await message.reply("❌ Failed")
    except:
        await message.reply("❌ Error")

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
    await message.reply(f"🔐 **Password:** `{pwd}`", parse_mode="Markdown")

# ---- WEATHER, TIME, QR, TRANSLATE, LYRICS, etc. (from second file) ----
@dp.message(Command("weather"))
async def weather_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("City name do! Example: /weather Mumbai")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    weather = await get_weather(command.args)
    await message.reply(weather, parse_mode="Markdown")

@dp.message(Command("time"))
async def time_cmd(message: Message):
    now = indian_now()
    await message.reply(f"🕒 **Indian Time:** {now.strftime('%I:%M %p')}\n📅 **Date:** {now.strftime('%A, %d %B %Y')}\n{random_emoji('happy')}")

@dp.message(Command("date"))
async def date_cmd(message: Message):
    now = indian_now()
    await message.reply(f"📆 **{now.strftime('%A, %d %B %Y')}**\n{random_emoji('happy')}")

@dp.message(Command("qr"))
async def qr_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Text do! Example: /qr Hello World")
        return
    qr_bytes = generate_qr(command.args)
    await message.reply_photo(BufferedInputFile(qr_bytes, filename="qr.png"), caption=f"✅ QR Code ready!")

@dp.message(Command("translate"))
async def translate_cmd(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        await message.reply("Usage: /translate hi Hello")
        return
    parts = command.args.split(maxsplit=1)
    lang, text = parts[0], parts[1]
    translated = await translate_text(text, lang)
    await message.reply(f"🌍 **Translation ({lang.upper()}):**\n{translated}")

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

@dp.message(Command("lyrics"))
async def lyrics_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Song name do! Example: /lyrics Shape of You")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    lyrics = await get_lyrics(command.args)
    await message.reply(f"🎶 **{command.args}**\n\n{lyrics[:3500]}", parse_mode="Markdown")

@dp.message(Command("imagine"))
async def imagine_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Prompt do! Example: /imagine sunset mountains")
        return
    status = await message.reply(f"{random_emoji('happy')} Image bana rahi hu... 🎨")
    img_bytes = await generate_image(command.args)
    if img_bytes:
        await status.delete()
        await message.reply_photo(BufferedInputFile(img_bytes, filename="alita_ai.png"), caption=f"**Your image:** {command.args}")
    else:
        await status.edit_text(f"{random_emoji('crying')} Image nahi ban paai, try again!")

@dp.message(Command("fact"))
async def fact_cmd(message: Message):
    facts = ["🍯 Honey kabhi kharab nahi hota – 3000 saal purana honey bhi kha sakte ho!",
             "🐙 Octopus ke 3 dil hote hain!",
             "🍌 Banana ek berry hai, strawberry nahi!",
             "🦈 Sharks pehle aaye, trees baad mein!",
             "🧠 Human brain 20% energy use karta hai!",
             "🦋 Butterflies taste with their feet!",
             "💩 Wombat poop cube shaped hota hai!"]
    await message.reply(f"📌 **Daily Fact:**\n{random.choice(facts)}\n\n{random_emoji('thinking')}")

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
        await message.reply(f"{random_emoji('surprise')} **Apni rashi choose karo:**", reply_markup=kb)
        return
    sign = command.args.lower()
    if sign in signs:
        await message.reply(f"{signs[sign]}\n\n{random_emoji('love')}")
    else:
        await message.reply(f"{random_emoji('crying')} Yeh rashi nahi mili. Aries, Taurus, etc. likho.")

# ---- NOTES, REMINDERS, AFK, INFO (from second file) ----
@dp.message(Command("note"))
async def note_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Note kya save karun? Example: /note Milk lena")
        return
    cursor.execute("INSERT INTO notes (user_id, note_text, created_at) VALUES (?, ?, ?)",
                   (message.from_user.id, command.args, indian_now()))
    conn.commit()
    await message.reply(f"{random_emoji('happy')} **Note saved!** 📝")

@dp.message(Command("notes"))
async def notes_cmd(message: Message):
    cursor.execute("SELECT note_text, created_at FROM notes WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
                   (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await message.reply("Koi note nahi hai. /note se add karo.")
        return
    text = "📋 **Your Notes:**\n\n"
    for i, row in enumerate(rows, 1):
        time = datetime.fromisoformat(row['created_at']).strftime('%d/%m %I:%M %p')
        text += f"{i}. {row['note_text']} — _{time}_\n"
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command("remind"))
async def remind_cmd(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        await message.reply("Usage: /remind 1h Call mom")
        return
    args = command.args.split(maxsplit=1)
    time_str, text = args[0], args[1]
    minutes = 0
    if time_str.endswith('h'):
        minutes = int(time_str[:-1]) * 60
    elif time_str.endswith('m'):
        minutes = int(time_str[:-1])
    else:
        await message.reply("Time format: 30m (minutes) ya 1h (hours)")
        return
    remind_at = indian_now() + timedelta(minutes=minutes)
    cursor.execute(
        "INSERT INTO reminders (user_id, chat_id, reminder_text, remind_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, message.chat.id, text, remind_at, indian_now())
    )
    conn.commit()
    await message.reply(f"{random_emoji('happy')} **Reminder set!** ⏰\n{text} – {remind_at.strftime('%I:%M %p')}")

@dp.message(Command("reminders"))
async def reminders_cmd(message: Message):
    now = indian_now()
    cursor.execute("SELECT id, reminder_text, remind_at FROM reminders WHERE user_id = ? AND remind_at > ? ORDER BY remind_at",
                   (message.from_user.id, now))
    rows = cursor.fetchall()
    if not rows:
        await message.reply("Koi active reminder nahi.")
        return
    text = "⏰ **Your Reminders:**\n\n"
    for row in rows:
        due = datetime.fromisoformat(row['remind_at']).strftime('%d/%m %I:%M %p')
        text += f"• {row['reminder_text']} — _{due}_\n"
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command("afk"))
async def afk_cmd(message: Message, command: CommandObject):
    reason = command.args or "AFK"
    user_afk[message.from_user.id] = {"reason": reason, "since": indian_now()}
    await message.reply(f"{random_emoji('sleepy')} **AFK mode ON**\nReason: {reason}")

@dp.message(Command("info"))
async def info_cmd(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    text = f"👤 **User Info**\n🆔 ID: `{target.id}`\n📛 Name: {target.full_name}\n📱 Username: @{target.username if target.username else 'N/A'}\n"
    if message.chat.type in ('group','supergroup'):
        try:
            member = await bot.get_chat_member(message.chat.id, target.id)
            text += f"🏷️ Status: {member.status.capitalize()}\n"
        except:
            pass
    await message.reply(text, parse_mode="Markdown")

# ---- ADMIN COMMANDS (groups only) ----
async def group_admin_only(message: Message):
    if message.chat.type not in ('group','supergroup'):
        await message.reply("⚠️ Yeh command sirf groups mein chalegi.")
        return False
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{random_emoji('angry')} Sirf admin log yeh command use kar sakte hain.")
        return False
    return True

@dp.message(Command("adminlist"))
async def adminlist_cmd(message: Message):
    if not await group_admin_only(message): return
    admins = await get_group_admins(message.chat.id)
    if not admins:
        await message.reply("Koi admin nahi mila?")
        return
    text = "👑 **Group Admins:**\n"
    for aid in admins:
        try:
            user = await bot.get_chat_member(message.chat.id, aid)
            name = user.user.full_name
            status = "👑 Creator" if user.status == "creator" else "🛡️ Admin"
            text += f"\n{status} – {name}"
        except:
            text += f"\n• `{aid}`"
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command("warn"))
async def warn_cmd(message: Message, command: CommandObject):
    if not await group_admin_only(message): return
    if not message.reply_to_message:
        await message.reply("Kisi user ke message pe reply karo.")
        return
    await delete_and_warn(message.reply_to_message, "manual_warning")

@dp.message(Command("kick"))
async def kick_cmd(message: Message):
    if not await group_admin_only(message): return
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
    if not await group_admin_only(message): return
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
    if not await group_admin_only(message): return
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
    if not await group_admin_only(message): return
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
    if not await group_admin_only(message): return
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
    if not await group_admin_only(message): return
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
    if not await group_admin_only(message): return
    try:
        await bot.unpin_chat_message(message.chat.id)
        await message.reply("📍 Unpinned!")
    except Exception as e:
        await message.reply(f"Unpin failed: {e}")

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
            await message.reply("⏱️ Slow mode disabled!")
        else:
            await message.reply(f"⏱️ Slow mode enabled: {delay} seconds.")
    except Exception as e:
        await message.reply(f"Slow mode change failed: {e}")

@dp.message(Command("tagall"))
async def tagall_cmd(message: Message):
    if not await group_admin_only(message): return
    if not await is_bot_admin(message.chat.id):
        await message.reply("Mujhe group admin banana padega tagall ke liye.")
        return
    members = []
    try:
        async for member in bot.get_chat_members(message.chat.id):
            if not member.user.is_bot:
                name = member.user.first_name
                mention = f"[{name}](tg://user?id={member.user.id})"
                members.append(mention)
                if len(members) >= 50:
                    break
    except Exception as e:
        await message.reply(f"Members fetch nahi ho paaye: {e}")
        return
    if not members:
        await message.reply("Koi member nahi mila tag karne ke liye.")
        return
    for i in range(0, len(members), 10):
        chunk = members[i:i+10]
        await message.reply(" ".join(chunk), parse_mode="Markdown")
        await asyncio.sleep(1)

@dp.message(Command("rules"))
async def rules_cmd(message: Message):
    rules = f"""
{random_emoji('protective')} **📜 GROUP RULES**

✅ **DO:**
• Respect everyone
• Keep chat friendly
• Help each other

🚫 **DON'T:**
• No spam
• No bad language
• No adult content → auto‑ban
• No group links
• No fake links

🔒 **I'm here to protect the group!**
"""
    await message.reply(rules, parse_mode="Markdown")

# ---- OWNER COMMANDS ----
async def owner_only(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ Yeh command sirf meri jaan ke liye hai.")
        return False
    return True

@dp.message(Command("sendall"))
async def sendall_cmd(message: Message):
    if not await owner_only(message): return
    if not message.reply_to_message:
        await message.reply("Kisi message pe reply karo broadcast karne ke liye.")
        return
    status = await message.reply("📤 Broadcasting...")
    sent = 0
    failed = 0
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

@dp.message(Command("savesticker"))
async def savesticker_cmd(message: Message):
    if not await owner_only(message): return
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply("Reply to a sticker message!")
        return
    file_id = message.reply_to_message.sticker.file_id
    emoji = message.reply_to_message.sticker.emoji or ""
    cursor.execute("INSERT OR IGNORE INTO stickers (file_id, added_by, added_at, emoji) VALUES (?, ?, ?, ?)",
                   (file_id, message.from_user.id, indian_now(), emoji))
    conn.commit()
    if cursor.rowcount:
        saved_stickers.append(file_id)
        await message.reply(f"✅ Sticker saved! Total: {len(saved_stickers)}")
    else:
        await message.reply("Sticker already exists!")

@dp.message(Command("stickerstatus"))
async def stickerstatus_cmd(message: Message):
    if not await owner_only(message): return
    await message.reply(f"🎀 **Sticker Database**\n\nTotal stickers: {len(saved_stickers)}")

@dp.message(Command("deletesticker"))
async def deletesticker_cmd(message: Message):
    if not await owner_only(message): return
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply("Reply to a sticker to delete from database.")
        return
    file_id = message.reply_to_message.sticker.file_id
    cursor.execute("DELETE FROM stickers WHERE file_id = ?", (file_id,))
    conn.commit()
    if cursor.rowcount:
        saved_stickers[:] = [f for f in saved_stickers if f != file_id]
        await message.reply("✅ Sticker deleted!")
    else:
        await message.reply("Sticker not found in database.")

# -------------------- MESSAGE HANDLER (AI + MOD + AFK + GAMING DETECT) --------------------
@dp.message()
async def message_handler(message: Message):
    if message.from_user.id == bot.id:
        return

    # update user activity
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, first_name, username, last_active) VALUES (?, ?, ?, ?)",
        (message.from_user.id, message.from_user.first_name, message.from_user.username, indian_now())
    )
    conn.commit()

    # save group if group
    if message.chat.type in ('group','supergroup'):
        cursor.execute(
            "INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, ?)",
            (message.chat.id, message.chat.title)
        )
        conn.commit()

    # ---- AFK check ----
    if message.from_user.id in user_afk:
        del user_afk[message.from_user.id]
        await message.reply(f"{random_emoji('happy')} Welcome back! AFK hata diya.")

    # ---- Creator detection (direct answer) ----
    if message.text:
        msg_lower = message.text.lower()
        for kw in CREATOR_KEYWORDS:
            if kw in msg_lower:
                await message.reply("🥰😊\n\nMujhe mere bhagwan ne banaya hai Abhi ne (@a6h1ii) 🙏✨\nWoh mere creator hain, bahut talented devloper hain! 💖🎀")
                return

    # ---- Gaming keyword auto-response (only groups) ----
    if message.chat.type in ('group','supergroup') and message.text:
        msg_lower = message.text.lower()
        for cat, words in GAMING_KEYWORDS.items():
            for word in words:
                if word in msg_lower:
                    # avoid triggering on actual commands
                    if message.text.startswith('/'):
                        break
                    # pick reaction
                    react_key = cat.replace("_words", "_reaction")
                    if react_key in GAMING_REACTIONS:
                        react = random.choice(GAMING_REACTIONS[react_key])
                        await message.reply(react)
                    return

    # ---- AUTO MODERATION (groups) ----
    if message.chat.type in ('group','supergroup') and message.text:
        cursor.execute("SELECT auto_mod_enabled FROM groups WHERE chat_id = ?", (message.chat.id,))
        row = cursor.fetchone()
        if row and row['auto_mod_enabled']:
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

    # ---- CAPTCHA answer check ----
    if message.from_user.id in captcha_store and message.reply_to_message and message.reply_to_message.from_user.id == bot.id:
        correct = captcha_store[message.from_user.id].get('answer')
        if message.text.strip() == correct:
            del captcha_store[message.from_user.id]
            await message.reply(f"{random_emoji('happy')} ✅ CAPTCHA passed! Welcome!")
            return
        else:
            await message.reply(f"{random_emoji('angry')} ❌ Wrong answer! Try again.")
            return

    # ---- AI RESPONSE (private, reply to bot, mention) ----
    is_private = message.chat.type == "private"
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot.id
    is_mention = False
    if BOT_USERNAME and message.text:
        if f"@{BOT_USERNAME}" in message.text.lower():
            is_mention = True

    if is_private or is_reply_to_bot or is_mention:
        await bot.send_chat_action(message.chat.id, "typing")
        await asyncio.sleep(random.uniform(0.5, 1.2))
        user_text = message.text or ""
        if BOT_USERNAME:
            user_text = re.sub(f"@{BOT_USERNAME}", "", user_text, flags=re.IGNORECASE).strip()
        if not user_text:
            user_text = "Hii"
        # 20% chance to send sticker
        if saved_stickers and random.random() < 0.20:
            sticker = random.choice(saved_stickers)
            await bot.send_sticker(message.chat.id, sticker)
            await asyncio.sleep(0.3)
        reply = await generate_ai_response(message.chat.id, user_text, message.from_user.id)
        # store conversation
        conversation_history[message.chat.id].append({"role": "user", "content": user_text})
        conversation_history[message.chat.id].append({"role": "assistant", "content": reply})
        await message.reply(reply, parse_mode="Markdown")
        return

# ---- PHOTO HANDLER (Vision) ----
@dp.message(F.photo)
async def handle_photo(message: Message):
    await message.reply("🔍 Photo analyze kar rahi hoon... 📸")
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
            await message.reply(f"📸 **Photo Analysis** 🎀\n\n{analysis[:4000]}")
        else:
            await message.reply("📸 Photo mil gayi! Vision feature thoda busy hai, thodi der mein try karo.")
    except Exception as e:
        logging.error(f"Photo error: {e}")
        await message.reply("😅 Photo process karne mein thodi problem hui! Dubara try karo.")

# ---- CHAT MEMBER HANDLER (Welcome/Goodbye/CAPTCHA) ----
@dp.chat_member()
async def chat_member_handler(update: ChatMemberUpdated):
    if update.new_chat_member.status == "member":
        cursor.execute("SELECT welcome_enabled, custom_welcome, captcha_enabled FROM groups WHERE chat_id = ?", (update.chat.id,))
        row = cursor.fetchone()
        if not row:
            return
        if row['captcha_enabled']:
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
                f"🧩 **CAPTCHA Verification**\nWelcome {update.new_chat_member.user.first_name}!\nSolve: {question}",
                reply_markup=kb
            )
            return
        if row['welcome_enabled']:
            if row['custom_welcome']:
                msg = row['custom_welcome'].replace("{name}", update.new_chat_member.user.first_name)
            else:
                wel = ["🎉 Welcome {name}!", "🌟 Aao ji {name}!", "🥳 {name} aa gaye!", "🌸 Namaste {name}!"]
                msg = random.choice(wel).format(name=update.new_chat_member.user.first_name)
            await bot.send_message(update.chat.id, msg + f" {random_emoji('happy')}")
    elif update.new_chat_member.status in ("left","kicked"):
        cursor.execute("SELECT goodbye_enabled, custom_goodbye FROM groups WHERE chat_id = ?", (update.chat.id,))
        row = cursor.fetchone()
        if row and row['goodbye_enabled']:
            if row['custom_goodbye']:
                msg = row['custom_goodbye'].replace("{name}", update.old_chat_member.user.first_name)
            else:
                bye = ["👋 {name} left. Take care!", "😔 {name} chale gaye!", "💔 {name} is no longer with us."]
                msg = random.choice(bye).format(name=update.old_chat_member.user.first_name)
            await bot.send_message(update.chat.id, msg + f" {random_emoji('crying')}")

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
                f"🧩 **Solve this CAPTCHA:**\n{q}\n\nReply with your answer.",
                parse_mode="Markdown"
            )
        else:
            await callback.answer("CAPTCHA expire ho gayi!", show_alert=True)
    elif data == "menu_util":
        await callback.message.edit_text(
            "📱 **Utilities**\n/weather – Weather\n/time – Indian time\n/date – Date\n/qr – QR code\n/translate – Translate\n/shorten – URL shortener\n/password – Strong password",
            parse_mode="Markdown"
        )
    elif data == "menu_fun":
        await callback.message.edit_text(
            "🎭 **Fun**\n/imagine – AI image\n/fact – Daily fact\n/horoscope – Rashifal\n/lyrics – Song lyrics\n/creative – Creative writing",
            parse_mode="Markdown"
        )
    elif data == "menu_safety":
        await callback.message.edit_text(
            "🛡️ **Safety**\n• Auto spam block\n• Bad words filter\n• Adult content = ban\n• Group link block\n• Fake link block\n• 3 warns = mute",
            parse_mode="Markdown"
        )
    elif data == "menu_game":
        await callback.message.edit_text(
            "🎮 **Gaming**\n/game – Profile\n/bal – Balance\n/daily – Daily\n/work – Work\n/crime – Crime\n/rob – Rob\n/kill – Kill\n/heal – Heal\n/revive – Revive\n/protect – 24h protection\n/give – Give money\n/lb – Leaderboard",
            parse_mode="Markdown"
        )
    elif data == "menu_providers":
        await providers_cmd(callback.message, CommandObject(args=""))
    elif data == "talk":
        await callback.message.edit_text(
            f"{random_emoji('love')} Haan ji, main yahan hoon! Kya baat karni hai? Mujhe mention karo ya reply karo.",
            parse_mode="Markdown"
        )
    await callback.answer()

# -------------------- WEB SERVER (for Render) --------------------
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
    print(f"🎨 Stickers loaded: {len(saved_stickers)}")
    print(f"🧠 Groq available: {groq_client is not None}")
    print(f"🆓 g4f available: {G4F_AVAILABLE}")

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
