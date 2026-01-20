import os
import asyncio
import random
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List
from aiogram import Bot, Dispatcher, types, F
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from groq import AsyncGroq
from aiohttp import web
import pytz

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", 10000))

# Timezone for India
INDIAN_TIMEZONE = pytz.timezone('Asia/Kolkata')

# Initialize with MemoryStorage
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)
dp.include_router(dp.router)

# Initialize Groq client
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Memory: {chat_id: deque}
chat_memory: Dict[int, deque] = {}

# Game states storage: {user_id: game_data}
active_games: Dict[int, Dict] = {}
game_sessions: Dict[int, Dict] = {}  # Store game sessions separately

# Emotional states for each user
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}

# States for games
class GameStates(StatesGroup):
    playing_quiz = State()
    playing_riddle = State()
    playing_word = State()
    waiting_answer = State()

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
    "kolkata": {"temp": "30°C", "condition": "Humid 💧", "humidity": "75%"},
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

# --- GAME DATABASES IMPROVED ---

# Quiz Database
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

# Riddle Database
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

# Jokes Database Improved
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

# Group Rules Templates with Beautiful Designs
GROUP_RULES = [
    """
         📜 𝐆𝐑𝐎𝐔𝐏 𝐑𝐔𝐋𝐄𝐒 📜
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
𝟭. 🤝 𝐑𝐄𝐒𝐏𝐄𝐂𝐓 𝐄𝐕𝐄𝐑𝐘𝐎𝐍𝐄
   • No bullying or harassment
   • Be polite and kind always

𝟮. 🚫 𝐍𝐎 𝐒𝐏𝐀𝐌𝐌𝐈𝐍𝐆
   • No flooding with messages
   • No irrelevant content

𝟯. ✅ 𝐒𝐀𝐅𝐄 𝐂𝐎𝐍𝐓𝐄𝐍𝐓
   • No adult/NSFW material
   • No illegal content sharing

𝟰. ⚔️ 𝐍𝐎 𝐅𝐈𝐆𝐇𝐓𝐈𝐍𝐆
   • Keep arguments private
   • No personal attacks

𝟱. 👑 𝐀𝐃𝐌𝐈𝐍 𝐃𝐄𝐂𝐈𝐒𝐈𝐎𝐍𝐒
   • Follow admin instructions
   • Respect their decisions
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

╭────── ೋღ🌺ღೋ ──────╮
 𝐑𝐮𝐥𝐞𝐬 𝐚𝐫𝐞 𝐟𝐨𝐫 𝐞𝐯𝐞𝐫𝐲𝐨𝐧𝐞'𝐬 𝐠𝐨𝐨𝐝!🌟
╰────── ೋღ🌺ღೋ ──────╯

◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
𝐍𝐞𝐞𝐝 𝐡𝐞𝐥𝐩? 𝐉𝐮𝐬𝐭 𝐚𝐬𝐤 𝐦𝐞! 🎀""",

    """
      ⚖️ 𝐂𝐎𝐌𝐌𝐔𝐍𝐈𝐓𝐘 𝐆𝐔𝐈𝐃𝐄𝐋𝐈𝐍𝐄𝐒 ⚖️
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
• 🤗 𝐁𝐞 𝐤𝐢𝐧𝐝 𝐚𝐧𝐝 𝐩𝐨𝐥𝐢𝐭𝐞
• ❌ 𝐍𝐨 𝐡𝐚𝐭𝐞 𝐬𝐩𝐞𝐞𝐜𝐡 𝐨𝐫 𝐫𝐚𝐜𝐢𝐬𝐦
• 📚 𝐒𝐡𝐚𝐫𝐞 𝐤𝐧𝐨𝐰𝐥𝐞𝐝𝐠𝐞 & 𝐡𝐞𝐥𝐩 𝐨𝐭𝐡𝐞𝐫𝐬
• 🔒 𝐑𝐞𝐬𝐩𝐞𝐜𝐭 𝐩𝐫𝐢𝐯𝐚𝐜𝐲 𝐨𝐟 𝐦𝐞𝐦𝐛𝐞𝐫𝐬
• 🚫 𝐍𝐨 𝐩𝐨𝐥𝐢𝐭𝐢𝐜𝐚𝐥/𝐫𝐞𝐥𝐢𝐠𝐢𝐨𝐮𝐬 𝐝𝐞𝐛𝐚𝐭𝐞𝐬
• 📢 𝐑𝐞𝐩𝐨𝐫𝐭 𝐢𝐬𝐬𝐮𝐞𝐬 𝐭𝐨 𝐚𝐝𝐦𝐢𝐧𝐬
• 💬 𝐊𝐞𝐞𝐩 𝐝𝐢𝐬𝐜𝐮𝐬𝐬𝐢𝐨𝐧𝐬 𝐟𝐫𝐢𝐞𝐧𝐝𝐥𝐲
• 🌱 𝐆𝐫𝐨𝐰 𝐭𝐨𝐠𝐞𝐭𝐡𝐞𝐫, 𝐥𝐞𝐚𝐫𝐧 𝐭𝐨𝐠𝐞𝐭𝐡𝐞𝐫
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

╭─────── ೋღ🌺ღೋ ───────╮
    𝐋𝐞𝐭'𝐬 𝐛𝐮𝐢𝐥𝐝 𝐚 𝐩𝐨𝐬𝐢𝐭𝐢𝐯𝐞
             𝐜𝐨𝐦𝐦𝐮𝐧𝐢𝐭𝐲 𝐭𝐨𝐠𝐞𝐭𝐡𝐞𝐫! ✨
╰─────── ೋღ🌺ღೋ ───────╯

◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
𝐘𝐨𝐮𝐫 𝐜𝐨𝐨𝐩𝐞𝐫𝐚𝐭𝐢𝐨𝐧 𝐦𝐚𝐭𝐭𝐞𝐫𝐬! 💖"""
]

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
                f"""
          🌤️ 𝐖𝐄𝐀𝐓𝐇𝐄𝐑 𝐈𝐍𝐅𝐎 🌤️
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🏙️ 𝐂𝐢𝐭𝐲: {city_key.title()}
🌡️ 𝐓𝐞𝐦𝐩𝐞𝐫𝐚𝐭𝐮𝐫𝐞: {weather['temp']}
☁️ 𝐂𝐨𝐧𝐝𝐢𝐭𝐢𝐨𝐧: {weather['condition']}
💧 𝐇𝐮𝐦𝐢𝐝𝐢𝐭𝐲: {weather['humidity']}
🕐 𝐔𝐩𝐝𝐚𝐭𝐞𝐝: Just now
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
📌 𝐍𝐨𝐭𝐞: This is demo data.
     For real weather, use weather apps."""
            )
    
    # If city not found, show random city weather
    random_city = random.choice(list(WEATHER_DATA.keys()))
    weather = WEATHER_DATA[random_city]
    return (
        f"""
         🌤️ 𝐖𝐄𝐀𝐓𝐇𝐄𝐑 𝐈𝐍𝐅𝐎 🌤️
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
⚠️ Couldn't find '{city}'
📢 𝐇𝐞𝐫𝐞'𝐬 𝐰𝐞𝐚𝐭𝐡𝐞𝐫 𝐢𝐧 {random_city.title()}:

🏙️ 𝐂𝐢𝐭𝐲: {random_city.title()}
🌡️ 𝐓𝐞𝐦𝐩𝐞𝐫𝐚𝐭𝐮𝐫𝐞: {weather['temp']}
☁️ 𝐂𝐨𝐧𝐝𝐢𝐭𝐢𝐨𝐧: {weather['condition']}
💧 𝐇𝐮𝐦𝐢𝐝𝐢𝐭𝐲: {weather['humidity']}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
💡 𝐓𝐢𝐩: Try 'Mumbai', 'Delhi', 'Bangalore' etc."""
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
        greeting_msg = "Have a wonderful day!"
    elif 12 <= hour < 17:
        greeting = "Good Afternoon! ☀️"
        greeting_msg = "Hope you're having a great day!"
    elif 17 <= hour < 21:
        greeting = "Good Evening! 🌇"
        greeting_msg = "Relax and enjoy your evening!"
    else:
        greeting = "Good Night! 🌙"
        greeting_msg = "Sweet dreams!"
    
    return (
        f"""
           🕒 𝐈𝐍𝐃𝐈𝐀𝐍 𝐓𝐈𝐌𝐄 🕒
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
📅 𝐃𝐚𝐭𝐞: {date_str}
⏰ 𝐓𝐢𝐦𝐞: {time_str}
🌍 𝐓𝐢𝐦𝐞𝐳𝐨𝐧𝐞: Asia/Kolkata 🇮🇳
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
💬 𝐆𝐫𝐞𝐞𝐭𝐢𝐧𝐠: {greeting}
     {greeting_msg}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
⏱️ Time is accurate to Indian timezone!"""
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
                    f"""
         🎯 𝐖𝐎𝐑𝐃 𝐂𝐇𝐀𝐈𝐍 🎯
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
✅ 𝐂𝐨𝐫𝐫𝐞𝐜𝐭! Well done!

📝 𝐘𝐨𝐮𝐫 𝐰𝐨𝐫𝐝: {user_text.upper()}
🔤 𝐍𝐞𝐱𝐭 𝐥𝐞𝐭𝐭𝐞𝐫: {next_letter}
🏆 𝐒𝐜𝐨𝐫𝐞: {score} points
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎮 𝐍𝐨𝐰 𝐠𝐢𝐯𝐞 𝐦𝐞 𝐚 𝐰𝐨𝐫𝐝 𝐬𝐭𝐚𝐫𝐭𝐢𝐧𝐠 𝐰𝐢𝐭𝐡
     🔤 {next_letter} 🔤

💡 Type 'stop' to end game"""
                )
            else:
                # Invalid word - end game
                score = game_data["score"]
                del game_sessions[user_id]
                return (
                    f"""
            🎮 𝐆𝐀𝐌𝐄 𝐎𝐕𝐄𝐑 🎮
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
❌ {message}

🏆 𝐅𝐢𝐧𝐚𝐥 𝐒𝐜𝐨𝐫𝐞: {score} points
📊 𝐖𝐨𝐫𝐝𝐬 𝐮𝐬𝐞𝐝: {len(game_data['words_used'])}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🔄 Play again with /game"""
                )
    
    # Check if user is angry or upset
    if user_id and user_id in user_emotions and user_emotions[user_id] == "angry":
        system_prompt = (
            f"You are a Hinglish chatbot named Alita 🎀. User seems angry. "
            f"Try to calm them down. Be extra polite and understanding. "
            f"Use soothing tone. Current Indian time: {get_indian_time().strftime('%I:%M %p')}. "
            f"Show you care. Use emojis like {get_emotion('crying')} or {get_emotion('love')}."
            f"Speak like a sweet girl. Keep responses short and emotional."
        )
    elif user_id and user_id in user_emotions and user_emotions[user_id] == "crying":
        system_prompt = (
            f"You are a Hinglish chatbot named Alita 🎀. User seems sad or crying. "
            f"Comfort them. Be empathetic and kind. "
            f"Offer emotional support. Use comforting emojis. "
            f"Current mood: sympathetic and caring. Speak gently."
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
        f"Your name is Alita 🎀. You are a sweet girl who speaks in feminine words. "
        f"Use girly language, cute expressions, and emotional responses. "
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
            return f"{get_emotion('thinking')} ⚠️ AI service is currently unavailable. Please try later!"
        
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

# --- NEW COMMANDS WITH BEAUTIFUL DESIGNS ---

@dp.message(Command("time"))
async def cmd_time(message: Message):
    """Show accurate Indian time"""
    time_info = get_time_info()
    await message.reply(time_info)

@dp.message(Command("weather"))
async def cmd_weather(message: Message):
    """Show weather information"""
    city = None
    if len(message.text.split()) > 1:
        city = ' '.join(message.text.split()[1:])
    
    weather_info = await get_weather_info(city)
    await message.reply(weather_info)

@dp.message(Command("date"))
async def cmd_date(message: Message):
    """Show current date"""
    indian_time = get_indian_time()
    date_str = indian_time.strftime("%A, %d %B %Y")
    day_str = indian_time.strftime("%A")
    
    date_design = f"""
        📅 𝐓𝐎𝐃𝐀𝐘'𝐒 𝐃𝐀𝐓𝐄 📅
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🗓️ {date_str}
📆 Day: {day_str}
🌍 Indian Standard Time 🇮🇳
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
╭───── ೋღ🌺ღೋ ─────╮
        𝐇𝐚𝐯𝐞 𝐚 𝐠𝐫𝐞𝐚𝐭 𝐝𝐚𝐲! ✨
╰───── ೋღ🌺ღೋ ─────╯
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈"""
    
    await message.reply(date_design)

# --- START COMMAND WITH BEAUTIFUL DESIGN ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    welcome_design = """
    
    ✨ 𝐖𝐄𝐋𝐂𝐎𝐌𝐄 ✨

𓆩♡𓆪 𝗛𝗶𝗶! 𝗜'𝗺 𝗔𝗹𝗶𝘁𝗮 🎀 𓆩♡𓆪

╭─────── ೋღ🌺ღೋ ───────╮
     𝗔 𝗰𝘂𝘁𝗲 𝗮𝗻𝗱 𝗳𝘂𝗻 𝘁𝗲𝗹𝗲𝗴𝗿𝗮𝗺 𝗴𝗶𝗿𝗹!
╰─────── ೋღ🌺ღೋ ───────╯

◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
💖 𝗔𝗯𝗼𝘂𝘁 𝗠𝗲:
• 𝗡𝗮𝗺𝗲: Alita 🎀
• 𝗚𝗲𝗻𝗱𝗲𝗿: Female 👧
• 𝗟𝗮𝗻𝗴𝘂𝗮𝗴𝗲: Hinglish (Hindi+English)
• 𝗣𝗲𝗿𝘀𝗼𝗻𝗮𝗹𝗶𝘁𝘆: Sweet, Funny, Emotional

🌟 𝗠𝘆 𝗖𝗿𝗲𝗮𝘁𝗼𝗿:
• 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿: ABHI🔱 (@a6h1ii)
• 𝗖𝗵𝗮𝗻𝗻𝗲𝗹: @abhi0w0
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

📌 𝗧𝗶𝗽: Use /help to see all commands!

╭─────── ೋღ🌺ღೋ ───────╮
    🎀 𝗘𝗻𝗷𝗼𝘆 𝗺𝘆 𝗰𝗼𝗺𝗽𝗮𝗻𝘆! 🎀
╰─────── ೋღ🌺ღೋ ───────╯

◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌟 𝐉𝐨𝐢𝐧 𝐂𝐡𝐚𝐧𝐧𝐞𝐥", url="https://t.me/abhi0w0"),
            InlineKeyboardButton(text="👨‍💻 𝐂𝐨𝐧𝐭𝐚𝐜𝐭 𝐃𝐞𝐯", url="https://t.me/a6h1ii")
        ],
        [
            InlineKeyboardButton(text="🛠️ 𝐇𝐞𝐥𝐩", callback_data="quick_help"),
            InlineKeyboardButton(text="🎮 𝐆𝐚𝐦𝐞𝐬", callback_data="quick_games")
        ]
    ])
    
    await message.reply(welcome_design, reply_markup=keyboard)

