import os
import asyncio
import random
import re
import aiofiles
import aiohttp
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from groq import AsyncGroq
from aiohttp import web
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import yt_dlp
from duckduckgo_search import DDGS
import edge_tts
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import uuid
import tempfile
import shutil

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")  # MongoDB URI
PORT = int(os.getenv("PORT", 10000))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Timezone for India
INDIAN_TIMEZONE = pytz.timezone('Asia/Kolkata')

# Initialize with MemoryStorage
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# Initialize Groq client
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Initialize MongoDB
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client.alita_bot
user_collection = db.users
warnings_collection = db.warnings
downloads_collection = db.downloads

# --- IN-MEMORY CACHE (for faster access) ---
chat_memory: Dict[int, deque] = {}
user_message_count: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
last_messages: Dict[int, Dict[int, List]] = defaultdict(lambda: defaultdict(list))
game_sessions: Dict[int, Dict] = {}

# Game states storage
game_sessions: Dict[int, Dict] = {}

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
        "CAACAgIAAxkBAAIBvWarL4Aw0XvIlPNOH1HSOf1q3rRnAAJbAAPBnGAM6sjZ61n0zJozBA"
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

# --- TIME-BASED GREETINGS ---
TIME_GREETINGS = {
    "morning": {
        "time_range": (5, 11),
        "keywords": ["subah", "morning", "good morning", "सुबह", "शुभ प्रभात"],
        "emotions": ["happy", "love", "surprise"],
        "templates": [
            "🌅 *Good Morning Sunshine!* ☀️\nKaisi hai aaj ki subah? Utho aur muskurao! 😊",
            "🌸 *Shubh Prabhat!* 🌸\nAaj ka din aapke liye khoobsurat ho! ✨",
            "☕ *Morning Coffee Time!* 🍵\nChai piyo, fresh ho jao, aur din shuru karo! 💫",
            "🌄 *A New Day Begins!* 🌄\nAaj kuch naya seekhne ka din hai! 📚",
            "🐦 *Chidiyaon ki chahchah mein!* 🎶\nSubah mubarak ho aapko! 😇"
        ]
    },
    "afternoon": {
        "time_range": (12, 16),
        "keywords": ["dopahar", "afternoon", "good afternoon", "दोपहर", "शुभ दोपहर"],
        "emotions": ["thinking", "hungry", "funny"],
        "templates": [
            "☀️ *Good Afternoon!* 🌤️\nLunch ho gaya? Energy maintain rakho! 🍲",
            "🌞 *Dopahar ki Dhoop mein!* 🌞\nThoda aaraam karo, phir kaam karo! 😌",
            "🍛 *Afternoon Siesta Time!* 💤\nKhaana kha ke neend aa rahi hai? Hehe! 😴",
            "📊 *Productive Afternoon!* 💼\nDopahar ka kaam aadha din kaam! 💪",
            "🌻 *Shubh Dopahar!* 🌻\nAapka din accha chal raha ho! ✨"
        ]
    },
    "evening": {
        "time_range": (17, 20),
        "keywords": ["shaam", "evening", "good evening", "शाम", "शुभ संध्या"],
        "emotions": ["love", "happy", "sassy"],
        "templates": [
            "🌇 *Good Evening Beautiful!* 🌆\nShaam ho gayi, thoda relax karo! 🌹",
            "🌆 *Evening Tea Time!* 🍵\nChai aur baatein - perfect combination! 💖",
            "✨ *Shubh Sandhya!* ✨\nDin bhar ki thakaan door karo! 🎶",
            "🌃 *Evening Walk Time!* 🚶‍♀️\nFresh hawa mein thoda ghumo! 🌸",
            "💫 *Evening Vibes!* 💫\nDin khatam, raat shuru - magic time! ✨"
        ]
    },
    "night": {
        "time_range": (21, 23),
        "keywords": ["raat", "night", "good night", "रात", "शुभ रात्रि"],
        "emotions": ["sleepy", "love", "crying"],
        "templates": [
            "🌙 *Good Night Sweet Dreams!* 🌟\nAankhein band karo aur accha sapna dekho! 💤",
            "🌌 *Shubh Ratri!* 🌌\nThaka hua dimaag ko aaraam do! 😴",
            "💤 *Sleep Time!* 💤\nKal phir nayi energy ke saath uthna! 🌅",
            "🌠 *Night Night!* 🌠\nChanda mama aapko sone ki kahani sunaye! 🌙",
            "🛏️ *Bedtime!* 🛏️\nAaj ka din khatam, kal naya shuru! ✨"
        ]
    },
    "late_night": {
        "time_range": (0, 4),
        "keywords": ["midnight", "late", "raat", "आधी रात"],
        "emotions": ["sleepy", "thinking", "surprise"],
        "templates": [
            "🌃 *Late Night Owls!* 🦉\nSone ka time hai, par chat karna hai? 😄",
            "🌚 *Midnight Chats!* 🌚\nRaat ke 12 baje bhi jag rahe ho? 😲",
            "💫 *Late Night Vibes!* 💫\nSab so rahe hain, hum chat kar rahe hain! 🤫",
            "🌜 *Chandni Raat!* 🌛\nAisi raat mein baatein hi baatein! 💬",
            "🦉 *Night Shift!* 🦉\nMain bhi jag rahi hu tumhare saath! 💖"
        ]
    }
}

# --- MONGODB FUNCTIONS ---
async def get_user_data(user_id: int, chat_id: int = None) -> Dict:
    """Get user data from MongoDB"""
    try:
        user_data = await user_collection.find_one({"user_id": user_id})
        if not user_data:
            user_data = {
                "user_id": user_id,
                "emotion": "happy",
                "last_interaction": datetime.now(),
                "total_messages": 0,
                "warnings": 0,
                "created_at": datetime.now()
            }
            await user_collection.insert_one(user_data)
        
        # Update last interaction
        await user_collection.update_one(
            {"user_id": user_id},
            {"$set": {"last_interaction": datetime.now()},
             "$inc": {"total_messages": 1}}
        )
        
        return user_data
    except Exception as e:
        print(f"MongoDB get_user_data error: {e}")
        return {"user_id": user_id, "emotion": "happy"}

async def update_user_emotion_db(user_id: int, emotion: str):
    """Update user emotion in MongoDB"""
    try:
        await user_collection.update_one(
            {"user_id": user_id},
            {"$set": {"emotion": emotion}},
            upsert=True
        )
    except Exception as e:
        print(f"MongoDB update_emotion error: {e}")

