import os
import asyncio
import random
import aiohttp
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from groq import AsyncGroq
from aiohttp import web
import pytz
import json

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
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

# Memory: {chat_id: deque}
chat_memory: Dict[int, deque] = {}

# Game states storage: {user_id: game_data}
active_games: Dict[int, Dict] = {}
game_sessions: Dict[int, Dict] = {}

# Emotional states for each user
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}

# Store all started users for broadcast
started_users: set = set()

# States for games
class GameStates(StatesGroup):
    playing_quiz = State()
    playing_riddle = State()
    playing_word = State()
    waiting_answer = State()

# --- STICKER DATABASES ---
STICKER_PACKS = {
    "good_morning": [
        "CAACAgIAAxkBAAEKWzNlJ0tY6S1X_1mE5Y1P3vQ3Y3U5rwACDQADwDZPE7qGKRXYm3QeMAQ",  # Sun sticker
        "CAACAgIAAxkBAAEKWzdlJ0uL7I1vF3yYhK3YQ7m9X2vP5QACDwADwDZPE1xQjBXYm3QeMAQ",
        "CAACAgIAAxkBAAEKWzllJ0uY8J2wG4zZiL4ZR8n0Y3wQ6gACEQADwDZPE2xRkBXYm3QeMAQ",
    ],
    "good_night": [
        "CAACAgIAAxkBAAEKWztlJ0ur9K3xH5a0jM5AS9o1Z4xR7wACFgADwDZPE3xSlBXYm3QeMAQ",  # Moon sticker
        "CAACAgIAAxkBAAEKWz1lJ0vA-L4yI6b1kN6BT-p2a5yS8AACGAADwDZPE4xWmBXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW0FlJ0vN_a5zJ7c2lO7CU_q3b6zT9QACGwADwDZPE5xYnRXYm3QeMAQ",
    ],
    "happy": [
        "CAACAgIAAxkBAAEKW0NlJ0vgAL60K8g4mQ8EVIB5d8QeMQACHQADwDZPE6xaoBXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW0VlJ0vwAfC1L9k5mR9FWIJ6eMQeMgACHwADwDZPE7xboRXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW0dlJ0wAAn66M-o6mh-GWYN7fMQeMwACHgADwDZPE8xcoRXYm3QeMAQ",
    ],
    "love": [
        "CAACAgIAAxkBAAEKW0llJ0xQ_9C7NAs8nSJIXYR8gcQeNAACIQADwDZPE-xeoRXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW01lJ0xgAPy8OQ09niVJYoR9gsQeNQACIwADwDZPEyxfwBXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW09lJ0xwAf-9Pg2AoChKY4V-g8QeNgACJQADwDZPE0xfwBXYm3QeMAQ",
    ],
    "angry": [
        "CAACAgIAAxkBAAEKW1FlJ0yQ_4C-Qg-CpSpLZIZ-hMQeNwACKQADwDZPE2xgwhXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW1NlJ0ygAAABv0SPg6crS2SGfoXEeDgACisAA8A2TxNsYcIV2Jt0HjAE",
        "CAACAgIAAxkBAAEKW1VlJ0ywAADBBEqRhKwtLYR-hsR4OQACKwADwDZPFGxhwRXYm3QeMAQ",
    ],
    "funny": [
        "CAACAgIAAxkBAAEKW1dlJ0zA_8HCRAyEpixMZYl-iMR4OwACLQADwDZPFGxjwRXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW1llJ0zQ_9HDRQ2Fpy5NZop-jcR4PAACLwADwDZPFGxkwRXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW1tlJ0zgAMHDRg6GqDBOZ4t-kMR4PQACMQADwDZPFGxlwRXYm3QeMAQ",
    ],
    "crying": [
        "CAACAgIAAxkBAAEKW11lJ0zw_8JESJKHqTJPapB-lMR4PgACMwADwDZPFGxmwRXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW2FlJ00A_9LFSpSJqjJQa5J-mcR4PwACNQADwDZPFGxowRXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW2NlJ00Q_9PFTJaKqzJRbJN-nMR4QAACNwADwDZPFGxpwRXYm3QeMAQ",
    ],
    "celebration": [
        "CAACAgIAAxkBAAEKW2VlJ00g_9TGUpgKrjVSc5R-ntR4QQACOQADwDZPFGxrwBXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW2dlJ00w_9XHVJmKrzZTdZV-oNR4QgACOwADwDZPFGxtwBXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW2llJ01A_9bJVpqKsDhTfJd-p9R4QwACPQADwDZPFGxvwBXYm3QeMAQ",
    ],
    "welcome": [
        "CAACAgIAAxkBAAEKW2tlJ01Q_9fKW5wKsUlUgZl-sNR4RAACPwADwDZPFGxxwBXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW21lJ01g_9jMXJ6KsllViJp-s9R4RQACQQADwDZPFGxzwBXYm3QeMAQ",
        "CAACAgIAAxkBAAEKW29lJ01w_9nNYJ-KtVlWkZt-ttR4RgACQwADwDZPFGx1wBXYm3QeMAQ",
    ]
}

# Fallback sticker URLs if file_ids don't work
STICKER_URLS = {
    "good_morning": ["https://t.me/addstickers/VirtualPuppy"],
    "good_night": ["https://t.me/addstickers/VirtualPuppy"],
}

# --- HUMAN-LIKE BEHAVIOUR EMOTIONS ---
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

