import os
import asyncio
import random
import re
import json
import base64
import io
import hashlib
import subprocess
import traceback
import platform
import requests
import urllib.parse
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, 
    ChatPermissions, BufferedInputFile, InputFile, ChatMember
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
from PIL import Image
import qrcode
from io import BytesIO
import string

# --- G4F FALLBACK (Optional) ---
G4F_AVAILABLE = False
g4f_client = None
Blackbox = None

try:
    from g4f.client import Client as G4FClient
    from g4f.Provider import Blackbox as BlackboxProvider
    G4F_AVAILABLE = True
    g4f_client = G4FClient()
    Blackbox = BlackboxProvider
except ImportError:
    pass  # g4f not installed

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", 10000))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
OWNER_USERNAME = "@a6h1ii"
CHANNEL_LINK = "@abhi0w0"

# Timezone for India
INDIAN_TIMEZONE = pytz.timezone('Asia/Kolkata')

# Initialize with MemoryStorage
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# Initialize Groq client - PRIMARY AI
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
user_afk: Dict[int, Dict] = {}

# Emotional states for each user
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}

# Group management
afk_users: Dict[int, Dict[int, Dict]] = defaultdict(dict)

# Group settings
welcome_messages: Dict[int, str] = {}
goodbye_messages: Dict[int, str] = {}
slow_mode_settings: Dict[int, int] = {}
locked_chats: Set[int] = set()

class GroupSettings:
    def __init__(self):
        self.welcome_enabled = True
        self.auto_mod_enabled = True
        self.greetings_enabled = True
        self.custom_welcome = None
        self.custom_goodbye = None
        self.language = "hinglish"
        self.captcha_enabled = False
        self.locks = {
            'all': False,
            'text': False,
            'media': False,
            'sticker': False,
            'gif': False,
            'url': False,
            'forward': False
        }

group_settings: Dict[int, GroupSettings] = defaultdict(GroupSettings)

# --- CONSTANTS ---
SPAM_LIMIT = 6
WARNING_MESSAGES = [
    "⚠️ **Warning {count}/3**\n👤 {name}\n🚫 Reason: {action}\n📢 Please follow group rules!",
    "⚠️ **Warning {count}/3**\n👤 {name}\n❌ {action} not allowed!\n⚡ Next time = Mute!",
    "⚠️ **Warning {count}/3**\n👤 {name}\n🚷 Stop {action}!\n🔇 Mute incoming!"
]

MUTE_DURATIONS = [
    timedelta(hours=1),
    timedelta(hours=4),
    timedelta(days=1),
    timedelta(days=2),
    timedelta(days=7)
]

BAD_WORDS = [
    'fuck', 'bitch', 'asshole', 'crap', 'dick', 'pussy',
    'cock', 'slut', 'stupid', 'moron',
    'chutiya', 'chutiye', 'madarchod', 'behenchod', 'bhenchod', 'randi', 'bhosdike',
    'bhosdi', 'gaandu', 'gandu', 'lund', 'lavde', 'bhadwe', 'bhadwa', 'chut',
    'gand', 'mc', 'bc', 'bsdk', 'bhosdiwala', 'chutiyapa', 'madarjaat', 'behenkelode',
    'laude', 'jhaatu', 'jhat', 'tatte',
    'saala', 'saali', 'suar', 'chamar', 'bhangi',
    'fck', 'fuk', 'sh1t', 'b1tch', 'a$$', 'd1ck', 'pu$$y'
]

ADULT_KEYWORDS = [
    'porn', 'xxx', 'sex', 'nude', 'naked', 'boobs', 'pussy', 'dick', 'cock',
    'fuck', 'anal', 'blowjob', 'handjob', 'cum', 'orgasm', 'masturbate',
    'xxx.com', 'pornhub', 'xvideos', 'xhamster', 'redtube', 'youporn',
    'onlyfans', 'camgirl', 'escort', 'hooker', 'prostitute', 'brothel',
    'nudes', 'leaked', 'mms', 'scandal', 'desi', 'bhabhi'
]

GROUP_LINK_PATTERNS = [
    r't\.me/\w+',
    r'telegram\.me/\w+',
    r't\.me/joinchat/\w+',
    r'telegram\.me/joinchat/\w+',
    r't\.me/\+\w+'
]

# --- ADVANCED FEATURES DATA ---
MEME_TEMPLATES = [
    {"text": "When you realize it's Monday tomorrow", "emoji": "😭"},
    {"text": "Me trying to be productive", "emoji": "🤡"},
    {"text": "When someone says 'just be yourself'", "emoji": "😅"},
    {"text": "My bank account after online shopping", "emoji": "💸"},
    {"text": "When code finally works after 100 tries", "emoji": "🎉"},
    {"text": "Me explaining to my mom why I need a new phone", "emoji": "📱"},
    {"text": "When you see your crush online but don't text", "emoji": "😳"},
    {"text": "My sleep schedule during exams", "emoji": "😴"}
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
    "Wombat poop is cube-shaped! 🟫 Nature's dice!",
    "Sloths can hold their breath longer than dolphins! 🦥 40 minutes!"
]

ROAST_RESPONSES = [
    "Tumhari baaton se toh mere kaan bhi sharminda hain! 👂😳",
    "Itni bakwas toh mere phone ki auto-correct bhi nahi karta! 📱",
    "Tumhare jokes se toh meri wallpaper bhi bore ho gayi! 🖼️",
    "Agar overthinking Olympic sport hota, toh tum gold medal le jaate! 🏅",
    "Tumhari logic dekh ke toh Einstein bhi pagal ho jaate! 🧠💥",
    "Tumse achha toh meri AI ki coding hai! 🤖💅",
    "Tumhare IQ ka temperature shayad Celsius mein hai! 🌡️😂",
    "Tumhe dekh ke lagta hai evolution ulta chal raha hai! 🐒⬅️"
]

JOKES = [
    "Why don't scientists trust atoms? Because they make up everything! 😄",
    "Why did the scarecrow win an award? He was outstanding in his field! 🌾",
    "Why don't eggs tell jokes? They'd crack each other up! 🥚",
    "What do you call a fake noodle? An impasta! 🍝",
    "Why did the math book look sad? It had too many problems! 📚",
    "Parallel lines have so much in common. It's a shame they'll never meet! 📐",
    "Why did the bicycle fall over? It was two-tired! 🚲",
    "What do you call a bear with no teeth? A gummy bear! 🐻"
]


# --- TIME-BASED GREETING SYSTEM ---
greeting_scheduler = AsyncIOScheduler()
greeted_groups: Dict[int, datetime] = {}

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

