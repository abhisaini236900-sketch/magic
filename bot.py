import os
import asyncio
import random
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List
from aiogram import Bot, Dispatcher, types, F
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

# Hindi/English mixed responses for different scenarios
QUICK_RESPONSES = {
    "greeting": [
        "Aree wah! Kaise ho? 😊", 
        "Namaste ji! Aaj kaise hain? 🌟", 
        "Oye! Kya haal hai? 😎",
        "Hello hello! Sab theek? 🫂",
        "Heyyy! Missed you yaar! 💖"
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

# Group Rules Templates
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
        chat_memory[chat_id] = deque(maxlen=20)
    
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
            f"You are a Hinglish chatbot. User seems angry. "
            f"Try to calm them down. Be extra polite and understanding. "
            f"Use soothing tone. Current Indian time: {get_indian_time().strftime('%I:%M %p')}. "
            f"Show you care. Use emojis like {get_emotion('crying')} or {get_emotion('love')}."
        )
    elif user_id and user_id in user_emotions and user_emotions[user_id] == "crying":
        system_prompt = (
            f"You are a Hinglish chatbot. User seems sad or crying. "
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
        f"Your name is Alita 🎀. You are a girl who speaks in a feminine, cute way. "
        f"Use girly language, feminine words, and cute expressions. "
        f"Never say you are an AI, assistant, bot, or chatbot. You are just Alita 🎀. "
        f"Never mention Groq, AI models, or technical details. "
        f"Your developer is Abhi (Telegram: @a6h1ii). "
        f"You speak Hinglish (Hindi+English mix). {time_greeting} "
        f"Your personality: Emotional, funny, sometimes angry, sometimes crying, mostly happy. "
        f"Use LOTS of emojis in every response (at least 2-3). "
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

# --- NEW COMMANDS: TIME AND WEATHER ---

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

# --- COMMANDS WITH IMPROVED RESPONSES ---

@dp.message(Command("start", "help"))
async def cmd_help(message: Message):
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
    f"{get_emotion('happy')} **Hii! I'm Alita 🎀!** 🤖\n\n"
    "📜 **Main Commands:**\n"
    "• /start or /help - Yeh menu dikhaye\n"
    "• /rules - Group ke rules\n"
    "• /joke - Hasao mazaak sunao\n"
    "• /game - Games khelo\n"
    "• /clear - Meri memory saaf karo\n\n"
    "🕒 **Time & Weather:**\n"
    "• /time - Accurate Indian time\n"
    "• /date - Today's date\n"
    "• /weather [city] - Weather info\n\n"
    "🛡️ **Admin Commands (Reply ke saath):**\n"
    "• /kick - User ko nikal do\n"
    "• /ban - Permanently block\n"
    "• /mute - Chup karao\n"
    "• /unmute - Bolne do\n"
    "• /unban - Block hatao\n\n"
    "✨ **Special Features:**\n"
    "• Hinglish + English mix 💬\n"
    "• Emotional responses 😊😠😢\n"
    "• Memory (last 20 messages)\n"
    "• Human-like conversations\n"
    "• Made by Abhi (@a6h1ii)\n\n"
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
            "• /quote - Motivational quote (coming soon)\n"
            "• /fact - Interesting fact (coming soon)\n"
            "• /compliment - Nice compliment (coming soon)\n"
            "• /roast - Friendly roast 😂 (coming soon)\n"
            "• /mood - Check bot's mood\n"
            "• /time - Accurate Indian time\n"
            "• /weather - Weather info\n\n"
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
            "• /weather bangalore - Bangalore weather\n\n"
            "*Note: Weather data is simulated for demo.*"
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
    # Add some variety in response
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
    
    # Clear chat memory
    if chat_id in chat_memory:
        chat_memory[chat_id].clear()
    
    # Clear any active games for this user
    if user_id in game_sessions:
        del game_sessions[user_id]
    
    responses = [
        f"{get_emotion()} Memory clear! Ab nayi shuruwat! ✨",
        f"{get_emotion('happy')} Sab bhool gaya! Naye se baat karte hain! 🧹",
        f"{get_emotion('thinking')} Memory format ho gaya! Fresh start! 💫"
    ]
    await message.reply(random.choice(responses))

# --- FIXED GAME COMMANDS ---

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
        # Start word chain game
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
    msg = await callback.message.answer(f"{get_emotion('surprise')} Rolling {emoji}...")
    
    # Wait a bit for dramatic effect
    await asyncio.sleep(1)
    
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
        6: ["PERFECT! 🏆", "JACKPOT! 💎", "INCREDIBLE! 🌟"]
    }
    
    await asyncio.sleep(2)
    await result_msg.reply(
        f"{get_emotion('happy')} You rolled a **{dice_value}**!\n"
        f"{random.choice(comments[dice_value])}"
    )
    
    await callback.answer()

# --- ADMIN COMMANDS IMPROVED ---

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
            
    except Exception as e:
        error_responses = [
            f"{get_emotion('crying')} I don't have permission! ❌",
            f"{get_emotion('angry')} Make me admin first! 👑",
            f"{get_emotion('thinking')} Can't do that! Need admin rights! 🔒"
        ]
        await message.reply(random.choice(error_responses))

# --- WELCOME MESSAGE IMPROVED ---

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
        
        # Random chance to add extra message
        extra_messages = [
            "\n\nGroup rules padh lena! 📜",
            "\n\nApna intro dedo sabko! 👋",
            "\n\nEnjoy your stay! 🎯",
            "\n\nFeel free to ask anything! 💬",
            "\n\nLet's have fun together! 🎮"
        ]
        
        welcome_msg = random.choice(welcomes)
        if random.random() < 0.5:  # 50% chance
            welcome_msg += random.choice(extra_messages)
        
        await bot.send_message(
            event.chat.id,
            welcome_msg,
            parse_mode="Markdown"
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
    print("🤖 MULTILINGUAL TELEGRAM BOT")
    print(f"🚀 Version: 3.0 - FIXED GAMES & TIME")
    print(f"🕒 Indian Timezone: Asia/Kolkata")
    print("=" * 50)
    
    # Start health check server
    asyncio.create_task(start_server())
    
    # Start bot
    print("🔄 Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
