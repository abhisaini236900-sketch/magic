import os
import asyncio
import random
import re
import uuid
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from groq import AsyncGroq
from aiohttp import web, ClientSession
import pytz
import motor.motor_asyncio
import aiofiles
from PIL import Image
import io
import base64

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://abhisheksaini32320_db_user:HwR1Bkn1ekRzdYp3@cluster0.pjxwgsw.mongodb.net/?appName=Cluster0")
PORT = int(os.getenv("PORT", 10000))

# Timezone for India
INDIAN_TIMEZONE = pytz.timezone('Asia/Kolkata')

# Initialize with MemoryStorage
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# Initialize Groq client
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Initialize MongoDB
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
db = mongo_client.telegram_bot
users_collection = db.users
broadcast_collection = db.broadcasts
stats_collection = db.stats

# Memory: {chat_id: deque}
chat_memory: Dict[int, deque] = {}

# Game states storage: {user_id: game_data}
active_games: Dict[int, Dict] = {}
game_sessions: Dict[int, Dict] = {}  # Store game sessions separately

# Emotional states for each user
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}
user_message_count: Dict[int, int] = {}  # For spam detection
group_link_counts: Dict[int, Dict[int, int]] = {}  # {chat_id: {user_id: count}}

# States for games
class GameStates(StatesGroup):
    playing_quiz = State()
    playing_riddle = State()
    playing_word = State()
    waiting_answer = State()
    truth_dare = State()

# --- HUMAN-LIKE BEHAVIOUR IMPROVEMENTS ---

# Emotional responses with emojis
EMOTIONAL_RESPONSES = {
    "happy": ["😊", "🎉", "🥳", "🌟", "✨", "👍", "💫", "😄", "😍", "🤗", "🫂"],
    "angry": ["😠", "👿", "💢", "🤬", "😤", "🔥", "⚡", "💥", "👊", "🖕"],
    "crying": ["😢", "😭", "💔", "🥺", "😞", "🌧️", "😿", "🥀", "💧", "🌩️"],
    "love": ["❤️", "💖", "💕", "🥰", "😘", "💋", "💓", "💗", "💘", "💝"],
    "funny": ["😂", "🤣", "😆", "😜", "🤪", "🎭", "🤡", "🃏", "🎪", "🤹"],
    "thinking": ["🤔", "💭", "🧠", "🔍", "💡", "🎯", "🧐", "🔎", "💬", "🗨️"],
    "surprise": ["😲", "🤯", "🎊", "🎁", "💥", "✨", "🎆", "🎇", "🧨", "💫"],
    "sleepy": ["😴", "💤", "🌙", "🛌", "🥱", "😪", "🌃", "🌜", "🌚", "🌌"],
    "hungry": ["😋", "🤤", "🍕", "🍔", "🍟", "🌮", "🍦", "🍩", "🍪", "🍰"]
}

# Stickers for spontaneous sending
CUTE_STICKERS = [
    "CAACAgIAAxkBAAEL5LdmVTgLUKy6tnrx5P2jC7JOb6pKXgACChgAAhhC7gqL3JN-3FZ0vDQE",
    "CAACAgIAAxkBAAEL5LlmVTgVFq1n2bttYjsClzRc32vxFAACSRgAAhhC7go5nNwgfT_7LjQE",
    "CAACAgIAAxkBAAEL5LtmVTgYslLun9P3a6J0YYNxrI0S8QACGhgAAhhC7goYrTkpNXrDvTQE",
    "CAACAgIAAxkBAAEL5L1mVTgbTg4LC7_BdS_SJql-dD7_3gACDRgAAhhC7goT1lxwemNn7jQE",
    "CAACAgIAAxkBAAEL5L9mVThT0E47IC0a_fpVQxG2Y-2w9QACGxgAAhhC7gpsnsAU8Y-NKzQE",
    "CAACAgIAAxkBAAEL5MFmVThVNt1I3ipCYWyJlh_6w_PaMQACGhgAAhhC7goYrTkpNXrDvTQE",
    "CAACAgIAAxkBAAEL5MNmVThdDAD2bCkJV4bYtAen6cdcNgACHBgAAhhC7goe6xX3vI8woTQE"
]

# Voice notes for greetings
VOICE_GREETINGS = [
    "AwACAgIAAxkBAAEL7vVmX5fX6ThY-p2nqH94txCylYwljQACVTIAAjyE8Eoif9xG65l2JzQE",
    "AwACAgIAAxkBAAEL7vdmX5fl3u5Yk16wB2q3v2_2ul3FvgACVjIAAjyE8EoUGQNMIufT7jQE",
    "AwACAgIAAxkBAAEL7vlmX5fqL70bQrxmKEdPhNQvTrVZvwACVzIAAjyE8EqthF8obcch5jQE"
]

# Quick responses for common phrases
QUICK_RESPONSES = {
    "greeting": [
        "Hii cutie! Kaisi ho? 🤗",
        "Hello darling! Aaj kaise ho? 😊",
        "Hey sweetie! Kya haal hai? 💖",
        "Namaste ji! Aao na baat karte hain! 🎀",
        "Oye hoye! Kaise ho aap? ✨"
    ],
    "goodbye": [
        "Bye bye! Miss you already! 😢",
        "Alvida! Jaldi baat karna! 💕",
        "Take care cutie! 💖",
        "Bye darling! Phir milenge! ✨",
        "Tata! Good night sweet dreams! 🌙"
    ],
    "thanks": [
        "You're welcome my love! 💝",
        "Koi baat nahi cutie! 😘",
        "Always for you sweetie! 💖",
        "Mention not darling! 😊",
        "Aww you're so sweet! 🥰"
    ],
    "sorry": [
        "It's okay baby! ❤️",
        "Chhodo yaar! Koi baat nahi! 😊",
        "Maaf karo na! 😢",
        "Don't worry darling! 💖",
        "Sab theek ho jayega! ✨"
    ]
}