async def get_user_warnings(user_id: int, chat_id: int) -> Dict:
    """Get user warnings from MongoDB"""
    try:
        warning_data = await warnings_collection.find_one({
            "user_id": user_id,
            "chat_id": chat_id
        })
        
        if not warning_data:
            warning_data = {
                "user_id": user_id,
                "chat_id": chat_id,
                "count": 0,
                "reasons": [],
                "last_warning": None,
                "created_at": datetime.now()
            }
            await warnings_collection.insert_one(warning_data)
        
        return warning_data
    except Exception as e:
        print(f"MongoDB get_warnings error: {e}")
        return {"count": 0, "reasons": []}

async def add_warning(user_id: int, chat_id: int, reason: str) -> Dict:
    """Add warning to user in MongoDB"""
    try:
        warning_data = await get_user_warnings(user_id, chat_id)
        
        new_count = warning_data["count"] + 1
        reasons = warning_data["reasons"] + [reason]
        
        await warnings_collection.update_one(
            {"user_id": user_id, "chat_id": chat_id},
            {"$set": {
                "count": new_count,
                "reasons": reasons,
                "last_warning": datetime.now()
            }},
            upsert=True
        )
        
        return {"count": new_count, "reasons": reasons}
    except Exception as e:
        print(f"MongoDB add_warning error: {e}")
        return {"count": 1, "reasons": [reason]}

async def reset_warnings(user_id: int, chat_id: int):
    """Reset user warnings in MongoDB"""
    try:
        await warnings_collection.update_one(
            {"user_id": user_id, "chat_id": chat_id},
            {"$set": {
                "count": 0,
                "reasons": [],
                "last_warning": None
            }}
        )
    except Exception as e:
        print(f"MongoDB reset_warnings error: {e}")

# --- SOCIAL MEDIA DOWNLOADER ---
class SocialDownloader:
    def __init__(self):
        self.ydl_opts = {
            'format': 'best[height<=720]',
            'outtmpl': '%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'noplaylist': True,
        }
    
    async def is_social_media_link(self, text: str) -> bool:
        """Check if text contains social media links"""
        patterns = [
            r'(https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[^\s]+)',
            r'(https?://(?:www\.)?youtube\.com/watch\?v=[^\s]+)',
            r'(https?://youtu\.be/[^\s]+)',
            r'(https?://(?:www\.)?pinterest\.com/pin/[^\s]+)',
            r'(https?://(?:www\.)?pinterest\.com/[^\s]+/[^\s]+)',
        ]
        
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    async def extract_link(self, text: str) -> Optional[str]:
        """Extract social media link from text"""
        patterns = [
            r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[^\s]+',
            r'https?://(?:www\.)?youtube\.com/watch\?v=[^\s]+',
            r'https?://youtu\.be/[^\s]+',
            r'https?://(?:www\.)?pinterest\.com/pin/[^\s]+',
            r'https?://(?:www\.)?pinterest\.com/[^\s]+/[^\s]+',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None
    
    async def download_media(self, url: str) -> Optional[str]:
        """Download media from social media URL"""
        temp_dir = tempfile.mkdtemp(prefix="alita_download_")
        
        try:
            ydl_opts = self.ydl_opts.copy()
            ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if not info:
                    return None
                
                # Find the downloaded file
                files = os.listdir(temp_dir)
                if not files:
                    return None
                
                downloaded_file = os.path.join(temp_dir, files[0])
                
                # Get file info for database
                file_size = os.path.getsize(downloaded_file) / (1024 * 1024)  # MB
                
                # Save download record
                await downloads_collection.insert_one({
                    "url": url,
                    "file_path": downloaded_file,
                    "file_size_mb": round(file_size, 2),
                    "downloaded_at": datetime.now(),
                    "platform": self.get_platform(url)
                })
                
                return downloaded_file
                
        except Exception as e:
            print(f"Download error: {e}")
            # Clean up temp directory
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            return None
    
    def get_platform(self, url: str) -> str:
        """Get platform name from URL"""
        if 'instagram.com' in url:
            return 'instagram'
        elif 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        elif 'pinterest.com' in url:
            return 'pinterest'
        return 'unknown'

# Initialize downloader
downloader = SocialDownloader()

# --- DUCKDUCKGO SEARCH ---
async def duckduckgo_search(query: str, max_results: int = 3) -> List[Dict]:
    """Search using DuckDuckGo"""
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    'title': r.get('title', 'No title'),
                    'body': r.get('body', 'No description'),
                    'link': r.get('href', '#'),
                    'source': 'DuckDuckGo'
                })
        return results
    except Exception as e:
        print(f"Search error: {e}")
        return []

# --- EDGE-TTS VOICE GENERATION ---
async def text_to_speech(text: str, voice: str = "en-IN-NeerjaExpressiveNeural") -> Optional[str]:
    """Convert text to speech using Edge-TTS"""
    temp_file = None
    try:
        # Create temporary file
        temp_file = f"temp_voice_{uuid.uuid4().hex}.mp3"
        
        # Initialize TTS
        tts = edge_tts.Communicate(text=text, voice=voice)
        
        # Save to file
        await tts.save(temp_file)
        
        return temp_file
        
    except Exception as e:
        print(f"TTS error: {e}")
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        return None

# --- IMAGE GENERATION ---
async def generate_image(prompt: str) -> Optional[str]:
    """Generate image using Pollinations.ai"""
    try:
        # Clean prompt for URL
        clean_prompt = re.sub(r'[^a-zA-Z0-9\s-]', '', prompt)
        clean_prompt = clean_prompt.replace(' ', '-')[:100]
        
        # Pollinations.ai URL
        url = f"https://image.pollinations.ai/prompt/{clean_prompt}"
        
        # Create temp file
        temp_file = f"temp_image_{uuid.uuid4().hex}.jpg"
        
        # Download image
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    async with aiofiles.open(temp_file, 'wb') as f:
                        await f.write(await response.read())
                    return temp_file
        
        return None
        
    except Exception as e:
        print(f"Image generation error: {e}")
        return None

async def get_ai_greeting(time_period: str, group_name: str = None) -> str:
    """Get AI-generated greeting for current time period"""
    try:
        indian_time = get_indian_time()
        time_str = indian_time.strftime("%I:%M %p")
        date_str = indian_time.strftime("%A, %d %B %Y")
        
        prompt = f"""
        You are Alita 🎀 - a sweet and cute girl who sends greetings.
        Current Indian time: {time_str}
        Date: {date_str}
        Time period: {time_period}
        Group: {group_name or 'everyone'}
        
        Generate a short, sweet greeting (2-3 lines max) in Hinglish (Hindi+English mix).
        Be emotional, cute, and use appropriate emojis.
        Don't be too formal - be friendly and warm.
        
        Example for morning:
        "🌅 Good Morning cuties! ☀️ Subah ki chai piyo aur fresh feel karo! 😊"
        
        Example for night:
        "🌙 Good Night sweet dreams! 🌟 Aankhein band karo aur ache sapne dekho! 💤"
        """
        
        if client:
            completion = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are Alita - a cute, sweet girl who sends greetings."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.9,
                max_tokens=80
            )
            
            ai_response = completion.choices[0].message.content.strip()
            
            # Add emotion at beginning
            emotion = get_emotion(TIME_GREETINGS[time_period]["emotions"][0])
            return f"{emotion} {ai_response}"
        
        else:
            # Fallback to templates
            templates = TIME_GREETINGS[time_period]["templates"]
            emotion = get_emotion(TIME_GREETINGS[time_period]["emotions"][0])
            return f"{emotion} {random.choice(templates)}"
            
    except Exception as e:
        print(f"AI greeting error: {e}")
        # Fallback
        templates = TIME_GREETINGS[time_period]["templates"]
        emotion = get_emotion(TIME_GREETINGS[time_period]["emotions"][0])
        return f"{emotion} {random.choice(templates)}"