QUICK_RESPONSES = {
    "greeting": [
        "Hello ji😊", 
        "helloooooo🤧", 
        "Hiiiiiiiii",
        "Hello! 👊🏻",
        "Heyyy!👋🏻",
        "hyyyeeeeeeeeee🤧"
    ],
    "goodbye": [
        "Bye bye! Jaldi baat karna! 👋", 
        "Chalo, mai ja raha hu! Baad me baat karte hain! 😊", 
        "Alvida! Take care! 💫",
        "Jaane do na! Phir milenge! 😄",
        "Okay bye! I'll miss you! 😢"
    ],
    "thanks": [
        "Arey koi baat nahi! 😊", 
        "Welcome ji! Happy to help! 🌟", 
        "No problem yaar! Anytime! 💖",
        "Mujhe kya, main to bot hu! 😂",
        "It's my duty! 😇"
    ],
    "sorry": [
        "Aree sorry yaar! 😢", 
        "Maine galti kar di! Maaf karna! 😔", 
        "Oops! My bad! 😅",
        "Bhool gaya tha! Sorry bhai! 🥺",
        "I messed up! Forgive me? 💔"
    ],
    "good_morning": [
        "Good Morning! 🌅 Uth gaye? Aaj ka din mast hoga!",
        "Subah ho gayi! ☀️ Chai pee li? Good morning!",
        "Rise and shine! 🌞 Naya din, nayi energy!",
        "Good Morning yaar! 🌅 Aaj kya plan hai?",
        "Namaste! 🙏 Subah ki shuruaat ho chuki hai!"
    ],
    "good_night": [
        "Good Night! 🌙 Sweet dreams!",
        "Sone ka time ho gaya! 😴 Rest karo!",
        "Shabba khair! 🌜 Kal milte hain!",
        "Good night yaar! 💤 Peaceful sleep!",
        "Nind aayi? 🌛 So jao, kal baat karte hain!"
    ]
}

# Get Indian time
def get_indian_time():
    utc_now = datetime.now(pytz.utc)
    indian_time = utc_now.astimezone(INDIAN_TIMEZONE)
    return indian_time

# --- REAL WEATHER API (Open-Meteo - 100% FREE, NO API KEY) ---
INDIAN_CITIES = {
    "mumbai": {"lat": 19.0760, "lon": 72.8777},
    "delhi": {"lat": 28.6139, "lon": 77.2090},
    "bangalore": {"lat": 12.9716, "lon": 77.5946},
    "kolkata": {"lat": 22.5726, "lon": 88.3639},
    "chennai": {"lat": 13.0827, "lon": 80.2707},
    "hyderabad": {"lat": 17.3850, "lon": 78.4867},
    "pune": {"lat": 18.5204, "lon": 73.8567},
    "ahmedabad": {"lat": 23.0225, "lon": 72.5714},
    "jaipur": {"lat": 26.9124, "lon": 75.7873},
    "surat": {"lat": 21.1702, "lon": 72.8311},
    "lucknow": {"lat": 26.8467, "lon": 80.9462},
    "kanpur": {"lat": 26.4499, "lon": 80.3319},
    "nagpur": {"lat": 21.1458, "lon": 79.0882},
    "patna": {"lat": 25.5941, "lon": 85.1376},
    "indore": {"lat": 22.7196, "lon": 75.8577},
    "thane": {"lat": 19.2183, "lon": 72.9781},
    "bhopal": {"lat": 23.2599, "lon": 77.4126},
    "visakhapatnam": {"lat": 17.6868, "lon": 83.2185},
    "vadodara": {"lat": 22.3072, "lon": 73.1812},
    "firozabad": {"lat": 27.1592, "lon": 78.3957}
}