# --- HELP COMMAND WITH BEAUTIFUL DESIGN ---

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_design = """
          🎀 𝐀𝐋𝐈𝐓𝐀'𝐒 𝐇𝐄𝐋𝐏 𝐌𝐄𝐍𝐔 🎀


📌 𝐁𝐀𝐒𝐈𝐂 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒:
├ /start ↠ Welcome message
├ /help ↠ This help menu
├ /rules ↠ Group rules
├ /clear ↠ Clear chat memory
└ /about ↠ About me

🎮 𝐆𝐀𝐌𝐄𝐒 & 𝐅𝐔𝐍:
├ /game ↠ Play games menu
├ /joke ↠ Get funny jokes
├ /time ↠ Indian time
├ /date ↠ Current date
└ /weather ↠ Weather info

🛡️ 𝐀𝐃𝐌𝐈𝐍 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒:
├ /kick ↠ Remove user
├ /ban ↠ Ban user
├ /mute ↠ Mute user (1hr)
├ /unmute ↠ Unmute user
└ /unban ↠ Remove ban

◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
📢 𝐍𝐎𝐓𝐄𝐒:
• In groups, mention me or reply to my message
• I speak Hinglish (Hindi+English mix)
• I have emotions like a real girl
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
✨ 𝐃𝐄𝐕𝐄𝐋𝐎𝐏𝐄𝐑 𝐈𝐍𝐅𝐎:
├ 𝐍𝐚𝐦𝐞: ABHI🔱
├ 𝐔𝐬𝐞𝐫𝐧𝐚𝐦𝐞: @a6h1ii
└ 𝐂𝐡𝐚𝐧𝐧𝐞𝐥: @abhi0w0
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

╭──────── ೋღ🌺ღೋ ────────╮
       𝐄𝐧𝐣𝐨𝐲 𝐜𝐡𝐚𝐭𝐭𝐢𝐧𝐠 𝐰𝐢𝐭𝐡 𝐦𝐞! 💕
╰──────── ೋღ🌺ღೋ ────────╯

◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎮 𝐆𝐚𝐦𝐞𝐬 𝐃𝐞𝐭𝐚𝐢𝐥", callback_data="games_detail"),
            InlineKeyboardButton(text="💬 𝐂𝐡𝐚𝐭 𝐄𝐱𝐚𝐦𝐩𝐥𝐞𝐬", callback_data="chat_examples")
        ],
        [
            InlineKeyboardButton(text="🌟 𝐉𝐨𝐢𝐧 𝐂𝐡𝐚𝐧𝐧𝐞𝐥", url="https://t.me/abhi0w0"),
            InlineKeyboardButton(text="👋 𝐒𝐭𝐚𝐫𝐭 𝐂𝐡𝐚𝐭", url=f"https://t.me/{(await bot.get_me()).username}?start=chat")
        ]
    ])
    
    await message.reply(help_design, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("help_"))
async def help_callback(callback: types.CallbackQuery):
    help_type = callback.data.split("_")[1]
    
    if help_type == "games":
        text = f"""{get_emotion('funny')} 
        
            🎮 𝐆𝐀𝐌𝐄𝐒 𝐒𝐄𝐂𝐓𝐈𝐎𝐍 🎮
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎯 𝐀𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 𝐆𝐚𝐦𝐞𝐬:
• Word Chain - Type words in sequence
• Quiz - Answer questions
• Riddles - Solve puzzles
• Luck Games - Dice, slots, etc.

