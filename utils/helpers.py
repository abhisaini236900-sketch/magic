import random
import re
from datetime import datetime, timedelta
from config import config, saved_stickers
from aiogram import Bot
from aiogram.types import ChatPermissions

# Time functions
def get_indian_time():
    """Get current Indian time"""
    return datetime.now(config.INDIAN_TZ)

def get_time_period():
    """Get current time period"""
    hour = get_indian_time().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    elif 21 <= hour <= 23:
        return "night"
    else:
        return "late_night"

# Permission checks - MOST IMPORTANT
async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Check if user is admin, creator, or bot owner"""
    try:
        # Bot owner always has access
        if user_id == config.ADMIN_ID:
            return True
            
        # Check if private chat
        if chat_id == user_id:
            return True
            
        # Get chat member
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception as e:
        print(f"Admin check error: {e}")
        return False

async def is_creator(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Check if user is group creator"""
    try:
        if user_id == config.ADMIN_ID:
            return True
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status == "creator"
    except:
        return False

async def can_restrict(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Check if user can restrict members"""
    try:
        if user_id == config.ADMIN_ID:
            return True
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status == "creator":
            return True
        if member.status == "administrator":
            return member.can_restrict_members or member.can_promote_members
        return False
    except:
        return False

async def can_delete(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Check if user can delete messages"""
    try:
        if user_id == config.ADMIN_ID:
            return True
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status == "creator":
            return True
        if member.status == "administrator":
            return member.can_delete_messages or member.can_promote_members
        return False
    except:
        return False

# Content filters
BAD_WORDS = [
    "chutiya", "chutiye", "madarchod", "behenchod", "bhosdike", "lodu", "gandu",
    "fuck", "shit", "asshole", "motherfucker", "cunt", "dick",
    "gaand", "lund", "randi", "harami", "bhosdi",
    "bc", "mc", "gand", "lauda", "choot", "maa ki", "behen ki"
]

ADULT_KEYWORDS = [
    "porn", "xxx", "nsfw", "adult", "sex", "nude", "naked", "boobs", "ass",
    "dick", "pussy", "hentai", "porno", "horny", "fuck", "sexy", "hot", 
    "desi", "chudai", "lund", "chod"
]

def contains_bad_words(text: str) -> bool:
    text_lower = text.lower()
    return any(word in text_lower for word in BAD_WORDS)

def contains_adult_content(text: str) -> bool:
    text_lower = text.lower()
    return any(word in text_lower for word in ADULT_KEYWORDS)

def contains_group_link(text: str) -> bool:
    patterns = [
        r'telegram\.me\/[a-zA-Z0-9_]+',
        r'telegram\.dog\/[a-zA-Z0-9_]+',
    ]
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True
    return False

# Emotion system
EMOTIONS = {
    "happy": ["😊", "🎉", "🥳", "🌟", "✨", "👍", "💫", "😄", "😍", "🤗"],
    "angry": ["😠", "👿", "💢", "🤬", "😤", "🔥", "⚡", "💥", "👊"],
    "crying": ["😢", "😭", "💔", "🥺", "😞", "🌧️", "😿", "🥀", "💧"],
    "love": ["❤️", "💖", "💕", "🥰", "😘", "💋", "💓", "💗", "💘", "💝"],
    "funny": ["😂", "🤣", "😆", "😜", "🤪", "🎭", "🤡", "🃏", "🎪"],
    "thinking": ["🤔", "💭", "🧠", "🔍", "💡", "🎯", "🧐", "🔎", "💬"],
    "sassy": ["💅", "👑", "💁", "💃", "🕶️", "💄", "👠", "✨", "🌟"],
    "sleepy": ["😴", "💤", "🌙", "🛌", "🥱", "😪", "🌃", "🌜", "🌚"],
    "flirty": ["😏", "😉", "😘", "💋", "💄", "💅", "👠", "💃", "🫦"]
}

GIRL_RESPONSES = [
    "Aarey waah! 😏", "Haye haye! 😅", "Oh my god! 😲", "Seriously? 🤨",
    "Chalo thik hai! 😊", "Mujhe pata tha! 😌", "Aise mat bolo na! 🥺",
    "Sahi pakde hain! 😎", "Kya baat hai! 🤩", "Mast hai yaar! 😄",
    "Waah bhai waah! 👏", "Kya keh rahe ho? 🤔", "Arey yaar! 😂",
    "Haan na! 😉", "Theek hai ji! 🙏", "Chalo chalo! 🚶‍♀️",
    "Achha ji! 👍", "Hmm interesting! 🤓", "Wow! 😍", "No way! 😱"
]

def get_emotion(emotion_type: str = None) -> str:
    if emotion_type and emotion_type in EMOTIONS:
        return random.choice(EMOTIONS[emotion_type])
    return random.choice(random.choice(list(EMOTIONS.values())))

def get_girl_response() -> str:
    return random.choice(GIRL_RESPONSES)

# Random sticker sender
async def send_random_sticker(bot: Bot, chat_id: int):
    """Send random sticker if available"""
    if saved_stickers and random.random() < 0.3:
        try:
            sticker = random.choice(saved_stickers)
            await bot.send_sticker(chat_id, sticker)
            return True
        except:
            pass
    return False

# Time-based greetings
TIME_GREETINGS = {
    "morning": {
        "templates": [
            "🌅 *Good Morning Sunshine!* ☀️\nKaisi hai aaj ki subah? Utho aur muskurao! 😊",
            "🌸 *Shubh Prabhat!* 🌸\nAaj ka din aapke liye khoobsurat ho! ✨",
            "☕ *Morning Coffee Time!* 🍵\nChai piyo, fresh ho jao! 💫"
        ]
    },
    "afternoon": {
        "templates": [
            "☀️ *Good Afternoon!* 🌤️\nLunch ho gaya? Energy maintain rakho! 🍲",
            "🌞 *Dopahar ki Dhoop mein!* 🌞\nThoda aaraam karo! 😌",
            "🍛 *Afternoon Time!* 💤\nKhaana kha ke neend aa rahi hai? Hehe! 😴"
        ]
    },
    "evening": {
        "templates": [
            "🌇 *Good Evening Beautiful!* 🌆\nShaam ho gayi, thoda relax karo! 🌹",
            "🌆 *Evening Tea Time!* 🍵\nChai aur baatein! 💖",
            "✨ *Shubh Sandhya!* ✨\nDin bhar ki thakaan door karo! 🎶"
        ]
    },
    "night": {
        "templates": [
            "🌙 *Good Night Sweet Dreams!* 🌟\nAankhein band karo! 💤",
            "🌌 *Shubh Ratri!* 🌌\nThaka hua dimaag ko aaraam do! 😴",
            "💤 *Sleep Time!* 💤\nKal phir nayi energy ke saath! 🌅"
        ]
    },
    "late_night": {
        "templates": [
            "🌃 *Late Night Owls!* 🦉\nSone ka time hai! 😄",
            "🌚 *Midnight Chats!* 🌚\nRaat ke 12 baje bhi jag rahe ho? 😲",
            "💫 *Late Night Vibes!* 💫\nSab so rahe hain! 🤫"
        ]
    }
}

def get_time_greeting() -> str:
    period = get_time_period()
    return random.choice(TIME_GREETINGS[period]["templates"])
