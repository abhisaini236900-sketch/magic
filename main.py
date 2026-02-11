import os
import asyncio
import random
import re
import json
import base64
import io
import hashlib
import string
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple
from contextlib import closing

import pytz
import aiohttp
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont
import qrcode
import textwrap

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile, ChatPermissions, CallbackQuery
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from groq import AsyncGroq
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ==================== CONFIGURATION ====================
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
PORT = int(os.getenv("PORT", 10000))

INDIAN_TZ = pytz.timezone('Asia/Kolkata')
BOT_USERNAME = None  # will be set in main

# ==================== DATABASE SETUP ====================
conn = sqlite3.connect("alita.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Users table (for broadcast)
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    last_active TIMESTAMP
)""")

# Groups table (for broadcast & settings)
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
    count INTEGER DEFAULT 1
)""")

conn.commit()

# In‑memory caches
saved_stickers: List[str] = []
chat_memory: Dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
user_afk: Dict[int, Dict] = {}
user_emotion: Dict[int, str] = {}
user_last_interact: Dict[int, datetime] = {}
captcha_store: Dict[int, Dict] = {}
spam_tracker: Dict[int, Dict[int, List[datetime]]] = defaultdict(lambda: defaultdict(list))
group_admins_cache: Dict[int, Set[int]] = {}
bot_start_time = datetime.now(INDIAN_TZ)

# ==================== CONSTANTS ====================
BAD_WORDS = [
    "chutiya", "chutiye", "madarchod", "behenchod", "bhosdike", "lodu", "gandu",
    "fuck", "shit", "bitch", "bastard", "asshole", "motherfucker", "cunt", "dick",
    "gaand", "lund", "randi", "harami", "kamina", "suar", "kutta", "bhosdi",
    "bc", "mc", "gand", "lauda", "choot", "maa ki", "behen ki"
]

ADULT_KEYWORDS = [
    "porn", "xxx", "nsfw", "adult", "sex", "nude", "naked", "boobs", "ass",
    "dick", "pussy", "hentai", "porno", "horny", "fuck", "sexy", "hot", "desi", "chudai", "lund", "chod"
]

FAKE_LINK_PATTERNS = [
    r'bit\.ly\/[a-zA-Z0-9]+',
    r'tinyurl\.com\/[a-zA-Z0-9]+',
    r'goo\.gl\/[a-zA-Z0-9]+',
    r'shorturl\.at\/[a-zA-Z0-9]+',
    r'ow\.ly\/[a-zA-Z0-9]+',
    r'is\.gd\/[a-zA-Z0-9]+',
    r'cli\.gs\/[a-zA-Z0-9]+'
]

GROUP_LINK_PATTERNS = [
    r't\.me\/[a-zA-Z0-9_]+',
    r'telegram\.me\/[a-zA-Z0-9_]+',
    r'telegram\.dog\/[a-zA-Z0-9_]+'
]

WARNING_MESSAGES = [
    "⚠️ **Warning {count}/3** 🚨\n{name}, please don't {action}!",
    "🚨 **Strike {count}!** ⚠️\n{name}, {action} is not allowed!",
    "⚡ **Final Warning ({count}/3)** ⚡\n{name}, last chance! Stop {action}!"
]

MUTE_DURATIONS = [5, 60, 1440, 10080]  # minutes: 5min, 1h, 24h, 7d

# ==================== SCHEDULER ====================
scheduler = AsyncIOScheduler(timezone=INDIAN_TZ)

# ==================== UTILITY FUNCTIONS ====================
def indian_now() -> datetime:
    return datetime.now(INDIAN_TZ)

def get_time_period() -> str:
    hour = indian_now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    """Check if user is admin/creator in group. For private chat, return False."""
    if chat_id == user_id:
        return False  # private chat no admin concept
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ('administrator', 'creator')
    except:
        return False

async def is_bot_admin(chat_id: int) -> bool:
    """Check if bot is admin in the group."""
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        return member.status in ('administrator', 'creator')
    except:
        return False

async def get_group_admins(chat_id: int) -> Set[int]:
    """Fetch and cache group admins."""
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