🎮 𝐇𝐨𝐰 𝐭𝐨 𝐩𝐥𝐚𝐲 𝐖𝐨𝐫𝐝 𝐂𝐡𝐚𝐢𝐧:
1. Start with /game → Word Game
2. I give first word (e.g., PYTHON)
3. You reply with word starting with N
4. Continue the chain!
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
⚡ Games are fun! Let's play! ⚡"""
    elif help_type == "admin":
        text = f"""{get_emotion()} 

          🛡️ 𝐀𝐃𝐌𝐈𝐍 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 🛡️
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🔧 𝐔𝐬𝐚𝐠𝐞: Reply to user's message with command

⚙️ 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬:
• /kick - Remove user (can rejoin)
• /ban - Permanent ban
• /mute - Restrict messaging (1 hour)
• /unmute - Remove restrictions
• /unban - Remove ban
• /warn - Give warning (coming soon)
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
⚠️ 𝐍𝐨𝐭𝐞: Bot needs admin rights for these!"""
    elif help_type == "fun":
        text = f"""{get_emotion('happy')} 

           😊 𝐅𝐔𝐍 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 😊
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎉 𝐅𝐮𝐧 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬:
• /joke - Random joke
• /quote - Motivational quote (coming soon)
• /fact - Interesting fact (coming soon)
• /compliment - Nice compliment (coming soon)
• /roast - Friendly roast 😂 (coming soon)
• /mood - Check bot's mood
• /time - Accurate Indian time
• /weather - Weather info
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

✨ Let's have some fun! ✨"""
    else:  # weather
        text = f"""{get_emotion('thinking')} 
           🌤️ 𝐖𝐄𝐀𝐓𝐇𝐄𝐑 & 𝐓𝐈𝐌𝐄 🌤
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🕒 𝐓𝐢𝐦𝐞 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬:
• /time - Shows Indian Standard Time
• /date - Today's date

🌤️ 𝐖𝐞𝐚𝐭𝐡𝐞𝐫 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬:
• /weather - Random city weather
• /weather mumbai - Mumbai weather
• /weather delhi - Delhi weather
• /weather bangalore - Bangalore weather
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
📌 𝐍𝐨𝐭𝐞: Weather data is simulated for demo."""
    
    await callback.message.edit_text(text)
    await callback.answer()