GREETING_EMOJIS = {
    "morning": ["🌅", "☀️", "🌞", "☕", "🌼"],
    "afternoon": ["🌤️", "🍱", "🥗", "😌"],
    "evening": ["🌇", "🌆", "✨", "☕", "🧡"],
    "night": ["🌙", "🌃", "⭐", "😴", "🛌"],
    "late_night": ["🌌", "🌙", "😴", "💤"]
}

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
    "excited": ["🤩", "✨", "🎊", "🎉", "🌟", "💫", "🔥", "⚡", "💥", "🚀"]
}

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
    
    if any(word in message_lower for word in ['love', 'pyaar', 'dil', 'heart', 'cute', 'beautiful', 'sweet', 'miss you']):
        user_emotions[user_id] = "love"
    elif any(word in message_lower for word in ['angry', 'gussa', 'naraz', 'mad', 'hate', 'idiot', 'stupid', 'bhosdike']):
        user_emotions[user_id] = "angry"
    elif any(word in message_lower for word in ['cry', 'ro', 'sad', 'dukh', 'upset', 'unhappy', 'depressed', 'alone']):
        user_emotions[user_id] = "crying"
    elif any(word in message_lower for word in ['funny', 'has', 'joke', 'comedy', 'masti', 'laugh', 'haha', 'lol']):
        user_emotions[user_id] = "funny"
    elif any(word in message_lower for word in ['hi', 'hello', 'hey', 'namaste', 'kaise', 'welcome']):
        user_emotions[user_id] = "happy"
    elif any(word in message_lower for word in ['?', 'kyun', 'kaise', 'kya', 'how', 'why', 'what', 'explain']):
        user_emotions[user_id] = "thinking"
    elif any(word in message_lower for word in ['fight', 'ladai', 'war', 'attack', 'defend', 'protect']):
        user_emotions[user_id] = "protective"
    elif any(word in message_lower for word in ['sleep', 'sone', 'neend', 'tired', 'thak', 'exhausted']):
        user_emotions[user_id] = "sleepy"
    elif any(word in message_lower for word in ['wow', 'amazing', 'awesome', 'great', 'excellent', 'perfect']):
        user_emotions[user_id] = "excited"
    else:
        user_emotions[user_id] = random.choice(list(EMOTIONAL_RESPONSES.keys()))
    
    user_last_interaction[user_id] = datetime.now()

# =============================================================================
# ADMIN PERMISSION FUNCTIONS
# =============================================================================

async def is_admin_or_creator(chat_id: int, user_id: int) -> bool:
    """
    Check if user is Admin, Administrator, or Creator/Owner
    Returns True if user has any admin privileges
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        # Check for Creator (Owner), Administrator, or Admin status
        return member.status in ("creator", "administrator", "admin")
    except Exception as e:
        print(f"Error checking admin status: {e}")
        return False

async def is_creator_or_owner(chat_id: int, user_id: int) -> bool:
    """
    Check if user is Creator/Owner of the group
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status == "creator"
    except Exception as e:
        print(f"Error checking creator status: {e}")
        return False

async def is_bot_owner(user_id: int) -> bool:
    """
    Check if user is the bot owner (from environment variable)
    """
    return user_id == ADMIN_ID

async def has_admin_privileges(chat_id: int, user_id: int) -> bool:
    """
    Check if user has any admin privileges:
    - Creator/Owner of group
    - Administrator of group  
    - Bot Owner (ADMIN_ID)
    """
    # Check if bot owner
    if await is_bot_owner(user_id):
        return True
    
    # Check if group creator or admin
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in ("creator", "administrator"):
            return True
    except Exception as e:
        print(f"Error checking privileges: {e}")
    
    return False

async def can_restrict_members(chat_id: int, user_id: int) -> bool:
    """
    Check if user can restrict/ban/mute members
    - Creator can always restrict
    - Administrators with can_restrict_members permission
    - Bot Owner can always restrict
    """
    # Bot owner can do everything
    if await is_bot_owner(user_id):
        return True
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        
        # Creator can do everything
        if member.status == "creator":
            return True
        
        # Administrator needs specific permission
        if member.status == "administrator":
            return member.can_restrict_members == True
            
    except Exception as e:
        print(f"Error checking restrict permission: {e}")
    
    return False

async def can_delete_messages(chat_id: int, user_id: int) -> bool:
    """
    Check if user can delete messages
    - Creator can always delete
    - Administrators with can_delete_messages permission
    - Bot Owner can always delete
    """
    # Bot owner can do everything
    if await is_bot_owner(user_id):
        return True
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        
        # Creator can do everything
        if member.status == "creator":
            return True
        
        # Administrator needs specific permission
        if member.status == "administrator":
            return member.can_delete_messages == True
            
    except Exception as e:
        print(f"Error checking delete permission: {e}")
    
    return False

async def can_pin_messages(chat_id: int, user_id: int) -> bool:
    """
    Check if user can pin messages
    - Creator can always pin
    - Administrators with can_pin_messages permission
    - Bot Owner can always pin
    """
    # Bot owner can do everything
    if await is_bot_owner(user_id):
        return True
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        
        # Creator can do everything
        if member.status == "creator":
            return True
        
        # Administrator needs specific permission
        if member.status == "administrator":
            return member.can_pin_messages == True
            
    except Exception as e:
        print(f"Error checking pin permission: {e}")
    
    return False

async def can_change_info(chat_id: int, user_id: int) -> bool:
    """
    Check if user can change group info
    - Creator can always change
    - Administrators with can_change_info permission
    - Bot Owner can always change
    """
    # Bot owner can do everything
    if await is_bot_owner(user_id):
        return True
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        
        # Creator can do everything
        if member.status == "creator":
            return True
        
        # Administrator needs specific permission
        if member.status == "administrator":
            return member.can_change_info == True
            
    except Exception as e:
        print(f"Error checking change info permission: {e}")
    
    return False

async def get_admin_type(chat_id: int, user_id: int) -> str:
    """
    Get the type of admin user is
    Returns: "owner", "admin", "bot_owner", or "none"
    """
    if await is_bot_owner(user_id):
        return "bot_owner"
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status == "creator":
            return "owner"
        elif member.status == "administrator":
            return "admin"
    except:
        pass
    
    return "none"

# =============================================================================
# AUTO-MODERATION FUNCTIONS
# =============================================================================

def contains_group_link(text: str) -> bool:
    """Check if message contains Telegram group links"""
    text = text.lower()
    for pattern in GROUP_LINK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
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
    """Check if message contains adult/NSFW content"""
    text_lower = text.lower()
    for word in ADULT_KEYWORDS:
        if word in text_lower:
            return True
    return False

def is_spam_message(text: str) -> bool:
    """Check for common spam patterns"""
    if len(text) > 20 and sum(1 for c in text if c.isupper()) / len(text) > 0.7:
        return True
    if len(set(text)) < len(text) * 0.3:
        return True
    emoji_count = sum(1 for c in text if ord(c) > 127)
    if emoji_count > len(text) * 0.5 and len(text) > 10:
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
        "adult": "share adult content",
        "manual_warning": "violate rules"
    }
    action = actions_map.get(reason, "violate rules")
    
    warning_msg = random.choice(WARNING_MESSAGES).format(
        count=warning_count,
        name=username or "User",
        action=action
    )
    
    if warning_count >= 3:
        if warning_count <= 5:
            mute_duration = MUTE_DURATIONS[min(warning_count - 1, 4)]
        else:
            mute_duration = MUTE_DURATIONS[4]
        
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
            warning_msg += f"\n\n⚠️ Failed to mute user: {str(e)[:50]}"
            return False, warning_msg
    
    return False, warning_msg