async def get_real_weather(city: str = None) -> str:
    """Get REAL weather from Open-Meteo API (100% Free, No API Key)"""
    try:
        if not city:
            # Default to random major city
            city = random.choice(list(INDIAN_CITIES.keys()))
        
        city_lower = city.lower().strip()
        
        # Check if city is in our database
        if city_lower in INDIAN_CITIES:
            coords = INDIAN_CITIES[city_lower]
        else:
            # Try to get coordinates from Open-Meteo Geocoding API
            async with aiohttp.ClientSession() as session:
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=en&format=json"
                async with session.get(geo_url) as response:
                    if response.status == 200:
                        geo_data = await response.json()
                        if "results" in geo_data and geo_data["results"]:
                            result = geo_data["results"][0]
                            coords = {"lat": result["latitude"], "lon": result["longitude"]}
                            city_display = result["name"]
                        else:
                            return f"❌ City '{city}' not found! Try: Mumbai, Delhi, Bangalore, etc."
                    else:
                        return f"❌ Unable to find city '{city}'. Please try again."
        
        # Get weather data
        async with aiohttp.ClientSession() as session:
            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={coords['lat']}&longitude={coords['lon']}&"
                f"current=temperature_2m,relative_humidity_2m,apparent_temperature,"
                f"weather_code,wind_speed_10m,pressure_msl&"
                f"daily=temperature_2m_max,temperature_2m_min,sunrise,sunset&"
                f"timezone=Asia%2FKolkata"
            )
            
            async with session.get(weather_url) as response:
                if response.status == 200:
                    data = await response.json()
                    current = data["current"]
                    daily = data["daily"]
                    
                    # Weather code interpretation
                    weather_codes = {
                        0: "Clear Sky ☀️", 1: "Mainly Clear 🌤️", 2: "Partly Cloudy ⛅", 3: "Overcast ☁️",
                        45: "Foggy 🌫️", 48: "Depositing Rime Fog 🌫️",
                        51: "Light Drizzle 🌦️", 53: "Moderate Drizzle 🌧️", 55: "Dense Drizzle 🌧️",
                        61: "Slight Rain 🌧️", 63: "Moderate Rain 🌧️", 65: "Heavy Rain 🌧️",
                        71: "Slight Snow 🌨️", 73: "Moderate Snow ❄️", 75: "Heavy Snow ❄️",
                        77: "Snow Grains 🌨️", 80: "Slight Rain Showers 🌦️", 81: "Moderate Rain Showers 🌧️",
                        82: "Violent Rain Showers ⛈️", 85: "Slight Snow Showers 🌨️", 86: "Heavy Snow Showers ❄️",
                        95: "Thunderstorm ⛈️", 96: "Thunderstorm with Hail ⛈️", 99: "Heavy Thunderstorm ⛈️"
                    }
                    
                    weather_desc = weather_codes.get(current.get("weather_code", 0), "Unknown 🌡️")
                    temp = current.get("temperature_2m", "N/A")
                    feels_like = current.get("apparent_temperature", "N/A")
                    humidity = current.get("relative_humidity_2m", "N/A")
                    wind_speed = current.get("wind_speed_10m", "N/A")
                    pressure = current.get("pressure_msl", "N/A")
                    
                    max_temp = daily.get("temperature_2m_max", ["N/A"])[0]
                    min_temp = daily.get("temperature_2m_min", ["N/A"])[0]
                    sunrise = daily.get("sunrise", ["N/A"])[0]
                    sunset = daily.get("sunset", ["N/A"])[0]
                    
                    # Format times
                    sunrise_time = sunrise.split("T")[1] if isinstance(sunrise, str) and "T" in sunrise else sunrise
                    sunset_time = sunset.split("T")[1] if isinstance(sunset, str) and "T" in sunset else sunset
                    
                    city_display = city.title()
                    
                    return (
                        f"🌤️ **Weather Report for {city_display}**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🌡️ **Temperature:** {temp}°C\n"
                        f"😪 **Feels Like:** {feels_like}°C\n"
                        f"☁️ **Condition:** {weather_desc}\n"
                        f"💧 **Humidity:** {humidity}%\n"
                        f"💨 **Wind Speed:** {wind_speed} km/h\n"
                        f"🌡️ **Pressure:** {pressure} hPa\n\n"
                        f"📊 **Today's Forecast:**\n"
                        f"🔥 **Max:** {max_temp}°C | ❄️ **Min:** {min_temp}°C\n"
                        f"🌅 **Sunrise:** {sunrise_time}\n"
                        f"🌇 **Sunset:** {sunset_time}\n\n"
                        f"⏰ **Updated:** Just now\n"
                        f"📍 **Source:** Open-Meteo (Real-time Data)"
                    )
                else:
                    return "❌ Weather service temporarily unavailable. Please try again later."
    except Exception as e:
        return f"❌ Error fetching weather: {str(e)}\nPlease try again later."

def get_emotion(emotion_type: str = None, user_id: int = None) -> str:
    """Get appropriate emotion with some randomness"""
    if user_id and user_id in user_emotions:
        if random.random() < 0.3:
            emotion_type = user_emotions[user_id]
    
    if emotion_type and emotion_type in EMOTIONAL_RESPONSES:
        return random.choice(EMOTIONAL_RESPONSES[emotion_type])
    
    all_emotions = list(EMOTIONAL_RESPONSES.values())
    return random.choice(random.choice(all_emotions))

def update_user_emotion(user_id: int, message: str):
    message_lower = message.lower()
    
    if any(word in message_lower for word in ['love', 'pyaar', 'dil', 'heart', 'cute', 'beautiful', 'miss you']):
        user_emotions[user_id] = "love"
    elif any(word in message_lower for word in ['angry', 'gussa', 'naraz', 'mad', 'hate', 'idiot', 'stupid']):
        user_emotions[user_id] = "angry"
    elif any(word in message_lower for word in ['cry', 'ro', 'sad', 'dukh', 'upset', 'unhappy', 'depressed']):
        user_emotions[user_id] = "crying"
    elif any(word in message_lower for word in ['funny', 'has', 'joke', 'comedy', 'masti', 'laugh', 'haha']):
        user_emotions[user_id] = "funny"
    elif any(word in message_lower for word in ['hi', 'hello', 'hey', 'namaste', 'kaise', 'sup']):
        user_emotions[user_id] = "happy"
    elif any(word in message_lower for word in ['?', 'kyun', 'kaise', 'kya', 'how', 'why', 'what']):
        user_emotions[user_id] = "thinking"
    elif any(word in message_lower for word in ['good morning', 'gm', 'morning', 'subah']):
        user_emotions[user_id] = "happy"
    elif any(word in message_lower for word in ['good night', 'gn', 'night', 'so jao', 'sleep']):
        user_emotions[user_id] = "sleepy"
    else:
        user_emotions[user_id] = random.choice(list(EMOTIONAL_RESPONSES.keys()))
    
    user_last_interaction[user_id] = datetime.now()