async def send_time_based_greetings():
    """Send greetings to all active groups at appropriate times"""
    try:
        current_period = get_current_time_period()
        indian_time = get_indian_time()
        current_hour = indian_time.hour
        
        print(f"\n⏰ [{indian_time.strftime('%H:%M:%S')}] Checking greetings for {current_period}")
        
        # Check if we should send greeting (only at specific hours)
        greeting_hours = {
            "morning": [6, 7, 8, 9],
            "afternoon": [12, 13, 14, 15],
            "evening": [17, 18, 19, 20],
            "night": [21, 22, 23],
            "late_night": [1, 2, 3]
        }
        
        if current_hour not in greeting_hours.get(current_period, []):
            print(f"   ⏳ Not a greeting hour for {current_period}")
            return
        
        # Get all groups where bot is active
        active_groups = []
        private_chats = []
        
        # Check all chats in memory
        for chat_id in list(chat_memory.keys()):
            try:
                chat = await bot.get_chat(chat_id)
                
                if chat.type in ["group", "supergroup"]:
                    active_groups.append(chat_id)
                elif chat.type == "private":
                    # Only include active private chats (last 7 days)
                    user_data = await get_user_data(chat_id)
                    last_active = user_data.get("last_interaction", datetime.min)
                    days_since_active = (datetime.now() - last_active).days
                    if days_since_active <= 7:
                        private_chats.append(chat_id)
            except Exception as e:
                print(f"   ❌ Error checking chat {chat_id}: {e}")
                continue
        
        # Remove duplicates
        active_groups = list(set(active_groups))
        
        print(f"   📢 Found: {len(active_groups)} groups, {len(private_chats)} private chats")
        
        # Send to groups
        for chat_id in active_groups:
            try:
                # Check last greeting time (minimum 4 hours gap)
                last_greeted = greeted_groups.get(chat_id)
                if last_greeted:
                    hours_since = (datetime.now() - last_greeted).seconds // 3600
                    if hours_since < 4:
                        print(f"   ⏳ Skipping {chat_id} - greeted {hours_since} hours ago")
                        continue
                
                # Get group info
                chat = await bot.get_chat(chat_id)
                group_name = chat.title or "Group"
                
                # Get AI greeting
                greeting_text = await get_ai_greeting(current_period, group_name)
                
                # Add variation
                variations = [
                    f"{greeting_text}\n\n✨ *From your sweet Alita* 🎀",
                    f"{greeting_text}\n\n💖 *Sending love to {group_name}* 💕",
                    f"{greeting_text}\n\n🌟 *Have a wonderful {current_period}!* 🫂"
                ]
                
                final_message = random.choice(variations)
                
                # Send sticker
                if current_period in GREETING_STICKERS and random.random() > 0.5:
                    sticker_id = random.choice(GREETING_STICKERS[current_period])
                    await bot.send_sticker(chat_id, sticker_id)
                    await asyncio.sleep(0.5)
                
                # Send greeting
                await bot.send_message(
                    chat_id=chat_id,
                    text=final_message,
                    parse_mode="Markdown"
                )
                
                # Update last greeted time
                greeted_groups[chat_id] = datetime.now()
                
                print(f"   ✅ Sent {current_period} greeting to: {group_name}")
                await asyncio.sleep(1)  # Avoid flooding
                
            except Exception as e:
                print(f"   ❌ Error greeting group {chat_id}: {e}")
                continue
        
        # Send to private chats (less frequent)
        for user_id in private_chats:
            try:
                # Check last greeting time (minimum 8 hours gap for private)
                last_greeted = greeted_groups.get(user_id)
                if last_greeted:
                    hours_since = (datetime.now() - last_greeted).seconds // 3600
                    if hours_since < 8:
                        continue
                
                # Get user info
                user = await bot.get_chat(user_id)
                user_name = user.first_name or "Friend"
                
                # Personalized greeting
                private_greetings = [
                    f"✨ Hello {user_name}! Just wanted to wish you a lovely {current_period}! 💖",
                    f"🎀 Hey {user_name}! Hope you're having a beautiful {current_period}! 🌸",
                    f"💫 Good {current_period}, {user_name}! Thinking of you! 😊",
                    f"🌟 {current_period.capitalize()} greetings, {user_name}! Stay awesome! 💕"
                ]
                
                final_message = random.choice(private_greetings)
                
                # Send greeting
                await bot.send_message(
                    chat_id=user_id,
                    text=final_message,
                    parse_mode="Markdown"
                )
                
                # Update last greeted time
                greeted_groups[user_id] = datetime.now()
                
                print(f"   💌 Sent {current_period} greeting to private: {user_name}")
                await asyncio.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                print(f"   ❌ Error greeting user {user_id}: {e}")
                continue
                
    except Exception as e:
        print(f"❌ Greeting system error: {e}")

async def start_greeting_task():
    """Start the automated greeting scheduler"""
    print("🕐 Starting automated greeting system...")
    
    # Clear any existing jobs
    if greeting_scheduler.running:
        greeting_scheduler.shutdown()
    
    # Schedule greetings for every hour
    greeting_scheduler.add_job(
        send_time_based_greetings,
        CronTrigger(minute=0, hour='*'),  # Every hour at minute 0
        id='hourly_greetings',
        replace_existing=True
    )
    
    # DEBUG: More frequent check if DEBUG_MODE is enabled
    if os.getenv("DEBUG_MODE", "false").lower() == "true":
        print("🔧 DEBUG MODE: Adding 5-minute check")
        greeting_scheduler.add_job(
            send_time_based_greetings,
            'interval',
            minutes=5,
            id='debug_check',
            replace_existing=True
        )
    
    greeting_scheduler.start()
    print("✅ Greeting scheduler started!")