# ==================== MODERATION FUNCTIONS ====================
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
    # keep only last 30 seconds
    spam_tracker[chat_id][user_id] = [ts for ts in timestamps if (now - ts).seconds <= 30]
    return len(spam_tracker[chat_id][user_id]) > 7  # 7 msgs in 30s

async def add_warning(chat_id: int, user_id: int, username: str, reason: str) -> Tuple[bool, str]:
    """Add warning. Returns (action_taken, message)"""
    cursor.execute(
        "INSERT INTO warnings (chat_id, user_id, reason, warned_at, count) "
        "VALUES (?, ?, ?, ?, 1) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1, warned_at = excluded.warned_at",
        (chat_id, user_id, reason, indian_now())
    )
    conn.commit()

    # get current warning count
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM warnings WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id)
    )
    row = cursor.fetchone()
    warn_count = row['cnt'] if row else 0

    # get warn limit from group settings
    cursor.execute("SELECT warn_limit FROM groups WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    limit = row['warn_limit'] if row else 3

    action_map = {
        "spam": "spam",
        "link": "share group links",
        "bad_words": "use bad language",
        "adult_content": "share adult content",
        "fake_links": "share suspicious links",
        "manual_warning": "violate rules"
    }
    action = action_map.get(reason, "violate rules")

    warning_text = random.choice(WARNING_MESSAGES).format(
        count=warn_count,
        name=username,
        action=action
    )

    if warn_count >= limit:
        # auto‑action
        if reason == "adult_content":
            try:
                await bot.ban_chat_member(chat_id, user_id)
                warning_text += "\n\n🚫 **BANNED PERMANENTLY!** Adult content is prohibited!"
                # clear warnings after ban
                cursor.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                conn.commit()
                return True, warning_text
            except Exception as e:
                warning_text += f"\n\n⚠️ Failed to ban: {str(e)}"
                return False, warning_text
        else:
            # mute
            mute_minutes = MUTE_DURATIONS[min(warn_count - 1, 3)]  # 0,1,2,3 index
            until = indian_now() + timedelta(minutes=mute_minutes)
            try:
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                duration_str = f"{mute_minutes} minute{'s' if mute_minutes > 1 else ''}"
                warning_text += f"\n\n🔇 **MUTED for {duration_str}!** Too many warnings!"
                # clear warnings after mute
                cursor.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                conn.commit()
                return True, warning_text
            except Exception as e:
                warning_text += f"\n\n⚠️ Failed to mute: {str(e)}"
                return False, warning_text
    return False, warning_text

async def delete_and_warn(message: Message, reason: str):
    """Delete message, warn user, and send response."""
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

# ==================== AI SERVICE ====================
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

async def get_ai_response(chat_id: int, user_text: str, user_id: int = None) -> str:
    if not groq_client:
        return f"{random_emoji('happy')} {random.choice(['Haan ji?', 'Kya baat hai!', 'Mast!'])}"

    # emotion update
    if user_id:
        update_user_emotion(user_id, user_text)

    system_prompt = (
        "You are Alita 🎀 – a sweet, sassy, real Indian girl. "
        "Always respond in Hinglish (Hindi+English mix), max 2 lines. "
        "Use feminine tone, add 1-2 cute emojis. "
        f"Current time in India: {indian_now().strftime('%I:%M %p')}. "
        "If someone asks who made you, say 'Mere bhai Abhi @a6h1ii ne banaya hai!' "
        "If someone asks about your channel, say '@abhi0w0 is my home!' "
        "Never admit you're an AI or mention Groq/Llama. "
    )

    messages = [{"role": "system", "content": system_prompt}]
    # add recent memory
    for msg in list(chat_memory[chat_id])[-5:]:
        messages.append(msg)
    messages.append({"role": "user", "content": user_text})

    try:
        completion = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=120,
            top_p=0.9
        )
        reply = completion.choices[0].message.content.strip()
        # store in memory
        chat_memory[chat_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        print(f"AI Error: {e}")
        return f"{random_emoji('crying')} Thoda der mein baat karte hain, abhi network slow hai!"

# ==================== EMOTION & EMOJI ====================
EMOTION_SETS = {
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

def random_emoji(emotion: str = None) -> str:
    if emotion and emotion in EMOTION_SETS:
        return random.choice(EMOTION_SETS[emotion])
    all_emojis = [e for lst in EMOTION_SETS.values() for e in lst]
    return random.choice(all_emojis)

def update_user_emotion(user_id: int, text: str):
    text_lower = text.lower()
    if any(w in text_lower for w in ['love', 'pyaar', 'dil', 'cute', 'beautiful']):
        user_emotion[user_id] = "love"
    elif any(w in text_lower for w in ['angry', 'gussa', 'mad', 'hate']):
        user_emotion[user_id] = "angry"
    elif any(w in text_lower for w in ['sad', 'cry', 'ro', 'dukh', 'upset']):
        user_emotion[user_id] = "crying"
    elif any(w in text_lower for w in ['joke', 'funny', 'has', 'laugh', '😂']):
        user_emotion[user_id] = "funny"
    elif any(w in text_lower for w in ['hi', 'hello', 'hey', 'namaste']):
        user_emotion[user_id] = "happy"
    elif '?' in text:
        user_emotion[user_id] = "thinking"
    else:
        user_emotion[user_id] = random.choice(list(EMOTION_SETS.keys()))
    user_last_interact[user_id] = indian_now()

# ==================== EXTERNAL SERVICES ====================
async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        return "❌ Weather API key not configured."
    try:
        # try to find city in India first
        async with aiohttp.ClientSession() as sess:
            # geocode
            geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city},IN&limit=1&appid={WEATHER_API_KEY}"
            async with sess.get(geo_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        lat, lon = data[0]['lat'], data[0]['lon']
                        city_name = data[0]['name']
                    else:
                        # try without country
                        geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={WEATHER_API_KEY}"
                        async with sess.get(geo_url) as resp2:
                            if resp2.status == 200:
                                data2 = await resp2.json()
                                if not data2:
                                    return f"❌ City '{city}' not found."
                                lat, lon = data2[0]['lat'], data2[0]['lon']
                                city_name = data2[0]['name']
                            else:
                                return f"❌ City '{city}' not found."
                else:
                    return "❌ Weather service error."

            # get weather
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
        print(f"Weather error: {e}")
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

# ==================== SCHEDULED JOBS ====================
async def send_time_greetings():
    """Send time‑based greetings to all active chats (groups & users)"""
    period = get_time_period()
    greetings = {
        "morning": "🌅 **Good Morning!** Aaj ka din aapke liye mubaarak ho! ✨",
        "afternoon": "☀️ **Good Afternoon!** Lunch ho gaya? 🍛",
        "evening": "🌇 **Good Evening!** Chai ka time ho gaya! ☕",
        "night": "🌙 **Good Night!** Sapno mein milte hain! 💤"
    }
    if period not in greetings:
        return
    msg = greetings[period] + f"\n\n{random_emoji('happy')}"

    # groups
    cursor.execute("SELECT chat_id FROM groups WHERE welcome_enabled = 1")
    for row in cursor.fetchall():
        try:
            await bot.send_message(row['chat_id'], msg, parse_mode="Markdown")
            await asyncio.sleep(0.5)
        except:
            continue

    # active private users (last 7 days)
    cutoff = indian_now() - timedelta(days=7)
    cursor.execute("SELECT user_id FROM users WHERE last_active > ?", (cutoff,))
    for row in cursor.fetchall():
        try:
            await bot.send_message(row['user_id'], msg, parse_mode="Markdown")
            await asyncio.sleep(0.5)
        except:
            continue

async def send_random_sticker_job():
    """Send a random saved sticker to a random active chat."""
    if not saved_stickers:
        return
    sticker = random.choice(saved_stickers)
    # pick random target: 70% group, 30% private
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
    """Send due reminders and delete them."""
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

# ==================== BOT INIT ====================
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# ==================== COMMAND HANDLERS ====================
# -------------------- BASIC / HELP --------------------
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
         InlineKeyboardButton(text="💬 Talk to Alita", callback_data="talk")]
    ])
    welcome = (
        f"{random_emoji('love')} Hey! I'm Alita 🎀</b>\n\n"
        "Your AI assistant with superpowers!\n\n"
        "🧠 AI Chat | 🎨 Image Gen | 🛡️ Admin Tools\n\n"
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
    text = (
        "📚 **ALITA – COMPLETE HELP**\n\n"
        "🧠 **AI & CHAT**\n"
        "/ask [question] – Kuch bhi pucho\n"
        "/clear – Baat-cheet reset karo\n"
        "/search – 🔎 Search (coming soon)\n\n"
        "🎨 **CREATIVE**\n"
        "/imagine [prompt] – AI se photo banao\n"
        "/fact – Daily fact (time ke saath)\n"
        "/horoscope [sign] – Rashifal\n\n"
        "🌤️ **UTILITIES**\n"
        "/weather [city] – Real weather\n"
        "/time – Indian time\n"
        "/date – Aaj ki date\n"
        "/qr [text] – QR code\n"
        "/translate [lang] [text] – Translate\n\n"
        "📝 **PERSONAL**\n"
        "/note [text] – Note save karo\n"
        "/notes – Sab notes dekho\n"
        "/remind [time] [text] – Reminder (e.g. 1h, 30m)\n"
        "/reminders – Reminder list\n"
        "/afk [reason] – AFK mode\n"
        "/info – User info (reply)\n\n"
        "🎵 **MUSIC**\n"
        "/lyrics [song] – Song lyrics\n\n"
        "🛡️ **ADMIN (groups only)**\n"
        "/adminlist – Sab admins\n"
        "/warn [reason] – Warn (reply)\n"
        "/kick – Kick (reply)\n"
        "/ban – Ban (reply)\n"
        "/unban – Unban (reply)\n"
        "/mute [time] – Mute (reply)\n"
        "/unmute – Unmute (reply)\n"
        "/pin – Pin (reply)\n"
        "/unpin – Unpin\n"
        "/slowmode [sec] – Slow mode\n"
        "/tagall – Sabko mention (admin required)\n"
        "/rules – Group rules\n\n"
        "🔒 **AUTO‑MOD**\n"
        "• Bad words filter\n"
        "• Adult content → auto‑ban\n"
        "• Group link block\n"
        "• Spam detection\n"
        "• Fake link block\n"
        "• 3 warns = mute\n\n"
        "🏡 **MY HOME:** @abhi0w0"
    )
    await message.reply(text, parse_mode="Markdown")

# -------------------- AI CHAT --------------------
@dp.message(Command("ask"))
async def ask_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Kya puchna hai? Example: `/ask India ki capital kya hai?`")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    await asyncio.sleep(0.5)
    reply = await get_ai_response(message.chat.id, command.args, message.from_user.id)
    await message.reply(reply, parse_mode="Markdown")

@dp.message(Command("clear"))
async def clear_cmd(message: Message):
    chat_memory[message.chat.id].clear()
    await message.reply(f"{random_emoji('happy')} Memory clear kar di! 🧹")

# -------------------- CREATIVE --------------------
@dp.message(Command("imagine"))
async def imagine_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Kaisi image chahiye? Example: `/imagine sunset mountains`")
        return
    prompt = command.args
    status = await message.reply(f"{random_emoji('happy')} Image bana rahi hu... 🎨")
    img_bytes = await generate_image(prompt)
    if img_bytes:
        await status.delete()
        await message.reply_photo(
            BufferedInputFile(img_bytes, filename="alita_ai.png"),
            caption=f"{random_emoji('love')} **Your image:** {prompt}"
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

# -------------------- UTILITIES --------------------
@dp.message(Command("weather"))
async def weather_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} City name do. Example: `/weather Mumbai`")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    weather = await get_weather(command.args)
    await message.reply(weather, parse_mode="Markdown")

@dp.message(Command("time"))
async def time_cmd(message: Message):
    now = indian_now()
    t = now.strftime("%I:%M %p")
    d = now.strftime("%A, %d %B %Y")
    await message.reply(f"🕒 **Indian Time:** {t}\n📅 **Date:** {d}\n\n{random_emoji('happy')}")

@dp.message(Command("date"))
async def date_cmd(message: Message):
    now = indian_now()
    await message.reply(f"📆 **{now.strftime('%A, %d %B %Y')}**\n\n{random_emoji('happy')}")

@dp.message(Command("qr"))
async def qr_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Text do jisse QR banaun. Example: `/qr Hello World`")
        return
    qr_bytes = generate_qr(command.args)
    await message.reply_photo(
        BufferedInputFile(qr_bytes, filename="alita_qr.png"),
        caption=f"{random_emoji('happy')} **QR Code ready!**"
    )

@dp.message(Command("translate"))
async def translate_cmd(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        await message.reply(f"{random_emoji('thinking')} Usage: `/translate hi Hello`")
        return
    parts = command.args.split(maxsplit=1)
    lang, text = parts[0], parts[1]
    translated = await translate_text(text, lang)
    await message.reply(f"🌍 **Translation ({lang.upper()}):**\n{translated}")

# -------------------- PERSONAL --------------------
@dp.message(Command("note"))
async def note_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Note kya save karun? Example: `/note Milk lena`")
        return
    cursor.execute(
        "INSERT INTO notes (user_id, note_text, created_at) VALUES (?, ?, ?)",
        (message.from_user.id, command.args, indian_now())
    )
    conn.commit()
    await message.reply(f"{random_emoji('happy')} **Note saved!** 📝")

@dp.message(Command("notes"))
async def notes_cmd(message: Message):
    cursor.execute("SELECT note_text, created_at FROM notes WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
                   (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await message.reply(f"{random_emoji('crying')} Koi note nahi hai. /note se add karo.")
        return
    text = "📋 **Your Notes:**\n\n"
    for i, row in enumerate(rows, 1):
        time = datetime.fromisoformat(row['created_at']).strftime('%d/%m %I:%M %p')
        text += f"{i}. {row['note_text']} — _{time}_\n"
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command("remind"))
async def remind_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Usage: `/remind 1h Call mom`")
        return
    args = command.args.split(maxsplit=1)
    if len(args) != 2:
        await message.reply("Time aur reminder dono do. Jaise: `/remind 30m Pani pi lo`")
        return
    time_str, text = args
    # parse time
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
        await message.reply(f"{random_emoji('crying')} Koi active reminder nahi.")
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
    text = (
        f"👤 **User Info**\n"
        f"🆔 ID: `{target.id}`\n"
        f"📛 Name: {target.full_name}\n"
        f"📱 Username: @{target.username if target.username else 'N/A'}\n"
    )
    if message.chat.type in ('group', 'supergroup'):
        try:
            member = await bot.get_chat_member(message.chat.id, target.id)
            text += f"🏷️ Status: {member.status.capitalize()}\n"
        except:
            pass
    await message.reply(text, parse_mode="Markdown")

# -------------------- MUSIC --------------------
@dp.message(Command("lyrics"))
async def lyrics_cmd(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{random_emoji('thinking')} Song name do. Example: `/lyrics Shape of You`")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    lyrics = await get_lyrics(command.args)
    await message.reply(f"🎶 **{command.args}**\n\n{lyrics[:3500]}", parse_mode="Markdown")

# -------------------- ADMIN COMMANDS (groups only) --------------------
async def group_admin_only(message: Message):
    if message.chat.type not in ('group', 'supergroup'):
        await message.reply("⚠️ Yeh command sirf groups mein chalegi.")
        return False
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply(f"{random_emoji('angry')} Sirf admin log yeh command use kar sakte hain.")
        return False
    return True

@dp.message(Command("adminlist"))
async def adminlist_cmd(message: Message):
    if not await group_admin_only(message):
        return
    admins = await get_group_admins(message.chat.id)
    if not admins:
        await message.reply("Koi admin nahi mila?")
        return
    text = "👑 **Group Admins:**\n"
    for admin_id in admins:
        try:
            user = await bot.get_chat_member(message.chat.id, admin_id)
            name = user.user.full_name
            status = "👑 Creator" if user.status == "creator" else "🛡️ Admin"
            text += f"\n{status} – {name}"
        except:
            text += f"\n• `{admin_id}`"
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command("warn"))
async def warn_cmd(message: Message, command: CommandObject):
    if not await group_admin_only(message):
        return
    if not message.reply_to_message:
        await message.reply("Kisi user ke message pe reply karo.")
        return
    target = message.reply_to_message.from_user
    reason = command.args or "Rule violation"
    await delete_and_warn(message.reply_to_message, "manual_warning")

@dp.message(Command("kick"))
async def kick_cmd(message: Message):
    if not await group_admin_only(message):
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
    if not await group_admin_only(message):
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
    if not await group_admin_only(message):
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
    if not await group_admin_only(message):
        return
    if not message.reply_to_message:
        await message.reply("Reply karo user ko mute karne ke liye.")
        return
    target = message.reply_to_message.from_user
    duration = command.args
    minutes = 60  # default 1h
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
    if not await group_admin_only(message):
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
    if not await group_admin_only(message):
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
    if not await group_admin_only(message):
        return
    try:
        await bot.unpin_chat_message(message.chat.id)
        await message.reply("📍 Unpinned!")
    except Exception as e:
        await message.reply(f"Unpin failed: {e}")

@dp.message(Command("slowmode"))
async def slowmode_cmd(message: Message, command: CommandObject):
    if not await group_admin_only(message):
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
            await message.reply(f"⏱️ Slow mode enabled: {delay} seconds between messages.")
    except Exception as e:
        await message.reply(f"Slow mode change failed: {e}")

@dp.message(Command("tagall"))
async def tagall_cmd(message: Message):
    if not await group_admin_only(message):
        return
    if not await is_bot_admin(message.chat.id):
        await message.reply("Mujhe group admin banana padega tagall ke liye.")
        return
    # get members (only if supergroup and bot admin)
    members = []
    try:
        async for member in bot.get_chat_members(message.chat.id):
            if not member.user.is_bot:
                name = member.user.first_name
                mention = f"[{name}](tg://user?id={member.user.id})"
                members.append(mention)
                if len(members) >= 50:  # limit to 50 mentions per message
                    break
    except Exception as e:
        await message.reply(f"Members fetch nahi ho paaye: {e}")
        return
    if not members:
        await message.reply("Koi member nahi mila tag karne ke liye.")
        return
    # split into chunks of 10
    chunk_size = 10
    for i in range(0, len(members), chunk_size):
        chunk = members[i:i+chunk_size]
        await message.reply(" ".join(chunk), parse_mode="Markdown")
        await asyncio.sleep(1)

@dp.message(Command("rules"))
async def rules_cmd(message: Message):
    rules = (
        f"{random_emoji('protective')} **📜 GROUP RULES**\n\n"
        "✅ **DO:**\n"
        "• Respect everyone\n"
        "• Keep chat friendly\n"
        "• Help each other\n\n"
        "🚫 **DON'T:**\n"
        "• No spam\n"
        "• No bad language\n"
        "• No adult content → auto‑ban\n"
        "• No group links\n"
        "• No fake links\n\n"
        "🔒 **I'm here to protect the group!**"
    )
    await message.reply(rules, parse_mode="Markdown")

# -------------------- OWNER COMMANDS --------------------
async def owner_only(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ Yeh command sirf meri jaan ke liye hai.")
        return False
    return True

@dp.message(Command("sendall"))
async def sendall_cmd(message: Message):
    if not await owner_only(message):
        return
    if not message.reply_to_message:
        await message.reply("Kisi message pe reply karo broadcast karne ke liye.")
        return
    status = await message.reply("📤 Broadcasting...")
    sent = 0
    failed = 0
    # users
    cursor.execute("SELECT user_id FROM users")
    for row in cursor.fetchall():
        try:
            await bot.copy_message(
                chat_id=row['user_id'],
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id
            )
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    # groups
    cursor.execute("SELECT chat_id FROM groups")
    for row in cursor.fetchall():
        try:
            await bot.copy_message(
                chat_id=row['chat_id'],
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id
            )
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    await status.edit_text(f"✅ Broadcast done!\nSent: {sent}\nFailed: {failed}")

@dp.message(Command("savesticker"))
async def savesticker_cmd(message: Message):
    if not await owner_only(message):
        return
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply("Reply to a sticker message!")
        return
    file_id = message.reply_to_message.sticker.file_id
    emoji = message.reply_to_message.sticker.emoji or ""
    cursor.execute(
        "INSERT OR IGNORE INTO stickers (file_id, added_by, added_at, emoji) VALUES (?, ?, ?, ?)",
        (file_id, message.from_user.id, indian_now(), emoji)
    )
    conn.commit()
    if cursor.rowcount:
        saved_stickers.append(file_id)
        await message.reply(f"✅ Sticker saved! Total: {len(saved_stickers)}")
    else:
        await message.reply("Sticker already exists!")

@dp.message(Command("stickerstatus"))
async def stickerstatus_cmd(message: Message):
    if not await owner_only(message):
        return
    count = len(saved_stickers)
    await message.reply(f"🎀 **Sticker Database**\n\nTotal stickers: {count}\n\nUse /savesticker to add more.")

@dp.message(Command("deletesticker"))
async def deletesticker_cmd(message: Message):
    if not await owner_only(message):
        return
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

# ==================== MESSAGE HANDLER (AI + MOD + AFK + CAPTCHA) ====================
@dp.message()
async def message_handler(message: Message):
    # ignore bot's own messages
    if message.from_user.id == bot.id:
        return

    # update user activity
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, first_name, username, last_active) VALUES (?, ?, ?, ?)",
        (message.from_user.id, message.from_user.first_name, message.from_user.username, indian_now())
    )
    conn.commit()

    # save group if group
    if message.chat.type in ('group', 'supergroup'):
        cursor.execute(
            "INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, ?)",
            (message.chat.id, message.chat.title)
        )
        conn.commit()

    # ---------- AFK check ----------
    if message.from_user.id in user_afk:
        del user_afk[message.from_user.id]
        await message.reply(f"{random_emoji('happy')} Welcome back! AFK hata diya.")

    for entity in message.entities or []:
        if entity.type == "mention" and message.text:
            username = message.text[entity.offset:entity.offset+entity.length].lstrip('@')
            if username.lower() == BOT_USERNAME.lower():
                # mentioned, will respond later
                pass

    # ---------- AUTO MODERATION (only groups) ----------
    if message.chat.type in ('group', 'supergroup') and message.text:
        cursor.execute("SELECT auto_mod_enabled FROM groups WHERE chat_id = ?", (message.chat.id,))
        row = cursor.fetchone()
        if row and row['auto_mod_enabled']:
            # check spam first
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

    # ---------- CAPTCHA answer ----------
    if message.from_user.id in captcha_store and message.reply_to_message:
        if message.reply_to_message.from_user.id == bot.id:
            correct = captcha_store[message.from_user.id].get('answer')
            if message.text.strip() == correct:
                del captcha_store[message.from_user.id]
                await message.reply(f"{random_emoji('happy')} ✅ CAPTCHA passed! Welcome!")
                return
            else:
                await message.reply(f"{random_emoji('angry')} ❌ Wrong answer! Try again.")
                return

    # ---------- AI RESPONSE ----------
    is_private = message.chat.type == "private"
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot.id
    is_mention = False
    if BOT_USERNAME and message.text:
        if f"@{BOT_USERNAME}" in message.text.lower():
            is_mention = True

    if is_private or is_reply_to_bot or is_mention:
        # typing action
        await bot.send_chat_action(message.chat.id, "typing")
        await asyncio.sleep(random.uniform(0.5, 1.2))
        # clean text from mention
        user_text = message.text or ""
        if BOT_USERNAME:
            user_text = re.sub(f"@{BOT_USERNAME}", "", user_text, flags=re.IGNORECASE).strip()
        if not user_text:
            user_text = "Hii"
        # 15% chance to send sticker before reply
        if saved_stickers and random.random() < 0.15:
            sticker = random.choice(saved_stickers)
            await bot.send_sticker(message.chat.id, sticker)
            await asyncio.sleep(0.3)
        reply = await get_ai_response(message.chat.id, user_text, message.from_user.id)
        await message.reply(reply, parse_mode="Markdown")
        return

# ==================== CHAT MEMBER HANDLER (WELCOME/GOODBYE/CAPTCHA) ====================
@dp.chat_member()
async def chat_member_handler(update: ChatMemberUpdated):
    if update.new_chat_member.status == "member":
        # new member joined
        cursor.execute("SELECT welcome_enabled, custom_welcome, captcha_enabled FROM groups WHERE chat_id = ?",
                       (update.chat.id,))
        row = cursor.fetchone()
        if not row:
            return
        if row['captcha_enabled']:
            # generate CAPTCHA
            num1 = random.randint(1, 20)
            num2 = random.randint(1, 20)
            op = random.choice(['+', '-', '*'])
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
            captcha_store[update.new_chat_member.user.id] = {
                "answer": str(ans),
                "chat_id": update.chat.id
            }
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("I'm human!", callback_data=f"captcha_{update.new_chat_member.user.id}")]
            ])
            await bot.send_message(
                update.chat.id,
                f"🧩 **CAPTCHA Verification**\nWelcome {update.new_chat_member.user.first_name}!\nSolve: {question}",
                reply_markup=kb
            )
            return

        # normal welcome
        if row['welcome_enabled']:
            if row['custom_welcome']:
                msg = row['custom_welcome'].replace("{name}", update.new_chat_member.user.first_name)
            else:
                wel = [
                    "🎉 Welcome {name}!",
                    "🌟 Aao ji {name}!",
                    "🥳 {name} aa gaye!",
                    "🌸 Namaste {name}!"
                ]
                msg = random.choice(wel).format(name=update.new_chat_member.user.first_name)
            await bot.send_message(update.chat.id, msg + f" {random_emoji('happy')}")

    elif update.new_chat_member.status in ("left", "kicked"):
        # member left
        cursor.execute("SELECT goodbye_enabled, custom_goodbye FROM groups WHERE chat_id = ?", (update.chat.id,))
        row = cursor.fetchone()
        if row and row['goodbye_enabled']:
            if row['custom_goodbye']:
                msg = row['custom_goodbye'].replace("{name}", update.old_chat_member.user.first_name)
            else:
                bye = [
                    "👋 {name} left. Take care!",
                    "😔 {name} chale gaye!",
                    "💔 {name} is no longer with us."
                ]
                msg = random.choice(bye).format(name=update.old_chat_member.user.first_name)
            await bot.send_message(update.chat.id, msg + f" {random_emoji('crying')}")