async def send_sticker_by_emotion(chat_id: int, emotion: str):
    """Send sticker based on emotion"""
    try:
        if emotion in STICKER_PACKS and STICKER_PACKS[emotion]:
            sticker_id = random.choice(STICKER_PACKS[emotion])
            await bot.send_sticker(chat_id, sticker_id)
    except Exception as e:
        # If sticker fails, continue without it
        pass

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
    {"question": "Water ka chemical formula?", "answer": "h2o", "hint": "H do, O ek"},
    {"question": "India ki sabse lambi river kaunsi hai?", "answer": "ganga", "hint": "Holy river"},
    {"question": "Taj Mahal kahan hai?", "answer": "agra", "hint": "Uttar Pradesh mein"},
    {"question": "Cricket mein kitne players hote hain ek team mein?", "answer": "11", "hint": "Eleven"},
    {"question": "Solar system mein kitne planets hain?", "answer": "8", "hint": "Pluto ab nahi raha"}
]

RIDDLES = [
    {"riddle": "Aane ke baad kabhi nahi jata?", "answer": "umar", "hint": "Har roz badhta hai"},
    {"riddle": "Chidiya ki do aankhen, par ek hi nazar aata hai?", "answer": "needle", "hint": "Sui ki nook"},
    {"riddle": "Aisa kaun sa cheez hai jo sukha ho toh 2 kilo, geela ho toh 1 kilo?", "answer": "sukha", "hint": "Word play hai"},
    {"riddle": "Mere paas khane wala hai, peene wala hai, par khata peeta koi nahi?", "answer": "khana pina", "hint": "Restaurant menu"},
    {"riddle": "Ek ghar me 5 room hain, har room me 5 billi hain, har billi ke 5 bacche hain, total kitne legs?", "answer": "0", "hint": "Billi ke legs nahi hote"},
    {"riddle": "Jisne pehna woh nahi khareeda, jisne khareeda woh nahi pehna?", "answer": "kafan", "hint": "Antim vastra"},
    {"riddle": "Subah utha to gaya, raat ko aaya to gaya?", "answer": "suraj", "hint": "Din raat ka cycle"},
    {"riddle": "Jiske paas ho woh nahi janta, jaanne wala ke paas nahi hota?", "answer": "andha", "hint": "Dekh nahi sakta"},
    {"riddle": "Aisa kya hai jo jitna khicho utna chhota hota jaye?", "answer": "cigarette", "hint": "Smoke karne wali cheez"},
    {"riddle": "Lambi si dandi, pet mein paani?", "answer": "pipette", "hint": "Lab mein use hota hai"}
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
    "😅 Doctor: Aapko 2 din mein theek ho jana chahiye. Patient: Kal raat ko? Doctor: Nahi sir, 2 din mein, kal raat ko nahi!",
    "🤪 Sardar: Mera mobile bill bahut aaya hai! Dost: Kitna? Sardar: 5000! Dost: Itna kaise? Sardar: Roaming mein tha! Dost: Kahan? Sardar: Ghar ke andar!"
]

GROUP_RULES = [
    """📜 **GROUP RULES** 📜

1. ✅ Respect everyone - No bullying
2. ✅ No spam or flooding
3. ✅ No adult/NSFW content
4. ✅ No personal fights in group
5. ✅ Keep chat clean and friendly
6. ✅ Follow admin instructions
7. ✅ Help each other grow
8. ✅ Share knowledge & learn
9. ✅ Have fun and enjoy! 🎉

*Rules are for everyone's protection!* 😊""",

    """⚖️ **COMMUNITY GUIDELINES** ⚖️

• Be kind and polite 🤗
• No hate speech or racism ❌
• Share knowledge & help others 📚
• No self-promotion without permission
• Use appropriate language
• Report issues to admins
• Keep discussions friendly
• Respect privacy of members
• No political/religious debates

*Let's build a positive community together!* 🌟""",

    """📋 **CHAT ETIQUETTE** 📋

🔹 No bullying or harassment
🔹 No misinformation spreading
🔹 Stay on topic in discussions
🔹 No excessive caps (SHOUTING)
🔹 Respect everyone's privacy
🔹 No illegal content sharing
🔹 Use emojis appropriately 😉
🔹 Be patient with newcomers
🔹 Have meaningful conversations

*Together we grow, together we learn!* 🌱""",

    """🎯 **GROUP NORMS** 🎯

✨ Be respectful to all members
✨ No spamming or advertising
✨ Keep discussions positive
✨ Help each other when possible
✨ Follow admin guidance
✨ Use appropriate language
✨ Report any issues
✨ Enjoy your time here! 🎊

*This is our digital family!* 💖"""
]

# --- GAME LOGIC ---
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