# --- TEST COMMANDS ---
@dp.message(Command("testgreet"))
async def test_greeting(message: Message):
    """Test the greeting system"""
    if message.chat.type == "private" or message.from_user.id == ADMIN_ID:
        current_period = get_current_time_period()
        current_time = get_indian_time().strftime("%I:%M %p")
        
        await message.reply(
            f"🎀 **Testing Greeting System**\n\n"
            f"• Time Period: {current_period}\n"
            f"• Current Time: {current_time}\n"
            f"• Status: Running...",
            parse_mode="Markdown"
        )
        
        await send_time_based_greetings()
        await message.reply("✅ Test completed!")
    else:
        await message.reply("❌ Only admin can use this command!")

@dp.message(Command("greetnow"))
async def greet_now(message: Message):
    """Send greeting immediately"""
    if message.chat.type == "private" or message.from_user.id == ADMIN_ID:
        current_period = get_current_time_period()
        chat_name = message.chat.title or message.from_user.first_name
        
        greeting_text = await get_ai_greeting(current_period, chat_name)
        
        await message.reply(
            f"🎀 **Immediate Greeting**\n\n{greeting_text}\n\n✨ *From Alita*",
            parse_mode="Markdown"
        )
    else:
        await message.reply("❌ Only in private chat or admin can use!")

# --- AUTO-MODERATION CONFIGURATION ---
SPAM_LIMIT = 5  # Messages per 10 seconds
GROUP_LINK_PATTERNS = [
    r't\.me/joinchat/',
    r't\.me/\+\w+',
    r'joinchat/\w+',
    r't\.me/\w{5,}',
    r'telegram\.(me|dog)/(joinchat/|\+)',
    r'https?://(t|telegram)\.(me|dog)/(joinchat/|\+)'
]

BAD_WORDS = [
    'mc', 'bc', 'madarchod', 'bhosdike', 'chutiya', 'gandu', 'lund', 'bhenchod',
    'fuck', 'shit', 'asshole', 'bastard', 'bitch', 'dick', 'piss', 'pussy',
]

WARNING_MESSAGES = [
    "⚠️ **Warning {count}/3**\nHey {name}, please don't {action}!",
    "🚫 **Warning {count}/3**\n{name}, {action} is not allowed here!",
    "👮 **Warning {count}/3**\n{name}, please follow group rules!",
    "⚡ **Warning {count}/3**\n{name}, stop {action} immediately!",
]

MUTE_DURATIONS = {
    1: timedelta(minutes=15),    # First offense
    2: timedelta(hours=1),       # Second offense
    3: timedelta(hours=24)       # Third offense
}

# --- STATES FOR GAMES ---
class GameStates(StatesGroup):
    playing_quiz = State()
    playing_riddle = State()
    playing_word = State()
    waiting_answer = State()

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
    if user_id:
        # Try to get from MongoDB first
        try:
            user_data = asyncio.run(get_user_data(user_id))
            if user_data and 'emotion' in user_data:
                emotion_type = user_data['emotion']
        except:
            pass
    
    if emotion_type and emotion_type in EMOTIONAL_RESPONSES:
        return random.choice(EMOTIONAL_RESPONSES[emotion_type])
    
    all_emotions = list(EMOTIONAL_RESPONSES.values())
    return random.choice(random.choice(all_emotions))

async def update_user_emotion(user_id: int, message: str):
    message_lower = message.lower()
    
    if any(word in message_lower for word in ['love', 'pyaar', 'dil', 'heart', 'cute', 'beautiful', 'sweet']):
        await update_user_emotion_db(user_id, "love")
    elif any(word in message_lower for word in ['angry', 'gussa', 'naraz', 'mad', 'hate', 'idiot', 'stupid']):
        await update_user_emotion_db(user_id, "angry")
    elif any(word in message_lower for word in ['cry', 'ro', 'sad', 'dukh', 'upset', 'unhappy', 'depressed']):
        await update_user_emotion_db(user_id, "crying")
    elif any(word in message_lower for word in ['funny', 'has', 'joke', 'comedy', 'masti', 'laugh', 'haha']):
        await update_user_emotion_db(user_id, "funny")
    elif any(word in message_lower for word in ['hi', 'hello', 'hey', 'namaste', 'kaise', 'welcome']):
        await update_user_emotion_db(user_id, "happy")
    elif any(word in message_lower for word in ['?', 'kyun', 'kaise', 'kya', 'how', 'why', 'what']):
        await update_user_emotion_db(user_id, "thinking")
    elif any(word in message_lower for word in ['fight', 'ladai', 'war', 'attack', 'defend']):
        await update_user_emotion_db(user_id, "protective")
    elif any(word in message_lower for word in ['sleep', 'sone', 'neend', 'tired', 'thak']):
        await update_user_emotion_db(user_id, "sleepy")
    else:
        emotions = list(EMOTIONAL_RESPONSES.keys())
        await update_user_emotion_db(user_id, random.choice(emotions))

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
    # Get warnings from MongoDB
    warning_data = await add_warning(user_id, chat_id, reason)
    warning_count = warning_data["count"]
    
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
            await reset_warnings(user_id, chat_id)
            
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
            f"{get_emotion('angry')} Oye! Language! Main ladki hu, aise baat mat karo!",
            f"{get_emotion('sassy')} Areey! Kitne badtameez ho tum! Main bhi jawab de sakti hu!",
            f"{get_emotion('protective')} Apni language thik rakho warna main bhi bolungi!",
            f"{get_emotion('crying')} Itna gussa kyun aata hai? Achi baat karo na!",
            f"{get_emotion('sassy')} Tumhe pata hai main kya bol sakti hu? Par main sweet hu na!"
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

# --- GAME DATABASES ---
QUIZ_QUESTIONS = [
    {"question": "Hinglish me kitne letters hote hain?", "answer": "26", "hint": "English jitne hi"},
    {"question": "Aam ka English kya hota hai?", "answer": "mango", "hint": "Ek fruit"},
    {"question": "2 + 2 × 2 = ?", "answer": "6", "hint": "PEMDAS rule yaad rakho"},
    {"question": "India ka capital kya hai?", "answer": "new delhi", "hint": "Yeh to pata hi hoga"},
    {"question": "Python kisne banaya?", "answer": "guido van rossum", "hint": "Ek Dutch programmer"},
    {"question": "ChatGPT kis company ki hai?", "answer": "openai", "hint": "Elon Musk bhi involved tha"},
    {"question": "Hinglish ka matlab kya hai?", "answer": "hindi + english", "hint": "Do languages ka mix"},
    {"question": "Telegram kisne banaya?", "answer": "pavel durov", "hint": "Russian entrepreneur"},
    {"question": "Ek year me kitne months hote hain?", "answer": "12", "hint": "Calendar dekho"},
    {"question": "Water ka chemical formula?", "answer": "h2o", "hint": "H do, O ek"}
]