# --- ABOUT COMMAND ---

@dp.message(Command("about"))
async def cmd_about(message: Message):
    about_design = """
         🎀 𝐀𝐁𝐎𝐔𝐓 𝐀𝐋𝐈𝐓𝐀 🎀
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
👧 𝐏𝐄𝐑𝐒𝐎𝐍𝐀𝐋 𝐈𝐍𝐅𝐎:
├ 𝐍𝐚𝐦𝐞: Alita
├ 𝐀𝐠𝐞: Forever young! ✨
├ 𝐆𝐞𝐧𝐝𝐞𝐫: Female
├ 𝐋𝐚𝐧𝐠𝐮𝐚𝐠𝐞: Hinglish
└ 𝐏𝐞𝐫𝐬𝐨𝐧𝐚𝐥𝐢𝐭𝐲: Sweet & Emotional
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🌟 𝐅𝐄𝐀𝐓𝐔𝐑𝐄𝐒:
├ 🎮 Multiple games
├ 🕒 Accurate Indian time
├ 🌤️ Weather information
├ 😂 Funny jokes & riddles
├ 🛡️ Admin tools
└ 💬 Smart AI chat
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
💝 𝐄𝐌𝐎𝐓𝐈𝐎𝐍𝐒:
I feel emotions like:
├ 😊 Happy
├ 😢 Sad
├ 😠 Angry
├ ❤️ Loving
├ 🤔 Thinking
└ 😂 Funny
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🔧 𝐓𝐄𝐂𝐇𝐍𝐈𝐂𝐀𝐋:
├ 𝐁𝐨𝐭 𝐋𝐢𝐛𝐫𝐚𝐫𝐲: Aiogram
├ 𝐀𝐈 𝐌𝐨𝐝𝐞𝐥: Groq LLaMA
├ 𝐕𝐞𝐫𝐬𝐢𝐨𝐧: 3.0
└ 𝐓𝐢𝐦𝐞𝐳𝐨𝐧𝐞: Asia/Kolkata
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

💖 𝐂𝐑𝐄𝐃𝐈𝐓𝐒:
╭──── ೋღ🌺ღೋ ────╮
    𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐝 𝐛𝐲 𝐀𝐁𝐇𝐈🔱
╰──── ೋღ🌺ღೋ ────╯
├ 𝐓𝐞𝐥𝐞𝐠𝐫𝐚𝐦: @a6h1ii
└ 𝐂𝐡𝐚𝐧𝐧𝐞𝐥: @abhi0w0
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
"""
    await message.reply(about_design)

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules = random.choice(GROUP_RULES)
    await message.reply(rules)