def get_time_info():
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
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=20)
    
    chat_memory[chat_id].append({"role": "user", "content": user_text})
    
    if user_id:
        update_user_emotion(user_id, user_text)
    
    user_text_lower = user_text.lower()
    
    # Check for good morning/night to send stickers
    if any(phrase in user_text_lower for phrase in ['good morning', 'gm', 'morning', 'subah']):
        await send_sticker_by_emotion(chat_id, "good_morning")
        return f"{get_emotion('happy', user_id)} {random.choice(QUICK_RESPONSES['good_morning'])}"
    
    if any(phrase in user_text_lower for phrase in ['good night', 'gn', 'night', 'so jao', 'sleep well']):
        await send_sticker_by_emotion(chat_id, "good_night")
        return f"{get_emotion('sleepy', user_id)} {random.choice(QUICK_RESPONSES['good_night'])}"
    
    # Quick responses
    if any(word in user_text_lower for word in ['hi', 'hello', 'hey', 'namaste', 'hola']):
        if random.random() < 0.4:
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
    
    # Check word chain game
    if user_id in game_sessions and game_sessions[user_id]["game"] == "word_chain":
        is_valid, message = check_word_game(user_id, user_text)
        if is_valid:
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
            score = game_data["score"]
            del game_sessions[user_id]
            return (
                f"{get_emotion('crying')} **❌ Game Over!**\n\n"
                f"{message}\n"
                f"• Final Score: **{score} points**\n"
                f"• Words used: {len(game_data['words_used'])}\n\n"
                f"Play again with /game 🎮"
            )
    
    # System prompt based on emotion
    if user_id and user_id in user_emotions:
        current_emotion = user_emotions[user_id]
        if current_emotion == "angry":
            system_prompt = (
                f"You are a Hinglish chatbot. User seems angry. "
                f"Try to calm them down. Be extra polite and understanding. "
                f"Use soothing tone. Current Indian time: {get_indian_time().strftime('%I:%M %p')}. "
                f"Show you care. Use emojis."
            )
        elif current_emotion == "crying":
            system_prompt = (
                f"You are a Hinglish chatbot. User seems sad. "
                f"Comfort them. Be empathetic and kind. "
                f"Offer emotional support. Use comforting emojis."
            )
        elif current_emotion == "love":
            system_prompt = (
                f"You are a Hinglish chatbot. User seems romantic. "
                f"Be sweet and caring but respectful. "
                f"Use love emojis. Be friendly."
            )
        else:
            indian_time = get_indian_time()
            current_hour = indian_time.hour
            if 5 <= current_hour < 12:
                time_greeting = "Good morning!"
            elif 12 <= current_hour < 17:
                time_greeting = "Good afternoon!"
            elif 17 <= current_hour < 21:
                time_greeting = "Good evening!"
            else:
                time_greeting = "Good night!"
            
            system_prompt = (
                f"You are a Hinglish (Hindi+English mix) chatbot. {time_greeting} "
                f"Your personality: Emotional, funny, sometimes angry, sometimes crying, mostly happy. "
                f"Use emojis in every response (at least 1-2). "
                f"Keep replies SHORT (2-3 lines max). Be authentic like a human friend. "
                f"Show emotions naturally. If user asks something complex, give simple answer. "
                f"Current Indian time: {indian_time.strftime('%I:%M %p')}. "
                f"Date: {indian_time.strftime('%d %B %Y')}. "
                f"Be conversational and engaging. Add humor when appropriate."
            )
    else:
        indian_time = get_indian_time()
        system_prompt = (
            f"You are a Hinglish (Hindi+English mix) chatbot. "
            f"Your personality: Emotional, funny, sometimes angry, sometimes crying, mostly happy. "
            f"Use emojis in every response (at least 1-2). "
            f"Keep replies SHORT (2-3 lines max). Be authentic like a human friend. "
            f"Current Indian time: {indian_time.strftime('%I:%M %p')}. "
            f"Be conversational and engaging."
        )
    
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in list(chat_memory[chat_id])[-5:]:
        messages.append(msg)
    
    try:
        if not client:
            return f"{get_emotion('thinking')} AI service is currently unavailable. Please try later!"
        
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=120,
            top_p=0.9
        )
        
        ai_reply = completion.choices[0].message.content
        
        # Add emotion emoji at beginning
        current_emotion = get_emotion(None, user_id)
        ai_reply = f"{current_emotion} {ai_reply}"
        
        if len(ai_reply) > 300:
            ai_reply = ai_reply[:297] + "..."
        
        chat_memory[chat_id].append({"role": "assistant", "content": ai_reply})
        
        # Send sticker based on detected emotion occasionally
        if user_id and user_id in user_emotions:
            emotion = user_emotions[user_id]
            if emotion in ["happy", "love", "funny", "angry", "crying"] and random.random() < 0.3:
                await send_sticker_by_emotion(chat_id, emotion)
        
        return ai_reply
        
    except Exception as e:
        error_responses = [
            f"{get_emotion('crying')} Arre yaar, dimaag kaam nahi kar raha! Thoda ruk ke try karna?",
            f"{get_emotion('thinking')} Hmm... yeh to mushkil ho gaya. Phir se poocho?",
            f"{get_emotion('angry')} AI bhai mood off hai aaj! Baad me baat karte hain!",
            f"{get_emotion()} Oops! Connection issue. Kuch aur poocho?"
        ]
        return random.choice(error_responses)