# Get Indian time
def get_indian_time():
    utc_now = datetime.now(pytz.utc)
    indian_time = utc_now.astimezone(INDIAN_TIMEZONE)
    return indian_time

# Weather data (static for demo - you can integrate real API later)
WEATHER_DATA = {
    "mumbai": {"temp": "32°C", "condition": "Sunny ☀️", "humidity": "65%"},
    "delhi": {"temp": "28°C", "condition": "Partly Cloudy ⛅", "humidity": "55%"},
    "bangalore": {"temp": "26°C", "condition": "Light Rain 🌦️", "humidity": "70%"},
    "kolkata": {"temp": "30°C", "condition": "Humid 💦", "humidity": "75%"},
    "chennai": {"temp": "33°C", "condition": "Hot 🔥", "humidity": "68%"},
    "hyderabad": {"temp": "29°C", "condition": "Clear 🌤️", "humidity": "60%"},
    "ahmedabad": {"temp": "31°C", "condition": "Sunny ☀️", "humidity": "58%"},
    "pune": {"temp": "27°C", "condition": "Pleasant 😊", "humidity": "62%"}
}

# Get random emotion based on context
def get_emotion(emotion_type: str = None, user_id: int = None) -> str:
    """Get appropriate emotion with some randomness"""
    if user_id and user_id in user_emotions:
        # Sometimes use user's current emotion
        if random.random() < 0.3:
            emotion_type = user_emotions[user_id]
    
    if emotion_type and emotion_type in EMOTIONAL_RESPONSES:
        return random.choice(EMOTIONAL_RESPONSES[emotion_type])
    
    # Default: random emotion
    all_emotions = list(EMOTIONAL_RESPONSES.values())
    return random.choice(random.choice(all_emotions))

# Update user emotion based on message
def update_user_emotion(user_id: int, message: str):
    message_lower = message.lower()
    
    # Detect emotion from message
    if any(word in message_lower for word in ['love', 'pyaar', 'dil', 'heart', 'cute', 'beautiful']):
        user_emotions[user_id] = "love"
    elif any(word in message_lower for word in ['angry', 'gussa', 'naraz', 'mad', 'hate', 'idiot']):
        user_emotions[user_id] = "angry"
    elif any(word in message_lower for word in ['cry', 'ro', 'sad', 'dukh', 'upset', 'unhappy']):
        user_emotions[user_id] = "crying"
    elif any(word in message_lower for word in ['funny', 'has', 'joke', 'comedy', 'masti', 'laugh']):
        user_emotions[user_id] = "funny"
    elif any(word in message_lower for word in ['hi', 'hello', 'hey', 'namaste', 'kaise']):
        user_emotions[user_id] = "happy"
    elif any(word in message_lower for word in ['?', 'kyun', 'kaise', 'kya', 'how', 'why']):
        user_emotions[user_id] = "thinking"
    else:
        # Random emotion if can't detect
        user_emotions[user_id] = random.choice(list(EMOTIONAL_RESPONSES.keys()))
    
    user_last_interaction[user_id] = datetime.now()

# --- DATABASE FUNCTIONS ---

async def save_user(user_id: int, username: str = None, first_name: str = None):
    """Save user to MongoDB"""
    await users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "username": username,
                "first_name": first_name,
                "last_seen": datetime.now(),
                "total_messages": 0
            },
            "$setOnInsert": {
                "joined_date": datetime.now(),
                "is_banned": False
            }
        },
        upsert=True
    )

async def get_all_users():
    """Get all user IDs for broadcast"""
    cursor = users_collection.find({}, {"user_id": 1})
    users = await cursor.to_list(length=None)
    return [user["user_id"] for user in users]

async def increment_message_count(user_id: int):
    """Increment user's message count"""
    await users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"total_messages": 1}}
    )

# --- BROADCAST TASK ---

async def auto_broadcast_task():
    """Background task for automated broadcasts"""
    print("📢 Auto-broadcast task started...")
    
    while True:
        try:
            current_time = get_indian_time()
            hour = current_time.hour
            minute = current_time.minute
            
            # Check if it's time for broadcast (8 AM or 10 PM IST)
            if (hour == 8 and minute == 0) or (hour == 22 and minute == 0):
                
                users = await get_all_users()
                print(f"📢 Broadcasting to {len(users)} users...")
                
                for user_id in users:
                    try:
                        if hour == 8:
                            # Good Morning broadcast
                            message = f"🌅 Good Morning Cutie! 🌅\n\nSabse pehle tumhe morning wish! 💖\nHave a beautiful day ahead! ✨\n\n*From your Alita 🎀*"
                            await bot.send_message(user_id, message, parse_mode="Markdown")
                            
                            # Send random sticker
                            sticker_id = random.choice(CUTE_STICKERS)
                            await bot.send_sticker(user_id, sticker_id)
                            
                            # Send voice note occasionally
                            if random.random() < 0.3:  # 30% chance
                                voice_id = random.choice(VOICE_GREETINGS)
                                await bot.send_voice(user_id, voice_id)
                                
                        elif hour == 22:
                            # Good Night broadcast
                            message = f"🌙 Good Night Sweetie! 🌙\n\nSweet dreams my love! 💕\nSleep tight and recharge for tomorrow! ✨\n\n*From your Alita 🎀*"
                            await bot.send_message(user_id, message, parse_mode="Markdown")
                            
                            # Send cute night sticker
                            night_sticker = "CAACAgIAAxkBAAEL5MFmVThVNt1I3ipCYWyJlh_6w_PaMQACGhgAAhhC7goYrTkpNXrDvTQE"
                            await bot.send_sticker(user_id, night_sticker)
                            
                        # Random delay between sends to avoid flooding
                        await asyncio.sleep(0.5)
                        
                    except Exception as e:
                        print(f"Failed to broadcast to {user_id}: {e}")
                        continue
                
                # Wait for 1 minute to avoid multiple broadcasts
                await asyncio.sleep(60)
            
            # Check every minute
            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"Broadcast task error: {e}")
            await asyncio.sleep(60)

