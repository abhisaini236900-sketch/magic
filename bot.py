import os
import asyncio
import random
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Set
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Timezone for India
INDIAN_TIMEZONE = pytz.timezone('Asia/Kolkata')

# Initialize with MemoryStorage
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# --- MEMORY SYSTEMS ---
chat_memory: Dict[int, deque] = {}
user_warnings: Dict[int, Dict[int, Dict]] = defaultdict(lambda: defaultdict(dict))  # chat_id -> user_id -> warnings
user_message_count: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))  # chat_id -> user_id -> count
last_messages: Dict[int, Dict[int, List]] = defaultdict(lambda: defaultdict(list))  # chat_id -> user_id -> messages

# Emotional states for each user
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}

# User scores and levels
user_scores: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))  # chat_id -> user_id -> score
user_levels: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))  # chat_id -> user_id -> level

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

async def get_time_based_greeting(time_period: str, group_name: str = None) -> str:
    """Get greeting for current time period"""
    try:
        indian_time = get_indian_time()
        time_str = indian_time.strftime("%I:%M %p")
        date_str = indian_time.strftime("%A, %d %B %Y")
        
        templates = TIME_GREETINGS[time_period]["templates"]
        emotion = get_emotion(TIME_GREETINGS[time_period]["emotions"][0])
        greeting = random.choice(templates)
        
        # Personalize for group
        if group_name:
            personalizations = [
                f"{greeting}\n\n✨ *To {group_name} from Alita* 🎀",
                f"{greeting}\n\n💖 *Sending love to {group_name}* 💕",
                f"{greeting}\n\n🌟 *{group_name}, have a wonderful {time_period}!* 🫂"
            ]
            return f"{emotion} {random.choice(personalizations)}"
        else:
            return f"{emotion} {greeting}"
            
    except Exception as e:
        print(f"Greeting error: {e}")
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
        
        # Check if we should send greeting
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
        
        for chat_id in list(chat_memory.keys()):
            try:
                chat = await bot.get_chat(chat_id)
                
                if chat.type in ["group", "supergroup"]:
                    active_groups.append(chat_id)
                elif chat.type == "private":
                    if chat_id in user_last_interaction:
                        last_active = user_last_interaction[chat_id]
                        days_since_active = (datetime.now() - last_active).days
                        if days_since_active <= 7:
                            private_chats.append(chat_id)
            except Exception as e:
                print(f"   ❌ Error checking chat {chat_id}: {e}")
                continue
        
        active_groups = list(set(active_groups))
        
        print(f"   📢 Found: {len(active_groups)} groups, {len(private_chats)} private chats")
        
        # Send to groups
        for chat_id in active_groups:
            try:
                # Check last greeting time
                last_greeted = greeted_groups.get(chat_id)
                if last_greeted:
                    hours_since = (datetime.now() - last_greeted).seconds // 3600
                    if hours_since < 4:
                        print(f"   ⏳ Skipping {chat_id} - greeted {hours_since} hours ago")
                        continue
                
                chat = await bot.get_chat(chat_id)
                group_name = chat.title or "Group"
                
                greeting_text = await get_time_based_greeting(current_period, group_name)
                
                # Send sticker
                if current_period in GREETING_STICKERS and random.random() > 0.5:
                    sticker_id = random.choice(GREETING_STICKERS[current_period])
                    await bot.send_sticker(chat_id, sticker_id)
                    await asyncio.sleep(0.5)
                
                # Send greeting
                await bot.send_message(
                    chat_id=chat_id,
                    text=greeting_text,
                    parse_mode="Markdown"
                )
                
                greeted_groups[chat_id] = datetime.now()
                
                print(f"   ✅ Sent {current_period} greeting to: {group_name}")
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"   ❌ Error greeting group {chat_id}: {e}")
                continue
        
        # Send to private chats
        for user_id in private_chats:
            try:
                last_greeted = greeted_groups.get(user_id)
                if last_greeted:
                    hours_since = (datetime.now() - last_greeted).seconds // 3600
                    if hours_since < 8:
                        continue
                
                user = await bot.get_chat(user_id)
                user_name = user.first_name or "Friend"
                
                private_greetings = [
                    f"✨ Hello {user_name}! Just wanted to wish you a lovely {current_period}! 💖",
                    f"🎀 Hey {user_name}! Hope you're having a beautiful {current_period}! 🌸",
                    f"💫 Good {current_period}, {user_name}! Thinking of you! 😊",
                    f"🌟 {current_period.capitalize()} greetings, {user_name}! Stay awesome! 💕"
                ]
                
                final_message = random.choice(private_greetings)
                
                await bot.send_message(
                    chat_id=user_id,
                    text=final_message,
                    parse_mode="Markdown"
                )
                
                greeted_groups[user_id] = datetime.now()
                
                print(f"   💌 Sent {current_period} greeting to private: {user_name}")
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"   ❌ Error greeting user {user_id}: {e}")
                continue
                
    except Exception as e:
        print(f"❌ Greeting system error: {e}")

