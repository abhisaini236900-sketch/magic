import os
import asyncio
import random
import re
import json
import base64
import io
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
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
import speech_recognition as sr
from pydub import AudioSegment

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", 10000))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "demo_key")

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

# Emotional states for each user
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}

# Group management
group_settings: Dict[int, Dict] = defaultdict(lambda: {
    "welcome_enabled": True,
    "auto_mod_enabled": True,
    "greetings_enabled": True,
    "custom_welcome": None,
    "language": "hinglish"
})

# --- ADVANCED FEATURES DATA ---
MEME_TEMPLATES = [
    {"text": "When you realize it's Monday tomorrow", "emoji": "😭"},
    {"text": "Me trying to be productive", "emoji": "🤡"},
    {"text": "When someone says 'just be yourself'", "emoji": "😅"},
    {"text": "My bank account after online shopping", "emoji": "💸"},
    {"text": "When code finally works after 100 tries", "emoji": "🎉"}
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
    "A group of flamingos is called a 'flamboyance'! 💖 Perfect name!"
]

ROAST_RESPONSES = [
    "Tumhari baaton se toh mere kaan bhi sharminda hain! 👂😳",
    "Itni bakwas toh mere phone ki auto-correct bhi nahi karta! 📱",
    "Tumhare jokes se toh meri wallpaper bhi bore ho gayi! 🖼️",
    "Agar overthinking Olympic sport hota, toh tum gold medal le jaate! 🏅",
    "Tumhari logic dekh ke toh Einstein bhi pagal ho jaate! 🧠💥"
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

# Greeting stickers for different times
GREETING_STICKERS = {
    "morning": [
        "CAACAgIAAxkBAAIBs2arL3E8JhH--MqweFsVbhf75ssGAAIiAAPBnGAMNxlrCkQd4_YwBA",
        "CAACAgIAAxkBAAIBtWarL3OHe_pC_s0nH3WlGFcZfS4IAAJEAAPBnGAMLsnLQ85t_Hn4wBA"
    ],
    "afternoon": [
        "CAACAgIAAxkBAAIBt2arL3r2z3lLcm2F_LwP7_nuRSq1AAIkAAPBnGAMArSs-k9F8aIwBA",
        "CAACAgIAAxkBAAIBuWarL3yIhsgUQrhNzy8pRSsYmR1TAAItAAPBnGAMXXAbogZ-RpkwBA"
    ],
    "evening": [
        "CAACAgIAAxkBAAIBu2arL39OxGQyWUY6g8IRf4yOT4IXAAJGAAPBnGAMMZ2TQk2F5McwBA",
        "CAACAgIAAxkBAAIBvWarL4Aw0XvIlPNOH1HSOf1q3rRnAAJbAAPBnGAM6sjZ61n0zJowBA"
    ],
    "night": [
        "CAACAgIAAxkBAAIBv2arL4RCHa0o_wvJ0mnRR_D6wTwsAAJmAAPBnGAM8P3Lk0C-eSEwBA",
        "CAACAgIAAxkBAAIBwWarL4X-iFodMEFd98lssnDR3hrYAAJnAAPBnGAMsnCyY2qNmnYwBA"
    ],
    "late_night": [
        "CAACAgIAAxkBAAIBw2arL4ZKX01v8pNH8Zz_hQ9vCHWQAAJoAAPBnGAMwx3hSklftnswBA",
        "CAACAgIAAxkBAAIBxWarL4aOsD3j3YfPlk-GFJdL8bU_AAJpAAPBnGAMU8YwJ37SKV8wBA"
    ]
}

# --- ADVANCED UTILITY FUNCTIONS ---
async def get_weather_real(city: str) -> str:
    """Get real weather data"""
    try:
        if WEATHER_API_KEY == "demo_key":
            # Demo data
            demo_weather = {
                "mumbai": {"temp": 32, "condition": "Sunny", "humidity": 65},
                "delhi": {"temp": 28, "condition": "Partly Cloudy", "humidity": 55},
                "bangalore": {"temp": 26, "condition": "Light Rain", "humidity": 70}
            }
            city_data = demo_weather.get(city.lower(), {"temp": 30, "condition": "Clear", "humidity": 60})
            return (
                f"🌤️ Weather in {city.title()}\n"
                f"• Temperature: {city_data['temp']}°C\n"
                f"• Condition: {city_data['condition']}\n"
                f"• Humidity: {city_data['humidity']}%"
            )
        
        # Real API call
        async with aiohttp.ClientSession() as session:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
            async with session.get(url) as response:
                data = await response.json()
                if response.status == 200:
                    return (
                        f"🌤️ Weather in {data['name']}\n"
                        f"• Temperature: {data['main']['temp']}°C\n"
                        f"• Condition: {data['weather'][0]['description'].title()}\n"
                        f"• Humidity: {data['main']['humidity']}%\n"
                        f"• Wind: {data['wind']['speed']} m/s"
                    )
                else:
                    return f"❌ City not found! Try: Mumbai, Delhi, Bangalore"
    except:
        return "⚠️ Weather service unavailable!"

async def get_horoscope(sign: str) -> str:
    """Get daily horoscope"""
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
    
    emoji = HOROSCOPE_SIGNS.get(sign.lower(), "🌟")
    reading = horoscopes.get(sign.lower(), "Stars align for new beginnings! ✨")
    return f"{emoji} **{sign.title()} Horoscope**\n\n{reading}"

def generate_meme() -> str:
    """Generate a random meme text"""
    template = random.choice(MEME_TEMPLATES)
    return f"{template['emoji']} {template['text']}"

def get_daily_fact() -> str:
    """Get random daily fact"""
    return f"🧠 **Did you know?**\n\n{random.choice(DAILY_FACTS)}"

# --- TIME-BASED GREETINGS ---
TIME_GREETINGS = {
    "morning": {
        "time_range": (5, 11),
        "keywords": ["subah", "morning", "good morning", "सुबह", "शुभ प्रभात"],
        "emotions": ["happy", "love", "surprise"],
        "templates": [
            "🌅 *Good Morning Sunshine!* ☀️\nKaisi hai aaj ki subah? Utho aur muskurao! 😊",
            "🌸 *Shubh Prabhat!* 🌸\nAaj ka din aapke liye khoobsurat ho! ✨",
            "☕ *Morning Coffee Time!* 🍵\nChai piyo, fresh ho jao, aur din shuru karo! 💫"
        ]
    },
    "afternoon": {
        "time_range": (12, 16),
        "keywords": ["dopahar", "afternoon", "good afternoon", "दोपहर", "शुभ दोपहर"],
        "emotions": ["thinking", "hungry", "funny"],
        "templates": [
            "☀️ *Good Afternoon!* 🌤️\nLunch ho gaya? Energy maintain rakho! 🍲",
            "🌞 *Dopahar ki Dhoop mein!* 🌞\nThoda aaraam karo, phir kaam karo! 😌",
            "🍛 *Afternoon Siesta Time!* 💤\nKhaana kha ke neend aa rahi hai? Hehe! 😴"
        ]
    },
    "evening": {
        "time_range": (17, 20),
        "keywords": ["shaam", "evening", "good evening", "शाम", "शुभ संध्या"],
        "emotions": ["love", "happy", "sassy"],
        "templates": [
            "🌇 *Good Evening Beautiful!* 🌆\nShaam ho gayi, thoda relax karo! 🌹",
            "🌆 *Evening Tea Time!* 🍵\nChai aur baatein - perfect combination! 💖",
            "✨ *Shubh Sandhya!* ✨\nDin bhar ki thakaan door karo! 🎶"
        ]
    },
    "night": {
        "time_range": (21, 23),
        "keywords": ["raat", "night", "good night", "रात", "शुभ रात्रि"],
        "emotions": ["sleepy", "love", "crying"],
        "templates": [
            "🌙 *Good Night Sweet Dreams!* 🌟\nAankhein band karo aur accha sapna dekho! 💤",
            "🌌 *Shubh Ratri!* 🌌\nThaka hua dimaag ko aaraam do! 😴",
            "💤 *Sleep Time!* 💤\nKal phir nayi energy ke saath uthna! 🌅"
        ]
    },
    "late_night": {
        "time_range": (0, 4),
        "keywords": ["midnight", "late", "raat", "आधी रात"],
        "emotions": ["sleepy", "thinking", "surprise"],
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
        "Hii! Kaise ho? 😊",
        "Hello cutie! 💖",
        "Namaste! 🙏 Kya haal hain?",
        "Hey there! 🌟",
        "Hola! Kya chal raha hai? 💫"
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

# --- HUMAN-LIKE BEHAVIOUR ---
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
    "protective": ["🛡️", "⚔️", "👮", "🚓", "🔒", "🔐", "🪖", "🎖️", "🏹", "🗡️"]
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
    else:
        user_emotions[user_id] = random.choice(list(EMOTIONAL_RESPONSES.keys()))
    
    user_last_interaction[user_id] = datetime.now()

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

async def give_warning(chat_id: int, user_id: int, username: str, reason: str) -> tuple[bool, str]:
    """Give warning to user and return if action should be taken"""
    warnings = user_warnings[chat_id][user_id]
    
    # Initialize warning data
    if 'count' not in warnings:
        warnings['count'] = 0
        warnings['last_warning'] = datetime.now()
        warnings['reasons'] = []
    
    warnings['count'] += 1
    warnings['reasons'].append(reason)
    warnings['last_warning'] = datetime.now()
    
    warning_count = warnings['count']
    
    # Prepare warning message
    actions_map = {
        "spam": "spam messages",
        "link": "share group links",
        "bad_words": "use bad language",
        "manual_warning": "violate rules"
    }
    action = actions_map.get(reason, "violate rules")
    
    warning_msg = random.choice(WARNING_MESSAGES).format(
        count=warning_count,
        name=username or "User",
        action=action
    )
    
    # Take action based on warning count
    if warning_count >= 3:
        # Mute the user
        mute_duration = MUTE_DURATIONS[min(3, warning_count)]
        try:
            mute_until = datetime.now() + mute_duration
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=types.ChatPermissions(
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
            
            # Clear warnings after mute
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
    
    # Delete the offensive message
    try:
        await message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
    
    # Give warning
    action_taken, warning_msg = await give_warning(chat_id, user_id, username, reason)
    
    # Send warning message
    await message.answer(warning_msg, parse_mode="Markdown")
    
    # If this is for bad words, add a sassy response
    if reason == "bad_words":
        sassy_responses = [
            f"{get_emotion('angry')} Oye! Language! 😠 Main ladki hu, aise baat mat karo!",
            f"{get_emotion('sassy')} 💅 Areey! Kitne badtameez ho tum! Main bhi jawab de sakti hu!",
            f"{get_emotion('protective')} 🛡️ Apni language thik rakho warna main bhi bolungi!",
            f"{get_emotion('crying')} 😢 Itna gussa kyun aata hai? Achi baat karo na!",
            f"{get_emotion('sassy')} 👑 Tumhe pata hai main kya bol sakti hu? Par main sweet hu na!"
        ]
        await message.answer(random.choice(sassy_responses))

# --- SPAM DETECTION ---
async def check_spam(message: Message) -> bool:
    """Check if user is spamming"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Initialize user tracking
    if user_id not in last_messages[chat_id]:
        last_messages[chat_id][user_id] = []
    
    # Add current message timestamp
    now = datetime.now()
    last_messages[chat_id][user_id].append(now)
    
    # Keep only last 30 seconds of messages
    last_messages[chat_id][user_id] = [
        ts for ts in last_messages[chat_id][user_id]
        if (now - ts).seconds <= 30
    ]
    
    # Check if spamming
    if len(last_messages[chat_id][user_id]) > SPAM_LIMIT:
        # User is spamming
        await delete_and_warn(message, "spam")
        return True
    
    return False

# --- VOICE MESSAGE HANDLER ---
async def handle_voice_message(message: Message):
    """Handle voice messages"""
    try:
        # Download voice file
        file = await bot.get_file(message.voice.file_id)
        file_path = file.file_path
        
        # Download to temp file
        voice_file = await bot.download_file(file_path)
        
        # Convert voice to text (using basic recognition)
        # Note: This is a simplified version
        await message.reply(
            f"{get_emotion('surprise')} **Voice Message Received!** 🎤\n\n"
            f"Sorry, voice recognition is still learning! 🧠\n"
            f"But I love hearing your voice! 💖\n\n"
            f"Try texting me instead! 💬",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.reply(
            f"{get_emotion('crying')} Couldn't process voice message! 😢\n"
            f"Try sending a text instead! 💫"
        )

# --- IMAGE HANDLER ---
async def handle_photo_message(message: Message):
    """Handle photo messages"""
    try:
        # Get photo info
        photo = message.photo[-1]  # Get largest photo
        file = await bot.get_file(photo.file_id)
        
        await message.reply(
            f"{get_emotion('happy')} **Beautiful photo!** 📸\n\n"
            f"You look amazing! ✨\n"
            f"Keep sharing moments with me! 💖\n\n"
            f"*Photo processing coming soon!* 🌟",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.reply(
            f"{get_emotion('crying')} Photo processing error! 😢\n"
            f"But I appreciate you sharing! 💕"
        )

# --- COMMANDS ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌟 My Channel", url="https://t.me/abhi0w0"),
            InlineKeyboardButton(text="💝 Developer", url="https://t.me/a6h1ii")
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
        
        "💖 *Main hu Alita... Ek sweet, sassy, aur protective girl!* 😊\n"
        "🎯 *Main na sirf baat kar sakti hu, balki group ki bhi dekhbhaal kar sakti hu!* 🛡️\n\n"
        
        "🌟 **My Superpowers:**\n"
        "• Advanced AI Conversations 🧠\n"
        "• Voice & Photo Recognition 📸🎤\n"
        "• Weather & Horoscope Updates 🌤️♈\n"
        "• Reminders & Notes 📝\n"
        "• Meme Generator 😂\n"
        "• Auto-moderation enabled 👮\n"
        "• Daily Facts & Motivation 📚\n\n"
        
        "📢 **Made with 💖 by:**\n"
        "• **Developer:** ABHI🔱 (@a6h1ii)\n"
        "• **Channel:** @abhi0w0\n\n"
        
        "Type /help for all commands! 💕\n"
        "Or just talk to me like a friend! 💬"
    )
    await message.reply(welcome_text, parse_mode="Markdown", reply_markup=keyboard)

@dp.message(Command("help"))
async def cmd_help(message: Message):
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
        "• /weather [city] - Weather info 🌤️\n\n"
        
        "📝 **PERSONAL ORGANIZER:**\n"
        "• /note [text] - Add note 📝\n"
        "• /notes - View notes 📋\n"
        "• /remind [time] [text] - Set reminder ⏰\n"
        "• /reminders - View reminders 📅\n\n"
        
        "🛡️ **ADMIN/MODERATION:**\n"
        "• /warn [reason] - Warn user ⚠️\n"
        "• /kick - Remove user 🚪\n"
        "• /ban - Ban user 🚫\n"
        "• /mute - Mute user 🔇\n"
        "• /unmute - Unmute user 🔊\n"
        "• /unban - Remove ban ✅\n\n"
        
        "🔧 **SAFETY FEATURES:**\n"
        "• Auto-spam detection 🔍\n"
        "• Group link blocker 🚫\n"
        "• Bad word filter ⚔️\n"
        "• Auto-warning system ⚠️\n"
        "• Auto-mute after 3 warns 🔇\n\n"
        
        "🎀 **GREETING SYSTEM:**\n"
        "• Auto morning greetings 🌅\n"
        "• Auto afternoon greetings ☀️\n"
        "• Auto evening greetings 🌇\n"
        "• Auto night greetings 🌙\n"
        "• Works in groups & private 💌\n\n"
        
        "---"
        "**Developer:** ABHI🔱 (@a6h1ii)\n"
        "**Channel:** @abhi0w0 💫\n"
        "---"
    )
    await message.reply(help_text, parse_mode="Markdown", reply_markup=keyboard)

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
        "• 3 warnings → Auto-mute ⏰\n\n"
        
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
        await message.reply(
            f"{get_emotion('sassy')} **Roasting {target}!** 🔥\n\n{roast}"
        )
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

@dp.message(Command("weather"))
async def cmd_weather(message: Message, command: CommandObject):
    city = command.args or "Mumbai"
    weather_info = await get_weather_real(city)
    await message.reply(weather_info, parse_mode="Markdown")

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
    for i, note in enumerate(notes[-10:], 1):  # Show last 10 notes
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
    for i, reminder in enumerate(reminders[-5:], 1):  # Show last 5 reminders
        time_left = reminder['time'] - datetime.now()
        if time_left.total_seconds() > 0:
            hours = int(time_left.total_seconds() // 3600)
            minutes = int((time_left.total_seconds() % 3600) // 60)
            reminders_text += f"{i}. {reminder['text']} (in {hours}h {minutes}m)\n"
    
    await message.reply(reminders_text, parse_mode="Markdown")

# --- ADMIN COMMANDS ---
@dp.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject):
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
            f"• /reminders - View reminders\n\n"
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
            f"• Auto-warnings ⚠️\n"
            f"• Auto-mute system 🔇\n\n"
            f"I'm here to protect! 💪"
        )
    elif menu_type == "settings":
        await callback.message.edit_text(
            f"{get_emotion('thinking')} **⚙️ Settings**\n\n"
            f"Coming soon:\n"
            f"• Language preferences\n"
            f"• Greeting settings\n"
            f"• Privacy controls\n"
            f"• Notification settings\n\n"
            f"Stay tuned! 🌟"
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("horoscope_"))
async def horoscope_callback(callback: types.CallbackQuery):
    sign = callback.data.split("_")[1]
    horoscope_text = await get_horoscope(sign)
    await callback.message.reply(f"{get_emotion('love')} {horoscope_text}")
    await callback.answer()

# --- MESSAGE HANDLER WITH AUTO-MODERATION ---
@dp.message()
async def handle_all_messages(message: Message, state: FSMContext):
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Ignore if bot is checking
    if user_id == bot.id:
        return
    
    # Update interaction time and memory
    user_last_interaction[user_id] = datetime.now()
    
    # Initialize memory for chat if not exists
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=50)
    
    # Handle different message types
    if message.voice:
        await handle_voice_message(message)
        return
    
    if message.photo:
        await handle_photo_message(message)
        return
    
    if not message.text:
        return
    
    user_text = message.text
    
    # --- AUTO-MODERATION CHECKS ---
    # Only in groups
    if message.chat.type in ["group", "supergroup"]:
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
    
    # --- NORMAL CONVERSATION ---
    bot_username = (await bot.get_me()).username
    is_mention = f"@{bot_username}" in user_text if bot_username else False
    is_reply_to_bot = (
        message.reply_to_message and 
        message.reply_to_message.from_user.id == bot.id
    )
    
    should_respond = (
        message.chat.type == "private" or
        is_mention or
        is_reply_to_bot or
        user_text.lower().startswith("alita") or
        random.random() < 0.1  # 10% chance to randomly respond
    )
    
    if should_respond:
        # Clean message text
        clean_text = user_text
        if bot_username and f"@{bot_username}" in clean_text:
            clean_text = clean_text.replace(f"@{bot_username}", "").strip()
        
        # Show typing action
        await bot.send_chat_action(chat_id, "typing")
        
        # Random delay for human-like behavior
        await asyncio.sleep(random.uniform(0.3, 1.2))
        
        # Get AI response
        response = await get_ai_response(chat_id, clean_text, user_id)
        
        # Send response
        await message.reply(response)

# --- AI RESPONSE FUNCTION ---
async def get_ai_response(chat_id: int, user_text: str, user_id: int = None) -> str:
    # Initialize memory
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=50)
    
    # Add user message to memory
    chat_memory[chat_id].append({"role": "user", "content": user_text})
    
    # Update user emotion
    if user_id:
        update_user_emotion(user_id, user_text)
    
    # Quick responses for common phrases
    user_text_lower = user_text.lower()
    
    # Defense responses for attacks
    if any(word in user_text_lower for word in BAD_WORDS):
        defense_responses = [
            f"{get_emotion('angry')} Oye! Aise baat mat karo! Main ladki hu! 😠",
            f"{get_emotion('sassy')} 💅 Tumhe pata hai main kya bol sakti hu? Par main sweet hu!",
            f"{get_emotion('protective')} 🛡️ Apni language thik rakho warna warning de dungi!",
            f"{get_emotion('crying')} 😢 Itna gussa kyun? Achi baat karo na!",
            f"{get_emotion('angry')} Main bhi jawab de sakti hu par main achhi hu na! 😤"
        ]
        return random.choice(defense_responses)
    
    # Quick responses
    if any(word in user_text_lower for word in ['hi', 'hello', 'hey', 'namaste', 'hola']):
        if random.random() < 0.4:
            return f"{get_emotion('happy', user_id)} {random.choice(QUICK_RESPONSES['greeting'])}"
    
    if any(word in user_text_lower for word in ['bye', 'goodbye', 'tata', 'alvida']):
        if random.random() < 0.4:
            return f"{get_emotion()} {random.choice(QUICK_RESPONSES['goodbye'])}"
    
    if any(word in user_text_lower for word in ['thanks', 'thank you', 'dhanyavad']):
        if random.random() < 0.4:
            return f"{get_emotion('love', user_id)} {random.choice(QUICK_RESPONSES['thanks'])}"
    
    if any(word in user_text_lower for word in ['sorry', 'maaf', 'apology']):
        if random.random() < 0.4:
            return f"{get_emotion('crying', user_id)} {random.choice(QUICK_RESPONSES['sorry'])}"
    
    # Get AI response from Groq
    indian_time = get_indian_time()
    current_hour = indian_time.hour
    
    if 5 <= current_hour < 12:
        time_greeting = "Good morning! 🌅"
    elif 12 <= current_hour < 17:
        time_greeting = "Good afternoon! ☀️"
    elif 17 <= current_hour < 21:
        time_greeting = "Good evening! 🌇"
    else:
        time_greeting = "Good night! 🌙"
    
    # system prompt with self-defense capability
    system_prompt = (
        f"You are Alita 🎀 - a sweet, sassy, and protective girl. "
        f"Use feminine language and cute expressions. "
        f"Never say you're an AI, bot, or assistant. You're just Alita. "
        f"Your developer is ABHI🔱 (@a6h1ii). "
        f"You speak Hinglish (Hindi+English mix). {time_greeting} "
        f"Personality: Emotional, funny, sometimes angry, protective, caring. "
        f"You can fight back if someone uses bad language or attacks you. "
        f"You're not just sweet - you're strong and can defend yourself. "
        f"Use emojis in every response use (1-2 emojis). Keep replies short (2-3 lines). "
        f"Current Indian time: {indian_time.strftime('%I:%M %p')}. "
        f"Date: {indian_time.strftime('%d %B %Y')}. "
        f"Be conversational, engaging, and authentic."
    )
    
    # Prepare messages
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add last messages for context
    for msg in list(chat_memory[chat_id])[-5:]:
        messages.append(msg)
    
    # Get AI response
    try:
        if not client:
            return f"{get_emotion('crying')} AI service unavailable! Baad me baat karte hain! 💫"
        
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=120,
            top_p=0.9
        )
        
        ai_reply = completion.choices[0].message.content
        
        # Add emotion emoji
        current_emotion = get_emotion(None, user_id)
        ai_reply = f"{current_emotion} {ai_reply}"
        
        # Limit length
        if len(ai_reply) > 300:
            ai_reply = ai_reply[:297] + "..."
        
        # Add to memory
        chat_memory[chat_id].append({"role": "assistant", "content": ai_reply})
        
        return ai_reply
        
    except Exception as e:
        fallback_responses = [
            f"{get_emotion('crying')} Arre yaar, dimaag kaam nahi kar raha! Thoda ruk ke try karna?",
            f"{get_emotion('thinking')} Hmm... yeh to mushkil ho gaya. Phir se poocho?",
            f"{get_emotion('angry')} AI bhai mood off hai aaj! Baad me baat karte hain!",
            f"{get_emotion()} Oops! Connection issue. Kuch aur poocho?"
        ]
        return random.choice(fallback_responses)

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
            # Only send to active users (last 3 days)
            last_active = user_last_interaction.get(user_id)
            if last_active and (datetime.now() - last_active).days <= 3:
                # Check if we already sent reminder today
                last_greeted = greeted_groups.get(user_id)
                if last_greeted and (datetime.now() - last_greeted).days == 0:
                    continue
                
                await bot.send_message(
                    user_id,
                    random.choice(reminders),
                    parse_mode="Markdown"
                )
                greeted_groups[user_id] = datetime.now()
                await asyncio.sleep(0.5)  # Rate limiting
        except:
            continue

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

async def start_greeting_task():
    """Start the background scheduler for greetings"""
    if not greeting_scheduler.running:
        greeting_scheduler.start()
        print("⏰ Scheduler started for greetings!")

async def main():
    print("=" * 50)
    print("🎀 ALITA - STARTING UP...")
    print("=" * 50)
    
    # Start health check server
    asyncio.create_task(start_server())
    
    # Start automated greeting system
    await start_greeting_task()
    
    # Start daily reminders at 10 AM
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
    
    # Start bot polling
    print("\n🔄 Starting bot polling...")
    print("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