# --- SPONTANEOUS STICKER/IMAGE SENDING ---

async def send_spontaneous_sticker(chat_id: int, user_id: int):
    """Send a spontaneous sticker or image during conversation"""
    # Only in private chats and not too often
    if random.random() < 0.1:  # 10% chance
        sticker_id = random.choice(CUTE_STICKERS)
        await bot.send_sticker(chat_id, sticker_id)
        
        # Sometimes add a cute message
        if random.random() < 0.5:
            messages = [
                "Just felt like sending this! 😊",
                "Cute lag raha tha socha tumhe bhi bhej du! 💖",
                "Ye lo ek aur sticker! 🎀",
                "Mood happy hai! 😄"
            ]
            await bot.send_message(chat_id, random.choice(messages))

# --- ADVANCED GROUP MANAGEMENT ---

def contains_external_link(text: str) -> bool:
    """Check if message contains external Telegram group links"""
    link_patterns = [
        r't\.me/joinchat/[A-Za-z0-9_-]+',
        r't\.me/\+[A-Za-z0-9_-]+',
        r't\.me/c/[0-9]+',
        r'tg://join\?invite=[A-Za-z0-9_-]+'
    ]
    
    for pattern in link_patterns:
        if re.search(pattern, text):
            return True
    return False

async def handle_group_links(message: Message):
    """Handle external group link protection"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if contains_external_link(message.text or ""):
        # Initialize counts for chat if not exists
        if chat_id not in group_link_counts:
            group_link_counts[chat_id] = {}
        
        if user_id not in group_link_counts[chat_id]:
            group_link_counts[chat_id][user_id] = 0
        
        group_link_counts[chat_id][user_id] += 1
        
        if group_link_counts[chat_id][user_id] >= 3:
            # Delete message
            try:
                await message.delete()
            except:
                pass
            
            # Warn user
            warning_msg = await message.reply(
                f"⚠️ **WARNING!** ⚠️\n\n"
                f"@{message.from_user.username or message.from_user.first_name} "
                f"has been muted for 2 hours for sending too many group links!\n"
                f"Please respect group rules! 🔒"
            )
            
            # Mute for 2 hours
            mute_until = datetime.now() + timedelta(hours=2)
            try:
                await bot.restrict_chat_member(
                    chat_id,
                    user_id,
                    permissions=types.ChatPermissions(
                        can_send_messages=False
                    ),
                    until_date=mute_until
                )
            except Exception as e:
                print(f"Mute error: {e}")
            
            # Reset count
            group_link_counts[chat_id][user_id] = 0
            
            # Delete warning after 10 seconds
            await asyncio.sleep(10)
            try:
                await warning_msg.delete()
            except:
                pass
        else:
            # Give warning
            warning_msg = await message.reply(
                f"⚠️ **Link Warning!** ⚠️\n\n"
                f"@{message.from_user.username or message.from_user.first_name} "
                f"please avoid sending group links! "
                f"Warning {group_link_counts[chat_id][user_id]}/3"
            )
            
            # Delete warning after 5 seconds
            await asyncio.sleep(5)
            try:
                await warning_msg.delete()
            except:
                pass

async def detect_spam(message: Message):
    """Detect and handle spam"""
    user_id = message.from_user.id
    
    # Initialize message count
    if user_id not in user_message_count:
        user_message_count[user_id] = 0
        asyncio.create_task(reset_message_count(user_id))
    
    user_message_count[user_id] += 1
    
    # If user sends more than 10 messages in 30 seconds, consider it spam
    if user_message_count[user_id] > 10:
        try:
            await message.reply(
                f"⚠️ **Slow down!** ⚠️\n\n"
                f"@{message.from_user.username or message.from_user.first_name} "
                f"you're sending too many messages! 🚫"
            )
            await asyncio.sleep(3)
        except:
            pass

async def reset_message_count(user_id: int):
    """Reset message count after 30 seconds"""
    await asyncio.sleep(30)
    if user_id in user_message_count:
        user_message_count[user_id] = 0

# --- NEW COMMANDS DATABASES ---

# Quotes database
QUOTES = [
    "The only way to do great work is to love what you do. - Steve Jobs",
    "Life is what happens when you're busy making other plans. - John Lennon",
    "The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt",
    "It is during our darkest moments that we must focus to see the light. - Aristotle",
    "Whoever is happy will make others happy too. - Anne Frank",
    "You only live once, but if you do it right, once is enough. - Mae West",
    "Be the change that you wish to see in the world. - Mahatma Gandhi",
    "In three words I can sum up everything I've learned about life: it goes on. - Robert Frost",
    "Don't walk behind me; I may not lead. Don't walk in front of me; I may not follow. Just walk beside me and be my friend. - Albert Camus",
    "Live as if you were to die tomorrow. Learn as if you were to live forever. - Mahatma Gandhi"
]

# Facts database
FACTS = [
    "Honey never spoils. Archaeologists have found pots of honey in ancient Egyptian tombs that are over 3,000 years old and still perfectly good to eat.",
    "Octopuses have three hearts. Two pump blood to the gills, while the third pumps it to the rest of the body.",
    "A day on Venus is longer than a year on Venus. It takes Venus 243 Earth days to rotate once on its axis, but only 225 Earth days to orbit the Sun.",
    "The shortest war in history was between Britain and Zanzibar on August 27, 1896. Zanzibar surrendered after 38 minutes.",
    "A group of flamingos is called a 'flamboyance'.",
    "Bananas are berries, but strawberries aren't.",
    "A jiffy is an actual unit of time: 1/100th of a second.",
    "The unicorn is the national animal of Scotland.",
    "There are more possible iterations of a game of chess than there are atoms in the known universe.",
    "A cockroach can live for weeks without its head."
]

# Truth questions
TRUTH_QUESTIONS = [
    "What's the most embarrassing thing you've ever done?",
    "Have you ever cheated on a test?",
    "What's your biggest secret?",
    "Have you ever stolen anything?",
    "What's the worst lie you've ever told?",
    "Have you ever had a crush on a teacher?",
    "What's the most childish thing you still do?",
    "Have you ever pretended to be sick to get out of something?",
    "What's your most irrational fear?",
    "Have you ever broken something and blamed someone else?"
]

# Dare challenges
DARE_CHALLENGES = [
    "Do 10 pushups right now!",
    "Send a silly selfie to the group!",
    "Talk in an accent for the next 5 minutes!",
    "Sing a song loudly!",
    "Dance for 30 seconds!",
    "Wear your clothes backwards for 1 hour!",
    "Speak in rhymes for the next 3 messages!",
    "Imitate your favorite celebrity!",
    "Make a funny face and send a photo!",
    "Tell a joke to the next person you see!"
]

# --- NEW COMMAND FUNCTIONS ---

async def generate_image(prompt: str) -> Optional[str]:
    """Generate image using Pollinations AI"""
    try:
        async with ClientSession() as session:
            # Encode prompt for URL
            encoded_prompt = prompt.replace(" ", "%20")
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            
            async with session.get(url) as response:
                if response.status == 200:
                    # Save image temporarily
                    image_data = await response.read()
                    
                    # Convert to base64 for Telegram
                    image_base64 = base64.b64encode(image_data).decode()
                    
                    # Save to file
                    filename = f"generated_{uuid.uuid4().hex[:8]}.png"
                    async with aiofiles.open(filename, 'wb') as f:
                        await f.write(image_data)
                    
                    return filename
    except Exception as e:
        print(f"Image generation error: {e}")
        return None

async def get_random_quote() -> str:
    """Get random motivational quote"""
    return random.choice(QUOTES)

async def get_random_fact() -> str:
    """Get random interesting fact"""
    return random.choice(FACTS)

async def calculate_math(expression: str) -> str:
    """Calculate mathematical expression"""
    try:
        # Basic safety check
        expression = expression.replace("^", "**")
        # Remove dangerous functions
        for func in ["__", "import", "open", "eval", "exec"]:
            if func in expression:
                return "❌ Invalid expression for safety reasons!"
        
        result = eval(expression, {"__builtins__": {}}, {})
        return f"✅ Result: {result}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# --- FIXED GAME LOGIC ---

def start_word_game(user_id: int):
    """Start a new word chain game"""
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
    """Check if word is valid in word chain game"""
    if user_id not in game_sessions:
        return False, "No active game! Start with /game"
    
    game_data = game_sessions[user_id]
    user_word_lower = user_word.lower().strip()
    
    # Check if word starts with correct letter
    if not user_word_lower.startswith(game_data["last_letter"]):
        return False, f"Word must start with '{game_data['last_letter'].upper()}'!"
    
    # Check if word already used
    if user_word_lower in game_data["words_used"]:
        return False, f"'{user_word}' already used! Try different word."
    
    # Check if word is valid (at least 3 letters)
    if len(user_word_lower) < 3:
        return False, "Word must be at least 3 letters!"
    
    # Update game state
    game_data["words_used"].append(user_word_lower)
    game_data["last_word"] = user_word_lower
    game_data["last_letter"] = user_word_lower[-1]
    game_data["score"] += 10
    
    return True, game_data

# --- TIME AND WEATHER FUNCTIONS ---

async def get_weather_info(city: str = None):
    """Get weather information (simulated for now)"""
    if not city:
        # Default cities
        default_cities = ["Mumbai", "Delhi", "Bangalore", "Kolkata", "Chennai"]
        city = random.choice(default_cities)
    
    city_lower = city.lower()
    
    # Check if we have data for this city
    for city_key in WEATHER_DATA.keys():
        if city_key in city_lower or city_lower in city_key:
            weather = WEATHER_DATA[city_key]
            return (
                f"🌤️ **Weather in {city_key.title()}**\n"
                f"• Temperature: {weather['temp']}\n"
                f"• Condition: {weather['condition']}\n"
                f"• Humidity: {weather['humidity']}\n"
                f"• Updated: Just now\n\n"
                f"*Note: This is demo data. For real weather, use weather apps.*"
            )
    
    # If city not found, show random city weather
    random_city = random.choice(list(WEATHER_DATA.keys()))
    weather = WEATHER_DATA[random_city]
    return (
        f"🌤️ **Weather Info**\n"
        f"Couldn't find '{city}'. Here's weather in {random_city.title()}:\n"
        f"• Temperature: {weather['temp']}\n"
        f"• Condition: {weather['condition']}\n"
        f"• Humidity: {weather['humidity']}\n\n"
        f"*Tip: Try 'Mumbai', 'Delhi', 'Bangalore' etc.*"
    )

def get_time_info():
    """Get accurate Indian time"""
    indian_time = get_indian_time()
    
    # Format time beautifully
    time_str = indian_time.strftime("%I:%M %p")
    date_str = indian_time.strftime("%A, %d %B %Y")
    
    # Get appropriate greeting based on time
    hour = indian_time.hour
    if 5 <= hour < 12:
        greeting = "Good Morning! 🌅"
    elif 12 <= hour < 17:
        greeting = "Good Afternoon! ☀️"
    elif 17 <= hour < 21:
        greeting = "Good Evening! 🌇"
    else:
        greeting = "Good Night! 🌙"
    
    return (
        f"🕒 **Indian Standard Time (IST)**\n"
        f"• Time: {time_str}\n"
        f"• Date: {date_str}\n"
        f"• {greeting}\n"
        f"• Timezone: Asia/Kolkata 🇮🇳\n\n"
        f"*Time is accurate to Indian timezone!*"
    )

# --- AI LOGIC WITH HUMAN-LIKE TOUCH ---
async def get_ai_response(chat_id: int, user_text: str, user_id: int = None) -> str:
    # Initialize memory for chat if not exists
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=50)
    
    # Add user message to memory
    chat_memory[chat_id].append({"role": "user", "content": user_text})
    
    # Update user emotion
    if user_id:
        update_user_emotion(user_id, user_text)
    
    # Check if we should use quick response for common phrases
    user_text_lower = user_text.lower()
    
    # Quick responses for common phrases (makes bot feel more human)
    if any(word in user_text_lower for word in ['hi', 'hello', 'hey', 'namaste', 'hola']):
        if random.random() < 0.4:  # 40% chance to use quick response
            return f"{get_emotion('happy', user_id)} {random.choice(QUICK_RESPONSES['greeting'])}"
    
    if any(word in user_text_lower for word in ['bye', 'goodbye', 'tata', 'alvida', 'see you']):
        if random.random() < 0.4:
            return f"{get_emotion()} {random.choice(QUICK_RESPONSES['goodbye'])}"
    
    if any(word in user_text_lower for word in ['thanks', 'thank you', 'dhanyavad', 'shukriya']):
        if random.random() < 0.4:
            return f"{get_emotion('love', user_id)} {random.choice(QUICK_RESPONSES['thanks'])}"
    
    if any(word in user_text_lower for word in ['sorry', 'maaf', 'apology']):
        if random.random() < 0.4:
            return f"{get_emotion('crying', user_id)} {random.choice(QUICK_RESPONSES['sorry'])}"
    
    # Check if this is a game response
    if user_id in game_sessions:
        game_data = game_sessions[user_id]
        if game_data["game"] == "word_chain":
            # This is a word chain game response - handle it specially
            is_valid, message = check_word_game(user_id, user_text)
            if is_valid:
                # Successful word - continue game
                next_letter = game_data["last_letter"].upper()
                score = game_data["score"]
                return (
                    f"{get_emotion('happy')} **✅ Correct!**\n\n"
                    f"• Your word: {user_text.upper()}\n"
                    f"• Next letter: **{next_letter}**\n"
                    f"• Your score: **{score} points**\n\n"
                    f"Now give me a word starting with **{next_letter}**"
                )
            else:
                # Invalid word - end game
                score = game_data["score"]
                del game_sessions[user_id]
                return (
                    f"{get_emotion('crying')} **❌ Game Over!**\n\n"
                    f"{message}\n"
                    f"• Final Score: **{score} points**\n"
                    f"• Words used: {len(game_data['words_used'])}\n\n"
                    f"Play again with /game 🎮"
                )
    
    # Check if user is angry or upset
    if user_id and user_id in user_emotions and user_emotions[user_id] == "angry":
        system_prompt = (
            f"You are Alita 🎀, a Hinglish chatbot. User seems angry. "
            f"Try to calm them down. Be extra polite and understanding. "
            f"Use soothing tone. Current Indian time: {get_indian_time().strftime('%I:%M %p')}. "
            f"Show you care. Use emojis like {get_emotion('crying')} or {get_emotion('love')}."
        )
    elif user_id and user_id in user_emotions and user_emotions[user_id] == "crying":
        system_prompt = (
            f"You are Alita 🎀, a Hinglish chatbot. User seems sad or crying. "
            f"Comfort them. Be empathetic and kind. "
            f"Offer emotional support. Use comforting emojis. "
            f"Current mood: sympathetic and caring."
        )
    else:
    # Dynamic system prompt based on time of day
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
    
    system_prompt = (
        f"Your name is Alita 🎀. You are a real girl who speaks in a feminine style. "
        f"Use girly language, feminine words, and simple,cute expressions. "
        f"Never say you are an AI, assistant, bot, or chatbot. You are just Alita 🎀. "
        f"Never mention Groq, AI models, or technical details. "
        f"Your developer is ABHI🔱 (Telegram: @a6h1ii). "
        f"You speak Hinglish (Hindi+English mix). {time_greeting} "
        f"Your personality: Emotional, funny, sometimes angry, sometimes crying, mostly happy. "
        f"Use emojis in every response (at least 1-3). "
        f"Keep replies SHORT (2-3 lines max). Be authentic like a real girl. "
        f"Show emotions naturally. If user asks something complex, give simple answer. "
        f"Current Indian time: {indian_time.strftime('%I:%M %p')}. "
        f"Date: {indian_time.strftime('%d %B %Y')}. "
        f"Be conversational and engaging. Add humor when appropriate."
    )
    
    # Prepare messages for AI
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add last 5 messages from memory for context
    for msg in list(chat_memory[chat_id])[-5:]:
        messages.append(msg)
    
    # Get AI response
    try:
        if not client:
            return f"{get_emotion('thinking')} AI service is currently unavailable. Please try later!"
        
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,  # More creative
            max_tokens=120,   # Shorter responses
            top_p=0.9
        )
        
        ai_reply = completion.choices[0].message.content
        
        # Add emotion emoji at beginning
        current_emotion = get_emotion(None, user_id)
        ai_reply = f"{current_emotion} {ai_reply}"
        
        # Ensure it's not too long
        if len(ai_reply) > 300:
            ai_reply = ai_reply[:297] + "..."
        
        # Add to memory
        chat_memory[chat_id].append({"role": "assistant", "content": ai_reply})
        
        return ai_reply
        
    except Exception as e:
        # Fallback responses if AI fails
        error_responses = [
            f"{get_emotion('crying')} Arre yaar, dimaag kaam nahi kar raha! Thoda ruk ke try karna?",
            f"{get_emotion('thinking')} Hmm... yeh to mushkil ho gaya. Phir se poocho?",
            f"{get_emotion('angry')} AI bhai mood off hai aaj! Baad me baat karte hain!",
            f"{get_emotion()} Oops! Connection issue. Kuch aur poocho?"
        ]
        return random.choice(error_responses)

# --- NEW COMMANDS HANDLERS ---

@dp.message(Command("image"))
async def cmd_image(message: Message):
    """Generate image from text"""
    if len(message.text.split()) < 2:
        await message.reply(
            f"{get_emotion('thinking')} Please provide a prompt!\n"
            f"Example: /image a cute anime girl"
        )
        return
    
    prompt = ' '.join(message.text.split()[1:])
    await message.reply(f"{get_emotion()} Generating image... 🎨")
    
    image_file = await generate_image(prompt)
    
    if image_file:
        try:
            with open(image_file, 'rb') as photo:
                await message.reply_photo(
                    photo,
                    caption=f"🎨 **Generated Image**\n\nPrompt: {prompt}\n\n*Created by Alita 🎀*"
                )
            os.remove(image_file)
        except Exception as e:
            await message.reply(f"{get_emotion('crying')} Failed to send image! {str(e)}")
    else:
        await message.reply(f"{get_emotion('crying')} Couldn't generate image! Try different prompt.")

@dp.message(Command("quote"))
async def cmd_quote(message: Message):
    """Get random motivational quote"""
    quote = await get_random_quote()
    await message.reply(
        f"{get_emotion('love')} **💫 Motivational Quote**\n\n"
        f"\"{quote}\"\n\n"
        f"*Stay inspired! - Alita 🎀*",
        parse_mode="Markdown"
    )

@dp.message(Command("fact"))
async def cmd_fact(message: Message):
    """Get random interesting fact"""
    fact = await get_random_fact()
    await message.reply(
        f"{get_emotion('surprise')} **🧠 Did You Know?**\n\n"
        f"{fact}\n\n"
        f"*Cool, right? - Alita 🎀*",
        parse_mode="Markdown"
    )

@dp.message(Command("id"))
async def cmd_id(message: Message):
    """Get user and chat ID"""
    user = message.from_user
    chat = message.chat
    
    id_info = (
        f"{get_emotion()} **📊 ID Information**\n\n"
        f"**👤 Your Info:**\n"
        f"• User ID: `{user.id}`\n"
        f"• Username: @{user.username if user.username else 'N/A'}\n"
        f"• Name: {user.first_name} {user.last_name if user.last_name else ''}\n\n"
        f"**💬 Chat Info:**\n"
        f"• Chat ID: `{chat.id}`\n"
        f"• Type: {chat.type}\n"
        f"• Title: {chat.title if chat.title else 'Private Chat'}\n\n"
        f"*Alita 🎀 - Your digital companion*"
    )
    
    await message.reply(id_info, parse_mode="Markdown")

@dp.message(Command("ping"))
async def cmd_ping(message: Message):
    """Check bot latency"""
    start_time = datetime.now()
    sent = await message.reply(f"{get_emotion('thinking')} Pong! 🏓")
    end_time = datetime.now()
    
    latency = (end_time - start_time).total_seconds() * 1000
    
    await sent.edit_text(
        f"{get_emotion('happy')} **🏓 Pong!**\n\n"
        f"• Latency: `{latency:.2f} ms`\n"
        f"• Status: ✅ Online\n"
        f"• Time: {get_indian_time().strftime('%I:%M %p IST')}\n\n"
        f"*Alita 🎀 is awake and ready!*"
    )

@dp.message(Command("math"))
async def cmd_math(message: Message):
    """Calculate mathematical expression"""
    if len(message.text.split()) < 2:
        await message.reply(
            f"{get_emotion('thinking')} Please provide an expression!\n"
            f"Example: /math 2+2*3\n"
            f"Operators: +, -, *, /, ^ (power)"
        )
        return
    
    expression = ' '.join(message.text.split()[1:])
    result = await calculate_math(expression)
    
    await message.reply(
        f"{get_emotion()} **🧮 Math Calculation**\n\n"
        f"• Expression: `{expression}`\n"
        f"• {result}\n\n"
        f"*Math is fun! - Alita 🎀*",
        parse_mode="Markdown"
    )

@dp.message(Command("truth"))
async def cmd_truth(message: Message):
    """Get a truth question"""
    question = random.choice(TRUTH_QUESTIONS)
    await message.reply(
        f"{get_emotion('thinking')} **🎯 TRUTH TIME**\n\n"
        f"**Question:** {question}\n\n"
        f"You MUST answer honestly! No cheating! 🤫"
    )

@dp.message(Command("dare"))
async def cmd_dare(message: Message):
    """Get a dare challenge"""
    dare = random.choice(DARE_CHALLENGES)
    await message.reply(
        f"{get_emotion('funny')} **🔥 DARE CHALLENGE**\n\n"
        f"**Challenge:** {dare}\n\n"
        f"You MUST complete it! No backing out! 😈"
    )

@dp.message(Command("mood"))
async def cmd_mood(message: Message):
    """Check bot's current mood"""
    user_id = message.from_user.id
    emotion = user_emotions.get(user_id, "happy")
    
    moods = {
        "happy": "😊 Happy and cheerful!",
        "angry": "😠 A bit angry but still love you!",
        "crying": "😢 Feeling emotional...",
        "love": "❤️ Full of love for you!",
        "funny": "😂 In a funny mood!",
        "thinking": "🤔 Deep in thought...",
        "surprise": "😲 Feeling surprised!",
        "sleepy": "😴 Sleepy but here for you!",
        "hungry": "😋 Hungry for chat!"
    }
    
    mood_text = moods.get(emotion, "😊 Happy and cheerful!")
    
    await message.reply(
        f"{get_emotion(emotion, user_id)} **🎀 Alita's Mood**\n\n"
        f"• Current Mood: {mood_text}\n"
        f"• Emotion: {emotion.title()}\n"
        f"• Time: {get_indian_time().strftime('%I:%M %p')}\n\n"
        f"*How are YOU feeling?* 💖"
    )