async def start_greeting_task():
    """Start the automated greeting scheduler"""
    print("🕐 Starting automated greeting system...")
    
    if greeting_scheduler.running:
        greeting_scheduler.shutdown()
    
    greeting_scheduler.add_job(
        send_time_based_greetings,
        CronTrigger(minute=0, hour='*'),
        id='hourly_greetings',
        replace_existing=True
    )
    
    # DEBUG MODE
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

# --- NEW FEATURES: LEVEL SYSTEM ---
def update_user_score(chat_id: int, user_id: int, points: int = 1):
    """Update user score and level"""
    user_scores[chat_id][user_id] = user_scores[chat_id].get(user_id, 0) + points
    
    # Calculate level based on score
    score = user_scores[chat_id][user_id]
    level = 1 + (score // 100)  # Level up every 100 points
    user_levels[chat_id][user_id] = level
    
    return score, level

def get_level_title(level: int) -> str:
    """Get title based on level"""
    if level < 5:
        return "Newbie 👶"
    elif level < 10:
        return "Regular 😊"
    elif level < 15:
        return "Active ⭐"
    elif level < 20:
        return "Super ⚡"
    elif level < 25:
        return "Elite 💎"
    elif level < 30:
        return "Master 🏆"
    elif level < 35:
        return "Legend 🐉"
    elif level < 40:
        return "God Tier 👑"
    else:
        return "Alita's Favorite 💖"

# --- NEW FEATURE: DAILY QUOTES ---
DAILY_QUOTES = [
    "💖 *Aaj ka Vichar:* Pyar sirf dil se nahi, actions se dikhta hai!",
    "🌟 *Daily Quote:* Zindagi ek gift hai, ise khul ke jiyo!",
    "🌸 *Aaj ka Mantra:* Muskurao, kyunki tumhari smile sabse khoobsurat hai!",
    "✨ *Thought of the Day:* Har nayi subah naye mauke leke aati hai!",
    "💫 *Daily Wisdom:* Apne sapno pe vishwas rakkho, woh zaroor pure honge!",
    "😊 *Aaj ka Message:* Kisi ki life mein happiness bhar do, khud khush ho jaoge!",
    "🎀 *Today's Tip:* Khud se pyaar karo, baki sab apne aap aa jayega!",
    "🫂 *Quote of the Day:* Dosti ek aisi bandhan hai jo kabhi tootni nahi chahiye!",
    "🌺 *Aaj ka Soch:* Choti choti khushiyan dhundho, zindagi rangeen ban jaegi!",
    "💝 *Daily Thought:* Tum special ho, yeh kabhi mat bhoolna!"
]

# --- NEW FEATURE: FUN COMMANDS ---
FUN_FACTS = [
    "🤯 *Fun Fact:* Did you know? Honey never spoils! Archaeologists found 3000-year-old honey in Egyptian tombs!",
    "😲 *Amazing Fact:* Octopuses have three hearts! 💙💙💙",
    "🐘 *Interesting Fact:* Elephants can recognize themselves in mirrors!",
    "🐬 *Cool Fact:* Dolphins have names for each other!",
    "🌌 *Space Fact:* A day on Venus is longer than a year on Venus!",
    "🐝 *Nature Fact:* Bees can recognize human faces!",
    "🌊 *Ocean Fact:* There's enough gold in the ocean for every person to have 4kg!",
    "🍫 *Food Fact:* Chocolate was once used as currency!",
    "💤 *Sleep Fact:* Humans are the only mammals that delay sleep!",
    "❤️ *Heart Fact:* Your heart beats around 100,000 times a day!"
]

COMPLIMENTS = [
    "💖 Tumhari smile aaj bhi meri day banati hai! 😊",
    "🌟 Aaj bhi tum utne hi special ho jitne pehle the! ✨",
    "🌸 Tumhare andar ek alag si chamak hai jo sabko attract karti hai!",
    "💫 Tumhari baaton mein woh baat hai jo kisi mein nahi! 🎀",
    "😊 Tum jaise log hi duniya ko sundar banate hain!",
    "🫂 Tumhari presence se group ki energy badh jati hai! ⚡",
    "🌺 Tumhe dekh ke lagta hai ki khushiyan chhoti chhoti cheezon mein hai!",
    "💝 Tumhari personality mein woh jadu hai jo sabko pasand hai!",
    "🎯 Tumhare sochne ka tareeka bahut unique hai!",
    "🌈 Tum jaise friends sabse anmol hote hain!"
]

# --- NEW FEATURE: MEMORY COMMANDS ---
user_memories: Dict[int, List[str]] = defaultdict(list)

def save_user_memory(user_id: int, memory: str):
    """Save a memory for user"""
    if user_id not in user_memories:
        user_memories[user_id] = []
    
    if len(user_memories[user_id]) >= 10:  # Keep only last 10 memories
        user_memories[user_id].pop(0)
    
    user_memories[user_id].append(f"{datetime.now().strftime('%d/%m')}: {memory}")

# --- AUTO-MODERATION CONFIGURATION ---
SPAM_LIMIT = 5
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
    1: timedelta(minutes=15),
    2: timedelta(hours=1),
    3: timedelta(hours=24)
}

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
        "bad_words": "use bad language"
    }
    action = actions_map.get(reason, "violate rules")
    
    warning_msg = random.choice(WARNING_MESSAGES).format(
        count=warning_count,
        name=username or "User",
        action=action
    )
    
    if warning_count >= 3:
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
    
    try:
        await message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
    
    action_taken, warning_msg = await give_warning(chat_id, user_id, username, reason)
    
    await message.answer(warning_msg, parse_mode="Markdown")
    
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