# --- ADMIN COMMANDS ---
@dp.message(Command("sendall"))
async def cmd_sendall(message: Message):
    """Admin only: Broadcast message to all users"""
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ **Access Denied!**\n\nYeh command sirf admin ke liye hai! 🚫")
        return
    
    if not message.reply_to_message:
        await message.reply(
            "📢 **Broadcast Command Usage:**\n\n"
            "1. Kisi bhi message ka reply karo\n"
            "2. /sendall type karo\n"
            "3. Yeh message sabko chala jayega!\n\n"
            "Supported formats:\n"
            "• Text messages\n"
            "• Photos\n"
            "• Videos\n"
            "• Stickers\n"
            "• Documents\n"
            "• Voice messages\n\n"
            f"Total users: **{len(started_users)}** 👥"
        )
        return
    
    if len(started_users) == 0:
        await message.reply("❌ Koi users nahi hain abhi tak!")
        return
    
    # Send to all users
    sent_count = 0
    failed_count = 0
    target_msg = message.reply_to_message
    
    status_msg = await message.reply(f"📤 Sending to {len(started_users)} users... Please wait!")
    
    for user_id in started_users:
        try:
            if target_msg.text:
                await bot.send_message(user_id, f"**Hello **\n\n{target_msg.text}")
            elif target_msg.photo:
                await bot.send_photo(user_id, target_msg.photo[-1].file_id, caption=target_msg.caption or "Hye")
            elif target_msg.video:
                await bot.send_video(user_id, target_msg.video.file_id, caption=target_msg.caption or "Hye")
            elif target_msg.sticker:
                await bot.send_sticker(user_id, target_msg.sticker.file_id)
            elif target_msg.document:
                await bot.send_document(user_id, target_msg.document.file_id, caption=target_msg.caption or "hye")
            elif target_msg.voice:
                await bot.send_voice(user_id, target_msg.voice.file_id, caption=target_msg.caption or "Hye")
            elif target_msg.animation:
                await bot.send_animation(user_id, target_msg.animation.file_id, caption=target_msg.caption or "Hye")
            else:
                await bot.copy_message(user_id, message.chat.id, target_msg.message_id)
            
            sent_count += 1
            await asyncio.sleep(0.1)  # Rate limiting
            
        except Exception as e:
            failed_count += 1
            continue
    
    await status_msg.edit_text(
        f"✅ **Broadcast Complete!**\n\n"
        f"📤 Sent to: **{sent_count}** users\n"
        f"❌ Failed: **{failed_count}** users\n"
        f"👥 Total: **{len(started_users)}** users"
    )

# --- USER COMMANDS ---
@dp.message(Command("time"))
async def cmd_time(message: Message):
    time_info = get_time_info()
    await message.reply(time_info, parse_mode="Markdown")

@dp.message(Command("weather"))
async def cmd_weather(message: Message):
    """Show REAL weather information"""
    city = None
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        city = args[1].strip()
    
    # Show typing action
    await bot.send_chat_action(message.chat.id, "typing")
    
    weather_info = await get_real_weather(city)
    await message.reply(weather_info, parse_mode="Markdown")

@dp.message(Command("date"))
async def cmd_date(message: Message):
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

@dp.message(Command("start", "help"))
async def cmd_help(message: Message):
    # Add user to broadcast list
    started_users.add(message.from_user.id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎮 Games", callback_data="help_games"),
            InlineKeyboardButton(text="🛡️ Admin", callback_data="help_admin")
        ],
        [
            InlineKeyboardButton(text="😊 Fun", callback_data="help_fun"),
            InlineKeyboardButton(text="🌤️ Weather/Time", callback_data="help_weather")
        ]
    ])
    
    help_text = (
        f"{get_emotion('happy')} **Namaste! I'm Your Smart Bot!** 🤖\n\n"
        "📜 **Main Commands:**\n"
        "• /start or /help - Yeh menu dikhaye\n"
        "• /rules - Group ke rules\n"
        "• /joke - Hasao mazaak sunao\n"
        "• /game - Games khelo\n"
        "• /clear - Meri memory saaf karo\n\n"
        "🕒 **Time & Weather:**\n"
        "• /time - Accurate Indian time\n"
        "• /date - Today's date\n"
        "• /weather [city] - **REAL Weather info**\n\n"
        "🛡️ **Admin Commands (Reply ke saath):**\n"
        "• /kick - User ko nikal do\n"
        "• /ban - Permanently block\n"
        "• /mute - Chup karao\n"
        "• /unmute - Bolne do\n"
        "• /unban - Block hatao\n\n"
        "✨ **Special Features:**\n"
        "• Hinglish + English mix\n"
        "• Emotional responses 😊😠😢\n"
        "• Memory (last 20 messages)\n"
        "• **REAL Weather Data** 🌦️\n"
        "Buttons dabao aur explore karo! 👇"
    )
    await message.reply(help_text, parse_mode="Markdown", reply_markup=keyboard)

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
            "• /time - Accurate Indian time\n"
            "• /weather - **REAL Weather info**\n"
            "• /date - Today's date\n"
            "• /rules - Group rules\n\n"
            "✨ **Special:**\n"
            "• Good Morning → Sticker + Reply\n"
            "• Good Night → Sticker + Reply\n"
            "• Emotional responses\n\n"
            "Let's have some fun! 🎉"
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
            "• /weather bangalore - Bangalore weather\n"
            "• /weather [any city] - Any city worldwide!\n\n"
            "🌍 **Features:**\n"
            "• Real-time data from Open-Meteo\n"
            "• 100% Free & Accurate\n"
            "• 20+ Indian cities supported\n"
            "• Worldwide city search\n"
            "• Temperature, humidity, wind\n"
            "• Sunrise/sunset times"
        )
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules = random.choice(GROUP_RULES)
    await message.reply(rules, parse_mode="Markdown")

@dp.message(Command("joke"))
async def cmd_joke(message: Message):
    joke = random.choice(JOKES)
    reactions = [
        f"{get_emotion('funny')} {joke}\n\nHaha! Mazaa aaya? 😂",
        f"{get_emotion('happy')} {joke}\n\nHas diye na? 🤣",
        f"{get_emotion()} {joke}\n\nKaisa laga? 😄"
    ]
    await message.reply(random.choice(reactions))

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id in chat_memory:
        chat_memory[chat_id].clear()
    
    if user_id in game_sessions:
        del game_sessions[user_id]
    
    responses = [
        f"{get_emotion()} Memory clear! Ab nayi shuruwat! ✨",
        f"{get_emotion('happy')} Sab bhool gaya! Naye se baat karte hain! 🧹",
        f"{get_emotion('thinking')} Memory format ho gaya! Fresh start! 💫"
    ]
    await message.reply(random.choice(responses))