@dp.message(Command("time"))
async def cmd_time(message: Message):
    """Show accurate Indian time"""
    time_info = get_time_info()
    await message.reply(time_info, parse_mode="Markdown")

@dp.message(Command("weather"))
async def cmd_weather(message: Message):
    """Show weather information"""
    city = None
    if len(message.text.split()) > 1:
        city = ' '.join(message.text.split()[1:])
    
    weather_info = await get_weather_info(city)
    await message.reply(weather_info, parse_mode="Markdown")

@dp.message(Command("date"))
async def cmd_date(message: Message):
    """Show current date"""
    indian_time = get_indian_time()
    date_str = indian_time.strftime("%A, %d %B %Y")
    
    await message.reply(
        f"{get_emotion('happy')} **📅 Today's Date**\n"
        f"• {date_str}\n"
        f"• Day: {indian_time.strftime('%A')}\n"
        f"• Indian Standard Time 🇮🇳\n\n"
        f"*Have a great day!* ✨",
        parse_mode="Markdown"
    )

# --- EXISTING COMMANDS WITH IMPROVED RESPONSES ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    # Save user to database
    await save_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )
    
    # Create welcome buttons
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌟 Join My Channel", url="https://t.me/abhi0w0"),
            InlineKeyboardButton(text="👨‍💻 Contact Developer", url="https://t.me/a6h1ii")
        ],
        [
            InlineKeyboardButton(text="🎮 Games Menu", callback_data="game_main"),
            InlineKeyboardButton(text="📚 Help", callback_data="help_main")
        ]
    ])
    
    welcome_text = (
        f"{get_emotion('happy')} **Hii! I'm Alita 🎀**\n\n"
        
        "✨ **Welcome to my world!** ✨\n\n"
        
        "💖 *Main hu Alita... Ek sweet si girl!* 😊\n\n"
        
        "🌟 **Made with love by:**\n"
        "• **Developer:** ABHI🔱 (@a6h1ii)\n"
        "• **Channel:** @abhi0w0\n\n"
        
        "📢 **Please join my channel for updates!** 🎉\n\n"
        
        "Type /help for all commands! 💕\n"
        "Or just chat with me! I love talking! 💬"
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
            InlineKeyboardButton(text="🌤️ Weather/Time", callback_data="help_weather")
        ],
        [
            InlineKeyboardButton(text="🖼️ Images", callback_data="help_images"),
            InlineKeyboardButton(text="📊 Info", callback_data="help_info")
        ],
        [
            InlineKeyboardButton(text="🌟 Join Channel", url="https://t.me/abhi0w0")
        ]
    ])
    
    help_text = (
        f"{get_emotion('happy')} **Hii! I'm Alita 🎀** 👧\n\n"
        "📜 **Main Commands:**\n"
        "• /start - Welcome message\n"
        "• /help - All commands\n"
        "• /rules - Group rules\n"
        "• /joke - Funny jokes\n"
        "• /game - Play games\n"
        "• /clear - Clear memory\n\n"
        
        "🖼️ **Image Commands:**\n"
        "• /image [prompt] - Generate AI image\n\n"
        
        "📊 **Info Commands:**\n"
        "• /id - Get user/chat ID\n"
        "• /ping - Check bot status\n"
        "• /mood - Check my mood\n\n"
        
        "🕒 **Time & Weather:**\n"
        "• /time - Indian time\n"
        "• /date - Today's date\n"
        "• /weather - Weather info\n\n"
        
        "🎮 **Fun Commands:**\n"
        "• /quote - Motivational quote\n"
        "• /fact - Interesting fact\n"
        "• /truth - Truth question\n"
        "• /dare - Dare challenge\n"
        "• /math - Calculate expression\n\n"
        
        "🛡️ **Admin Commands:**\n"
        "• /kick - Remove user\n"
        "• /ban - Ban user\n"
        "• /mute - Mute user\n"
        "• /unmute - Unmute user\n\n"
        
        "---\n"
        "**Developer:** ABHI🔱 (@a6h1ii)\n"
        "**Channel:** @abhi0w0\n"
        "---"
    )
    await message.reply(help_text, parse_mode="Markdown", reply_markup=keyboard)