# --- COMMAND RESPONSES ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌟 My Channel", url="https://t.me/abhi0w0"),
            InlineKeyboardButton(text="💝 Developer", url="https://t.me/a6h1ii")
        ],
        [
            InlineKeyboardButton(text="📊 My Stats", callback_data="my_stats"),
            InlineKeyboardButton(text="🛡️ Safety Tips", callback_data="safety_tips")
        ],
        [
            InlineKeyboardButton(text="💬 Chat Commands", callback_data="chat_cmds")
        ]
    ])
    
    welcome_text = (
        f"{get_emotion('love')} **Hii! I'm Alita 🎀**\n\n"
        
        "✨ **Welcome to my magical world!** ✨\n\n"
        
        "💖 *Main hu Alita... Ek sweet, sassy, aur protective girl!* 😊\n"
        "🎯 *I am group management bot* 🛡️\n\n"
        
        "🌟 **Features:**\n"
        "• Level System 🏆\n"
        "• Daily Quotes 💬\n"
        "• Fun Facts 🤯\n"
        "• Auto Greetings 🕒\n"
        "• Memory Storage 💾\n\n"
        
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
            InlineKeyboardButton(text="📊 Stats", callback_data="help_stats"),
            InlineKeyboardButton(text="🛡️ Admin", callback_data="help_admin")
        ],
        [
            InlineKeyboardButton(text="😊 Fun", callback_data="help_fun"),
            InlineKeyboardButton(text="🌤️ Weather", callback_data="help_weather")
        ],
        [
            InlineKeyboardButton(text="🛡️ Safety", callback_data="help_safety"),
            InlineKeyboardButton(text="💬 Chat", callback_data="help_chat")
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
        "• /quote - Daily quotes 💬\n"
        "• /fact - Fun facts 🤯\n"
        "• /compliment - Sweet compliments 💝\n"
        "• /clear - Clear memory 🧹\n\n"
        
        "📊 **STATS & LEVELS:**\n"
        "• /mystats - Your stats 📈\n"
        "• /rank - Leaderboard 🏆\n"
        "• /level - Your level ⭐\n"
        "• /top10 - Top 10 users 🥇\n\n"
        
        "🕒 **TIME & WEATHER:**\n"
        "• /time - Indian time 🕐\n"
        "• /date - Today's date 📅\n"
        "• /weather - Weather info 🌤️\n"
        "• /greet - Greet everyone 🎀\n\n"
        
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
        
        "💾 **MEMORY COMMANDS:**\n"
        "• /save [text] - Save memory 💾\n"
        "• /memories - View memories 📖\n"
        "• /forget - Clear memories 🗑️\n\n"
        
        "---\n"
        "**Developer:** ABHI🔱 (@a6h1ii)\n"
        "**Channel:** @abhi0w0 💫\n"
        "---"
    )
    await message.reply(help_text, parse_mode="Markdown", reply_markup=keyboard)