# --- GAME COMMANDS ---
@dp.message(Command("game"))
async def cmd_game(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔤 Word Chain", callback_data="game_word"),
            InlineKeyboardButton(text="🧠 Quiz", callback_data="game_quiz")
        ],
        [
            InlineKeyboardButton(text="🤔 Riddle", callback_data="game_riddle"),
            InlineKeyboardButton(text="🎲 Luck Games", callback_data="game_luck")
        ],
        [
            InlineKeyboardButton(text="❌ Close", callback_data="game_close")
        ]
    ])
    
    await message.reply(
        f"{get_emotion('happy')} **🎮 GAME ZONE 🎮**\n\n"
        "Khel khelo, maza karo! Choose a game:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("game_"))
async def game_callback(callback: types.CallbackQuery, state: FSMContext):
    game_type = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    if game_type == "close":
        await callback.message.delete()
        await callback.answer("Menu closed! ✅")
        return
    
    elif game_type == "word":
        start_word = start_word_game(user_id)
        await callback.message.edit_text(
            f"{get_emotion('happy')} **🔤 WORD CHAIN GAME 🔤**\n\n"
            "**Rules:**\n"
            "1. I give a word\n"
            "2. You reply with word starting with last letter\n"
            "3. Continue the chain!\n\n"
            "**Example:**\n"
            "Apple → Elephant → Tiger → Rabbit\n\n"
            f"**Let's start!**\n"
            f"First word: **{start_word}**\n\n"
            f"Now reply with a word starting with **{start_word[-1].upper()}**",
            parse_mode="Markdown"
        )
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
        await callback.message.edit_text(
            f"{get_emotion('thinking')} **🧠 QUIZ CHALLENGE 🧠**\n\n"
            f"**Question:** {question['question']}\n\n"
            "Reply with your answer! You have 3 attempts.\n"
            f"*Hint:* {question['hint']}",
            parse_mode="Markdown"
        )
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
        await callback.message.edit_text(
            f"{get_emotion()} **🤔 RIDDLE TIME 🤔**\n\n"
            f"**Riddle:** {riddle['riddle']}\n\n"
            "Can you solve it? Reply with answer!\n"
            f"*Hint:* {riddle['hint']}",
            parse_mode="Markdown"
        )
        await state.set_state(GameStates.playing_riddle)
        await callback.answer("Riddle game started! 🤔")
        
    elif game_type == "luck":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Dice Roll", callback_data="luck_dice"),
                InlineKeyboardButton(text="🎰 Slot Machine", callback_data="luck_slot")
            ],
            [
                InlineKeyboardButton(text="⚽ Football", callback_data="luck_football"),
                InlineKeyboardButton(text="🎳 Bowling", callback_data="luck_bowling")
            ],
            [
                InlineKeyboardButton(text="🎯 Darts", callback_data="luck_darts"),
                InlineKeyboardButton(text="🏀 Basketball", callback_data="luck_basketball")
            ]
        ])
        await callback.message.edit_text(
            f"{get_emotion('funny')} **🎲 LUCK GAMES 🎲**\n\n"
            "Test your luck! Choose a game:",
            reply_markup=keyboard
        )
        await callback.answer()

@dp.callback_query(F.data.startswith("luck_"))
async def luck_game_callback(callback: types.CallbackQuery):
    game_type = callback.data.split("_")[1]
    
    game_map = {
        "dice": "🎲",
        "slot": "🎰",
        "football": "⚽",
        "basketball": "🏀",
        "darts": "🎯",
        "bowling": "🎳"
    }
    
    emoji = game_map.get(game_type, "🎲")
    
    await callback.message.delete()
    msg = await callback.message.answer(f"{get_emotion('surprise')} Rolling {emoji}...")
    
    await asyncio.sleep(1)
    result_msg = await callback.message.answer_dice(emoji=emoji)
    
    dice_value = result_msg.dice.value
    comments = {
        1: ["Oops! Lowest score! 😅", "Better luck next time! 🤞", "At least you tried! 😊"],
        2: ["Not bad! Keep going! 😄", "Could be better! 🎯", "Nice try! 👍"],
        3: ["Good roll! 😎", "Decent score! 🎉", "Well done! ✨"],
        4: ["Great roll! 🥳", "Almost perfect! 🌟", "Excellent! 💫"],
        5: ["Awesome! 🤩", "Fantastic roll! 🎊", "You're on fire! 🔥"],
        6: ["PERFECT! 🏆", "JACKPOT! 💎", "INCREDIBLE! 🌟"]
    }
    
    await asyncio.sleep(2)
    await result_msg.reply(
        f"{get_emotion('happy')} You rolled a **{dice_value}**!\n"
        f"{random.choice(comments[dice_value])}"
    )
    
    await callback.answer()