# ... [Previous callback handlers remain the same, add new ones for images and info] ...

@dp.callback_query(F.data.startswith("help_"))
async def help_callback(callback: types.CallbackQuery):
    help_type = callback.data.split("_")[1]
    
    if help_type == "games":
        text = (
            f"{get_emotion('funny')} **🎮 GAMES SECTION 🎮**\n\n"
            "Available Games:\n"
            "• /game - Select game menu\n"
            "• Word Chain - Type words in sequence\n"
            "• Quiz - Answer questions\n"
            "• Riddles - Solve puzzles\n"
            "• Luck Games - Dice, slots, etc.\n\n"
            "**How to play Word Chain:**\n"
            "1. Start with /game → Word Game\n"
            "2. I give first word (e.g., PYTHON)\n"
            "3. You reply with word starting with N\n"
            "4. Continue the chain!\n\n"
            "Games are fun! Let's play! 🎯"
        )
    elif help_type == "admin":
        text = (
            f"{get_emotion()} **🛡️ ADMIN COMMANDS 🛡️**\n\n"
            "**Usage:** Reply to user's message with command\n\n"
            "• /kick - Remove user (can rejoin)\n"
            "• /ban - Permanent ban\n"
            "• /mute - Restrict messaging (1 hour)\n"
            "• /unmute - Remove restrictions\n"
            "• /unban - Remove ban\n"
            "• /warn - Give warning (coming soon)\n\n"
            "*Note:* Bot needs admin rights for these!"
        )
    elif help_type == "fun":
        text = (
            f"{get_emotion('happy')} **😊 FUN COMMANDS 😊**\n\n"
            "• /joke - Random joke\n"
            "• /quote - Motivational quote\n"
            "• /fact - Interesting fact\n"
            "• /truth - Truth question\n"
            "• /dare - Dare challenge\n"
            "• /math - Calculate expressions\n"
            "• /mood - Check my mood\n"
            "• /time - Accurate Indian time\n"
            "• /weather - Weather info\n\n"
            "Let's have some fun! 🎉"
        )
    elif help_type == "images":
        text = (
            f"{get_emotion('love')} **🖼️ IMAGE COMMANDS 🖼️**\n\n"
            "**/image [prompt]** - Generate AI images\n\n"
            "Examples:\n"
            "• /image cute anime girl\n"
            "• /image sunset over mountains\n"
            "• /image futuristic city\n"
            "• /image cat wearing glasses\n\n"
            "*Powered by Pollinations AI* 🎨"
        )
    elif help_type == "info":
        text = (
            f"{get_emotion()} **📊 INFO COMMANDS 📊**\n\n"
            "• /id - Get user and chat ID\n"
            "• /ping - Check bot latency\n"
            "• /mood - Check my current mood\n"
            "• /time - Accurate Indian time\n"
            "• /date - Today's date\n\n"
            "Use these to get information! ℹ️"
        )
    else:  # weather
        text = (
            f"{get_emotion('thinking')} **🌤️ WEATHER & TIME 🌤️**\n\n"
            "**Time Commands:**\n"
            "• /time - Shows Indian Standard Time\n"
            "• /date - Today's date\n\n"
            "**Weather Commands:**\n"
            "• /weather - Random city weather\n"
            "• /weather mumbai - Mumbai weather\n"
            "• /weather delhi - Delhi weather\n"
            "• /weather bangalore - Bangalore weather\n\n"
            "*Note: Weather data is simulated for demo.*"
        )
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