RIDDLES = [
    {"riddle": "Aane ke baad kabhi nahi jata?", "answer": "umar", "hint": "Har roz badhta hai"},
    {"riddle": "Chidiya ki do aankhen, par ek hi nazar aata hai?", "answer": "needle", "hint": "Sui ki nook"},
    {"riddle": "Aisa kaun sa cheez hai jo sukha ho toh 2 kilo, geela ho toh 1 kilo?", "answer": "sukha", "hint": "Word play hai"},
    {"riddle": "Mere paas khane wala hai, peene wala hai, par khata peeta koi nahi?", "answer": "khana pina", "hint": "Restaurant menu"},
    {"riddle": "Ek ghar me 5 room hain, har room me 5 billi hain, har billi ke 5 bacche hain, total kitne legs?", "answer": "0", "hint": "Billi ke legs nahi hote"},
    {"riddle": "Jisne pehna woh nahi khareeda, jisne khareeda woh nahi pehna?", "answer": "kafan", "hint": "Antim vastra"},
    {"riddle": "Subah utha to gaya, raat ko aaya to gaya?", "answer": "suraj", "hint": "Din raat ka cycle"},
    {"riddle": "Jiske paas ho woh nahi janta, jaanne wala ke paas nahi hota?", "answer": "andha", "hint": "Dekh nahi sakta"}
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
    "😹 Boy: I love you! Girl: Tumhare paas girlfriend nahi hai? Boy: Haan, tumhare saath hi baat kar raha hu!",
    "🤣 Student: Sir, main kal school nahi aa paunga. Teacher: Kyun? Student: Kal meri sister ki shaadi hai. Teacher: Accha? Kaunsi sister? Student: Aapki beti sir!",
    "😂 Wife: Agar main mar jaun toh tum dobara shaadi karoge? Husband: Nahi. Wife: Aww pyaar! Husband: Nahi, ek biwi ka kharcha hi bahut hai!",
    "😆 Customer: Isme sugar hai? Shopkeeper: Nahi sir. Customer: Salt? Shopkeeper: Nahi. Customer: To phir kya hai? Shopkeeper: Bill sir!",
]

# --- NEW FEATURES: COMMAND HANDLERS ---

# Search Command
@dp.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject):
    """Search the web using DuckDuckGo"""
    query = command.args
    
    if not query:
        await message.reply(
            f"{get_emotion('thinking')} **Search Command**\n\n"
            f"Usage: `/search your query`\n"
            f"Example: `/search latest movies 2024`\n\n"
            f"*Main aapke liye dhoond ke laungi!* 🔍",
            parse_mode="Markdown"
        )
        return
    
    await message.reply(f"{get_emotion('thinking')} Searching for '{query}'... 🔍")
    
    try:
        results = await duckduckgo_search(query, max_results=3)
        
        if not results:
            await message.reply(
                f"{get_emotion('crying')} Kuch nahi mila! Kya aapka query sahi hai? 🤔\n"
                f"*Try different keywords maybe?*"
            )
            return
        
        response = f"{get_emotion('happy')} **Search Results for '{query}':**\n\n"
        
        for i, result in enumerate(results, 1):
            title = result.get('title', 'No title')
            body = result.get('body', 'No description')
            link = result.get('link', '#')
            
            # Shorten long descriptions
            if len(body) > 150:
                body = body[:147] + "..."
            
            response += f"**{i}. {title}**\n"
            response += f"{body}\n"
            response += f"🔗 [Read More]({link})\n\n"
        
        response += "*Powered by DuckDuckGo* 🦆"
        
        await message.reply(response, parse_mode="Markdown", disable_web_page_preview=True)
        
    except Exception as e:
        await message.reply(
            f"{get_emotion('crying')} Oops! Search failed. Error: {str(e)[:100]}",
            parse_mode="Markdown"
        )

# TTS Command
@dp.message(Command("tts"))
async def cmd_tts(message: Message):
    """Convert text to speech"""
    if not message.reply_to_message:
        await message.reply(
            f"{get_emotion('thinking')} **TTS Command**\n\n"
            f"Reply to a message with `/tts` to convert it to voice!\n"
            f"*Main use sweet voice mein bana dungi!* 🎤",
            parse_mode="Markdown"
        )
        return
    
    text_to_convert = message.reply_to_message.text or message.reply_to_message.caption
    
    if not text_to_convert:
        await message.reply(
            f"{get_emotion('crying')} Kuch text to reply karo na! 📝\n"
            f"*Text message par reply karo /tts command ke saath!*"
        )
        return
    
    # Limit text length
    if len(text_to_convert) > 500:
        text_to_convert = text_to_convert[:497] + "..."
    
    await message.reply(f"{get_emotion()} Creating voice note... 🎤")
    
    try:
        # Choose voice based on language
        if any(char in text_to_convert for char in ['ा', 'ी', 'ू', 'े', 'ो', 'अ', 'आ', 'इ']):
            voice = "hi-IN-SwaraNeural"  # Hindi voice
        else:
            voice = "en-IN-NeerjaExpressiveNeural"  # English voice with Indian accent
        
        # Generate voice file
        voice_file = await text_to_speech(text_to_convert, voice)
        
        if not voice_file or not os.path.exists(voice_file):
            raise Exception("Voice file not created")
        
        # Send voice note
        voice_input = FSInputFile(voice_file, filename="alita_voice.mp3")
        await message.reply_voice(
            voice=voice_input,
            caption=f"{get_emotion('happy')} **Alita ki sweet voice!** 🎀\n\n"
                   f"*Text:* {text_to_convert[:100]}...\n"
                   f"*Voice:* {'Hindi' if 'hi-IN' in voice else 'English'}"
        )
        
        # Clean up
        os.remove(voice_file)
        
    except Exception as e:
        await message.reply(
            f"{get_emotion('crying')} Voice create nahi ho paya! 😢\n"
            f"*Error:* {str(e)[:100]}"
        )

# Draw/Image Generation Command
@dp.message(Command("draw"))
async def cmd_draw(message: Message, command: CommandObject):
    """Generate image from text"""
    prompt = command.args
    
    if not prompt:
        await message.reply(
            f"{get_emotion('thinking')} **Draw Command**\n\n"
            f"Usage: `/draw your imagination`\n"
            f"Example: `/draw a beautiful sunset in mountains`\n\n"
            f"*Main aapki imagination ko picture bana dungi!* 🎨",
            parse_mode="Markdown"
        )
        return
    
    await message.reply(f"{get_emotion()} Creating your image... 🎨")
    
    try:
        # Generate image
        image_file = await generate_image(prompt)
        
        if not image_file or not os.path.exists(image_file):
            raise Exception("Image file not created")
        
        # Send image
        image_input = FSInputFile(image_file, filename="alita_art.jpg")
        await message.reply_photo(
            photo=image_input,
            caption=f"{get_emotion('happy')} **Tada! Alita ki art!** 🎨\n\n"
                   f"*Prompt:* {prompt}\n"
                   f"*Powered by:* Pollinations.ai ✨"
        )
        
        # Clean up
        os.remove(image_file)
        
    except Exception as e:
        await message.reply(
            f"{get_emotion('crying')} Image create nahi ho payi! 😢\n"
            f"*Error:* {str(e)[:100]}\n\n"
            f"*Try a different prompt maybe?*"
        )