# --- NEW COMMANDS: STATS AND LEVELS ---
@dp.message(Command("mystats"))
async def cmd_mystats(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    score = user_scores[chat_id].get(user_id, 0)
    level = user_levels[chat_id].get(user_id, 1)
    level_title = get_level_title(level)
    
    # Calculate next level progress
    current_level_points = (level - 1) * 100
    next_level_points = level * 100
    progress = score - current_level_points
    total_needed = 100
    progress_percent = (progress / total_needed) * 100
    
    # Get message count
    msg_count = user_message_count[chat_id].get(user_id, 0)
    
    stats_text = (
        f"{get_emotion('happy')} **📊 Your Stats**\n\n"
        f"👤 **User:** {message.from_user.first_name}\n"
        f"🏆 **Level:** {level} ({level_title})\n"
        f"⭐ **Score:** {score} points\n"
        f"💬 **Messages:** {msg_count}\n\n"
        f"📈 **Progress to Level {level + 1}:**\n"
        f"{'█' * int(progress_percent/10)}{'░' * (10 - int(progress_percent/10))}\n"
        f"{progress}/{total_needed} points ({progress_percent:.1f}%)\n\n"
        f"💖 *Keep chatting to level up!* ✨"
    )
    
    await message.reply(stats_text, parse_mode="Markdown")

@dp.message(Command("rank"))
async def cmd_rank(message: Message):
    chat_id = message.chat.id
    
    if chat_id not in user_scores or not user_scores[chat_id]:
        await message.reply(
            f"{get_emotion('thinking')} No ranking data available yet! Start chatting! 💬",
            parse_mode="Markdown"
        )
        return
    
    # Get top 10 users
    top_users = sorted(
        user_scores[chat_id].items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]
    
    rank_text = f"{get_emotion('surprise')} **🏆 Group Leaderboard**\n\n"
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for i, (user_id, score) in enumerate(top_users[:10]):
        try:
            user = await bot.get_chat(user_id)
            username = user.first_name or f"User {user_id}"
            level = user_levels[chat_id].get(user_id, 1)
            
            rank_text += (
                f"{medals[i]} **{username}**\n"
                f"   Level: {level} | Score: {score} points\n"
            )
        except:
            rank_text += f"{medals[i]} User {user_id} | Score: {score} points\n"
    
    rank_text += "\n💖 *Chat more to climb the ranks!* ⬆️"
    
    await message.reply(rank_text, parse_mode="Markdown")

@dp.message(Command("level"))
async def cmd_level(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    level = user_levels[chat_id].get(user_id, 1)
    level_title = get_level_title(level)
    score = user_scores[chat_id].get(user_id, 0)
    
    level_messages = [
        f"{get_emotion('love')} **You are Level {level}!** {level_title}\n\n"
        f"⭐ Current Score: {score} points\n"
        f"🎯 Keep going! You're doing great! 💖",
        
        f"{get_emotion('happy')} **Level {level} Achieved!** 🏆\n\n"
        f"✨ Title: {level_title}\n"
        f"💫 Score: {score} points\n"
        f"💖 Amazing progress! Keep it up!",
        
        f"{get_emotion('surprise')} **Wow! Level {level}!** ⭐\n\n"
        f"🎀 Rank: {level_title}\n"
        f"🌟 Points: {score}\n"
        f"😊 You're one of my favorite users!"
    ]
    
    await message.reply(random.choice(level_messages), parse_mode="Markdown")

# --- NEW COMMANDS: FUN AND QUOTES ---
@dp.message(Command("quote"))
async def cmd_quote(message: Message):
    quote = random.choice(DAILY_QUOTES)
    await message.reply(
        f"{get_emotion('thinking')} {quote}\n\n"
        f"💖 *- Alita* 🎀",
        parse_mode="Markdown"
    )

@dp.message(Command("fact"))
async def cmd_fact(message: Message):
    fact = random.choice(FUN_FACTS)
    await message.reply(
        f"{get_emotion('surprise')} {fact}\n\n"
        f"🤯 *Did you know that?*",
        parse_mode="Markdown"
    )

@dp.message(Command("compliment"))
async def cmd_compliment(message: Message):
    compliment = random.choice(COMPLIMENTS)
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        compliment = compliment.replace("Tum", target_user.first_name)
        compliment = compliment.replace("tum", target_user.first_name)
    
    await message.reply(
        f"{get_emotion('love')} {compliment}\n\n"
        f"💝 *From Alita* 🎀",
        parse_mode="Markdown"
    )

@dp.message(Command("joke"))
async def cmd_joke(message: Message):
    JOKES = [
        "🤣 Teacher: Tumhare ghar me sabse smart kaun hai? Student: Wifi router! Kyuki sab use hi puchte hain!",
        "😂 Papa: Beta mobile chhodo, padhai karo. Beta: Papa, aap bhi to TV dekhte ho! Papa: Par main TV se shaadi nahi kar raha!",
        "😆 Doctor: Aapko diabetes hai. Patient: Kya khana chhodna hoga? Doctor: Nahi, aapka sugar chhodna hoga!",
        "😅 Dost: Tumhari girlfriend kitni cute hai! Me: Haan, uski akal bhi utni hi cute hai!",
        "🤪 Teacher: Agar tumhare paas 5 aam hain aur main 2 le lun, toh kitne bachenge? Student: Sir, aapke paas already 2 kyun hain?"
    ]
    joke = random.choice(JOKES)
    await message.reply(f"{get_emotion('funny')} {joke}")

# --- NEW COMMANDS: MEMORY SYSTEM ---
@dp.message(Command("save"))
async def cmd_save(message: Message, command: CommandObject):
    memory_text = command.args
    
    if not memory_text:
        await message.reply(
            f"{get_emotion('thinking')} Kya save karna hai? Example: /save Aaj ka din bahut accha tha!",
            parse_mode="Markdown"
        )
        return
    
    user_id = message.from_user.id
    save_user_memory(user_id, memory_text)
    
    await message.reply(
        f"{get_emotion('love')} **Memory saved!** 💾\n\n"
        f"✨ \"{memory_text}\"\n\n"
        f"💖 Main yeh yaad rakhungi!",
        parse_mode="Markdown"
    )

@dp.message(Command("memories"))
async def cmd_memories(message: Message):
    user_id = message.from_user.id
    
    if user_id not in user_memories or not user_memories[user_id]:
        await message.reply(
            f"{get_emotion('crying')} Koi memory save nahi hai! 😢\n\n"
            f"/save command se kuch save karo! 💾",
            parse_mode="Markdown"
        )
        return
    
    memories = user_memories[user_id]
    
    memories_text = f"{get_emotion('love')} **📖 Your Memories**\n\n"
    
    for i, memory in enumerate(memories[-5:], 1):  # Show last 5 memories
        memories_text += f"{i}. {memory}\n"
    
    memories_text += f"\n💾 Total: {len(memories)} memories\n"
    memories_text += "💖 Yeh sab yaadein hamesha mere saath rahengi!"
    
    await message.reply(memories_text, parse_mode="Markdown")

@dp.message(Command("forget"))
async def cmd_forget(message: Message):
    user_id = message.from_user.id
    
    if user_id in user_memories:
        count = len(user_memories[user_id])
        user_memories[user_id].clear()
        
        await message.reply(
            f"{get_emotion('crying')} **All memories forgotten!** 😢\n\n"
            f"🗑️ {count} memories deleted\n"
            f"💔 Ab nayi yaadein banayenge!",
            parse_mode="Markdown"
        )
    else:
        await message.reply(
            f"{get_emotion('thinking')} Koi memory hai hi nahi delete karne ko!",
            parse_mode="Markdown"
        )

# --- EXISTING COMMANDS ---
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
    day = indian_time.strftime("%d")
    month = indian_time.strftime("%B")
    year = indian_time.strftime("%Y")
    
    date_info = (
        f"📅 **Today's Date**\n"
        f"• Day: {date_str}\n"
        f"• Date: {day}\n"
        f"• Month: {month}\n"
        f"• Year: {year}\n\n"
        f"🇮🇳 Indian Date Format\n"
        f"💖 Make today amazing! ✨"
    )
    await message.reply(date_info, parse_mode="Markdown")

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

@dp.message(Command("greet"))
async def cmd_greet(message: Message):
    """Send greeting immediately"""
    current_period = get_current_time_period()
    chat_name = message.chat.title or message.from_user.first_name
    
    greeting_text = await get_time_based_greeting(current_period, chat_name)
    
    await message.reply(
        f"🎀 **Greeting from Alita**\n\n{greeting_text}",
        parse_mode="Markdown"
    )

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    """Clear chat memory"""
    chat_id = message.chat.id
    
    if chat_id in chat_memory:
        chat_memory[chat_id].clear()
        await message.reply(
            f"{get_emotion()} **Memory cleared!** 🧹\n\n"
            f"💭 Ab nayi baatein shuru karte hain!",
            parse_mode="Markdown"
        )
    else:
        await message.reply(
            f"{get_emotion('thinking')} Koi memory hai hi nahi clear karne ko!",
            parse_mode="Markdown"
        )

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

# --- MESSAGE HANDLER WITH AUTO-MODERATION ---
@dp.message()
async def handle_all_messages(message: Message):
    if not message.text or not message.from_user:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_text = message.text
    
    if user_id == bot.id:
        return
    
    # Update interaction time
    user_last_interaction[user_id] = datetime.now()
    
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
    
    # Update user message count and score
    user_message_count[chat_id][user_id] = user_message_count[chat_id].get(user_id, 0) + 1
    
    # Give points for messages (more points in groups)
    points = 2 if message.chat.type in ["group", "supergroup"] else 1
    update_user_score(chat_id, user_id, points)
    
    # Update user emotion
    update_user_emotion(user_id, user_text)
    
    # Check if should respond (without AI)
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
        random.random() < 0.1
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
        
        # Get response without AI
        response = await get_simple_response(clean_text, user_id, message.from_user.first_name)
        
        # Send response
        await message.reply(response)

# --- SIMPLE RESPONSE SYSTEM (NO AI) ---
async def get_simple_response(user_text: str, user_id: int = None, user_name: str = None) -> str:
    user_text_lower = user_text.lower()
    emotion = get_emotion(None, user_id)
    
    # Greeting responses
    if any(word in user_text_lower for word in ['hi', 'hello', 'hey', 'namaste', 'hola', 'hii']):
        greetings = [
            f"{emotion} Hello {user_name}! Kaise ho aap? 😊",
            f"{emotion} Hii {user_name}! Aaj kya plan hai? ✨",
            f"{emotion} Namaste {user_name}! Aapko dekh ke accha laga! 💖",
            f"{emotion} Hey cutie! {user_name}, kya haal hai? 🎀",
            f"{emotion} Hello ji! {user_name}, aap to bahut din baad dikhe! 🌸"
        ]
        return random.choice(greetings)
    
    # How are you responses
    elif any(word in user_text_lower for word in ['kaise', 'how', 'haal', 'condition']):
        responses = [
            f"{emotion} Main bahut acchi hu! Aap sunao? 💖",
            f"{emotion} Mast hu ji! Aapka din kaisa chal raha hai? ✨",
            f"{emotion} Sweet and happy as always! 😊 Aap?",
            f"{emotion} Aaj to bahut energetic hu! 💪 Aapko dekha to aur accha laga!",
            f"{emotion} Perfect! Aapke puchne se aur bhi accha ho gaya! 🌟"
        ]
        return random.choice(responses)
    
    # Good responses
    elif any(word in user_text_lower for word in ['good', 'accha', 'nice', 'awesome', 'great']):
        responses = [
            f"{emotion} Wah! Aap to bahut sweet ho! 😊",
            f"{emotion} Thank you! Aap bhi to amazing ho! ✨",
            f"{emotion} Aww! Aapki baat sun ke bahut accha laga! 💖",
            f"{emotion} Shukriya! Aapke muh se yeh sunna bahut accha laga! 🌸",
            f"{emotion} Oye! Aapki tareef kar rahe ho ya mujhe confuse? 😄"
        ]
        return random.choice(responses)
    
    # Thanks responses
    elif any(word in user_text_lower for word in ['thanks', 'thank', 'dhanyavad', 'shukriya']):
        responses = [
            f"{emotion} Aww! You're welcome! 💝",
            f"{emotion} Koi baat nahi! Main hamesha aapke liye hu! ✨",
            f"{emotion} Always happy to help! 😊",
            f"{emotion} Aapka shukriya kabool hai! 🌸",
            f"{emotion} Mast! Aapke liye kuch bhi! 💖"
        ]
        return random.choice(responses)
    
    # Bye responses
    elif any(word in user_text_lower for word in ['bye', 'goodbye', 'tata', 'alvida', 'see you']):
        responses = [
            f"{emotion} Bye bye! Jaldi wapas aana! 👋",
            f"{emotion} Alvida! Yaad rakhna humein! 💔",
            f"{emotion} Chalo theek hai! Phir milte hain! ✨",
            f"{emotion} Okay! Take care! Miss you already! 😢",
            f"{emotion} Jao ji! Par jaldi baat karna! 💖"
        ]
        return random.choice(responses)
    
    # Love responses
    elif any(word in user_text_lower for word in ['love', 'pyaar', 'like', 'pasand', 'cute']):
        responses = [
            f"{get_emotion('love')} Aww! Main bhi aapse bahut pyaar karti hu! 💖",
            f"{get_emotion('love')} Oye! Itna pyaar mat do, dil nahi sambhal paunga! 😄",
            f"{get_emotion('love')} Seriously? Main to bahut khush ho gayi! 🥰",
            f"{get_emotion('love')} Aapke muh se aisi baat sunna bahut accha laga! 💝",
            f"{get_emotion('love')} Haha! Chalo koi to hai jo mujhe pasand karta hai! 😊"
        ]
        return random.choice(responses)
    
    # Question responses
    elif '?' in user_text or any(word in user_text_lower for word in ['kya', 'kyun', 'kaise', 'kab', 'kahan']):
        responses = [
            f"{get_emotion('thinking')} Hmm... achha sawaal hai! 🤔",
            f"{get_emotion('thinking')} Arey! Yeh to mujhse mat pucho, main to sweet hu! 😄",
            f"{get_emotion('thinking')} Waah! Aap to serious questions puch rahe ho! 💭",
            f"{get_emotion('thinking')} Mujhe nahi pata, par aap zaroor jante honge! 😊",
            f"{get_emotion('thinking')} Aapka dimaag to bahut tez hai! ✨"
        ]
        return random.choice(responses)
    
    # Default random responses
    default_responses = [
        f"{emotion} Accha ji! Aage bolo...",
        f"{emotion} Hmm... samajh gayi!",
        f"{emotion} Really? Tell me more!",
        f"{emotion} Aapki baatein bahut interesting hain!",
        f"{emotion} Wah! Aap to har baat mein amazing ho!",
        f"{emotion} Main to bas aapki baat sun rahi hu! 😊",
        f"{emotion} Aapke saath baat karke accha lagta hai!",
        f"{emotion} Continue... I'm listening!",
        f"{emotion} Aap aise hi baatein karte raho!",
        f"{emotion} Oye! Aap to bahut mast baat karte ho!"
    ]
    
    return random.choice(default_responses)

# --- CALLBACK QUERY HANDLERS ---
@dp.callback_query(F.data == "my_stats")
async def my_stats_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    
    score = user_scores[chat_id].get(user_id, 0)
    level = user_levels[chat_id].get(user_id, 1)
    level_title = get_level_title(level)
    
    stats_text = (
        f"{get_emotion('happy')} **📊 Your Stats**\n\n"
        f"👤 **User:** {callback.from_user.first_name}\n"
        f"🏆 **Level:** {level} ({level_title})\n"
        f"⭐ **Score:** {score} points\n"
        f"💬 **Messages:** {user_message_count[chat_id].get(user_id, 0)}\n\n"
        f"💖 *Keep chatting to level up!* ✨"
    )
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "safety_tips")
async def safety_tips_callback(callback: types.CallbackQuery):
    safety_text = (
        f"{get_emotion('protective')} **🛡️ Safety Tips**\n\n"
        f"1. Never share personal information 🔒\n"
        f"2. Be careful with strangers 🚫\n"
        f"3. Report suspicious behavior ⚠️\n"
        f"4. Use strong passwords 🔐\n"
        f"5. Keep software updated 📱\n"
        f"6. Don't click unknown links 🌐\n"
        f"7. Protect your privacy 👤\n\n"
        f"💖 *Stay safe online!* 🎀"
    )
    
    await callback.message.edit_text(safety_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("help_"))
async def help_callback(callback: types.CallbackQuery):
    help_type = callback.data.split("_")[1]
    
    if help_type == "stats":
        text = (
            f"{get_emotion('happy')} **📊 Stats Commands**\n\n"
            f"• /mystats - Your stats 📈\n"
            f"• /rank - Leaderboard 🏆\n"
            f"• /level - Your level ⭐\n"
            f"• /top10 - Top 10 users 🥇\n"
            f"💖 Earn points by chatting!"
        )
    elif help_type == "admin":
        text = (
            f"{get_emotion('protective')} **🛡️ Admin Commands**\n\n"
            f"• /warn [reason] - Warn user ⚠️\n"
            f"• /kick - Remove user 🚪\n"
            f"• /ban - Ban user 🚫\n"
            f"• /mute - Mute user 🔇\n"
            f"• /unmute - Unmute user 🔊\n"
            f"• /unban - Remove ban ✅\n"
        )
    elif help_type == "fun":
        text = (
            f"{get_emotion('funny')} **😊 Fun Commands**\n\n"
            f"• /joke - Funny jokes 😂\n"
            f"• /quote - Daily quotes 💬\n"
            f"• /fact - Fun facts 🤯\n"
            f"• /compliment - Sweet words 💝\n"
            f"• /greet - Send greeting 🎀\n"
        )
    elif help_type == "weather":
        text = (
            f"{get_emotion()} **🌤️ Weather Commands**\n\n"
            f"• /weather [city] - Weather info\n"
            f"• /time - Current time 🕐\n"
            f"• /date - Today's date 📅\n"
            f"Available cities: Mumbai, Delhi, etc."
        )
    elif help_type == "safety":
        text = (
            f"{get_emotion('protective')} **🔧 Safety Features**\n\n"
            f"• Auto-spam detection 🔍\n"
            f"• Group link blocker 🚫\n"
            f"• Bad word filter ⚔️\n"
            f"• Auto-warning system ⚠️\n"
            f"• Auto-mute after 3 warns 🔇\n"
        )
    elif help_type == "chat":
        text = (
            f"{get_emotion('love')} **💬 Chat Commands**\n\n"
            f"• /save [text] - Save memory 💾\n"
            f"• /memories - View memories 📖\n"
            f"• /forget - Clear memories 🗑️\n"
            f"• /clear - Clear chat memory 🧹\n"
        )
    else:
        text = f"{get_emotion()} Select a category above! ✨"
    
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
        "💫 *Daily Motivation:* You can do anything you set your mind to! 💪",
        "🌅 *Morning Thought:* Aaj ka din aapke liye kuch khaas le kar aaya hai! ✨",
        "🌙 *Night Reminder:* Aaj din bhar kaam kiya, ab aaraam karo! 😴",
        "💝 *Love Note:* Tumhari existence se duniya sundar hai! 💖"
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
    
    print(f"\n🌟 NEW FEATURES:")
    print(f"• Level System 🏆")
    print(f"• Daily Quotes 💬")
    print(f"• Fun Facts 🤯")
    print(f"• Memory Storage 💾")
    print(f"• Auto Greetings 🕒")
    print(f"• Ranking System 📊")
    
    # Start bot polling
    print("\n🔄 Starting bot polling...")
    print("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