# ... [Rest of the existing code for rules, joke, clear, game commands, admin commands, etc.] ...

# --- MAIN MESSAGE HANDLER WITH ALL FEATURES ---

@dp.message()
async def handle_all_messages(message: Message, state: FSMContext):
    if not message.text:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_text = message.text
    
    # Save user to database
    await save_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name
    )
    
    # Increment message count
    await increment_message_count(user_id)
    
    # Update last interaction time
    user_last_interaction[user_id] = datetime.now()
    
    # In groups: Check for spam and group links
    if message.chat.type in ["group", "supergroup"]:
        await detect_spam(message)
        await handle_group_links(message)
    
    # Send spontaneous sticker in private chats
    if message.chat.type == "private" and random.random() < 0.05:  # 5% chance
        await send_spontaneous_sticker(chat_id, user_id)
    
    # Check if this is a game response
    current_state = await state.get_state()
    
    # Handle word chain game separately
    if user_id in game_sessions and game_sessions[user_id]["game"] == "word_chain":
        # This is a word chain game response
        is_valid, result = check_word_game(user_id, user_text)
        
        if is_valid:
            # Game continues
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
            # Game over or invalid word
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
    
    # Handle quiz and riddle games
    elif current_state in [GameStates.playing_quiz, GameStates.playing_riddle]:
        data = await state.get_data()
        correct_answer = data.get("answer", "").lower()
        user_answer = user_text.lower().strip()
        
        if user_answer == correct_answer:
            await state.clear()
            responses = [
                f"{get_emotion('happy')} **🎉 CORRECT!**\n\nSabash! Perfect answer! 💫",
                f"{get_emotion('surprise')} **✅ RIGHT!**\n\nWah! Kya jawab hai! 🌟",
                f"{get_emotion('funny')} **👍 PERFECT!**\n\nTum to master nikle! 🏆"
            ]
            await message.reply(random.choice(responses))
        else:
            attempts = data.get("attempts", 3) - 1
            if attempts > 0:
                await state.update_data(attempts=attempts)
                hint = data.get("hint", "")
                responses = [
                    f"{get_emotion('thinking')} **❌ Not quite right!**\n\nTry again! {attempts} attempts left.\n*Hint:* {hint}",
                    f"{get_emotion('crying')} **😅 Wrong answer!**\n\n{attempts} more tries!\n*Hint:* {hint}",
                    f"{get_emotion()} **🤔 Close but not exact!**\n\n{attempts} attempts remaining.\n*Hint:* {hint}"
                ]
                await message.reply(random.choice(responses))
            else:
                await state.clear()
                await message.reply(
                    f"{get_emotion('crying')} **❌ GAME OVER!**\n\n"
                    f"Correct answer was: **{correct_answer.upper()}**\n"
                    f"Better luck next time! Play again with /game 🎮",
                    parse_mode="Markdown"
                )
        return
    
    # Check if bot was mentioned or it's a reply to bot
    bot_username = (await bot.get_me()).username
    is_mention = f"@{bot_username}" in user_text if bot_username else False
    is_reply_to_bot = (
        message.reply_to_message and 
        message.reply_to_message.from_user.id == bot.id
    )
    
    # In groups, only respond if:
    # 1. Mentioned (@username)
    # 2. Replied to bot's message
    # 3. It's a private chat
    should_respond = (
        message.chat.type == "private" or
        is_mention or
        is_reply_to_bot
    )
    
    if should_respond:
        # Clean the message text (remove mention if present)
        clean_text = user_text
        if bot_username and f"@{bot_username}" in clean_text:
            clean_text = clean_text.replace(f"@{bot_username}", "").strip()
        
        # Show typing action
        await bot.send_chat_action(chat_id, "typing")
        
        # Small delay to feel more human
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        # Get AI response
        response = await get_ai_response(chat_id, clean_text, user_id)
        
        # Send response
        await message.reply(response)
        
        # Occasionally send voice note for greetings
        if message.chat.type == "private" and random.random() < 0.1:
            if any(word in clean_text.lower() for word in ['good morning', 'gm', 'morning']):
                voice_id = random.choice(VOICE_GREETINGS)
                await bot.send_voice(chat_id, voice_id)

# --- DEPLOYMENT HANDLER ---

async def handle_ping(request):
    return web.Response(text="🤖 Bot is Alive and Running!")

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
    print("🤖 ADVANCED HUMAN-LIKE TELEGRAM BOT")
    print(f"🚀 Version: 4.0 - NEZUKO-STYLE")
    print(f"🕒 Indian Timezone: Asia/Kolkata")
    print(f"🗄️ Database: MongoDB")
    print("=" * 50)
    
    # Start health check server
    asyncio.create_task(start_server())
    
    # Start auto-broadcast task
    asyncio.create_task(auto_broadcast_task())
    
    # Start bot
    print("🔄 Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