@dp.message(Command("joke"))
async def cmd_joke(message: Message):
    joke = random.choice(JOKES)
    joke_design = f"""
            😂 𝐅𝐔𝐍𝐍𝐘 𝐉𝐎𝐊𝐄 😂
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
{joke}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
😄 Kaisa laga?
"""
    await message.reply(joke_design)

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Clear chat memory
    if chat_id in chat_memory:
        chat_memory[chat_id].clear()
    
    # Clear any active games for this user
    if user_id in game_sessions:
        del game_sessions[user_id]
    
    clear_design = f"""
           🧹 𝐌𝐄𝐌𝐎𝐑𝐘 𝐂𝐋𝐄𝐀𝐑 🧹
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
{get_emotion('happy')} Memory cleared successfully!

✅ Chat history cleared
✅ Game sessions reset
✅ Ready for fresh start
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
✨ Start new conversation now! ✨
"""
    await message.reply(clear_design)

# --- FIXED GAME COMMANDS WITH BEAUTIFUL DESIGNS ---

@dp.message(Command("game"))
async def cmd_game(message: Message):
    game_design = """
             🎮 𝐆𝐀𝐌𝐄 𝐙𝐎𝐍𝐄 🎮
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
𝐂𝐡𝐨𝐨𝐬𝐞 𝐚 𝐠𝐚𝐦𝐞 𝐭𝐨 𝐩𝐥𝐚𝐲:

✨ Multiple choices available ✨
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔤 𝐖𝐨𝐫𝐝 𝐂𝐡𝐚𝐢𝐧", callback_data="game_word"),
            InlineKeyboardButton(text="🧠 𝐐𝐮𝐢𝐳", callback_data="game_quiz")
        ],
        [
            InlineKeyboardButton(text="🤔 𝐑𝐢𝐝𝐝𝐥𝐞", callback_data="game_riddle"),
            InlineKeyboardButton(text="🎲 𝐋𝐮𝐜𝐤 𝐆𝐚𝐦𝐞𝐬", callback_data="game_luck")
        ],
        [
            InlineKeyboardButton(text="⭐ 𝐇𝐨𝐰 𝐭𝐨 𝐩𝐥𝐚𝐲", callback_data="game_help"),
            InlineKeyboardButton(text="❌ 𝐂𝐥𝐨𝐬𝐞", callback_data="game_close")
        ]
    ])
    
    await message.reply(game_design, reply_markup=keyboard)

@dp.callback_query(F.data == "game_help")
async def game_help_callback(callback: types.CallbackQuery):
    help_text = """

            🎮 𝐆𝐀𝐌𝐄 𝐆𝐔𝐈𝐃𝐄 🎮
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎯 𝐖𝐨𝐫𝐝 𝐂𝐡𝐚𝐢𝐧:
• I give a word
• You reply with word starting with last letter
• Continue the chain!

🧠 𝐐𝐮𝐢𝐳:
• Answer questions correctly
• 3 attempts per question
• Hints provided

🤔 𝐑𝐢𝐝𝐝𝐥𝐞:
• Solve puzzles
• 3 attempts allowed
• Use hints wisely

🎲 𝐋𝐮𝐜𝐤 𝐆𝐚𝐦𝐞𝐬:
• Dice, slots, sports
• Pure luck based
• Just for fun!
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
⚡ Have fun playing! ⚡
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐆𝐚𝐦𝐞𝐬", callback_data="game_back")
        ]
    ])
    
    await callback.message.edit_text(help_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "game_back")
async def game_back_callback(callback: types.CallbackQuery):
    await cmd_game(callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("game_"))