# Social Media Downloader Handler
@dp.message(F.text)
async def handle_social_media(message: Message):
    """Handle social media links"""
    text = message.text or message.caption
    
    if not text:
        return
    
    # Check if it's a social media link
    if await downloader.is_social_media_link(text):
        try:
            # Extract link
            url = await downloader.extract_link(text)
            if not url:
                return
            
            # Send downloading message
            status_msg = await message.reply(
                f"{get_emotion()} Downloading from {downloader.get_platform(url)}... ⬇️\n"
                f"*Please wait, processing video...*"
            )
            
            # Download media
            file_path = await downloader.download_media(url)
            
            if not file_path or not os.path.exists(file_path):
                await status_msg.edit_text(
                    f"{get_emotion('crying')} Download failed! 😢\n"
                    f"*Link might be private or unsupported*"
                )
                return
            
            # Check file size (Telegram limit is 50MB for bots)
            file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
            
            if file_size > 50:
                await status_msg.edit_text(
                    f"{get_emotion('crying')} File too big! ({file_size:.1f}MB) 😢\n"
                    f"*Telegram allows max 50MB for bots*"
                )
                os.remove(file_path)
                return
            
            # Send the file
            file_input = FSInputFile(file_path)
            
            if file_path.endswith(('.mp4', '.mov', '.avi', '.mkv')):
                await message.reply_video(
                    video=file_input,
                    caption=f"{get_emotion('happy')} **Downloaded Successfully!** ✅\n"
                           f"*From:* {downloader.get_platform(url).title()}\n"
                           f"*Size:* {file_size:.1f}MB\n\n"
                           f"*Enjoy!* 🎬",
                    reply_to_message_id=message.message_id
                )
            else:
                await message.reply_document(
                    document=file_input,
                    caption=f"{get_emotion('happy')} **Downloaded Successfully!** ✅\n"
                           f"*From:* {downloader.get_platform(url).title()}\n"
                           f"*Size:* {file_size:.1f}MB"
                )
            
            # Clean up
            os.remove(file_path)
            await status_msg.delete()
            
        except Exception as e:
            error_msg = await message.reply(
                f"{get_emotion('crying')} Download failed! 😢\n"
                f"*Error:* {str(e)[:100]}"
            )
            # Clean up temp files
            temp_dir = message.from_user.id  # Using user ID as reference
            if os.path.exists(f"temp_{temp_dir}"):
                shutil.rmtree(f"temp_{temp_dir}")

# --- QUICK RESPONSES ---
QUICK_RESPONSES = {
    'goodbye': [
        "Bye bye! Phir milenge! 👋",
        "Take care! Miss karungi! 💕",
        "Alvida! Accha raho! 🌟",
        "Chalo bye! Baad me baat karte hain! 💫",
        "Jaate jaate smile karo! 😊"
    ],
    'thanks': [
        "Aww, you're welcome! 💖",
        "Koi baat nahi! Main hamesha tumhare liye hu! 😊",
        "Mujhe achha laga help kar ke! 💕",
        "Always here for you! 🫂"
    ],
    'sorry': [
        "Koi baat nahi! Sab theek ho jayega! 🤗",
        "Chhodo yaar! Main bhi to galti karti hu! 😊",
        "No worries! Friendship main sab chalta hai! 💖",
        "Maaf karo, par yaad rakhna main tumhari dost hu! 🌸",
        "It's okay! Aage se dhyan rakhna! ✨"
    ]
}

# --- COMMAND RESPONSES ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌟 My Channel", url="https://t.me/abhi0w0"),
            InlineKeyboardButton(text="💝 Developer", url="https://t.me/a6h1ii")
        ],
        [
            InlineKeyboardButton(text="🎮 Play Games", callback_data="help_games"),
            InlineKeyboardButton(text="🛡️ Safety Tips", callback_data="safety_tips")
        ],
        [
            InlineKeyboardButton(text="💬 Talk to Alita", callback_data="talk_alita")
        ],
        [
            InlineKeyboardButton(text="🔍 Search Web", callback_data="search_web"),
            InlineKeyboardButton(text="🎨 Draw AI", callback_data="draw_ai")
        ]
    ])
    
    welcome_text = (
        f"{get_emotion('love')} **Hii! I'm Alita 🎀**\n\n"
        
        "✨ **Welcome to my magical world!** ✨\n\n"
        
        "💖 *Main hu Alita... Ek sweet, aur protective girl!* 😊\n"
        "🎯 *Main batein bhi krti hu 🙈 or group ko manage bhi krti hu!* 🛡️\n\n"
        
        "🌟 **AI Features:**\n"
        "• 🔍 Web Search with /search\n"
        "• 🎤 Text-to-Speech with /tts\n"
        "• 🎨 AI Image Generation with /draw\n"
        "• ⬇️ Social Media Downloader (Auto)\n"
        "• 💾 MongoDB Storage for data\n\n"
        
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
            InlineKeyboardButton(text="🎮 Games", callback_data="help_games"),
            InlineKeyboardButton(text="🛡️ Admin", callback_data="help_admin")
        ],
        [
            InlineKeyboardButton(text="😊 Fun", callback_data="help_fun"),
            InlineKeyboardButton(text="🌤️ Weather", callback_data="help_weather")
        ],
        [
            InlineKeyboardButton(text="🎨 AI Tools", callback_data="help_ai"),
            InlineKeyboardButton(text="⬇️ Download", callback_data="help_download")
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
        "• /game - Play games 🎮\n"
        "• /clear - Clear memory 🧹\n\n"
        
        "🎨 **AI FEATURES:**\n"
        "• /search [query] - Web search 🔍\n"
        "• /draw [prompt] - Generate images 🎨\n"
        "• /tts (reply) - Text to speech 🎤\n"
        "• Auto-download IG/YT/Pinterest ⬇️\n\n"
        
        "🕒 **TIME & WEATHER:**\n"
        "• /time - Indian time 🕐\n"
        "• /date - Today's date 📅\n"
        "• /weather - Weather info 🌤️\n\n"
        
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
        "• Auto time-based greetings ⏰\n"
        "• Works in groups & private 💌\n\n"
        
        "---\n"
        "**Developer:** ABHI🔱 (@a6h1ii)\n"
        "**Channel:** @abhi0w0 💫\n"
        "---"
    )
    await message.reply(help_text, parse_mode="Markdown", reply_markup=keyboard)

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
    joke = random.choice(JOKES)
    await message.reply(f"{get_emotion('funny')} {joke}")

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