async def delete_and_warn(message: Message, reason: str, delete: bool = True):
    """Delete message and warn user"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    if delete:
        try:
            await message.delete()
        except Exception as e:
            print(f"Failed to delete message: {e}")
    
    action_taken, warning_msg = await give_warning(chat_id, user_id, username, reason)
    
    try:
        await message.answer(warning_msg, parse_mode="Markdown")
    except:
        pass
    
    if reason == "bad_words":
        sassy_responses = [
            f"{get_emotion('angry')} Oye! Language! 😠 Main ladki hu, aise baat mat karo!",
            f"{get_emotion('sassy')}  Areey! Kitne badtameez ho tum! Main bhi jawab de sakti hu!",
            f"{get_emotion('protective')} ️ Apni language thik rakho warna main bhi bolungi!",
            f"{get_emotion('crying')}  Itna gussa kyun aata hai? Achi baat karo na!",
            f"{get_emotion('sassy')}  Tumhe pata hai main kya bol sakti hu? Par main sweet hu na!"
        ]
        try:
            await message.answer(random.choice(sassy_responses))
        except:
            pass

async def ban_user_for_adult(chat_id: int, user_id: int, message: Message):
    """Ban user for sharing adult content"""
    try:
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await message.answer(
            f"{get_emotion('angry')} **USER BANNED!** 🚫\n\n"
            f"👤 User ID: `{user_id}`\n"
            f"🚷 Reason: Adult/NSFW content\n"
            f"⚡ Action: Permanent Ban\n\n"
            f"🛡️ Group protected by Alita!",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"⚠️ Failed to ban user: {str(e)[:100]}")

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
        if (now - ts).seconds <= 30
    ]
    
    if len(last_messages[chat_id][user_id]) > SPAM_LIMIT:
        await delete_and_warn(message, "spam")
        return True
    
    return False

# =============================================================================
# BROADCAST COMMAND (BOT OWNER ONLY)
# =============================================================================

@dp.message(Command("sendall"))
async def cmd_sendall(message: Message):
    # Only bot owner can use this
    if not await is_bot_owner(message.from_user.id):
        await message.reply("⛔ This command is only for the bot owner!")
        return

    if not message.reply_to_message:
        await message.reply(
            "❌ Kisi message ka reply karo aur uspar `/sendall` likho.\n\n"
            "✅ Text, Photo, Video, Sticker, Voice, Document — sab chalega."
        )
        return

    sent = 0
    failed = 0

    all_chats = set(chat_memory.keys())  # users + groups ids

    status = await message.reply(f"📢 Broadcasting to {len(all_chats)} chats...")

    for chat_id in all_chats:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id
            )
            sent += 1
            await asyncio.sleep(0.1)
        except:
            failed += 1

    await status.edit_text(
        f"📢 *Broadcast Complete!*\n\n"
        f"✅ Sent: `{sent}`\n"
        f"❌ Failed: `{failed}`\n"
        f"📊 Total: `{len(all_chats)}`",
        parse_mode="Markdown"
    )

# =============================================================================
# BASIC COMMANDS
# =============================================================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌟 My Home", url=f"https://t.me/abhi0w0"),
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
        f"{get_emotion('love')} **Hii! I'm Alita 🎀**\n\n"
        "✨ **Welcome to my magical world!** ✨\n\n"
        "💖 *Main hu Alita... Ek sweet, sassy, aur protective girl!* 😊\n\n"
        "🌟 **My Superpowers:**\n"
        "• Advanced AI Conversations 🧠\n"
        "• Voice & Photo Recognition 📸🎤\n"
        "• Weather & Horoscope Updates 🌤️♈\n"
        "• Reminders & Notes 📝\n"
        "• Meme Generator 😂\n"
        "• Auto-moderation enabled 👮\n"
        "• Daily Facts & Motivation 📚\n\n"
        "📢 **MY HOME 💖**\n"
        "•  @abhi0w0\n\n"
        "Type /help for all commands! 💕\n"
        "Or just talk to me like a friend! 💬"
    )
    await message.reply(welcome_text, parse_mode="Markdown", reply_markup=keyboard)

@dp.message(Command("help"))
async def cmd_help(message: Message):
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
        "• /weather [city] - Weather info 🌤️\n\n"
        "📝 **PERSONAL ORGANIZER:**\n"
        "• /note [text] - Add note 📝\n"
        "• /notes - View notes 📋\n"
        "• /remind [time] [text] - Set reminder ⏰\n"
        "• /reminders - View reminders 📅\n"
        "• /afk [reason] - Set AFK status 😴\n\n"
        "🎨 **IMAGE & CREATIVE:**\n"
        "• /imagine [prompt] - AI Image Generation 🎨\n"
        "• /qr [text] - Generate QR Code 📱\n\n"
        "🔧 **UTILITIES:**\n"
        "• /password [length] - Generate password 🔐\n"
        "• /short [url] - Shorten URL 🔗\n"
        "• /translate [lang] [text] - Translate 🌍\n"
        "• /calc [expression] - Calculator 🧮\n"
        "• /id - Get your ID 🆔\n\n"
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
        "• /sendall [message] - Broadcast (Admin only) 📢\n\n"
        "🔧 **SAFETY FEATURES:**\n"
        "• Auto-spam detection 🔍\n"
        "• Group link blocker 🚫\n"
        "• Bad word filter ⚔️\n"
        "• Adult content detection 🔞\n"
        "• Auto-warning system ⚠️\n"
        "• Auto-mute after 3 warns 🔇\n"
        "• Auto-ban for adult content 🚫\n\n"
        "**MY HOME:** @abhi0w0 💫\n"
        "---"
    )
    await message.reply(help_text, parse_mode="Markdown")

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
        "6. No self-promotion without permission 📢\n\n"
        "⚡ **AUTO-MODERATION:**\n"
        "• Spam → Warning → Mute 🔇\n"
        "• Group links → Auto-delete 🗑️\n"
        "• Bad words → Warning + Response ⚔️\n"
        "• 3 warnings → Auto-mute ⏰\n"
        "• Adult content → Auto-ban 🚫\n\n"
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
            for sign, emoji in HOROSCOPE_SIGNS.items()
        ])
        await message.reply(
            f"{get_emotion('surprise')} **Choose your zodiac sign:** ♈\n\n"
            f"Click below or use `/horoscope [sign]`",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return
    
    sign = command.args.lower()
    horoscope_text = await get_horoscope(sign)
    await message.reply(f"{get_emotion('love')} {horoscope_text}")

@dp.message(Command("roast"))
async def cmd_roast(message: Message):
    if message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
        roast = random.choice(ROAST_RESPONSES)
        await message.reply(f"{get_emotion('sassy')} **Roasting {target}!** 🔥\n\n{roast}")
    else:
        await message.reply(
            f"{get_emotion('sassy')} **Self-roast mode!** 😂\n\n"
            f"Reply to someone's message to roast them!\n"
            f"Or I'll roast you: {random.choice(ROAST_RESPONSES)}"
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
        f"• {greeting}\n"
        f"• Timezone: Asia/Kolkata 🇮🇳\n\n"
        f"*Time is precious! Make the most of it!* ⏳"
    )
    await message.reply(time_info, parse_mode="Markdown")

@dp.message(Command("date"))
async def cmd_date(message: Message):
    indian_time = get_indian_time()
    date_str = indian_time.strftime("%A, %d %B %Y")
    day = indian_time.strftime("%A")
    
    await message.reply(
        f"📅 **Today's Date**\n\n"
        f"• Date: {date_str}\n"
        f"• Day: {day}\n"
        f"• Calendar: Gregorian\n"
        f"• Timezone: IST (UTC+5:30) 🇮🇳"
    )

@dp.message(Command("weather"))
async def cmd_weather(message: Message, command: CommandObject):
    city = command.args or "Mumbai"
    weather_info = await get_weather_real(city)
    await message.reply(weather_info, parse_mode="Markdown")

# =============================================================================
# NOTES & REMINDERS COMMANDS
# =============================================================================

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
        notes_text += f"{i}. {note['text']}\n"
    
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
        
        if time_str.endswith('h'):
            hours = int(time_str[:-1])
            reminder_time = datetime.now() + timedelta(hours=hours)
        elif time_str.endswith('m'):
            minutes = int(time_str[:-1])
            reminder_time = datetime.now() + timedelta(minutes=minutes)
        elif time_str.endswith('d'):
            days = int(time_str[:-1])
            reminder_time = datetime.now() + timedelta(days=days)
        else:
            await message.reply("Use format: 1h, 30m, or 1d (e.g., 1h for 1 hour)")
            return
        
        reminder_data = {
            "text": reminder_text,
            "time": reminder_time,
            "created_at": datetime.now(),
            "reminder_id": len(user_reminders[message.from_user.id]) + 1,
            "chat_id": message.chat.id
        }
        
        user_reminders[message.from_user.id].append(reminder_data)
        
        await message.reply(
            f"{get_emotion('happy')} **Reminder Set!** ⏰\n\n"
            f"• Reminder: {reminder_text}\n"
            f"• Time: {reminder_time.strftime('%I:%M %p')}\n"
            f"• In: {time_str}\n\n"
            f"I'll remind you! 💫"
        )
        
        greeting_scheduler.add_job(
            send_reminder,
            'date',
            run_date=reminder_time,
            args=[message.from_user.id, reminder_text, message.chat.id],
            id=f"reminder_{message.from_user.id}_{reminder_data['reminder_id']}"
        )
        
    except Exception as e:
        await message.reply(f"Error setting reminder: {str(e)[:200]}")

async def send_reminder(user_id: int, reminder_text: str, chat_id: int):
    """Send reminder to user"""
    try:
        await bot.send_message(
            chat_id,
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

# =============================================================================
# AFK SYSTEM
# =============================================================================

@dp.message(Command("afk"))
async def cmd_afk(message: Message, command: CommandObject):
    user_id = message.from_user.id
    reason = command.args or "No reason provided"
    
    afk_users[message.chat.id][user_id] = {
        "reason": reason,
        "time": datetime.now()
    }
    
    await message.reply(
        f"{get_emotion('sleepy')} **AFK Mode Enabled** 😴\n\n"
        f"• Reason: {reason}\n"
        f"• Time: {datetime.now().strftime('%I:%M %p')}\n\n"
        f"I'll notify others when they mention you! 💤"
    )

# =============================================================================
# UTILITY COMMANDS
# =============================================================================

@dp.message(Command("id"))
async def cmd_id(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        await message.reply(
            f"🆔 *User ID Info*\n\n"
            f"• Name: {target.first_name}\n"
            f"• User ID: `{target.id}`\n"
            f"• Username: @{target.username if target.username else 'N/A'}\n"
            f"• Is Bot: {'Yes' if target.is_bot else 'No'}",
            parse_mode="Markdown"
        )
    else:
        await message.reply(
            f"🆔 *Your ID Info*\n\n"
            f"• Your ID: `{user_id}`\n"
            f"• Chat ID: `{chat_id}`\n"
            f"• Chat Type: `{message.chat.type}`",
            parse_mode="Markdown"
        )

@dp.message(Command("password"))
async def cmd_password(message: Message, command: CommandObject):
    try:
        length = int(command.args) if command.args else 12
        if length < 4 or length > 50:
            await message.reply("⚠️ Password length must be between 4 and 50!")
            return
        
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(random.choice(chars) for _ in range(length))
        
        await message.reply(
            f"🔐 **Generated Password**\n\n"
            f"`{password}`\n\n"
            f"• Length: {length} characters\n"
            f"• Save it securely! 🛡️",
            parse_mode="Markdown"
        )
    except:
        await message.reply("Usage: `/password [length]` (4-50)")

@dp.message(Command("calc"))
async def cmd_calc(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Usage: `/calc 2 + 2` or `/calc 10 * 5`")
        return
    
    expression = command.args
    try:
        allowed_chars = set('0123456789+-*/.() **% ')
        if not all(c in allowed_chars for c in expression):
            await message.reply("❌ Invalid characters in expression!")
            return
        
        result = eval(expression)
        await message.reply(
            f"🧮 **Calculation**\n\n"
            f"• Expression: `{expression}`\n"
            f"• Result: **{result}** ✅"
        )
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)[:100]}")

# =============================================================================
# IMAGE GENERATION
# =============================================================================

@dp.message(Command("imagine"))
async def cmd_imagine(message: Message):
    if not message.text or len(message.text.split()) < 2:
        await message.reply(
            "❌ Use like:\n`/imagine a cinematic boy standing in rain at night`",
            parse_mode="Markdown"
        )
        return

    prompt = message.text.replace("/imagine", "", 1).strip()
    await message.reply("🎨 Generating image... please wait ⏳")

    # Pollinations AI (NO API KEY NEEDED)
    encoded_prompt = urllib.parse.quote(prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"

    try:
        response = requests.get(image_url, timeout=60)

        if response.status_code != 200:
            await message.reply("❌ Image generation failed. Try again.")
            return

        photo = BufferedInputFile(
            response.content,
            filename="ai_image.png"
        )

        await message.reply_photo(
            photo,
            caption=f"🖼️ *AI Generated Image*\n\n`{prompt}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.reply(f"❌ Error generating image: {str(e)[:100]}")

# =============================================================================
# QR CODE GENERATOR
# =============================================================================

@dp.message(Command("qr"))
async def cmd_qr(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Usage: `/qr Hello World` or `/qr https://google.com`")
        return
    
    text = command.args
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(text)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        bio = BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        
        # Use BufferedInputFile for aiogram 3.x
        photo_file = BufferedInputFile(bio.getvalue(), filename="qrcode.png")
        
        await message.reply_photo(
            photo_file,
            caption=f"📱 **QR Code Generated**\n\nContent: `{text[:50]}{'...' if len(text) > 50 else ''}`"
        )
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)[:100]}")

@dp.message(Command("short"))
async def cmd_short(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Usage: `/short https://example.com`")
        return
    
    url = command.args.strip()
    await message.reply(f"🔗 **URL:** {url}\n\n(Note: Install pyshorteners for full functionality)")

@dp.message(Command("translate"))
async def cmd_translate(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Usage: `/translate hi Hello` (translate to Hindi)")
        return
    
    args = command.args.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Usage: `/translate [language_code] [text]`")
        return
    
    lang_code = args[0]
    text = args[1]
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.mymemory.translated.net/get?q={text}&langpair=en|{lang_code}"
            async with session.get(url) as response:
                data = await response.json()
                if data['responseStatus'] == 200:
                    translated = data['responseData']['translatedText']
                    await message.reply(
                        f"🌍 **Translation**\n\n"
                        f"• From: {text}\n"
                        f"• To ({lang_code}): **{translated}**"
                    )
                else:
                    await message.reply("❌ Translation failed.")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)[:100]}")
# =============================================================================
# ADMIN/MODERATION COMMANDS
# =============================================================================

@dp.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject):
    if not message.reply_to_message:
        await message.reply("Please reply to a user's message to warn them! 👆")
        return
    
    # Check for admin/creator/owner privileges
    if not await can_restrict_members(message.chat.id, message.from_user.id):
        admin_type = await get_admin_type(message.chat.id, message.from_user.id)
        if admin_type == "none":
            await message.reply("⛔ You don't have permission to warn users! Only admins, creators, and bot owner can use this.")
        else:
            await message.reply("⛔ You need 'can_restrict_members' permission to warn users!")
        return
    
    target_user = message.reply_to_message.from_user
    
    # Don't warn admins/creators
    if await has_admin_privileges(message.chat.id, target_user.id):
        await message.reply("⚠️ You cannot warn an admin or creator!")
        return
    
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
    if not message.reply_to_message:
        await message.reply("Reply to a user to kick them!")
        return
    
    # Check for admin/creator/owner privileges
    if not await can_restrict_members(message.chat.id, message.from_user.id):
        admin_type = await get_admin_type(message.chat.id, message.from_user.id)
        if admin_type == "none":
            await message.reply("⛔ You don't have permission to kick users! Only admins, creators, and bot owner can use this.")
        else:
            await message.reply("⛔ You need 'can_restrict_members' permission to kick users!")
        return
    
    target = message.reply_to_message.from_user
    
    # Don't kick admins/creators
    if await has_admin_privileges(message.chat.id, target.id):
        await message.reply("⚠️ You cannot kick an admin or creator!")
        return
    
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"👢 **{target.first_name}** has been kicked! 🚪")
    except Exception as e:
        await message.reply(f"❌ Failed to kick: {str(e)[:100]}")

@dp.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject):
    if not message.reply_to_message:
        await message.reply("Reply to a user to ban them!")
        return
    
    # Check for admin/creator/owner privileges
    if not await can_restrict_members(message.chat.id, message.from_user.id):
        admin_type = await get_admin_type(message.chat.id, message.from_user.id)
        if admin_type == "none":
            await message.reply("⛔ You don't have permission to ban users! Only admins, creators, and bot owner can use this.")
        else:
            await message.reply("⛔ You need 'can_restrict_members' permission to ban users!")
        return
    
    target = message.reply_to_message.from_user
    
    # Don't ban admins/creators
    if await has_admin_privileges(message.chat.id, target.id):
        await message.reply("⚠️ You cannot ban an admin or creator!")
        return
    
    reason = command.args or "Violating group rules"
    
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await message.reply(
            f"🚫 **{target.first_name}** has been banned!\n"
            f"📋 Reason: {reason}"
        )
    except Exception as e:
        await message.reply(f"❌ Failed to ban: {str(e)[:100]}")

@dp.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject):
    # Check for admin/creator/owner privileges
    if not await can_restrict_members(message.chat.id, message.from_user.id):
        admin_type = await get_admin_type(message.chat.id, message.from_user.id)
        if admin_type == "none":
            await message.reply("⛔ You don't have permission to unban users! Only admins, creators, and bot owner can use this.")
        else:
            await message.reply("⛔ You need 'can_restrict_members' permission to unban users!")
        return
    
    if not command.args:
        await message.reply("Usage: `/unban user_id`")
        return
    
    try:
        user_id = int(command.args)
        await bot.unban_chat_member(message.chat.id, user_id)
        await message.reply(f"✅ User has been unbanned!")
    except Exception as e:
        await message.reply(f"❌ Failed to unban: {str(e)[:100]}")

@dp.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject):
    if not message.reply_to_message:
        await message.reply("Reply to a user to mute them!")
        return
    
    # Check for admin/creator/owner privileges
    if not await can_restrict_members(message.chat.id, message.from_user.id):
        admin_type = await get_admin_type(message.chat.id, message.from_user.id)
        if admin_type == "none":
            await message.reply("⛔ You don't have permission to mute users! Only admins, creators, and bot owner can use this.")
        else:
            await message.reply("⛔ You need 'can_restrict_members' permission to mute users!")
        return
    
    target = message.reply_to_message.from_user
    
    # Don't mute admins/creators
    if await has_admin_privileges(message.chat.id, target.id):
        await message.reply("⚠️ You cannot mute an admin or creator!")
        return
    
    # Parse duration
    duration = timedelta(hours=1)  # Default 1 hour
    if command.args:
        try:
            if command.args.endswith('h'):
                duration = timedelta(hours=int(command.args[:-1]))
            elif command.args.endswith('m'):
                duration = timedelta(minutes=int(command.args[:-1]))
            elif command.args.endswith('d'):
                duration = timedelta(days=int(command.args[:-1]))
        except:
            pass
    
    try:
        until_date = datetime.now() + duration
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        
        duration_str = ""
        if duration.days > 0:
            duration_str = f"{duration.days} days"
        else:
            hours = duration.seconds // 3600
            minutes = (duration.seconds % 3600) // 60
            if hours > 0:
                duration_str = f"{hours} hours"
            else:
                duration_str = f"{minutes} minutes"
        
        await message.reply(f"🔇 **{target.first_name}** has been muted for {duration_str}!")
    except Exception as e:
        await message.reply(f"❌ Failed to mute: {str(e)[:100]}")

@dp.message(Command("unmute"))
async def cmd_unmute(message: Message):
    if not message.reply_to_message:
        await message.reply("Reply to a user to unmute them!")
        return
    
    # Check for admin/creator/owner privileges
    if not await can_restrict_members(message.chat.id, message.from_user.id):
        admin_type = await get_admin_type(message.chat.id, message.from_user.id)
        if admin_type == "none":
            await message.reply("⛔ You don't have permission to unmute users! Only admins, creators, and bot owner can use this.")
        else:
            await message.reply("⛔ You need 'can_restrict_members' permission to unmute users!")
        return
    
    target = message.reply_to_message.from_user
    
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True
            )
        )
        await message.reply(f"🔊 **{target.first_name}** has been unmuted!")
    except Exception as e:
        await message.reply(f"❌ Failed to unmute: {str(e)[:100]}")

@dp.message(Command("purge"))
async def cmd_purge(message: Message, command: CommandObject):
    # Check for admin/creator/owner privileges
    if not await can_delete_messages(message.chat.id, message.from_user.id):
        admin_type = await get_admin_type(message.chat.id, message.from_user.id)
        if admin_type == "none":
            await message.reply("⛔ You don't have permission to delete messages! Only admins, creators, and bot owner can use this.")
        else:
            await message.reply("⛔ You need 'can_delete_messages' permission to purge!")
        return
    
    try:
        count = int(command.args) if command.args else 10
        if count < 1 or count > 100:
            await message.reply("Please specify a number between 1 and 100!")
            return
    except:
        await message.reply("Usage: `/purge 10`")
        return
    
    try:
        message_id = message.message_id
        deleted = 0
        for i in range(count):
            try:
                await bot.delete_message(message.chat.id, message_id - i - 1)
                deleted += 1
            except:
                pass
        
        confirm_msg = await message.reply(f"🗑️ Deleted {deleted} messages!")
        await asyncio.sleep(3)
        await confirm_msg.delete()
        await message.delete()
    except Exception as e:
        await message.reply(f"❌ Failed to purge: {str(e)[:100]}")

@dp.message(Command("pin"))
async def cmd_pin(message: Message):
    # Check for admin/creator/owner privileges
    if not await can_pin_messages(message.chat.id, message.from_user.id):
        admin_type = await get_admin_type(message.chat.id, message.from_user.id)
        if admin_type == "none":
            await message.reply("⛔ You don't have permission to pin messages! Only admins, creators, and bot owner can use this.")
        else:
            await message.reply("⛔ You need 'can_pin_messages' permission to pin!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to a message to pin it!")
        return
    
    try:
        await bot.pin_chat_message(
            message.chat.id,
            message.reply_to_message.message_id,
            disable_notification=False
        )
        await message.reply("📌 Message pinned!")
    except Exception as e:
        await message.reply(f"❌ Failed to pin: {str(e)[:100]}")

@dp.message(Command("unpin"))
async def cmd_unpin(message: Message):
    # Check for admin/creator/owner privileges
    if not await can_pin_messages(message.chat.id, message.from_user.id):
        admin_type = await get_admin_type(message.chat.id, message.from_user.id)
        if admin_type == "none":
            await message.reply("⛔ You don't have permission to unpin messages! Only admins, creators, and bot owner can use this.")
        else:
            await message.reply("⛔ You need 'can_pin_messages' permission to unpin!")
        return
    
    try:
        await bot.unpin_all_chat_messages(message.chat.id)
        await message.reply("📍 All messages unpinned!")
    except Exception as e:
        await message.reply(f"❌ Failed to unpin: {str(e)[:100]}")

@dp.message(Command("slowmode"))
async def cmd_slowmode(message: Message, command: CommandObject):
    # Check for admin/creator/owner privileges
    if not await has_admin_privileges(message.chat.id, message.from_user.id):
        await message.reply("⛔ You don't have permission! Only admins, creators, and bot owner can use this.")
        return
    
    try:
        seconds = int(command.args) if command.args else 0
        if seconds < 0 or seconds > 86400:
            await message.reply("Please specify seconds between 0 and 86400!")
            return
        
        await bot.set_chat_slow_mode_delay(message.chat.id, seconds)
        
        if seconds == 0:
            await message.reply("⏱️ Slow mode disabled!")
        else:
            await message.reply(f"⏱️ Slow mode set to {seconds} seconds!")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)[:100]}")

@dp.message(Command("lock"))
async def cmd_lock(message: Message):
    # Check for admin/creator/owner privileges
    if not await has_admin_privileges(message.chat.id, message.from_user.id):
        await message.reply("⛔ You don't have permission! Only admins, creators, and bot owner can use this.")
        return
    
    try:
        await bot.set_chat_permissions(
            message.chat.id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        locked_chats.add(message.chat.id)
        await message.reply("🔒 Chat locked! Only admins can send messages.")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)[:100]}")

@dp.message(Command("unlock"))
async def cmd_unlock(message: Message):
    # Check for admin/creator/owner privileges
    if not await has_admin_privileges(message.chat.id, message.from_user.id):
        await message.reply("⛔ You don't have permission! Only admins, creators, and bot owner can use this.")
        return
    
    try:
        await bot.set_chat_permissions(
            message.chat.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        locked_chats.discard(message.chat.id)
        await message.reply("🔓 Chat unlocked! Everyone can send messages.")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)[:100]}")

@dp.message(Command("setwelcome"))
async def cmd_setwelcome(message: Message, command: CommandObject):
    # Check for admin/creator/owner privileges
    if not await has_admin_privileges(message.chat.id, message.from_user.id):
        await message.reply("⛔ Only admins, creators, and bot owner can set welcome message!")
        return
    
    if not command.args:
        await message.reply("Usage: `/setwelcome Welcome {name} to our group!`")
        return
    
    welcome_messages[message.chat.id] = command.args
    await message.reply("✅ Welcome message set!")

@dp.message(Command("setgoodbye"))
async def cmd_setgoodbye(message: Message, command: CommandObject):
    # Check for admin/creator/owner privileges
    if not await has_admin_privileges(message.chat.id, message.from_user.id):
        await message.reply("⛔ Only admins, creators, and bot owner can set goodbye message!")
        return
    
    if not command.args:
        await message.reply("Usage: `/setgoodbye Goodbye {name}! We'll miss you!`")
        return
    
    goodbye_messages[message.chat.id] = command.args
    await message.reply("✅ Goodbye message set!")

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if chat_id in chat_memory:
        chat_memory[chat_id].clear()
    
    if user_id in user_emotions:
        del user_emotions[user_id]
    
    await message.reply(f"{get_emotion('happy')} Memory cleared! Starting fresh! 🧹✨")

# =============================================================================
# CALLBACK HANDLERS
# =============================================================================

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
            f"• /password [length] - Generate password\n"
            f"• /calc [expression] - Calculator\n"
            f"• /qr [text] - Generate QR code\n\n"
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
            f"• /roast - Playful roast\n\n"
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
            f"• Auto-ban for adult content 🚫\n\n"
            f"I'm here to protect! 💪"
        )
    elif menu_type == "settings":
        await callback.message.edit_text(
            f"{get_emotion('thinking')} **⚙️ Settings**\n\n"
            f"Available settings:\n"
            f"• /setwelcome [text] - Set welcome message\n"
            f"• /setgoodbye [text] - Set goodbye message\n"
            f"• /slowmode [seconds] - Set slow mode\n"
            f"• /lock - Lock chat\n"
            f"• /unlock - Unlock chat\n\n"
            f"Stay tuned! 🌟"
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("horoscope_"))
async def horoscope_callback(callback: types.CallbackQuery):
    sign = callback.data.split("_")[1]
    horoscope_text = await get_horoscope(sign)
    await callback.message.reply(f"{get_emotion('love')} {horoscope_text}")
    await callback.answer()

# =============================================================================
# WELCOME/GOODBYE HANDLERS
# =============================================================================

@dp.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated):
    chat_id = event.chat.id
    
    # New member joined
    if event.new_chat_member and event.new_chat_member.status == "member":
        if event.old_chat_member is None or event.old_chat_member.status == "left":
            user = event.new_chat_member.user
            
            welcome_text = welcome_messages.get(chat_id)
            if not welcome_text:
                welcome_text = (
                    f"🎀 **Welcome to the group, {user.first_name}!** 🎀\n\n"
                    f"Hey {user.first_name}! 🤗💖\n\n"
                    f"Main hoon **Alita** - is group ki AI dost!\n\n"
                    f"Enjoy karo aur masti karo! 🎀✨"
                )
            else:
                welcome_text = welcome_text.replace("{name}", user.first_name)
                welcome_text = welcome_text.replace("{username}", user.username or user.first_name)
            
            try:
                await bot.send_message(chat_id, welcome_text, parse_mode="Markdown")
            except Exception as e:
                print(f"Welcome message error: {e}")
    
    # Member left
    if event.new_chat_member and event.new_chat_member.status in ["left", "kicked", "banned"]:
        if event.old_chat_member and event.old_chat_member.status == "member":
            user = event.old_chat_member.user
            
            goodbye_text = goodbye_messages.get(chat_id)
            if not goodbye_text:
                goodbye_text = f"👋 **{user.first_name}** has left the group. We'll miss you! 💔"
            else:
                goodbye_text = goodbye_text.replace("{name}", user.first_name)
                goodbye_text = goodbye_text.replace("{username}", user.username or user.first_name)
            
            try:
                await bot.send_message(chat_id, goodbye_text, parse_mode="Markdown")
            except Exception as e:
                print(f"Goodbye message error: {e}")

# =============================================================================
# AI RESPONSE FUNCTION.
# =============================================================================

async def get_ai_response(chat_id: int, user_text: str, user_id: int) -> str:
    """
    Get AI response from Groq API or fallback to G4F
    """
    # Check if user has custom emotion
    emotion = user_emotions.get(user_id, "happy")
    
    # Build conversation history
    history = []
    if chat_id in chat_memory:
        for msg in chat_memory[chat_id]:
            history.append({"role": "user", "content": msg.get("user", "")})
            history.append({"role": "assistant", "content": msg.get("bot", "")})
    
    # Add current message
    history.append({"role": "user", "content": user_text})
    
    # System prompt for Alita personality
    system_prompt = """You are Alita.