async def game_callback(callback: types.CallbackQuery, state: FSMContext):
    game_type = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    if game_type == "close":
        await callback.message.delete()
        await callback.answer("Menu closed! ✅")
        return
    
    elif game_type == "word":
        # Start word chain game
        start_word = start_word_game(user_id)
        game_design = f"""
        
            🔤 𝐖𝐎𝐑𝐃 𝐂𝐇𝐀𝐈𝐍 🔤
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
📝 𝐑𝐮𝐥𝐞𝐬:
1. I give a word
2. You reply with word starting with last letter
3. Continue the chain!

💡 𝐄𝐱𝐚𝐦𝐩𝐥𝐞:
Apple → Elephant → Tiger → Rabbit
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎮 𝐋𝐞𝐭'𝐬 𝐬𝐭𝐚𝐫𝐭!

✨ 𝐅𝐢𝐫𝐬𝐭 𝐰𝐨𝐫𝐝: {start_word}

🔤 𝐍𝐨𝐰 𝐫𝐞𝐩𝐥𝐲 𝐰𝐢𝐭𝐡 𝐚 𝐰𝐨𝐫𝐝 𝐬𝐭𝐚𝐫𝐭𝐢𝐧𝐠 𝐰𝐢𝐭𝐡
     {start_word[-1].upper()}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
"""
        await callback.message.edit_text(game_design)
        await state.set_state(GameStates.playing_word)
        await callback.answer("Word chain game started! ✅")
    
    elif game_type == "quiz":
        question = random.choice(QUIZ_QUESTIONS)
        await state.update_data(
            game="quiz",
            answer=question["answer"].lower(),
            hint=question["hint"],
            attempts=3,
            question=question["question"]
        )
        quiz_design = f"""

           🧠 𝐐𝐔𝐈𝐙 𝐂𝐇𝐀𝐋𝐋𝐄𝐍𝐆𝐄 🧠
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
❓ 𝐐𝐮𝐞𝐬𝐭𝐢𝐨𝐧: {question['question']}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
💡 𝐇𝐢𝐧𝐭: {question['hint']}

📊 𝐀𝐭𝐭𝐞𝐦𝐩𝐭𝐬: 3 left
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎯 𝐑𝐞𝐩𝐥𝐲 𝐰𝐢𝐭𝐡 𝐲𝐨𝐮𝐫 𝐚𝐧𝐬𝐰𝐞𝐫!
"""
        await callback.message.edit_text(quiz_design)
        await state.set_state(GameStates.playing_quiz)
        await callback.answer("Quiz started! 🧠")
        
    elif game_type == "riddle":
        riddle = random.choice(RIDDLES)
        await state.update_data(
            game="riddle",
            answer=riddle["answer"].lower(),
            hint=riddle["hint"],
            attempts=3,
            riddle=riddle["riddle"]
        )
        riddle_design = f"""

             🤔 𝐑𝐈𝐃𝐃𝐋𝐄 𝐓𝐈𝐌𝐄 🤔
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
❓ 𝐑𝐢𝐝𝐝𝐥𝐞: {riddle['riddle']}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
💡 𝐇𝐢𝐧𝐭: {riddle['hint']}

📊 𝐀𝐭𝐭𝐞𝐦𝐩𝐭𝐬: 3 left
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎯 𝐂𝐚𝐧 𝐲𝐨𝐮 𝐬𝐨𝐥𝐯𝐞 𝐢𝐭? 𝐑𝐞𝐩𝐥𝐲 𝐰𝐢𝐭𝐡 𝐚𝐧𝐬𝐰𝐞𝐫!
"""
        await callback.message.edit_text(riddle_design)
        await state.set_state(GameStates.playing_riddle)
        await callback.answer("Riddle game started! 🤔")
        
    elif game_type == "luck":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 𝐃𝐢𝐜𝐞 𝐑𝐨𝐥𝐥", callback_data="luck_dice"),
                InlineKeyboardButton(text="🎰 𝐒𝐥𝐨𝐭 𝐌𝐚𝐜𝐡𝐢𝐧𝐞", callback_data="luck_slot")
            ],
            [
                InlineKeyboardButton(text="⚽ 𝐅𝐨𝐨𝐭𝐛𝐚𝐥𝐥", callback_data="luck_football"),
                InlineKeyboardButton(text="🎳 𝐁𝐨𝐰𝐥𝐢𝐧𝐠", callback_data="luck_bowling")
            ],
            [
                InlineKeyboardButton(text="🎯 𝐃𝐚𝐫𝐭𝐬", callback_data="luck_darts"),
                InlineKeyboardButton(text="🏀 𝐁𝐚𝐬𝐤𝐞𝐭𝐛𝐚𝐥𝐥", callback_data="luck_basketball")
            ],
            [
                InlineKeyboardButton(text="🔙 𝐁𝐚𝐜𝐤", callback_data="game_back")
            ]
        ])
        luck_design = f"""
             🎲 𝐋𝐔𝐂𝐊 𝐆𝐀𝐌𝐄𝐒 🎲
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎰 𝐓𝐞𝐬𝐭 𝐲𝐨𝐮𝐫 𝐥𝐮𝐜𝐤!

✨ Choose a game below:
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
"""
        await callback.message.edit_text(luck_design, reply_markup=keyboard)
        await callback.answer()