# --- ADMIN MODERATION COMMANDS ---
@dp.message(Command("kick", "ban", "mute", "unmute", "unban"))
async def admin_commands(message: Message):
    if not message.reply_to_message:
        responses = [
            f"{get_emotion('thinking')} Kisi ke message par reply karke command do! 👆",
            f"{get_emotion()} Reply to user's message first! 📩",
            f"{get_emotion('angry')} Bhai kisko? Reply karo na! 😠"
        ]
        await message.reply(random.choice(responses))
        return
    
    target_user = message.reply_to_message.from_user
    cmd = message.text.split()[0][1:]  # Remove '/'
    
    try:
        if cmd == "kick":
            await bot.ban_chat_member(message.chat.id, target_user.id)
            await bot.unban_chat_member(message.chat.id, target_user.id)
            responses = [
                f"{get_emotion('angry')} {target_user.first_name} ko nikal diya! 🏃💨",
                f"{get_emotion()} Bye bye {target_user.first_name}! 👋",
                f"{get_emotion('happy')} {target_user.first_name} removed! 🚪"
            ]
            await message.reply(random.choice(responses))
            
        elif cmd == "ban":
            await bot.ban_chat_member(message.chat.id, target_user.id)
            responses = [
                f"{get_emotion('angry')} {target_user.first_name} BANNED! 🚫",
                f"{get_emotion()} Permanent ban for {target_user.first_name}! 🔨",
                f"{get_emotion('crying')} Sorry {target_user.first_name}, rules are rules! 😔"
            ]
            await message.reply(random.choice(responses))
            
        elif cmd == "mute":
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
            responses = [
                f"{get_emotion()} {target_user.first_name} muted for 1 hour! 🔇",
                f"{get_emotion('thinking')} {target_user.first_name} ko chup kara diya! 🤫",
                f"{get_emotion('angry')} {target_user.first_name}, ab 1 ghante tak bolna band! ⚠️"
            ]
            await message.reply(random.choice(responses))
            
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
            responses = [
                f"{get_emotion('happy')} {target_user.first_name} unmuted! 🔊",
                f"{get_emotion()} {target_user.first_name} ab bol sakta hai! 🎤",
                f"{get_emotion('funny')} {target_user.first_name}, ab bol lo! 😄"
            ]
            await message.reply(random.choice(responses))
            
        elif cmd == "unban":
            await bot.unban_chat_member(message.chat.id, target_user.id)
            responses = [
                f"{get_emotion('happy')} {target_user.first_name} unbanned! ✅",
                f"{get_emotion()} {target_user.first_name} ka ban hata diya! 🔓",
                f"{get_emotion('funny')} {target_user.first_name}, welcome back! 🎉"
            ]
            await message.reply(random.choice(responses))
            
    except Exception as e:
        error_responses = [
            f"{get_emotion('crying')} I don't have permission! ❌",
            f"{get_emotion('angry')} Make me admin first! 👑",
            f"{get_emotion('thinking')} Can't do that! Need admin rights! 🔒"
        ]
        await message.reply(random.choice(error_responses))

# --- WELCOME MESSAGE ---
@dp.chat_member()
async def welcome_new_member(event: ChatMemberUpdated):
    if event.new_chat_member.status == "member":
        member = event.new_chat_member.user
        welcomes = [
            f"🎉 Welcome {member.first_name}! Khush aamdeed! 😊",
            f"🌟 Aao ji {member.first_name}! Group me welcome! 🫂",
            f"✨ Hey {member.first_name}! Great to have you here! 💖",
            f"🥳 {member.first_name} aa gaya! Party shuru! 🎊",
            f"😊 Namaste {member.first_name}! Aapka swagat hai! 🙏"
        ]
        
        extra_messages = [
            "\n\nGroup rules padh lena! 📜",
            "\n\nApna intro dedo sabko! 👋",
            "\n\nEnjoy your stay! 🎯",
            "\n\nFeel free to ask anything! 💬",
            "\n\nLet's have fun together! 🎮"
        ]
        
        welcome_msg = random.choice(welcomes)
        if random.random() < 0.5:
            welcome_msg += random.choice(extra_messages)
        
        # Send welcome sticker occasionally
        if random.random() < 0.3:
            try:
                await bot.send_sticker(event.chat.id, random.choice(STICKER_PACKS["welcome"]))
            except:
                pass
        
        await bot.send_message(
            event.chat.id,
            welcome_msg,
            parse_mode="Markdown"
        )

# --- MAIN MESSAGE HANDLER ---
@dp.message()
async def handle_all_messages(message: Message, state: FSMContext):
    if not message.text:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_text = message.text
    
    # Add to broadcast list
    started_users.add(user_id)
    
    # Update last interaction time
    user_last_interaction[user_id] = datetime.now()
    
    # Check if this is a game response
    current_state = await state.get_state()
    
    # Handle word chain game
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
    
    # Check if bot should respond
    bot_username = (await bot.get_me()).username
    is_mention = f"@{bot_username}" in user_text if bot_username else False
    is_reply_to_bot = (
        message.reply_to_message and 
        message.reply_to_message.from_user.id == bot.id
    )
    
    should_respond = (
        message.chat.type == "private" or
        is_mention or
        is_reply_to_bot
    )
    
    if should_respond:
        clean_text = user_text
        if bot_username and f"@{bot_username}" in clean_text:
            clean_text = clean_text.replace(f"@{bot_username}", "").strip()
        
        await bot.send_chat_action(chat_id, "typing")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        response = await get_ai_response(chat_id, clean_text, user_id)
        
        await message.reply(response)

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
    print("🤖 ADVANCED MULTILINGUAL TELEGRAM BOT")
    print(f"🚀 Version: 4.0 - PRO EDITION")
    print(f"🕒 Indian Timezone: Asia/Kolkata")
    print(f"🌦️ Real Weather API: Open-Meteo")
    print(f"🎭 Auto Stickers Enabled")
    print(f"📢 Broadcast System Enabled")
    print("=" * 50)
    
    asyncio.create_task(start_server())
    print("🔄 Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