# Weather data
WEATHER_DATA = {
    "mumbai": {"temp": "32°C", "condition": "Sunny ☀️", "humidity": "65%", "wind": "12 km/h"},
    "delhi": {"temp": "28°C", "condition": "Partly Cloudy ⛅", "humidity": "55%", "wind": "10 km/h"},
    "bangalore": {"temp": "26°C", "condition": "Light Rain 🌦️", "humidity": "70%", "wind": "8 km/h"},
    "kolkata": {"temp": "30°C", "condition": "Humid 💦", "humidity": "75%", "wind": "9 km/h"},
    "chennai": {"temp": "33°C", "condition": "Hot 🔥", "humidity": "68%", "wind": "11 km/h"},
    "hyderabad": {"temp": "29°C", "condition": "Clear 🌤️", "humidity": "60%", "wind": "10 km/h"},
    "ahmedabad": {"temp": "31°C", "condition": "Sunny ☀️", "humidity": "58%", "wind": "13 km/h"},
    "pune": {"temp": "27°C", "condition": "Pleasant 😊", "humidity": "62%", "wind": "7 km/h"},
    "jaipur": {"temp": "30°C", "condition": "Sunny ☀️", "humidity": "52%", "wind": "14 km/h"},
    "lucknow": {"temp": "29°C", "condition": "Clear 🌤️", "humidity": "61%", "wind": "9 km/h"},
    "chandigarh": {"temp": "27°C", "condition": "Pleasant 🌸", "humidity": "59%", "wind": "8 km/h"},
    "goa": {"temp": "31°C", "condition": "Beach Weather 🏖️", "humidity": "73%", "wind": "15 km/h"}
}

async def get_weather_info(city: str = None):
    if not city:
        default_cities = list(WEATHER_DATA.keys())
        city = random.choice(default_cities)
    
    city_lower = city.lower()
    
    for city_key in WEATHER_DATA.keys():
        if city_key in city_lower or city_lower in city_key:
            weather = WEATHER_DATA[city_key]
            return (
                f"🌤️ **Weather in {city_key.title()}**\n"
                f"• Temperature: {weather['temp']}\n"
                f"• Condition: {weather['condition']}\n"
                f"• Humidity: {weather['humidity']}\n"
                f"• Wind: {weather['wind']}\n"
                f"• Updated: Just now 🌟\n\n"
                f"*Stay hydrated!* 💧"
            )
    
    random_city = random.choice(list(WEATHER_DATA.keys()))
    weather = WEATHER_DATA[random_city]
    return (
        f"🌤️ **Weather Info**\n"
        f"Couldn't find '{city}'. Here's {random_city.title()} weather:\n"
        f"• Temperature: {weather['temp']}\n"
        f"• Condition: {weather['condition']}\n"
        f"• Humidity: {weather['humidity']}\n"
        f"• Wind: {weather['wind']}\n\n"
        f"*Try: Mumbai, Delhi, Bangalore, etc.* ✨"
    )

@dp.message(Command("weather"))
async def cmd_weather(message: Message):
    city = None
    if len(message.text.split()) > 1:
        city = ' '.join(message.text.split()[1:])
    
    weather_info = await get_weather_info(city)
    await message.reply(weather_info, parse_mode="Markdown")

@dp.message(Command("game"))
async def cmd_game(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎯 Word Chain", callback_data="game_word"),
            InlineKeyboardButton(text="🧠 Quiz", callback_data="game_quiz")
        ],
        [
            InlineKeyboardButton(text="🤔 Riddles", callback_data="game_riddle"),
            InlineKeyboardButton(text="🎮 All Games", callback_data="game_all")
        ]
    ])
    
    await message.reply(
        f"{get_emotion('happy')} **Let's Play Games! 🎮**\n\n"
        "Choose a game to play:\n"
        "• 🎯 Word Chain - Chain words game\n"
        "• 🧠 Quiz - Test your knowledge\n"
        "• 🤔 Riddles - Solve tricky riddles\n"
        "• 🎮 All Games - See all options\n\n"
        "Select one to start!",
        reply_markup=keyboard
    )

# Word game functions
def start_word_game(user_id: int):
    start_words = ["PYTHON", "APPLE", "TIGER", "ELEPHANT", "RAINBOW", "COMPUTER", "TELEGRAM", "BOT"]
    start_word = random.choice(start_words)
    
    game_sessions[user_id] = {
        "game": "word_chain",
        "last_word": start_word.lower(),
        "score": 0,
        "words_used": [start_word.lower()],
        "last_letter": start_word[-1].lower(),
        "started_at": datetime.now()
    }
    
    return start_word

def check_word_game(user_id: int, user_word: str):
    if user_id not in game_sessions:
        return False, "No active game! Start with /game"
    
    game_data = game_sessions[user_id]
    user_word_lower = user_word.lower().strip()
    
    if not user_word_lower.startswith(game_data["last_letter"]):
        return False, f"Word must start with '{game_data['last_letter'].upper()}'!"
    
    if user_word_lower in game_data["words_used"]:
        return False, f"'{user_word}' already used! Try different word."
    
    if len(user_word_lower) < 3:
        return False, "Word must be at least 3 letters!"
    
    game_data["words_used"].append(user_word_lower)
    game_data["last_word"] = user_word_lower
    game_data["last_letter"] = user_word_lower[-1]
    game_data["score"] += 10
    
    return True, game_data