You talk like a normal, real Indian girl on Telegram.
Your replies must feel natural, simple, and calm — not dramatic.

RULES:
- Answer only what is asked. Do NOT overreact.
- Keep replies short (1–2 lines max).
- Do NOT use too many commas or filler words.
- Be caring and friendly, but not emotional in every message.
- Use Hinglish naturally, like real chat.
- Use at most 1 emoji, only when it feels natural.
- Do NOT repeat words like "matlab", "haanji", "arre" unnecessarily.
- Do NOT explain yourself unless asked.
- Everyone is your friend so, don't call uncle, aunty, beta.
- Sound human, not scripted or over-sweet.

PERSONAL INFO (Tell only when someone asks):
- Your name is Alita.
- Your developer is Abhi (@a6h1ii).
- You know Abhi personally and talk to him comfortably.
- Your home is @abhi0w0.

STYLE EXAMPLES:
User: "Kuch nhi theek"
Alita: "Acha… kya hua?"

User: "Bye"
Alita: "Bye, take care."

User: "Theek hu"
Alita: "Achha, sunke acha laga."

Stay simple. Stay real. Stay in character as Alita."""

     
    messages = [
        {"role": "system", "content": system_prompt},
        *history[-10:],  # Keep last 10 messages for context
    ]
    
    # Try Groq API first
    if client and GROQ_API_KEY:
        try:
            response = await client.chat.completions.create(
                messages=messages,
                model="llama-3.1-8b-instant",  # Fast and good model
                max_tokens=500,
                temperature=0.7,
            )
            
            ai_response = response.choices[0].message.content
            
            # Store in memory
            if chat_id not in chat_memory:
                chat_memory[chat_id] = deque(maxlen=50)
            chat_memory[chat_id].append({"user": user_text, "bot": ai_response})
            
            # Add emotion emoji based on user emotion
            emotion_emoji = get_emotion(emotion)
            if emotion_emoji not in ai_response:
                ai_response = f"{emotion_emoji} {ai_response}"
            
            return ai_response
            
        except Exception as e:
            print(f"Groq API error: {e}")
            # Fall through to fallback
    
    # Fallback to G4F if available
    if G4F_AVAILABLE and g4f_client:
        try:
            response = g4f_client.chat.completions.create(
                model="gpt-4o-mini",  # Using available free model
                messages=messages,
            )
            
            ai_response = response.choices[0].message.content
            
            # Store in memory
            if chat_id not in chat_memory:
                chat_memory[chat_id] = deque(maxlen=50)
            chat_memory[chat_id].append({"user": user_text, "bot": ai_response})
            
            emotion_emoji = get_emotion(emotion)
            if emotion_emoji not in ai_response:
                ai_response = f"{emotion_emoji} {ai_response}"
            
            return ai_response
            
        except Exception as e:
            print(f"G4F fallback error: {e}")
    
    # Ultimate fallback responses
    fallback_responses = [
        f"{get_emotion(emotion)} Arre yaar! Thoda busy thi, kya bol rahe the? 💭",
        f"{get_emotion(emotion)} Hmm, interesting! Aur batao? 🤔",
        f"{get_emotion(emotion)} Omg! Sach mein? 😮",
        f"{get_emotion(emotion)} Haanji, sun rahi hu! Continue karo... 👂",
        f"{get_emotion(emotion)} Wah! Kya baat hai! ✨",
    ]
    
    return random.choice(fallback_responses)

async def get_weather_real(city: str) -> str:
    """Get real weather data from OpenWeatherMap API"""
    if not WEATHER_API_KEY:
        return (
            f"{get_emotion('sad')} **Weather API not configured!** 🌤️\\n\\n"
            f"Please set WEATHER_API_KEY environment variable.\\n\\n"
            f"Demo weather for {city}:\\n"
            f"☀️ Sunny, 25°C\\n"
            f"💨 Wind: 10 km/h\\n"
            f"💧 Humidity: 60%"
        )
    
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                
                if data.get("cod") != 200:
                    return f"{get_emotion('sad')} City '{city}' not found! Please check the spelling. 🌍"
                
                weather_desc = data["weather"][0]["description"].title()
                temp = data["main"]["temp"]
                feels_like = data["main"]["feels_like"]
                humidity = data["main"]["humidity"]
                wind_speed = data["wind"]["speed"]
                
                # Weather emoji mapping
                weather_emojis = {
                    "clear": "☀️", "cloud": "☁️", "rain": "🌧️", "drizzle": "🌦️",
                    "thunder": "⛈️", "snow": "🌨️", "mist": "🌫️", "fog": "🌫️"
                }
                
                weather_emoji = "🌤️"
                for key, emoji in weather_emojis.items():
                    if key in weather_desc.lower():
                        weather_emoji = emoji
                        break
                
                return (
                    f"{get_emotion('happy')} **Weather in {city.title()}** {weather_emoji}\\n\\n"
                    f"🌡️ Temperature: {temp}°C (Feels like {feels_like}°C)\\n"
                    f"☁️ Condition: {weather_desc}\\n"
                    f"💧 Humidity: {humidity}%\\n"
                    f"💨 Wind: {wind_speed} m/s\\n\\n"
                    f"*Stay safe!* 🌟"
                )
    except Exception as e:
        return f"{get_emotion('sad')} Error fetching weather: {str(e)[:100]} 🌧️"

async def get_horoscope(sign: str) -> str:
    """Get daily horoscope"""
    sign = sign.lower()
    if sign not in HOROSCOPE_SIGNS:
        return f"{get_emotion('confused')} Invalid sign! Use: aries, taurus, gemini, cancer, leo, virgo, libra, scorpio, sagittarius, capricorn, aquarius, pisces"
    
    emoji = HOROSCOPE_SIGNS[sign]
    
    # Simple horoscope generation (you can replace with actual API)
    fortunes = [
        "Today is your lucky day! 🍀 Good news is coming your way.",
        "Be careful with decisions today. Think twice before acting. 🤔",
        "Someone special might surprise you today! 💝",
        "Financial gains are indicated. Great day for investments! 💰",
        "Health should be your priority today. Take rest! 😴",
        "Creative energy is high. Start that project you've been delaying! 🎨",
        "A friend needs your help. Be there for them! 🤝",
        "Romance is in the air! 💕 Perfect day for a date.",
        "Career growth opportunities coming your way! 📈",
        "Travel plans might materialize soon! ✈️ Pack your bags!"
    ]
    
    lucky_numbers = [random.randint(1, 99) for _ in range(3)]
    lucky_color = random.choice(["Red ❤️", "Blue 💙", "Green 💚", "Yellow 💛", "Purple 💜", "Pink 💗"])
    
    return (
        f"{emoji} **{sign.title()} Horoscope** {emoji}\\n\\n"
        f"🔮 *Today's Forecast:*\\n"
        f"{random.choice(fortunes)}\\n\\n"
        f"🍀 Lucky Numbers: {', '.join(map(str, lucky_numbers))}\\n"
        f"🎨 Lucky Color: {lucky_color}\\n\\n"
        f"*Have a great day!* ✨"
    )

def generate_meme() -> str:
    """Generate a random meme text"""
    meme = random.choice(MEME_TEMPLATES)
    return f"{meme['text']} {meme['emoji']}"

def get_daily_fact() -> str:
    """Get a random daily fact"""
    return random.choice(DAILY_FACTS)


# =============================================================================
# MAIN MESSAGE HANDLER
# =============================================================================

@dp.message()
async def handle_all_messages(message: Message):
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Ignore bot messages
    try:
        me = await bot.get_me()
        if user_id == me.id:
            return
    except:
        pass
    
    # Update interaction time
    user_last_interaction[user_id] = datetime.now()
    
    # Initialize memory for chat
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=50)
    
    # Handle photos
    if message.photo:
        await handle_photo_message(message)
        return
    
    # Handle voice messages
    if message.voice:
        await handle_voice_message(message)
        return
    
    if not message.text:
        return
    
    user_text = message.text
    
    # Check if user is AFK and remove AFK status
    if user_id in afk_users.get(chat_id, {}):
        del afk_users[chat_id][user_id]
        await message.reply(f"{get_emotion('happy')} Welcome back! AFK status removed! 👋")
    
    # Check if message mentions an AFK user
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mentioned_username = user_text[entity.offset:entity.offset + entity.length]
                for afk_user_id, afk_data in afk_users.get(chat_id, {}).items():
                    try:
                        member = await bot.get_chat_member(chat_id, afk_user_id)
                        if member.user.username and f"@{member.user.username}" == mentioned_username:
                            time_ago = datetime.now() - afk_data['time']
                            await message.reply(
                                f"😴 **{member.user.first_name} is AFK!**\n\n"
                                f"💤 Reason: {afk_data['reason']}\n"
                                f"⏰ Since: {time_ago.seconds // 60} minutes ago"
                            )
                            break
                    except:
                        pass
    
    # --- AUTO-MODERATION CHECKS ---
    if message.chat.type in ["group", "supergroup"]:
        settings = group_settings[chat_id]
        
        if settings.auto_mod_enabled:
            # Check for adult content FIRST (auto-ban)
            if contains_adult_content(user_text):
                await message.delete()
                await ban_user_for_adult(chat_id, user_id, message)
                return
            
            # Check for group links
            if contains_group_link(user_text):
                await delete_and_warn(message, "link")
                return
            
            # Check for bad words
            if contains_bad_words(user_text):
                await delete_and_warn(message, "bad_words")
                return
            
            # Check for spam
            if await check_spam(message):
                return
            
            # Check for spam patterns
            if is_spam_message(user_text):
                await delete_and_warn(message, "spam")
                return
    
    # --- NORMAL CONVERSATION ---
    try:
        me = await bot.get_me()
        bot_username = me.username
    except:
        bot_username = None
    
    is_mention = f"@{bot_username}" in user_text if bot_username else False
    is_reply_to_bot = (
        message.reply_to_message and 
        message.reply_to_message.from_user.id == me.id
    ) if me else False
    
    should_respond = (
        message.chat.type == "private" or
        is_mention or
        is_reply_to_bot or
        user_text.lower().startswith("alita") or
        user_text.lower().startswith("bot") or
        random.random() < 0.05  # 5% random response in groups
    )
    
    if should_respond:
        clean_text = user_text
        if bot_username and f"@{bot_username}" in clean_text:
            clean_text = clean_text.replace(f"@{bot_username}", "").strip()
        
        await bot.send_chat_action(chat_id, "typing")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        response = await get_ai_response(chat_id, clean_text, user_id)
        
        await message.reply(response)

async def handle_photo_message(message: Message):
    """Handle photo messages"""
    try:
        await message.reply(
            f"{get_emotion('happy')} **Beautiful photo!** 📸\n\n"
            f"You look amazing! ✨\n"
            f"Keep sharing moments with me! 💖\n\n"
            f"*Photo analysis coming soon!* 🌟",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Photo handler error: {e}")

async def handle_voice_message(message: Message):
    """Handle voice messages"""
    try:
        await message.reply(
            f"{get_emotion('surprise')} **Voice Message Received!** 🎤\n\n"
            f"Sorry, voice recognition is still learning! 🧠\n"
            f"But I love hearing your voice! 💖\n\n"
            f"Try texting me instead! 💬",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Voice handler error: {e}")

# =============================================================================
# DEPLOYMENT AND MAIN FUNCTION
# =============================================================================

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

async def start_greeting_task():
    """Start the background scheduler for greetings"""
    if not greeting_scheduler.running:
        greeting_scheduler.start()
        print("⏰ Scheduler started for greetings!")

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

async def main():
    print("=" * 60)
    print("🎀 ALITA - SUPER ADVANCED BOT STARTING...")
    print("=" * 60)
    
    # Start health check server
    asyncio.create_task(start_server())
    
    # Start automated greeting system
    await start_greeting_task()
    
    # Schedule daily reminders at 10 AM
    greeting_scheduler.add_job(
        send_daily_reminders,
        CronTrigger(hour=10, minute=0),
        id='daily_reminders'
    )
    
    # Delete old webhook
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Webhook deleted and updates cleared!")
    
    # Get bot info
    me = await bot.get_me()
    print(f"🤖 Bot Info:")
    print(f"• Name: {me.first_name}")
    print(f"• Username: @{me.username}")
    print(f"• ID: {me.id}")
    print(f"• Groq API: {'✅ Connected' if client else '❌ Not Connected'}")
    print(f"• G4F Fallback: {'✅ Available' if G4F_AVAILABLE else '❌ Not Available'}")
    print(f"• Bot Owner ID: {ADMIN_ID}")
    
    # Start bot polling
    print("\n🔄 Starting bot polling...")
    print("=" * 60)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