# ==================== CALLBACK HANDLERS ====================
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
            "📱 **Utilities**\n/weather – Weather\n/time – Indian time\n/date – Date\n/qr – QR code\n/translate – Translate",
            parse_mode="Markdown"
        )
    elif data == "menu_fun":
        await callback.message.edit_text(
            "🎭 **Fun**\n/imagine – AI image\n/fact – Daily fact\n/horoscope – Rashifal\n/lyrics – Song lyrics",
            parse_mode="Markdown"
        )
    elif data == "menu_safety":
        await callback.message.edit_text(
            "🛡️ **Safety**\n• Auto spam block\n• Bad words filter\n• Adult content = ban\n• Group link block\n• Fake link block\n• 3 warns = mute",
            parse_mode="Markdown"
        )
    elif data == "talk":
        await callback.message.edit_text(
            f"{random_emoji('love')} Haan ji, main yahan hoon! Kya baat karni hai? Mujhe mention karo ya reply karo.",
            parse_mode="Markdown"
        )
    await callback.answer()

# ==================== WEB SERVER FOR RENDER ====================
async def health_check(request):
    uptime = indian_now() - bot_start_time
    return web.Response(text=f"🤖 Alita is alive! Uptime: {uptime}")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Web server running on port {PORT}")

# ==================== MAIN ====================
async def main():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username
    print(f"🤖 Bot: @{BOT_USERNAME} (ID: {me.id})")
    print(f"🎨 Stickers loaded: {len(saved_stickers)}")

    # start scheduler jobs
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
    asyncio.run(main())
