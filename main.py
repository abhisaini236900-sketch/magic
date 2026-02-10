import os
import asyncio
import random
import re
import io
import string
import qrcode
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile, ChatPermissions, CallbackQuery
)
from aiogram.fsm.storage.memory import MemoryStorage
from groq import AsyncGroq
from aiohttp import web
import aiohttp
import pytz
from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PORT = int(os.getenv("PORT", "10000"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")

if not TOKEN:
    raise ValueError("BOT_TOKEN is required!")

# Initialize bot
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# MongoDB Setup
mongo_client = AsyncIOMotorClient(MONGODB_URI)
db = mongo_client.alita_bot
users_col = db.users
groups_col = db.groups
stickers_col = db.stickers
warnings_col = db.warnings
notes_col = db.notes
afk_col = db.afk

# FIXED: Accurate Indian Time
INDIAN_TIMEZONE = pytz.timezone('Asia/Kolkata')

def get_indian_time():
    """Get accurate Indian Standard Time"""
    return datetime.now(INDIAN_TIMEZONE)

def get_current_time_period():
    """Get current time period based on IST"""
    hour = get_indian_time().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"

# Data storage
chat_memory: Dict[int, deque] = {}
afk_users: Dict[int, Dict] = {}
started_users: Set[int] = set()
active_chats: Set[int] = set()
saved_stickers: List[str] = []

group_settings: Dict[int, Dict] = defaultdict(lambda: {
    "welcome_enabled": True, "goodbye_enabled": True,
    "greetings_enabled": True, "custom_welcome": None,
    "custom_goodbye": None, "warn_limit": 3
})

# Constants
BAD_WORDS = ["chutiya", "madarchod", "behenchod", "bhosdike", "lodu", "gandu", "fuck", "shit", "bitch", "bastard", "asshole", "motherfucker", "cunt", "dick", "gaand", "lund", "randi", "harami", "kamina", "suar", "kutta", "bc", "mc"]
ADULT_KEYWORDS = ["porn", "xxx", "sex", "nude", "naked", "boobs", "dick", "pussy", "hentai", "porno", "horny", "blowjob", "handjob", "tits", "cum", "orgasm", "chudai", "lund", "chod"]

EMOTIONAL_RESPONSES = {
    "happy": ["😊", "🎉", "🥳", "🌟", "✨"], "angry": ["😠", "👿", "💢", "🤬", "😤"],
    "love": ["❤️", "💖", "💕", "🥰", "😘"], "funny": ["😂", "🤣", "😆", "😜", "🤪"],
    "thinking": ["🤔", "💭", "🧠", "🔍", "💡"], "sleepy": ["😴", "💤", "🌙", "🛌", "🥱"]
}

WELCOME_MESSAGES = ["🎉 Welcome {name}! Group mein swagat hai! 🎊", "🌟 Aao ji {name}! Masti karenge! ✨", "✨ Hey {name}! Great to have you here! 💖", "🥳 {name} aa gaye! Party shuru! 🎈"]
GOODBYE_MESSAGES = ["👋 {name} left. We'll miss you! 😢", "😔 {name} has departed. Take care! 🌸", "🚪 {name} left. Bye bye! 👋"]

TIME_GREETINGS = {
    "morning": ["🌅 *Good Morning!* ☀️ Kaisi hai aaj ki subah? 😊", "🌸 *Shubh Prabhat!* ✨"],
    "afternoon": ["☀️ *Good Afternoon!* 🌤️ Lunch ho gaya? 🍲", "🌞 *Dopahar ki Dhoop!* 😌"],
    "evening": ["🌇 *Good Evening!* 🌆 Shaam mastani! 🌹", "🌆 *Evening Tea Time!* 🍵💖"],
    "night": ["🌙 *Good Night!* 🌟 Sweet dreams! 💤", "🌌 *Shubh Ratri!* 😴"]
}

MEME_TEMPLATES = [{"text": "When you realize it's Monday tomorrow", "emoji": "😭"}, {"text": "Me trying to be productive", "emoji": "🤡"}, {"text": "When code finally works after 100 tries", "emoji": "🎉"}]
ROAST_RESPONSES = ["Tumhari baaton se toh mere kaan bhi sharminda hain! 👂😳", "Itni bakwas toh mere phone ki auto-correct bhi nahi karta! 📱", "Agar overthinking Olympic sport hota, toh tum gold medal le jaate! 🏅"]
JOKES = ["Teacher: Tumhare ghar me sabse smart kaun hai?\\nStudent: WiFi router! 🤣", "Papa: Beta mobile chhodo, padhai karo.\\nBeta: Papa, aap bhi to TV dekhte ho!\\nPapa: Par main TV se shaadi nahi kar raha! 😂"]
DAILY_FACTS = ["Honey never spoils! Archaeologists found 3000-year-old honey still edible! 🍯", "Octopuses have 3 hearts! 💙", "Bananas are berries, but strawberries aren't! 🍌🍓"]

HOROSCOPE_SIGNS = {"aries": "♈", "taurus": "♉", "gemini": "♊", "cancer": "♋", "leo": "♌", "virgo": "♍", "libra": "♎", "scorpio": "♏", "sagittarius": "♐", "capricorn": "♑", "aquarius": "♒", "pisces": "♓"}

INDIAN_CITIES = {"mumbai": (19.0760, 72.8777), "delhi": (28.6139, 77.2090), "bangalore": (12.9716, 77.5946), "kolkata": (22.5726, 88.3639), "chennai": (13.0827, 80.2707), "hyderabad": (17.3850, 78.4867), "pune": (18.5204, 73.8567), "ahmedabad": (23.0225, 72.5714), "jaipur": (26.9124, 75.7873), "lucknow": (26.8467, 80.9462)}

# Helper functions
async def load_stickers():
    global saved_stickers
    try:
        stickers = await stickers_col.find().to_list(length=None)
        saved_stickers = [s['file_id'] for s in stickers]
        logger.info(f"Loaded {len(saved_stickers)} stickers")
    except Exception as e:
        logger.error(f"Error loading stickers: {e}")
        saved_stickers = []

def get_emotion(emotion_type: str = "happy"):
    return random.choice(EMOTIONAL_RESPONSES.get(emotion_type, EMOTIONAL_RESPONSES["happy"]))

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

def contains_bad_words(text: str) -> bool:
    return any(word in text.lower() for word in BAD_WORDS)

def contains_adult_content(text: str) -> bool:
    return any(word in text.lower() for word in ADULT_KEYWORDS)

# Weather
async def get_weather(city: str) -> str:
    try:
        city_lower = city.lower().strip()
        if city_lower in INDIAN_CITIES:
            lat, lon = INDIAN_CITIES[city_lower]
        else:
            async with aiohttp.ClientSession() as session:
                geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={WEATHER_API_KEY}"
                async with session.get(geo_url) as resp:
                    if resp.status != 200:
                        return "❌ Weather service error"
                    data = await resp.json()
                    if not data:
                        return f"❌ City '{city}' not found"
                    lat, lon = data[0]['lat'], data[0]['lon']
        async with aiohttp.ClientSession() as session:
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric"
            async with session.get(url) as resp:
                if resp.status != 200:
                    return "❌ Weather data unavailable"
                data = await resp.json()
                weather = data['weather'][0]
                main = data['main']
                wind = data['wind']
                icons = {"Clear": "☀️", "Clouds": "☁️", "Rain": "🌧️", "Drizzle": "🌦️", "Thunderstorm": "⛈️", "Snow": "❄️"}
                icon = icons.get(weather['main'], "🌡️")
                return f"🌤️ **Weather in {city.title()}**\n{'━' * 20}\n{icon} **Condition:** {weather['description'].title()}\n🌡️ **Temperature:** {main['temp']}°C\n😮‍💨 **Feels Like:** {main['feels_like']}°C\n💧 **Humidity:** {main['humidity']}%\n💨 **Wind:** {wind['speed']} m/s\n🌡️ **Pressure:** {main['pressure']} hPa\n\n📍 Powered by Alita"
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

# AI Response - FIXED for time queries
async def get_ai_response(chat_id: int, text: str, user_id: int) -> str:
    try:
        if not client:
            return f"{get_emotion('happy')} Main yahan hu! 😊"
        
        if chat_id not in chat_memory:
            chat_memory[chat_id] = deque(maxlen=10)
        
        text_lower = text.lower().strip()
        
        # Direct responses for common queries
        if text_lower in ['hi', 'hello', 'hey', 'hii']:
            return f"{get_emotion('happy')} Hii! Kaise ho? 😊"
        
        if 'good morning' in text_lower:
            return f"{get_emotion('happy')} Good Morning! 🌅 Subah ho gayi! ☀️"
        if 'good night' in text_lower:
            return f"{get_emotion('sleepy')} Good Night! 🌙 Sweet dreams! 💤"
        if 'good afternoon' in text_lower:
            return f"{get_emotion('happy')} Good Afternoon! ☀️ Lunch ho gaya? 🍛"
        if 'good evening' in text_lower:
            return f"{get_emotion('love')} Good Evening! 🌇 Shaam mastani! ✨"
        
        # FIXED: Time queries
        if any(x in text_lower for x in ['time', 'kitna baja', 'samay', 'ghadi', 'clock']):
            now = get_indian_time()
            return f"{get_emotion('thinking')} Abhi time hai: {now.strftime('%I:%M %p')} ⏰ (Indian Standard Time)"
        
        # FIXED: Date queries  
        if any(x in text_lower for x in ['date', 'din', 'tarikh', 'aaj ka din']):
            now = get_indian_time()
            return f"{get_emotion('happy')} Aaj hai: {now.strftime('%d %B %Y, %A')} 📅"
        
        # AI for complex queries
        messages = [{"role": "system", "content": "You are Alita, friendly Indian girl. Reply in Hinglish, short (1-2 lines). Be helpful and cute. Developer: @a6h1ii | Home: @abhi0w0"}]
        messages.append({"role": "user", "content": text})
        
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=100
        )
        
        reply = completion.choices[0].message.content.strip()
        chat_memory[chat_id].append({"role": "user", "content": text})
        chat_memory[chat_id].append({"role": "assistant", "content": reply})
        
        return f"{get_emotion('happy')} {reply}"
        
    except Exception as e:
        logger.error(f"AI error: {e}")
        return f"{get_emotion('happy')} Main yahan hu! Kya baat hai? 😊"

# ========== COMMAND HANDLERS ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    started_users.add(user_id)
    active_chats.add(chat_id)
    
    # Save to MongoDB
    try:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "username": message.from_user.username,
                "first_name": message.from_user.first_name,
                "last_active": datetime.now()
            }},
            upsert=True
        )
    except Exception as e:
        logger.error(f"DB error: {e}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📋 Commands", callback_data="show_help")],
        [InlineKeyboardButton("🌟 MY HOME", url="https://t.me/abhi0w0")]
    ])
    
    caption = f"{get_emotion('love')} <b>Hey! I'm Alita 🎀</b>\n\nYour AI assistant with superpowers!\n\n🧠 AI Chat | 🎨 Image Gen | 🛡️ Admin Tools\n\nType /help for all commands! 💕"
    
    image_url = "https://i.postimg.cc/yYWbPVQ4/1769349715111-result-image.png"
    
    try:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=image_url,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except:
        await message.answer(caption, parse_mode="HTML", reply_markup=keyboard)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        f"{get_emotion('happy')} <b>🎀 ALITA COMMAND CENTER 🎀</b>\n\n"
        f"<b>🧠 AI & CHAT</b>\n/start - Start the bot\n/ask [question] - Ask AI anything\n/clear - Clear chat memory\n\n"
        f"<b>🎨 CREATIVE</b>\n/imagine [prompt] - AI image generation\n/meme - Random meme text\n/joke - Random joke\n/fact - Daily fact\n/roast - Roast someone (reply)\n/horoscope [sign] - Daily horoscope\n\n"
        f"<b>🌤️ UTILITIES</b>\n/weather [city] - Weather info\n/time - Indian time (IST)\n/date - Today's date\n/qr [text] - Generate QR code\n/password [len] - Secure password\n/short [url] - Shorten URL\n/calc [expr] - Calculator\n/translate [lang] [text] - Translate\n\n"
        f"<b>📝 PERSONAL</b>\n/note [text] - Save a note\n/notes - View your notes\n/afk [reason] - Set AFK status\n/id - Get your info\n/info - Get user info (reply)\n\n"
        f"<b>🎵 MUSIC</b>\n/lyrics [song] - Get song lyrics\n\n"
        f"<b>🛡️ ADMIN COMMANDS</b>\n/adminlist - List all admins\n/warn [reason] - Warn user (reply)\n/kick - Kick user (reply)\n/ban - Ban user permanently (reply)\n/unban - Unban user (reply)\n/mute [time] - Mute user (reply)\n/unmute - Unmute user (reply)\n/purge [n] - Delete messages\n/pin - Pin message (reply)\n/unpin - Unpin last message\n/slowmode [sec] - Set slow mode\n/lock - Lock group chat\n/unlock - Unlock group chat\n/setwelcome [text] - Custom welcome\n/setgoodbye [text] - Custom goodbye\n/tagall - Mention all members\n/rules - Show group rules\n\n"
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
    await message.reply(f"{get_emotion('happy')} <b>Memory cleared!</b> 🧹", parse_mode="HTML")