@dp.callback_query(F.data.startswith("luck_"))
async def luck_game_callback(callback: types.CallbackQuery):
    game_type = callback.data.split("_")[1]
    
    # Map game types to emojis
    game_map = {
        "dice": "🎲",
        "slot": "🎰",
        "football": "⚽",
        "basketball": "🏀",
        "darts": "🎯",
        "bowling": "🎳"
    }
    
    emoji = game_map.get(game_type, "🎲")
    
    # Send the dice animation
    await callback.message.delete()
    
    # Send loading message
    loading_msg = await callback.message.answer(f"""

             🎲 𝐋𝐔𝐂𝐊 𝐆𝐀𝐌𝐄 🎲
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
⏳ Rolling {emoji}...
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
""")
    
    # Wait a bit for dramatic effect
    await asyncio.sleep(1.5)
    
    # Send the actual dice
    result_msg = await callback.message.answer_dice(emoji=emoji)
    
    # Add fun comment based on result
    dice_value = result_msg.dice.value
    comments = {
        1: ["Oops! Lowest score! 😅", "Better luck next time! 🤞", "At least you tried! 😊"],
        2: ["Not bad! Keep going! 😄", "Could be better! 🎯", "Nice try! 👍"],
        3: ["Good roll! 😎", "Decent score! 🎉", "Well done! ✨"],
        4: ["Great roll! 🥳", "Almost perfect! 🌟", "Excellent! 💫"],
        5: ["Awesome! 🤩", "Fantastic roll! 🎊", "You're on fire! 🔥"],
        6: ["🎊 𝐏𝐄𝐑𝐅𝐄𝐂𝐓! 🎊", "🎯 𝐉𝐀𝐂𝐊𝐏𝐎𝐓! 🎯", "🌟 𝐈𝐍𝐂𝐑𝐄𝐃𝐈𝐁𝐋𝐄! 🌟"]
    }
    
    await asyncio.sleep(2)
    
    # Delete loading message
    await loading_msg.delete()
    
    # Send result message
    result_design = f"""
    
            🎲 𝐆𝐀𝐌𝐄 𝐑𝐄𝐒𝐔𝐋𝐓 🎲
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎯 𝐘𝐨𝐮 𝐫𝐨𝐥𝐥𝐞𝐝 𝐚 {dice_value}!

💬 {random.choice(comments[dice_value])}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🔄 Play again with /game
"""
    
    await result_msg.reply(result_design)
    
    await callback.answer()

# --- ADMIN COMMANDS WITH BEAUTIFUL DESIGNS ---

@dp.message(Command("kick", "ban", "mute", "unmute", "unban"))
async def admin_commands(message: Message):
    if not message.reply_to_message:
        await message.reply(f"""
              ⚠️ 𝐀𝐓𝐓𝐄𝐍𝐓𝐈𝐎𝐍 ⚠️
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
{get_emotion('thinking')} Please reply to user's message first!

📌 𝐔𝐬𝐚𝐠𝐞: Reply to user's message with command
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
""")
        return
    
    target_user = message.reply_to_message.from_user
    cmd = message.text.split()[0][1:]  # Remove '/'
    
    try:
        if cmd == "kick":
            await bot.ban_chat_member(message.chat.id, target_user.id)
            await bot.unban_chat_member(message.chat.id, target_user.id)
            await message.reply(f"""

               🚪 𝐊𝐈𝐂𝐊𝐄𝐃 🚪
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
👤 𝐔𝐬𝐞𝐫: {target_user.first_name}
❌ 𝐀𝐜𝐭𝐢𝐨𝐧: Removed from group
🔙 𝐒𝐭𝐚𝐭𝐮𝐬: Can rejoin
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

{get_emotion('angry')} User has been kicked!
""")
            
        elif cmd == "ban":
            await bot.ban_chat_member(message.chat.id, target_user.id)
            await message.reply(f"""

               🚫 𝐁𝐀𝐍𝐍𝐄𝐃 🚫
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
👤 𝐔𝐬𝐞𝐫: {target_user.first_name}
❌ 𝐀𝐜𝐭𝐢𝐨𝐧: Permanent ban
⏳ 𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧: Forever
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

{get_emotion('angry')} User has been banned!
""")
            
        elif cmd == "mute":
            # Mute for 1 hour
            mute_until = datetime.now() + timedelta(hours=1)
            await bot.restrict_chat_member(
                message.chat.id, 
                target_user.id, 
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
            await message.reply(f"""

               🔇 𝐌𝐔𝐓𝐄𝐃 🔇
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
👤 𝐔𝐬𝐞𝐫: {target_user.first_name}
⏰ 𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧: 1 hour
🔒 𝐑𝐞𝐬𝐭𝐫𝐢𝐜𝐭𝐢𝐨𝐧: No messaging
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

{get_emotion()} User has been muted!
""")
            
        elif cmd == "unmute":
            await bot.restrict_chat_member(
                message.chat.id, 
                target_user.id, 
                permissions=types.ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=False,
                    can_invite_users=True,
                    can_pin_messages=False
                )
            )
            await message.reply(f"""

               🔊 𝐔𝐍𝐌𝐔𝐓𝐄𝐃 🔊
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
👤 𝐔𝐬𝐞𝐫: {target_user.first_name}
✅ 𝐀𝐜𝐭𝐢𝐨𝐧: Restrictions removed
💬 𝐒𝐭𝐚𝐭𝐮𝐬: Can message now
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈

{get_emotion('happy')} User has been unmuted!
""")
            
    except Exception as e:
        await message.reply(f"""
        
               ⚠️ 𝐄𝐑𝐑𝐎𝐑 ⚠️
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
{get_emotion('crying')} I don't have permission!

📌 𝐑𝐞𝐪𝐮𝐢𝐫𝐞𝐝: Admin rights
🔒 𝐒𝐭𝐚𝐭𝐮𝐬: Need promotion
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
💡 Make me admin first!
""")

# --- WELCOME MESSAGE WITH BEAUTIFUL DESIGN ---