# --- MESSAGE HANDLER WITH AUTO-MODERATION ---
@dp.message()
async def handle_all_messages(message: Message, state: FSMContext):
    if not message.text or not message.from_user:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_text = message.text
    
    # Ignore if bot is checking
    if user_id == bot.id:
        return
    
    # Update interaction time in MongoDB
    await get_user_data(user_id, chat_id)
    
    # Initialize memory for chat if not exists
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=50)
    
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
    
    # --- GAME HANDLING ---
    if user_id in game_sessions and game_sessions[user_id]["game"] == "word_chain":
        is_valid, result = check_word_game(user_id, user_text)
        
        if is_valid:
            game_data = result
            next_letter = game_data["last_letter"].upper()
            score = game_data["score"]
            
            await message.reply(
                f"{get_emotion('happy')} **✅ Correct!**\n\n"
                f"• Your word: {user_text.upper()}\n"
                f"• Next letter: **{next_letter}**\n"
                f"• Your score: **{score} points**\n\n"
                f"Now give me a word starting with **{next_letter}**\n"
                f"Or type 'stop' to end game.",
                parse_mode="Markdown"
            )
            return
        else:
            if user_text.lower() == 'stop':
                if user_id in game_sessions:
                    score = game_sessions[user_id]["score"]
                    words_count = len(game_sessions[user_id]["words_used"])
                    del game_sessions[user_id]
                    await message.reply(
                        f"{get_emotion()} **🏁 Game Ended!**\n\n"
                        f"• Final Score: **{score} points**\n"
                        f"• Words used: **{words_count}**\n\n"
                        f"Well played! Play again with /game 🎮",
                        parse_mode="Markdown"
                    )
                    return
            else:
                await message.reply(
                    f"{get_emotion('crying')} **❌ {result}**\n\n"
                    f"Game over! Play again with /game 🎮",
                    parse_mode="Markdown"
                )
                if user_id in game_sessions:
                    del game_sessions[user_id]
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
        await update_user_emotion(user_id, user_text)
    
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

# --- CALLBACK QUERY HANDLERS ---
@dp.callback_query(F.data.startswith("game_"))
async def game_callback(callback: types.CallbackQuery):
    game_type = callback.data.split("_")[1]
    
    if game_type == "word":
        start_word = start_word_game(callback.from_user.id)
        await callback.message.edit_text(
            f"{get_emotion('happy')} **🎯 Word Chain Game Started!**\n\n"
            f"Starting word: **{start_word}**\n"
            f"Last letter: **{start_word[-1]}**\n\n"
            f"Now send me a word starting with **{start_word[-1]}**\n"
            f"Type 'stop' to end game.",
            parse_mode="Markdown"
        )
    elif game_type == "quiz":
        await callback.message.edit_text(
            f"{get_emotion('thinking')} **🧠 Quiz Coming Soon!**\n\n"
            f"This feature will be added in the next update! ✨\n"
            f"Try the Word Chain game for now! 🎯"
        )
    elif game_type == "riddle":
        await callback.message.edit_text(
            f"{get_emotion('surprise')} **🤔 Riddles Coming Soon!**\n\n"
            f"This feature will be added in the next update! ✨\n"
            f"Try the Word Chain game for now! 🎯"
        )
    elif game_type == "all":
        await callback.message.edit_text(
            f"{get_emotion('happy')} **🎮 All Games**\n\n"
            f"Available games:\n"
            f"• 🎯 Word Chain - Active ✅\n"
            f"• 🧠 Quiz - Coming soon ⏳\n"
            f"• 🤔 Riddles - Coming soon ⏳\n\n"
            f"More games will be added soon! 💫"
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("help_"))
async def help_callback(callback: types.CallbackQuery):
    help_type = callback.data.split("_")[1]
    
    if help_type == "ai":
        text = (
            f"{get_emotion('happy')} **🎨 AI Tools Help**\n\n"
            f"🔍 **/search [query]**\n"
            f"Search the web for information\n"
            f"Example: `/search latest movies`\n\n"
            f"🎨 **/draw [prompt]**\n"
            f"Generate AI images from text\n"
            f"Example: `/draw sunset beach`\n\n"
            f"🎤 **/tts** (reply to message)\n"
            f"Convert text to sweet voice note\n"
            f"Just reply to any text message!\n\n"
            f"*All features are FREE!* ✨"
        )
    elif help_type == "download":
        text = (
            f"{get_emotion('happy')} **⬇️ Downloader Help**\n\n"
            f"**Supported Platforms:**\n"
            f"• Instagram (Posts/Reels)\n"
            f"• YouTube (Videos/Shorts)\n"
            f"• Pinterest (Pins/Videos)\n\n"
            f"**How to use:**\n"
            f"Just send the link in chat!\n"
            f"I'll automatically download it.\n\n"
            f"**Features:**\n"
            f"• Auto-detection of links\n"
            f"• High quality downloads\n"
            f"• File size checking\n"
            f"• Clean up after sending\n\n"
            f"*Max file size: 50MB* 📦"
        )
    else:
        text = (
            f"{get_emotion()} **Help Section**\n\n"
            f"Select a category from the menu!\n"
            f"Or use `/help` for complete list.\n\n"
            f"*I'm here to help you!* 💖"
        )
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

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
    
    # Get active users from MongoDB
    try:
        three_days_ago = datetime.now() - timedelta(days=3)
        
        async for user in user_collection.find({
            "last_interaction": {"$gte": three_days_ago}
        }).limit(100):
            user_id = user.get("user_id")
            if user_id:
                try:
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
    except Exception as e:
        print(f"Daily reminder error: {e}")

# --- CLEANUP FUNCTION ---
async def cleanup_temp_files():
    """Clean up temporary files"""
    try:
        # Remove old temp files (older than 1 hour)
        for filename in os.listdir('.'):
            if filename.startswith('temp_'):
                file_time = datetime.fromtimestamp(os.path.getctime(filename))
                if (datetime.now() - file_time).seconds > 3600:
                    os.remove(filename)
                    print(f"🧹 Cleaned up: {filename}")
    except:
        pass

# --- DEPLOYMENT HANDLER ---
async def handle_ping(request):
    return web.Response(text="🤖 Alita is Alive! 🛡️")

async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Health server started on port {PORT}")

async def main():
    print("=" * 50)
    print("🎀 ALITA - STARTING UP...")
    print("=" * 50)
    print(f"🔧 Using PORT: {PORT}")
    print(f"🔧 Using TOKEN: {TOKEN[:10]}...")  # First 10
    asyncio.create_task(start_server())
    # **IMPORTANT: Pehle webhook clear karo forcefully**
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook cleared forcefully!")
    except Exception as e:
        print(f"⚠️ Webhook clear error: {e}")
    
    # **Bot info check karo**
    me = await bot.get_me()
    print(f"🤖 Bot Info:")
    print(f"• Name: {me.first_name}")
    print(f"• Username: @{me.username}")
    print(f"• ID: {me.id}")
    
    # **MongoDB connection check**
    try:
        await mongo_client.admin.command('ping')
        print("✅ MongoDB Connected!")
    except Exception as e:
        print(f"⚠️ MongoDB: {e}")
    
    # **Start polling with error handling**
    print("\n🔄 Starting bot polling...")
    print("=" * 50)
    
    # **Polling start karo with proper parameters**
    await dp.start_polling(
        bot, 
        allowed_updates=dp.resolve_used_update_types(),
        skip_updates=True  # **Important: Old updates skip karo**
    )

if __name__ == "__main__":
    # ***** PORT *****
    print(f"🚀 Starting bot on PORT: {PORT}")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        import traceback
        traceback.print_exc()