@dp.message(Command("imagine"))
async def cmd_imagine(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("🎨 <b>Image Generation</b>\n\nUsage: <code>/imagine [description]</code>\n\nExample: <code>/imagine sunset over mountains</code>", parse_mode="HTML")
        return
    
    status_msg = await message.reply(f"{get_emotion('happy')} <b>Creating your image...</b> 🎨")
    
    try:
        image_data = await generate_image(command.args)
        if image_data:
            await status_msg.delete()
            await message.reply_photo(
                BufferedInputFile(image_data, filename="generated.png"),
                caption=f"🎨 <b>Generated Image</b>\n📝 <i>{command.args}</i>\n\n⚡ Powered by Alita AI",
                parse_mode="HTML"
            )
        else:
            await status_msg.edit_text("❌ <b>Failed to generate image.</b>", parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>Error:</b> {str(e)}", parse_mode="HTML")

@dp.message(Command("meme"))
async def cmd_meme(message: Message):
    template = random.choice(MEME_TEMPLATES)
    await message.reply(f"{get_emotion('funny')} <b>{template['emoji']} Random Meme</b>\n\n<i>\"{template['text']}\"</i>\n\nRelatable? 😂", parse_mode="HTML")

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
        await message.reply(f"{get_emotion('sassy')} <b>Roasting {target}</b> 🔥\n\n<i>{roast}</i>", parse_mode="HTML")
    else:
        await message.reply(f"{get_emotion('sassy')} <b>Self-Roast Mode</b> 😂\n\n<i>{random.choice(ROAST_RESPONSES)}</i>\n\nReply to someone to roast them!", parse_mode="HTML")

@dp.message(Command("horoscope"))
async def cmd_horoscope(message: Message, command: CommandObject):
    if not command.args:
        kb = []
        row = []
        for sign, emoji in list(HOROSCOPE_SIGNS.items())[:6]:
            row.append(InlineKeyboardButton(f"{emoji} {sign.title()}", callback_data=f"horo_{sign}"))
        kb.append(row)
        row = []
        for sign, emoji in list(HOROSCOPE_SIGNS.items())[6:]:
            row.append(InlineKeyboardButton(f"{emoji} {sign.title()}", callback_data=f"horo_{sign}"))
        kb.append(row)
        await message.reply(f"{get_emotion('love')} <b>Choose Your Zodiac Sign</b> ♈", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return
    
    sign = command.args.lower()
    if sign not in HOROSCOPE_SIGNS:
        await message.reply("❌ Invalid sign! Use: aries, taurus, gemini, etc.")
        return
    
    horoscopes = {
        "aries": "Energy and passion fill your day! 💪", "taurus": "Financial opportunities await. 💰",
        "gemini": "Communication is key today. 💬", "cancer": "Focus on home and family. 🏠",
        "leo": "Your charisma shines! 👑", "virgo": "Attention to detail pays off. 📋",
        "libra": "Balance is essential. ⚖️", "scorpio": "Trust your instincts today. 🔮",
        "sagittarius": "Adventure calls! 🌍", "capricorn": "Hard work yields results. 🏔️",
        "aquarius": "Innovation flows today. 💡", "pisces": "Creativity blooms. 🎨"
    }
    
    await message.reply(f"{get_emotion('love')} {HOROSCOPE_SIGNS[sign]} <b>{sign.title()} Horoscope</b>\n\n<i>{horoscopes[sign]}</i>\n\n✨ Stars are aligned for you today!", parse_mode="HTML")

@dp.message(Command("weather"))
async def cmd_weather(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(f"{get_emotion('thinking')} <b>Weather Command</b>\n\nUsage: <code>/weather [city]</code>\n\n<b>Popular cities:</b> Mumbai, Delhi, Bangalore, Kolkata, Chennai, Hyderabad, etc.", parse_mode="HTML")
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
    await message.reply(f"📅 <b>Today's Date</b>\n\n{now.strftime('%A, %d %B %Y')}\nDay {now.timetuple().tm_yday} of 365\n\n{get_emotion('happy')} Have a great day!", parse_mode="HTML")

@dp.message(Command("qr"))
async def cmd_qr(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("📱 <b>QR Code Generator</b>\n\nUsage: <code>/qr [text or URL]</code>", parse_mode="HTML")
        return
    try:
        qr_bytes = generate_qr(command.args)
        await message.reply_photo(BufferedInputFile(qr_bytes, filename="qr.png"), caption=f"📱 <b>QR Code Generated</b>\n\nScan karo! 📲", parse_mode="HTML")
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
        await message.reply(f"🔐 <b>Secure Password Generated</b>\n\n<code>{pwd}</code>\n\n📊 Length: {length} characters\n<i>Copy and store safely! 🤫</i>", parse_mode="HTML")
    except ValueError:
        await message.reply("❌ Usage: <code>/password [length]</code>\nExample: <code>/password 16</code>", parse_mode="HTML")

@dp.message(Command("short"))
async def cmd_short(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("🔗 <b>URL Shortener</b>\n\nUsage: <code>/short [long URL]</code>", parse_mode="HTML")
        return
    url = command.args.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    status = await message.reply("🔗 <b>Shortening URL...</b>")
    try:
        short = await shorten_url(url)
        await status.edit_text(f"✅ <b>URL Shortened!</b>\n\n🔗 <b>Short:</b> {short}", parse_mode="HTML")
    except Exception as e:
        await status.edit_text(f"❌ Error: {str(e)}")

@dp.message(Command("calc"))
async def cmd_calc(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("🧮 <b>Calculator</b>\n\nUsage: <code>/calc [expression]</code>\nExample: <code>/calc 2 + 2</code>", parse_mode="HTML")
        return
    expr = command.args
    allowed = set('0123456789+-*/.() ')
    if not all(c in allowed for c in expr):
        await message.reply("❌ Invalid characters!")
        return
    try:
        result = eval(expr)
        await message.reply(f"🧮 <b>Calculator</b>\n\nExpression: <code>{expr}</code>\nResult: <b>{result}</b>", parse_mode="HTML")
    except:
        await message.reply("❌ Invalid expression!")

@dp.message(Command("translate"))
async def cmd_translate(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("🌍 <b>Translator</b>\n\nUsage: <code>/translate [language_code] [text]</code>\nExample: <code>/translate hi Hello</code>", parse_mode="HTML")
        return
    args = command.args.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Please provide both language code and text!")
        return
    target_lang, text = args[0], args[1]
    status = await message.reply("🌍 <b>Translating...</b>")
    try:
        translated = await translate_text(text, target_lang)
        await status.edit_text(f"✅ <b>Translation</b>\n\n📝 <b>Original:</b> {text}\n🔀 <b>Translated:</b> <i>{translated}</i>", parse_mode="HTML")
    except Exception as e:
        await status.edit_text(f"❌ Translation failed: {str(e)}")

@dp.message(Command("note"))
async def cmd_note(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("📝 <b>Note Taker</b>\n\nUsage: <code>/note [your note]</code>", parse_mode="HTML")
        return
    try:
        await notes_col.insert_one({
            "user_id": message.from_user.id,
            "note_text": command.args,
            "created_at": datetime.now()
        })
        await message.reply(f"{get_emotion('happy')} <b>Note Saved!</b> 📝\n\n<i>{command.args[:100]}{'...' if len(command.args) > 100 else ''}</i>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("notes"))
async def cmd_notes(message: Message):
    try:
        notes = await notes_col.find({"user_id": message.from_user.id}).sort("created_at", -1).limit(10).to_list(length=None)
        if not notes:
            await message.reply(f"{get_emotion('crying')} <b>No notes found!</b>", parse_mode="HTML")
            return
        text = f"📝 <b>Your Notes</b> ({len(notes)} total)\n\n"
        for i, note in enumerate(notes, 1):
            time_str = note['created_at'].strftime('%d/%m %H:%M')
            text += f"{i}. {note['note_text'][:50]}{'...' if len(note['note_text']) > 50 else ''} <i>({time_str})</i>\n"
        await message.reply(text, parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("afk"))
async def cmd_afk(message: Message, command: CommandObject):
    reason = command.args or "Busy"
    afk_users[message.from_user.id] = {"reason": reason, "since": datetime.now()}
    await message.reply(f"😴 <b>AFK Mode Activated</b>\n\n💤 <b>Reason:</b> {reason}\n⏰ <b>Since:</b> {datetime.now().strftime('%I:%M %p')}", parse_mode="HTML")

@dp.message(Command("id"))
async def cmd_id(message: Message):
    user = message.from_user
    text = f"👤 <b>Your Information</b>\n━━〘 🆔 〙━━\n\n<b>User ID:</b> <code>{user.id}</code>\n<b>Name:</b> {user.full_name}\n<b>Username:</b> @{user.username or 'N/A'}\n<b>Chat ID:</b> <code>{message.chat.id}</code>\n<b>Chat Type:</b> {message.chat.type}"
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        text += f"\n\n👤 <b>Replied User</b>\n<b>User ID:</b> <code>{target.id}</code>\n<b>Name:</b> {target.full_name}"
    await message.reply(text, parse_mode="HTML")

@dp.message(Command("info"))
async def cmd_info(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    try:
        member_info = ""
        if message.chat.type in ["group", "supergroup"]:
            member = await bot.get_chat_member(message.chat.id, target.id)
            status = {"creator": "👑 Creator", "administrator": "🛡️ Admin", "member": "👤 Member"}.get(member.status, "❓ Unknown")
            member_info = f"\n<b>Status:</b> {status}"
        await message.reply(f"👤 <b>User Information</b>\n<b>ID:</b> <code>{target.id}</code>\n<b>Name:</b> {target.full_name}\n<b>Username:</b> @{target.username or 'N/A'}{member_info}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("lyrics"))
async def cmd_lyrics(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("🎵 <b>Lyrics Finder</b>\n\nUsage: <code>/lyrics [song name]</code>\nExample: <code>/lyrics Shape of You</code>", parse_mode="HTML")
        return
    status = await message.reply(f"{get_emotion('happy')} 🔍 <b>Searching lyrics...</b>")
    try:
        lyrics = await get_lyrics(command.args)
        if len(lyrics) > 4000:
            lyrics = lyrics[:4000] + "\n\n... (truncated)"
        await status.edit_text(f"🎵 <b>Lyrics: {command.args}</b>\n<pre>{lyrics}</pre>", parse_mode="HTML")
    except Exception as e:
        await status.edit_text(f"❌ <b>Error:</b> {str(e)}")

# ========== ADMIN COMMANDS ==========

@dp.message(Command("adminlist"))
async def cmd_adminlist(message: Message):
    if message.chat.type == "private":
        await message.reply("❌ This command works in groups only!")
        return
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        if not admins:
            await message.reply("❌ Could not fetch admin list!")
            return
        
        text = f"{get_emotion('protective')} <b>Group Administrators</b> 👑\n\n"
        creator = None
        admin_list = []
        
        for admin in admins:
            if admin.status == "creator":
                creator = admin
            else:
                admin_list.append(admin)
        
        if creator:
            user = creator.user
            name = f"{user.first_name} {user.last_name or ''}".strip()
            username = f"@{user.username}" if user.username else "No username"
            text += f"👑 <b>CREATOR</b>\n├ <b>{name}</b>\n├ <code>{user.id}</code>\n└ {username}\n\n"
        
        if admin_list:
            text += f"🛡️ <b>ADMINISTRATORS ({len(admin_list)})</b>\n"
            for i, admin in enumerate(admin_list, 1):
                user = admin.user
                name = f"{user.first_name} {user.last_name or ''}".strip()
                username = f"@{user.username}" if user.username else "No username"
                text += f"{i}. <b>{name}</b>\n   ├ <code>{user.id}</code>\n   └ {username}\n"
        
        await message.reply(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Adminlist error: {e}")
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules = f"{get_emotion('protective')} <b>📜 GROUP RULES</b> 🛡️\n\n<b>✅ DO's:</b>\n• Be respectful to everyone 🤝\n• Keep chat friendly 🌟\n• Help each other 📚\n\n<b>🚫 DON'Ts:</b>\n• No spam or flooding ⚠️\n• No bad language 🚫\n• No adult content 🚷 (Auto-ban!)\n\n<b>⚡ Auto-Moderation:</b>\n• 3 Warnings = Auto-mute 🔇\n• Adult content = Instant ban 🚫\n\n{get_emotion('love')} <i>I'm here to keep everyone safe!</i> 💪"
    await message.reply(rules, parse_mode="HTML")

@dp.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a user to warn them!")
        return
    
    target = message.reply_to_message.from_user
    reason = command.args or "Rule violation"
    
    await warnings_col.insert_one({
        "chat_id": message.chat.id,
        "user_id": target.id,
        "reason": reason,
        "warned_at": datetime.now()
    })
    
    count = await warnings_col.count_documents({"chat_id": message.chat.id, "user_id": target.id})
    limit = 3
    
    if count >= limit:
        try:
            until = datetime.now() + timedelta(hours=24)
            await bot.restrict_chat_member(message.chat.id, target.id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
            await warnings_col.delete_many({"chat_id": message.chat.id, "user_id": target.id})
            await message.reply(f"🚫 <b>User Muted!</b>\n\n👤 <b>{target.first_name}</b>\n⚠️ Warnings: {count}/{limit}\n⏰ Duration: 24 hours", parse_mode="HTML")
        except Exception as e:
            await message.reply(f"❌ Failed: {str(e)}")
    else:
        await message.reply(f"⚠️ <b>Warning Issued!</b>\n\n👤 <b>{target.first_name}</b>\n📝 Reason: {reason}\n📊 Count: {count}/{limit}", parse_mode="HTML")

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
        await message.reply(f"👢 <b>Kicked!</b>\n\n👤 {target.first_name}\n🆔 <code>{target.id}</code>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)}")

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
        await message.reply(f"🚫 <b>Banned Permanently!</b>\n\n👤 {target.first_name}\n🆔 <code>{target.id}</code>", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)}")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a user to unban them!")
        return
    target = message.reply_to_message.from_user
    try:
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"✅ <b>Unbanned!</b>\n\n👤 {target.first_name}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)}")

@dp.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a user to mute them!")
        return
    
    target = message.reply_to_message.from_user
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
        else:
            until = datetime.now() + timedelta(hours=1)
            duration_text = "1 hour"
        
        await bot.restrict_chat_member(message.chat.id, target.id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
        await message.reply(f"🔇 <b>Muted!</b>\n\n👤 {target.first_name}\n⏰ Duration: {duration_text}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)}")

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
        await bot.restrict_chat_member(message.chat.id, target.id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True))
        await message.reply(f"🔊 <b>Unmuted!</b>\n\n👤 {target.first_name}\n✅ Can speak again!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)}")

@dp.message(Command("purge"))
async def cmd_purge(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to the oldest message to delete!")
        return
    try:
        count = int(command.args) if command.args else 10
        count = min(max(count, 1), 100)
        
        message_ids = []
        async for msg in bot.get_chat_history(message.chat.id, limit=count):
            if msg.message_id >= message.reply_to_message.message_id:
                message_ids.append(msg.message_id)
        
        if message_ids:
            for i in range(0, len(message_ids), 100):
                batch = message_ids[i:i+100]
                await bot.delete_messages(message.chat.id, batch)
            await message.reply(f"🗑️ <b>Purged!</b>\n\nDeleted {len(message_ids)} messages!", parse_mode="HTML")
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
        await bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id, disable_notification=False)
        await message.reply("📌 <b>Pinned!</b>")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)}")

@dp.message(Command("unpin"))
async def cmd_unpin(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    try:
        await bot.unpin_chat_message(message.chat.id)
        await message.reply("📍 <b>Unpinned!</b>")
    except Exception as e:
        await message.reply(f"❌ Failed: {str(e)}")

@dp.message(Command("slowmode"))
async def cmd_slowmode(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    try:
        delay = int(command.args) if command.args else 0
        delay = max(0, min(delay, 86400))
        await bot.set_chat_slow_mode_delay(message.chat.id, delay)
        if delay == 0:
            await message.reply("🚀 <b>Slow mode disabled!</b>")
        else:
            await message.reply(f"⏱️ <b>Slow mode enabled!</b>\n\n1 message every {delay} seconds.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("lock"))
async def cmd_lock(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    try:
        await bot.set_chat_permissions(message.chat.id, permissions=ChatPermissions(can_send_messages=False))
        await message.reply("🔒 <b>Chat Locked!</b>\n\nOnly admins can send messages now.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("unlock"))
async def cmd_unlock(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    try:
        await bot.set_chat_permissions(message.chat.id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_polls=True, can_send_other_messages=True))
        await message.reply("🔓 <b>Chat Unlocked!</b>\n\nEveryone can send messages now! 🎉", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command("setwelcome"))
async def cmd_setwelcome(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    if not command.args:
        await message.reply("👋 <b>Set Custom Welcome</b>\n\nUsage: <code>/setwelcome [message]</code>\n\nVariables: <code>{name}</code>, <code>{username}</code>, <code>{chat}</code>", parse_mode="HTML")
        return
    group_settings[message.chat.id]["custom_welcome"] = command.args
    await message.reply(f"✅ <b>Custom welcome message set!</b>\n\nPreview:\n<i>{command.args}</i>", parse_mode="HTML")

@dp.message(Command("setgoodbye"))
async def cmd_setgoodbye(message: Message, command: CommandObject):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    if not command.args:
        await message.reply("👋 <b>Set Custom Goodbye</b>\n\nUsage: <code>/setgoodbye [message]</code>", parse_mode="HTML")
        return
    group_settings[message.chat.id]["custom_goodbye"] = command.args
    await message.reply(f"✅ <b>Custom goodbye message set!</b>", parse_mode="HTML")

# FIXED TAGALL - Gets actual recent members
@dp.message(Command("tagall"))
async def cmd_tagall(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("❌ <b>Admin only!</b>")
        return
    if message.chat.type == "private":
        await message.reply("❌ Works in groups only!")
        return
    
    try:
        status_msg = await message.reply("📢 <b>Collecting members...</b>")
        
        mentions = []
        seen_users = set()
        
        # Get recent 100 messages to find active members
        async for msg in bot.get_chat_history(message.chat.id, limit=100):
            if msg.from_user and msg.from_user.id not in seen_users:
                seen_users.add(msg.from_user.id)
                user = msg.from_user
                if user.id != bot.id:  # Don't tag bot
                    if user.username:
                        mentions.append(f"@{user.username}")
                    else:
                        mentions.append(f"<a href='tg://user?id={user.id}'>{user.first_name}</a>")
        
        if not mentions:
            await status_msg.edit_text("❌ No members found!")
            return
        
        await status_msg.edit_text(f"📢 <b>Tagging {len(mentions)} members...</b>")
        
        # Send in batches of 5
        for i in range(0, len(mentions), 5):
            batch = mentions[i:i+5]
            await message.reply("📢 " + " | ".join(batch), parse_mode="HTML")
            await asyncio.sleep(2)
            
    except Exception as e:
        logger.error(f"Tagall error: {e}")
        await message.reply(f"❌ Error: {str(e)}")

# ========== OWNER COMMANDS ==========

@dp.message(Command("sendall"))
async def cmd_sendall(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ <b>Owner only!</b>")
        return
    if not message.reply_to_message:
        await message.reply("📢 Reply to a message to broadcast it!")
        return
    
    status = await message.reply("📤 <b>Broadcasting...</b>")
    
    users = await users_col.find().to_list(length=None)
    groups = await groups_col.find().to_list(length=None)
    
    sent = 0
    failed = 0
    
    for user in users:
        try:
            await bot.copy_message(user['user_id'], message.chat.id, message.reply_to_message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    for group in groups:
        try:
            await bot.copy_message(group['chat_id'], message.chat.id, message.reply_to_message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await status.edit_text(f"✅ <b>Broadcast Complete!</b>\n\n📤 Sent: {sent}\n❌ Failed: {failed}", parse_mode="HTML")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ <b>Owner only!</b>")
        return
    if not command.args:
        await message.reply("Usage: /broadcast [message]")
        return
    
    status = await message.reply("📤 Broadcasting...")
    users = await users_col.find().to_list(length=None)
    
    sent = 0
    failed = 0
    
    for user in users:
        try:
            await bot.send_message(user['user_id'], command.args, parse_mode="HTML")
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
        await stickers_col.insert_one({
            "file_id": file_id,
            "added_by": message.from_user.id,
            "added_at": datetime.now()
        })
        saved_stickers.append(file_id)
        await message.reply(f"✅ <b>Sticker Saved!</b>\n\n🎭 Total stickers: {len(saved_stickers)}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

# ========== CALLBACK HANDLERS ==========

@dp.callback_query(F.data == "show_help")
async def cb_show_help(callback: CallbackQuery):
    await cmd_help(callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("horo_"))
async def cb_horoscope(callback: CallbackQuery):
    sign = callback.data.split("_")[1]
    await callback.message.reply(f"{get_emotion('love')} {HOROSCOPE_SIGNS[sign]} <b>{sign.title()} Horoscope</b>\n\n✨ Your day looks bright!", parse_mode="HTML")
    await callback.answer()

# ========== CHAT EVENTS ==========

@dp.chat_member()
async def handle_chat_member(update: ChatMemberUpdated):
    if not update.new_chat_member:
        return
    
    chat_id = update.chat.id
    new_member = update.new_chat_member
    
    # Save group
    if update.chat.type in ["group", "supergroup"]:
        try:
            await groups_col.update_one(
                {"chat_id": chat_id},
                {"$set": {
                    "chat_id": chat_id,
                    "title": update.chat.title,
                    "type": update.chat.type,
                    "added_at": datetime.now()
                }},
                upsert=True
            )
            active_chats.add(chat_id)
        except Exception as e:
            logger.error(f"Group save error: {e}")
    
    # Member joined
    if new_member.status == "member":
        user = new_member.user
        try:
            await users_col.update_one(
                {"user_id": user.id},
                {"$set": {
                    "user_id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_active": datetime.now()
                }},
                upsert=True
            )
        except:
            pass
        
        custom = group_settings[chat_id].get("custom_welcome")
        if custom:
            text = custom.replace("{name}", user.first_name).replace("{username}", user.username or "").replace("{chat}", update.chat.title or "Group")
        else:
            text = random.choice(WELCOME_MESSAGES).format(name=user.first_name)
        
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown")
            # Random sticker on welcome
            if saved_stickers and random.random() < 0.3:
                await asyncio.sleep(1)
                await bot.send_sticker(chat_id, random.choice(saved_stickers))
        except Exception as e:
            logger.error(f"Welcome error: {e}")
    
    # Member left
    elif new_member.status in ["left", "kicked", "banned"]:
        user = new_member.user
        custom = group_settings[chat_id].get("custom_goodbye")
        if custom:
            text = custom.replace("{name}", user.first_name).replace("{username}", user.username or "")
        else:
            text = random.choice(GOODBYE_MESSAGES).format(name=user.first_name)
        
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown")
        except:
            pass

# ========== MAIN MESSAGE HANDLER ==========

@dp.message()
async def handle_all_messages(message: Message):
    if not message.from_user or not message.text:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text
    
    # Skip commands
    if text.startswith('/'):
        return
    
    # Track activity
    started_users.add(user_id)
    active_chats.add(chat_id)
    
    # Update user in DB
    try:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "username": message.from_user.username,
                "first_name": message.from_user.first_name,
                "last_active": datetime.now()
            }},
            upsert=True
        )
    except:
        pass
    
    # Check AFK mentions
    if message.reply_to_message:
        replied_id = message.reply_to_message.from_user.id
        if replied_id in afk_users:
            afk_data = afk_users[replied_id]
            await message.reply(f"😴 <b>{message.reply_to_message.from_user.first_name} is AFK</b>\nReason: {afk_data['reason']}", parse_mode="HTML")
    
    # Remove AFK if user sends message
    if user_id in afk_users:
        del afk_users[user_id]
        await message.reply(f"👋 Welcome back {message.from_user.first_name}!", parse_mode="HTML")
        return
    
    # Auto-moderation in groups
    if message.chat.type in ["group", "supergroup"]:
        if contains_bad_words(text):
            try:
                await message.delete()
                await message.reply(f"⚠️ {message.from_user.first_name}, bad words not allowed!", parse_mode="HTML")
            except:
                pass
            return
        
        if contains_adult_content(text):
            try:
                await message.delete()
                await bot.ban_chat_member(chat_id, user_id)
                await message.reply(f"🚫 {message.from_user.first_name} banned for adult content!", parse_mode="HTML")
            except:
                pass
            return
    
    # AI Response
    try:
        me = await bot.get_me()
        is_private = message.chat.type == "private"
        is_mention = me.username and f"@{me.username.lower()}" in text.lower()
        is_reply = message.reply_to_message and message.reply_to_message.from_user.id == me.id
        
        if is_private or is_mention or is_reply:
            clean_text = text
            if me.username:
                clean_text = re.sub(rf'@{me.username}\\s*', '', text, flags=re.IGNORECASE).strip()
            
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(0.5)
            response = await get_ai_response(chat_id, clean_text, user_id)
            await message.reply(response)
            
    except Exception as e:
        logger.error(f"Handler error: {e}")

# ========== WEB SERVER & SCHEDULER ==========

async def health_check(request):
    return web.Response(text="✅ Alita Bot is Running! 🎀", content_type="text/plain")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web server started on port {PORT}")

# RANDOM and NON-INTRUSIVE scheduled tasks
async def send_time_greetings():
    try:
        period = get_current_time_period()
        if period not in TIME_GREETINGS:
            return
        
        greeting = random.choice(TIME_GREETINGS[period])
        
        # Send to some active groups (not all, to avoid spam)
        groups = await groups_col.find().to_list(length=None)
        for group in groups:
            try:
                if random.random() < 0.5:  # 50% chance
                    await bot.send_message(group['chat_id'], greeting, parse_mode="Markdown")
                    await asyncio.sleep(2)
            except:
                pass
        
        # Send to some active users
        users = await users_col.find().sort("last_active", -1).limit(10).to_list(length=None)
        for user in users:
            try:
                if random.random() < 0.2:  # 20% chance
                    await bot.send_message(user['user_id'], greeting, parse_mode="Markdown")
                    await asyncio.sleep(1)
            except:
                pass
    except Exception as e:
        logger.error(f"Greeting error: {e}")

async def send_random_stickers():
    if not saved_stickers:
        return
    try:
        # Random stickers to random groups
        groups = await groups_col.find().to_list(length=None)
        for group in groups:
            if random.random() < 0.2:  # 20% chance
                try:
                    await bot.send_sticker(group['chat_id'], random.choice(saved_stickers))
                    await asyncio.sleep(2)
                except:
                    pass
    except Exception as e:
        logger.error(f"Sticker error: {e}")

def setup_scheduler():
    try:
        sched = AsyncIOScheduler()
        # Greetings at specific times only
        sched.add_job(send_time_greetings, 'cron', hour=9, minute=0)
        sched.add_job(send_time_greetings, 'cron', hour=14, minute=0)
        sched.add_job(send_time_greetings, 'cron', hour=19, minute=0)
        sched.add_job(send_time_greetings, 'cron', hour=22, minute=0)
        # Random stickers every 4 hours
        sched.add_job(send_random_stickers, 'interval', hours=4)
        sched.start()
        logger.info("⏰ Scheduler started")
        return sched
    except Exception as e:
        logger.error(f"Scheduler error: {e}")
        return None

# ========== MAIN ==========

async def main():
    logger.info("=" * 60)
    logger.info("🎀 ALITA BOT v3.0 - STARTING")
    logger.info("=" * 60)
    
    try:
        # Load stickers
        await load_stickers()
        
        # Start web server
        asyncio.create_task(start_web_server())
        
        # Setup scheduler
        setup_scheduler()
        
        # Delete webhook
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Get bot info
        me = await bot.get_me()
        logger.info(f"🤖 Bot: @{me.username}")
        logger.info(f"👑 Admin ID: {ADMIN_ID}")
        logger.info(f"⏰ Timezone: Asia/Kolkata (IST)")
        
        # Start polling
        logger.info("🚀 Starting polling...")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped")
    except Exception as e:
        logger.error(f"💥 Critical error: {e}")