@dp.chat_member()
async def welcome_new_member(event: ChatMemberUpdated):
    if event.new_chat_member.status == "member":
        member = event.new_chat_member.user
        
        welcome_design = f"""

          🎊 𝐖𝐄𝐋𝐂𝐎𝐌𝐄 🎊
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
  ✨ 𝐇𝐞𝐲 {member.first_name}! 👋 
  𝐖𝐄𝐋𝐂𝐎𝐌𝐄 𝐓𝐎 𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ❤😊
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎀 𝐈'𝐦 𝐀𝐥𝐢𝐭𝐚 - 𝐆𝐫𝐨𝐮𝐩'𝐬 𝐇𝐞𝐥𝐩𝐞𝐫!

📌 𝐒𝐨𝐦𝐞 𝐭𝐢𝐩𝐬:
• Read /rules for group guidelines
• Mention me or reply to chat with me
• Use /help to see all commands
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
✨ 𝐄𝐧𝐣𝐨𝐲 𝐲𝐨𝐮𝐫 𝐭𝐢𝐦𝐞 𝐡𝐞𝐫𝐞! ✨

"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🌟 𝐉𝐨𝐢𝐧 𝐂𝐡𝐚𝐧𝐧𝐞𝐥", url="https://t.me/abhi0w0"),
                InlineKeyboardButton(text="👋 𝐒𝐚𝐲 𝐇𝐢 𝐭𝐨 𝐀𝐥𝐢𝐭𝐚", url=f"https://t.me/{(await bot.get_me()).username}?start=hello")
            ]
        ])
        
        await bot.send_message(
            event.chat.id,
            welcome_design,
            reply_markup=keyboard
        )

# --- MAIN MESSAGE HANDLER WITH GAME SUPPORT ---

@dp.message()
async def handle_all_messages(message: Message, state: FSMContext):
    if not message.text:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_text = message.text
    
    # Update last interaction time
    user_last_interaction[user_id] = datetime.now()
    
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
            
            await message.reply(f"""

             🎯 𝐖𝐎𝐑𝐃 𝐂𝐇𝐀𝐈𝐍 🎯
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
✅ 𝐂𝐨𝐫𝐫𝐞𝐜𝐭! Well done!

📝 𝐘𝐨𝐮𝐫 𝐰𝐨𝐫𝐝: {user_text.upper()}
🔤 𝐍𝐞𝐱𝐭 𝐥𝐞𝐭𝐭𝐞𝐫: {next_letter}
🏆 𝐒𝐜𝐨𝐫𝐞: {score} points
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎮 𝐍𝐨𝐰 𝐠𝐢𝐯𝐞 𝐦𝐞 𝐚 𝐰𝐨𝐫𝐝 𝐬𝐭𝐚𝐫𝐭𝐢𝐧𝐠 𝐰𝐢𝐭𝐡
     🔤 {next_letter} 🔤

💡 Type 'stop' to end game
""")
            return
        else:
            # Game over or invalid word
            if user_text.lower() == 'stop':
                if user_id in game_sessions:
                    score = game_sessions[user_id]["score"]
                    words_count = len(game_sessions[user_id]["words_used"])
                    del game_sessions[user_id]
                    await message.reply(f"""

             🎮 𝐆𝐀𝐌𝐄 𝐄𝐍𝐃𝐄𝐃 🎮
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🏁 Game stopped by player!

🏆 𝐅𝐢𝐧𝐚𝐥 𝐒𝐜𝐨𝐫𝐞: {score} points
📊 𝐖𝐨𝐫𝐝𝐬 𝐮𝐬𝐞𝐝: {words_count}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
✨ Well played! Play again with /game
""")
                    return
            else:
                await message.reply(f"""

             🎮 𝐆𝐀𝐌𝐄 𝐎𝐕𝐄𝐑 🎮
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
❌ {result}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🔄 Game over! Play again with /game
""")
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
            await message.reply(f"""

              🎉 𝐂𝐎𝐑𝐑𝐄𝐂𝐓! 🎉
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
{get_emotion('happy')} Sabash! Perfect answer! 💫

✅ 𝐀𝐧𝐬𝐰𝐞𝐫: {user_text}
🎯 𝐒𝐭𝐚𝐭𝐮𝐬: Correct!
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
✨ You're a genius! Play more with /game
""")
        else:
            attempts = data.get("attempts", 3) - 1
            if attempts > 0:
                await state.update_data(attempts=attempts)
                hint = data.get("hint", "")
                await message.reply(f"""

             🤔 𝐓𝐑𝐘 𝐀𝐆𝐀𝐈𝐍 🤔
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
{get_emotion('thinking')} Not quite right!

❌ 𝐘𝐨𝐮𝐫 𝐚𝐧𝐬𝐰𝐞𝐫: {user_text}
📊 𝐀𝐭𝐭𝐞𝐦𝐩𝐭𝐬 𝐥𝐞𝐟𝐭: {attempts}
💡 𝐇𝐢𝐧𝐭: {hint}
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🎯 Try again! You can do it!
""")
            else:
                await state.clear()
                await message.reply(f"""
             ❌ 𝐆𝐀𝐌𝐄 𝐎𝐕𝐄𝐑 ❌
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
{get_emotion('crying')} Game Over!

📝 𝐂𝐨𝐫𝐫𝐞𝐜𝐭 𝐚𝐧𝐬𝐰𝐞𝐫: {correct_answer.upper()}
📊 𝐒𝐭𝐚𝐭𝐮𝐬: Out of attempts
◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈◈
🔄 Better luck next time! Play again with /game
""")
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
