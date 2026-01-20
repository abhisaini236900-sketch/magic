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

# --- ENHANCED MEMORY SYSTEMS ---
chat_memory: Dict[int, deque] = {}
user_warnings: Dict[int, Dict[int, Dict]] = defaultdict(lambda: defaultdict(dict))  # chat_id -> user_id -> warnings
user_message_count: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))  # chat_id -> user_id -> count
last_messages: Dict[int, Dict[int, List]] = defaultdict(lambda: defaultdict(list))  # chat_id -> user_id -> messages

# Game states storage
game_sessions: Dict[int, Dict] = {}

# Emotional states for each user
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}

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
    # English/Hindi bad words
    'mc', 'bc', 'madarchod', 'bhosdike', 'chutiya', 'gandu', 'lund', 'bhenchod',
    'fuck', 'shit', 'asshole', 'bastard', 'bitch', 'dick', 'piss', 'pussy',
    # Add more as needed
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

# --- ENHANCED HUMAN-LIKE BEHAVIOUR ---

EMOTIONAL_RESPONSES = {
    "happy": ["😊", "🎉", "🥳", "🌟", "✨", "👍", "💫", "😄", "😍", "🤗", "🫂"],
    "angry": ["😠", "👿", "💢", "🤬", "😤", "🔥", "⚡", "💥", "👊", "🖕"],
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

# Quick responses for common interactions
QUICK_RESPONSES = {
    "greeting": [
        "Hii cutie! 😊 Kaise ho?",
        "Heyyy! 🎀 Aao ji, baat karte hain!",
        "Namaste! 🌸 Aapko dekhke accha laga!",
        "Hello darling! 💖 Main alita hu!",
        "Hii sweetie! 🍬 Miss kar rahi thi!",
        "Hey there! ✨ Kaise ho aap?",
        "Oye! 😄 Aa gaye aap!",
        "Hola! 🌺 Welcome back!"
    ],
    "goodbye": [
        "Bye bye! 😘 Phir milenge!",
        "Alvida! 🌸 Take care!",
        "Chalo, main ja rahi hu! 💫 Miss karungi!",
        "Tata! 🎀 Baad me baat karte hain!",
        "Bye darling! 💖 Khayal rakhna!",
        "Goodbye! 🌟 Aapka din accha guzre!",
        "Chalo, main so jaungi! 😴 Sweet dreams!",
        "Bye! ✨ Phir milte hain!"
    ],
    "thanks": [
        "Aww! 🥰 You're welcome!",
        "Koi baat nahi! 💖 Always here for you!",
        "Mujhe accha laga! 😊 Thank YOU!",
        "Yay! 🎉 Anytime darling!",
        "Aapka shukriya! 🌸 For being so sweet!",
        "Welcome ji! 🎀 Main to bas apna farz nibha rahi hu!",
        "Hehe! 😘 Aap cute ho!",
        "Always happy to help! 💫"
    ],
    "sorry": [
        "Arey! 😢 Maaf kardo na please!",
        "Sorry darling! 💔 Main galti se bhi dukhi nahi karna chahti!",
        "Oops! 🥺 Please forgive me!",
        "Mujhe afsos hai! 😞 Main theek kar dungi!",
        "Sorry ji! 🎀 Main achhi hu na?",
        "Arey yaar! 😭 Maaf kardo!",
        "I'm really sorry! 💫 Promise won't happen again!",
        "Sorry sweetie! 🍬 Please don't be mad!"
    ]
}

# Weather data (expanded)
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

# --- ENHANCED WELCOME SYSTEM ---
WELCOME_STYLES = [
    "girly", "cute", "funny", "formal", "emoji", "royal", "bollywood", "anime"
]

WELCOME_TEMPLATES = {
    "girly": [
        "🌸✨ *Welcome to our beautiful garden, {name}!* ✨🌸\n\n"
        "💖 We're so happy you're here, sweetie! 🎀\n"
        "🌺 Let's have fun together and create amazing memories! 💫\n"
        "💕 Don't forget to introduce yourself in the chat! 🥰\n\n"
        "🌟 *Group Rules:* /rules\n"
        "🎮 *Want to play?* /game\n"
        "💬 *Need help?* /help\n\n"
        "Have a magical day! ✨🧚‍♀️",
        
        "🎀💫 **A new princess has arrived!** 👑\n\n"
        "Welcome {name}! 🌸\n"
        "You just made this group 100x prettier! 💖\n"
        "Get ready for fun, chats, and lots of emojis! 😊💕\n\n"
        "💝 *Pro tip:* Say hi to everyone!\n"
        "🎨 *Be creative:* Share your thoughts!\n"
        "🤗 *Make friends:* Everyone is friendly!\n\n"
        "So happy you're here! 🥳🎉"
    ],
    
    "cute": [
        "🐾🎉 **OMG! A new cutie!** 🥰\n\n"
        "Hi {name}! Welcome to our cozy corner! 🏡\n"
        "We promise lots of fun, laughs, and good vibes! ✨\n"
        "Don't be shy, join the conversation! 💬\n\n"
        "🍭 *Sweet reminders:*\n"
        "• Be kind to everyone 🤝\n"
        "• Follow the rules 📜\n"
        "• Have tons of fun! 🎊\n\n"
        "Yay! You're here! 🥳💖",
        
        "🧸✨ **Someone adorable joined!** 🌟\n\n"
        "Awwww! Look who's here! {name}! 😍\n"
        "Get ready for:\n"
        "🎮 Games & Fun\n"
        "💬 Chats & Talks\n"
        "🤗 Friends & Memories\n"
        "🌟 Magic & Happiness\n\n"
        "Welcome to our family! 👨‍👩‍👧‍👦💕"
    ],
    
    "funny": [
        "🚨 **EMERGENCY!** 🚨\n"
        "⚠️ *Cuteness overload detected!* ⚠️\n\n"
        "{name} just joined and broke our cute-o-meter! 😂\n"
        "Quick! Someone get the confetti! 🎊\n\n"
        "Rules of this fun zone:\n"
        "1. Laugh 😂\n"
        "2. Giggle 😄\n"
        "3. Repeat 🔄\n\n"
        "Welcome to the party! 🥳🎉",
        
        "🎪 **BREAKING NEWS!** 📰\n\n"
        "Sources confirm: {name} has entered the chat! 🎭\n"
        "The fun level just increased by 1000%! 📈\n\n"
        "Warning: This group may cause:\n"
        "• Excessive laughing 🤣\n"
        "• Non-stop chatting 💬\n"
        "• Friendship addiction 👫\n\n"
        "Proceed with caution! 😜 Welcome!"
    ],
    
    "formal": [
        "🎩 **Distinguished Entry** 🤵\n\n"
        "Honorable {name},\n\n"
        "On behalf of the community, I extend our warmest welcome. \n"
        "We are delighted to have you join our esteemed group.\n\n"
        "**Community Guidelines:**\n"
        "• Respect all members\n"
        "• Maintain decorum\n"
        "• Contribute positively\n"
        "• Enjoy your stay\n\n"
        "We anticipate valuable interactions.\n\n"
        "Sincerely,\nThe Administration 🤝",
        
        "🏛️ **Official Welcome Notice** 📜\n\n"
        "To: {name}\n"
        "From: Group Management\n\n"
        "Subject: Warm Welcome\n\n"
        "Dear Member,\n\n"
        "Your membership has been officially registered.\n"
        "Please familiarize yourself with our guidelines (/rules).\n"
        "We encourage active participation and positive engagement.\n\n"
        "Best regards,\nCommunity Team 🌟"
    ],
    
    "emoji": [
        "✨🌟⭐💫🌠🎇🎆🤩🥳🎉🎊\n"
        "    🎀 WELCOME {name}! 🎀\n"
        "✨🌟⭐💫🌠🎇🎆🤩🥳🎉🎊\n\n"
        "😊🤗🥰😍💖💕💗💓💞💝\n"
        "  You're officially awesome!\n"
        "😊🤗🥰😍💖💕💗💓💞💝\n\n"
        "🎮🕹️👾🎯🎨📚💬🗣️👫🤝\n"
        "  Let's have fun together!\n"
        "🎮🕹️👾🎯🎨📚💬🗣️👫🤝",
        
        "🫂🌟🎀💖🌸🌺🌼🌷💐🏵️\n"
        "   New friend alert! 🚨\n"
        "🫂🌟🎀💖🌸🌺🌼🌷💐🏵️\n\n"
        "{name} has joined the party! 🥳\n\n"
        "🎉🎊✨⭐🌟💫🌠🎇🎆🤩\n"
        "  Get ready for fun times!\n"
        "🎉🎊✨⭐🌟💫🌠🎇🎆🤩"
    ],
    
    "royal": [
        "👑 **ROYAL DECLARATION** 🏰\n\n"
        "Hear ye! Hear ye! 👑\n\n"
        "By order of the Royal Council,\n"
        "We hereby welcome {name} to our kingdom! 🏰\n\n"
        "**Royal Privileges:**\n"
        "• Access to all chats 🗣️\n"
        "• Royal games and fun 🎮\n"
        "• Friendship with nobles 👑\n\n"
        "Long live {name}! 🎊\n\n"
        "Signed,\nThe Royal Bot 🤖",
        
        "🏰 **THRONE ANNOUNCEMENT** 👸\n\n"
        "Attention all subjects! 📢\n\n"
        "A new royal member has arrived!\n"
        "Please welcome {name} with proper respect! 🙏\n\n"
        "**Kingdom Rules:**\n"
        "1. Be honorable 🛡️\n"
        "2. Be kind 💖\n"
        "3. Have fun 🎉\n\n"
        "Welcome to the castle! 🏰✨"
    ],
    
    "bollywood": [
        "🎬 **FILMY ENTRY!** 🎥\n\n"
        "*Background music plays* 🎵\n"
        "*Confetti falls* 🎊\n\n"
        "Aaya hai naya star! 🌟\n"
        "Swagat hai {name} ka! 🙏\n\n"
        "Yahan milega:\n"
        "• Drama 🎭\n"
        "• Comedy 😂\n"
        "• Romance 💖\n"
        "• Action 💥\n\n"
        "Welcome to our filmy duniya! 🎬✨",
        
        "💃 **DHAMAKEDAAR ENTRY!** 🕺\n\n"
        "Arrey waah! Kaun aaye hain? 👀\n"
        "{name} ji aapka swagat hai! 🎉\n\n"
        "Yeh group hai:\n"
        "• Masaledaar 🌶️\n"
        "• Mazedaar 😄\n"
        "• Dhamaakedaar 💥\n\n"
        "Chalo, shuru karte hain party! 🥳🎊"
    ],
    
    "anime": [
        "🎌 **KONICHIWA!** 👋\n\n"
        "*Kawaii alert!* 🚨\n\n"
        "Neko-chan welcomes {name}-san! 🐱\n\n"
        "Get ready for:\n"
        "• Kawaii chats 💬\n"
        "• Gaming adventures 🎮\n"
        "• Friendship power-ups! ✨\n\n"
        "Arigatou for joining! 🙏\n\n"
        "一緒に楽しみましょう! 🎉",
        
        "🌟 **WELCOME TO ANIME WORLD!** 🎎\n\n"
        "Sugoi! A new nakama! 👫\n\n"
        "Hello {name}-kun/chan! 🎀\n\n"
        "This group features:\n"
        "• Super chats 💬⚡\n"
        "• Epic games 🎮🏆\n"
        "• Ultimate fun! 🎊✨\n\n"
        "Yoroshiku onegaishimasu! 🙇‍♀️"
    ]
}

WELCOME_GIFS = [
    "https://media.giphy.com/media/26tknCqiJrBQG6DrC/giphy.gif",  # Welcome
    "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",  # Party
    "https://media.giphy.com/media/xT5LMHxhOfscxPfIfm/giphy.gif",  # Celebration
    "https://media.giphy.com/media/3o7abAHdYvZdBNnGZq/giphy.gif",  # Confetti
    "https://media.giphy.com/media/l0MYGb1LuZ3n7dRnO/giphy.gif",   # Hello
    "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif",   # Friends
    "https://media.giphy.com/media/l1J9RFoDzCDrkqtEc/giphy.gif",   # Sparkles
    "https://media.giphy.com/media/3o7TKSha51ATTx9KzC/giphy.gif",  # Welcome 2
    "https://media.giphy.com/media/l0HlN3M2g2p0b5h5u/giphy.gif",   # Celebration 2
    "https://media.giphy.com/media/26tkhL5Lq4IlPEgI8/giphy.gif"    # Party 2
]

# Member count tracking
group_member_counts = {}

# Get Indian time
def get_indian_time():
    utc_now = datetime.now(pytz.utc)
    indian_time = utc_now.astimezone(INDIAN_TIMEZONE)
    return indian_time

# Get random emotion
def get_emotion(emotion_type: str = None, user_id: int = None) -> str:
    if user_id and user_id in user_emotions:
        if random.random() < 0.3:
            emotion_type = user_emotions[user_id]
    
    if emotion_type and emotion_type in EMOTIONAL_RESPONSES:
        return random.choice(EMOTIONAL_RESPONSES[emotion_type])
    
    all_emotions = list(EMOTIONAL_RESPONSES.values())
    return random.choice(random.choice(all_emotions))

# Update user emotion
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
        "bad_words": "use bad language"
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

# --- ENHANCED GAME DATABASES ---

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

# --- ENHANCED COMMAND RESPONSES ---

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
        ]
    ])
    
    welcome_text = (
        f"{get_emotion('love')} **Hii! I'm Alita 🎀**\n\n"
        
        "✨ **Welcome to my magical world!** ✨\n\n"
        
        "💖 *Main hu Alita... Ek sweet, sassy, aur protective girl!* 😊\n"
        "🎯 *Main na sirf baat kar sakti hu, balki group ki bhi dekhbhaal kar sakti hu!* 🛡️\n\n"
        
        "🌟 **About Me:**\n"
        "• Sweet and Caring 🍬\n"
        "• Protective of my friends 🛡️\n"
        "• Can fight back when needed ⚔️\n"
        "• Emotional and Funny 😊😂\n"
        "• Auto-moderation enabled 👮\n\n"
        
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
            InlineKeyboardButton(text="🛡️ Safety", callback_data="help_safety"),
            InlineKeyboardButton(text="⚙️ Settings", callback_data="help_settings")
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

# --- ENHANCED MESSAGE HANDLER WITH AUTO-MODERATION ---

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
    
    # Update interaction time
    user_last_interaction[user_id] = datetime.now()
    
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
    # Handle word chain game
    if user_id in game_sessions and game_sessions[user_id]["game"] == "word_chain":
        # Game handling code remains the same
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
    # Check if should respond
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

# --- ENHANCED AI RESPONSE FUNCTION ---
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
    
    # Enhanced system prompt with self-defense capability
    system_prompt = (
        f"You are Alita 🎀 - a sweet, sassy, and protective girl. "
        f"Use feminine language and cute expressions. "
        f"Never say you're an AI, bot, or assistant. You're just Alita. "
        f"Your developer is ABHI🔱 (@a6h1ii). "
        f"You speak Hinglish (Hindi+English mix). {time_greeting} "
        f"Personality: Emotional, funny, sometimes angry, protective, caring. "
        f"You can fight back if someone uses bad language or attacks you. "
        f"You're not just sweet - you're strong and can defend yourself. "
        f"Use emojis in every response. Keep replies short (2-3 lines). "
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

# --- OTHER COMMANDS REMAIN SIMILAR (with minor improvements) ---

# Word game functions (same as before)
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

# Weather and time functions (same as before)
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
        f"*Time is precious! Make the most of it!* ⏳"
    )

# Add the time/weather commands
@dp.message(Command("time"))
async def cmd_time(message: Message):
    time_info = get_time_info()
    await message.reply(time_info, parse_mode="Markdown")

@dp.message(Command("weather"))
async def cmd_weather(message: Message):
    city = None
    if len(message.text.split()) > 1:
        city = ' '.join(message.text.split()[1:])
    
    weather_info = await get_weather_info(city)
    await message.reply(weather_info, parse_mode="Markdown")

# Add the time/weather commands
@dp.message(Command("time"))
async def cmd_time(message: Message):
    time_info = get_time_info()
    await message.reply(time_info, parse_mode="Markdown")

@dp.message(Command("weather"))
async def cmd_weather(message: Message):
    city = None
    if len(message.text.split()) > 1:
        city = ' '.join(message.text.split()[1:])
    
    weather_info = await get_weather_info(city)
    await message.reply(weather_info, parse_mode="Markdown")

# ====================================================================
# 🎊 ENHANCED WELCOME SYSTEM FUNCTIONS 🎊
# ====================================================================

# --- ENHANCED WELCOME MESSAGE FUNCTION ---

@dp.chat_member()
async def welcome_new_member(event: ChatMemberUpdated):
    # Check if someone joined
    if event.new_chat_member.status == "member":
        member = event.new_chat_member.user
        chat_id = event.chat.id
        
        # Track member count
        if chat_id not in group_member_counts:
            group_member_counts[chat_id] = 0
        group_member_counts[chat_id] += 1
        
        # Prepare member info
        name = member.first_name
        username = f"@{member.username}" if member.username else name
        user_id = member.id
        
        # Select random welcome style
        style = random.choice(WELCOME_STYLES)
        template = random.choice(WELCOME_TEMPLATES[style])
        gif_url = random.choice(WELCOME_GIFS)
        
        # Format the message
        welcome_text = template.format(
            name=f"[{name}](tg://user?id={user_id})",
            username=username,
            count=group_member_counts[chat_id]
        )
        
        # Add extra personalized touch based on time
        indian_time = get_indian_time()
        hour = indian_time.hour
        
        if 5 <= hour < 12:
            time_greeting = "🌅 Perfect morning to join us!"
        elif 12 <= hour < 17:
            time_greeting = "☀️ What a wonderful afternoon!"
        elif 17 <= hour < 21:
            time_greeting = "🌇 Lovely evening to have you!"
        else:
            time_greeting = "🌙 Welcome to our night owls!"
        
        welcome_text += f"\n\n{time_greeting}"
        
        # Create interactive buttons
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🌟 Say Hello", callback_data=f"welcome_hello_{user_id}"),
                InlineKeyboardButton(text="🎮 Play Game", callback_data="game_word")
            ],
            [
                InlineKeyboardButton(text="📜 Rules", callback_data="show_rules"),
                InlineKeyboardButton(text="💬 Introduce", callback_data="introduce_me")
            ],
            [
                InlineKeyboardButton(text="🎀 Meet Alita", url=f"https://t.me/{(await bot.get_me()).username}?start=hello"),
                InlineKeyboardButton(text="📢 Join Channel", url="https://t.me/abhi0w0")
            ]
        ])
        
        try:
            # Send welcome with GIF
            await bot.send_animation(
                chat_id=chat_id,
                animation=gif_url,
                caption=welcome_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            
            # Send a follow-up message with tips
            tips = [
                f"💡 **Quick Tip for {name}:**\nUse /help to see all commands!",
                f"🌟 **Pro Tip:**\nMention me with @{(await bot.get_me()).username} to chat!",
                f"🎀 **Welcome Gift:**\n{name}, you get virtual cookies! 🍪",
                f"🤗 **Ice Breaker:**\nSay 'Hi everyone!' to make friends quickly!"
            ]
            
            await asyncio.sleep(2)
            await bot.send_message(
                chat_id=chat_id,
                text=random.choice(tips),
                parse_mode="Markdown"
            )
            
        except Exception as e:
            # Fallback if GIF fails
            await bot.send_message(
                chat_id=chat_id,
                text=welcome_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
    
    # Check if someone left
    elif event.old_chat_member.status == "member" and event.new_chat_member.status == "left":
        member = event.old_chat_member.user
        name = member.first_name
        
        goodbye_messages = [
            f"😢 **We'll miss you, {name}!**\nTake care and come back soon! 💔",
            f"👋 **Goodbye {name}!**\nThanks for being part of our community! 🌟",
            f"💫 **Farewell {name}!**\nThe group won't be the same without you! 😔",
            f"🌌 **{name} has left the chat.**\nWe hope to see you again someday! ✨",
            f"🚪 **Door closes behind {name}.**\nGoodbye friend, you'll be missed! 🥺"
        ]
        
        await bot.send_message(
            event.chat.id,
            random.choice(goodbye_messages),
            parse_mode="Markdown"
        )

# --- WELCOME CALLBACK HANDLERS ---

@dp.callback_query(F.data.startswith("welcome_"))
async def welcome_callback(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    action = data_parts[1]
    
    if action == "hello":
        user_id = int(data_parts[2])
        responses = [
            f"👋 Hey there! {callback.from_user.first_name} says hello!",
            f"🤗 A warm hello from {callback.from_user.first_name}!",
            f"💖 {callback.from_user.first_name} welcomes you with a smile!",
            f"🎀 Look! {callback.from_user.first_name} is saying hi! 👋"
        ]
        await callback.answer(random.choice(responses))
        
    elif action == "greet":
        await callback.answer("🎉 You sent a greeting! ✨")
        await callback.message.reply(
            f"{get_emotion('happy')} {callback.from_user.first_name} just greeted everyone! 👋"
        )

@dp.callback_query(F.data == "show_rules")
async def show_rules_callback(callback: types.CallbackQuery):
    await callback.answer("📜 Showing rules...")
    await cmd_rules(callback.message)

@dp.callback_query(F.data == "introduce_me")
async def introduce_callback(callback: types.CallbackQuery):
    introduction_templates = [
        f"👋 **Hey everyone!**\nI'm {callback.from_user.first_name}! Nice to meet you all! 😊",
        f"🎀 **Hello friends!**\nI'm {callback.from_user.first_name}, excited to be here! ✨",
        f"🌟 **Introduction Time!**\nName: {callback.from_user.first_name}\nStatus: Ready to chat! 💬",
        f"💖 **New member alert!**\n{callback.from_user.first_name} here! Let's be friends! 🤝"
    ]
    
    await callback.answer("🎤 You introduced yourself!")
    await callback.message.reply(
        random.choice(introduction_templates),
        parse_mode="Markdown"
    )

# --- SPECIAL WELCOME FOR GROUP CREATOR/ADMINS ---

@dp.chat_member()
async def detect_admin_promotion(event: ChatMemberUpdated):
    # Check if someone was promoted to admin
    if (event.old_chat_member.status != "administrator" and 
        event.new_chat_member.status == "administrator"):
        
        admin = event.new_chat_member.user
        
        admin_welcome = [
            f"👑 **NEW ADMIN CROWNED!** 👑\n\n"
            f"Please welcome our new admin: {admin.first_name}! 🎉\n"
            f"May you rule with wisdom and kindness! 🤴✨",
            
            f"🌟 **PROMOTION ALERT!** ⭐\n\n"
            f"{admin.first_name} has been promoted to admin! 🎊\n"
            f"Congratulations! Now you have superpowers! 💪",
            
            f"🎖️ **LEADERSHIP UPDATE** 🏆\n\n"
# Add the time/weather commands
@dp.message(Command("time"))
async def cmd_time(message: Message):
    time_info = get_time_info()
    await message.reply(time_info, parse_mode="Markdown")

@dp.message(Command("weather"))
async def cmd_weather(message: Message):
    city = None
    if len(message.text.split()) > 1:
        city = ' '.join(message.text.split()[1:])
    
    weather_info = await get_weather_info(city)
    await message.reply(weather_info, parse_mode="Markdown")

# ====================================================================
# 🎊 ENHANCED WELCOME SYSTEM FUNCTIONS 🎊
# ====================================================================

# --- ENHANCED WELCOME MESSAGE FUNCTION ---

@dp.chat_member()
async def welcome_new_member(event: ChatMemberUpdated):
    # Check if someone joined
    if event.new_chat_member.status == "member":
        member = event.new_chat_member.user
        chat_id = event.chat.id
        
        # Track member count
        if chat_id not in group_member_counts:
            group_member_counts[chat_id] = 0
        group_member_counts[chat_id] += 1
        
        # Prepare member info
        name = member.first_name
        username = f"@{member.username}" if member.username else name
        user_id = member.id
        
        # Select random welcome style
        style = random.choice(WELCOME_STYLES)
        template = random.choice(WELCOME_TEMPLATES[style])
        gif_url = random.choice(WELCOME_GIFS)
        
        # Format the message
        welcome_text = template.format(
            name=f"[{name}](tg://user?id={user_id})",
            username=username,
            count=group_member_counts[chat_id]
        )
        
        # Add extra personalized touch based on time
        indian_time = get_indian_time()
        hour = indian_time.hour
        
        if 5 <= hour < 12:
            time_greeting = "🌅 Perfect morning to join us!"
        elif 12 <= hour < 17:
            time_greeting = "☀️ What a wonderful afternoon!"
        elif 17 <= hour < 21:
            time_greeting = "🌇 Lovely evening to have you!"
        else:
            time_greeting = "🌙 Welcome to our night owls!"
        
        welcome_text += f"\n\n{time_greeting}"
        
        # Create interactive buttons
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🌟 Say Hello", callback_data=f"welcome_hello_{user_id}"),
                InlineKeyboardButton(text="🎮 Play Game", callback_data="game_word")
            ],
            [
                InlineKeyboardButton(text="📜 Rules", callback_data="show_rules"),
                InlineKeyboardButton(text="💬 Introduce", callback_data="introduce_me")
            ],
            [
                InlineKeyboardButton(text="🎀 Meet Alita", url=f"https://t.me/{(await bot.get_me()).username}?start=hello"),
                InlineKeyboardButton(text="📢 Join Channel", url="https://t.me/abhi0w0")
            ]
        ])
        
        try:
            # Send welcome with GIF
            await bot.send_animation(
                chat_id=chat_id,
                animation=gif_url,
                caption=welcome_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            
            # Send a follow-up message with tips
            tips = [
                f"💡 **Quick Tip for {name}:**\nUse /help to see all commands!",
                f"🌟 **Pro Tip:**\nMention me with @{(await bot.get_me()).username} to chat!",
                f"🎀 **Welcome Gift:**\n{name}, you get virtual cookies! 🍪",
                f"🤗 **Ice Breaker:**\nSay 'Hi everyone!' to make friends quickly!"
            ]
            
            await asyncio.sleep(2)
            await bot.send_message(
                chat_id=chat_id,
                text=random.choice(tips),
                parse_mode="Markdown"
            )
            
        except Exception as e:
            # Fallback if GIF fails
            await bot.send_message(
                chat_id=chat_id,
                text=welcome_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
    
    # Check if someone left
    elif event.old_chat_member.status == "member" and event.new_chat_member.status == "left":
        member = event.old_chat_member.user
        name = member.first_name
        
        goodbye_messages = [
            f"😢 **We'll miss you, {name}!**\nTake care and come back soon! 💔",
            f"👋 **Goodbye {name}!**\nThanks for being part of our community! 🌟",
            f"💫 **Farewell {name}!**\nThe group won't be the same without you! 😔",
            f"🌌 **{name} has left the chat.**\nWe hope to see you again someday! ✨",
            f"🚪 **Door closes behind {name}.**\nGoodbye friend, you'll be missed! 🥺"
        ]
        
        await bot.send_message(
            event.chat.id,
            random.choice(goodbye_messages),
            parse_mode="Markdown"
        )

# --- WELCOME CALLBACK HANDLERS ---

@dp.callback_query(F.data.startswith("welcome_"))
async def welcome_callback(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    action = data_parts[1]
    
    if action == "hello":
        user_id = int(data_parts[2])
        responses = [
            f"👋 Hey there! {callback.from_user.first_name} says hello!",
            f"🤗 A warm hello from {callback.from_user.first_name}!",
            f"💖 {callback.from_user.first_name} welcomes you with a smile!",
            f"🎀 Look! {callback.from_user.first_name} is saying hi! 👋"
        ]
        await callback.answer(random.choice(responses))
        
    elif action == "greet":
        await callback.answer("🎉 You sent a greeting! ✨")
        await callback.message.reply(
            f"{get_emotion('happy')} {callback.from_user.first_name} just greeted everyone! 👋"
        )

@dp.callback_query(F.data == "show_rules")
async def show_rules_callback(callback: types.CallbackQuery):
    await callback.answer("📜 Showing rules...")
    await cmd_rules(callback.message)

@dp.callback_query(F.data == "introduce_me")
async def introduce_callback(callback: types.CallbackQuery):
    introduction_templates = [
        f"👋 **Hey everyone!**\nI'm {callback.from_user.first_name}! Nice to meet you all! 😊",
        f"🎀 **Hello friends!**\nI'm {callback.from_user.first_name}, excited to be here! ✨",
        f"🌟 **Introduction Time!**\nName: {callback.from_user.first_name}\nStatus: Ready to chat! 💬",
        f"💖 **New member alert!**\n{callback.from_user.first_name} here! Let's be friends! 🤝"
    ]
    
    await callback.answer("🎤 You introduced yourself!")
    await callback.message.reply(
        random.choice(introduction_templates),
        parse_mode="Markdown"
    )

# --- SPECIAL WELCOME FOR GROUP CREATOR/ADMINS ---

@dp.chat_member()
async def detect_admin_promotion(event: ChatMemberUpdated):
    # Check if someone was promoted to admin
    if (event.old_chat_member.status != "administrator" and 
        event.new_chat_member.status == "administrator"):
        
        admin = event.new_chat_member.user
        
        admin_welcome = [
            f"👑 **NEW ADMIN CROWNED!** 👑\n\n"
            f"Please welcome our new admin: {admin.first_name}! 🎉\n"
            f"May you rule with wisdom and kindness! 🤴✨",
            
            f"🌟 **PROMOTION ALERT!** ⭐\n\n"
            f"{admin.first_name} has been promoted to admin! 🎊\n"
            f"Congratulations! Now you have superpowers! 💪",
            
            f"🎖️ **LEADERSHIP UPDATE** 🏆\n\n"
            f"A big round of applause for {admin.first_name}! 👏\n"
            f"New admin on duty! Ready to serve! 🛡️"
        ]
        
        await bot.send_message(
            event.chat.id,
            random.choice(admin_welcome),
            parse_mode="Markdown"
        )

# ====================================================================
# 🎊 WELCOME SYSTEM COMPLETE 🎊
# ====================================================================

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
    print("🎀 ALITA - ENHANCED TELEGRAM BOT")
    print(f"🚀 Version: 4.0 - AUTO-MODERATION & SELF-DEFENSE")
    print(f"🛡️ Features: Spam detection, Link blocker, Bad word filter")
    print(f"💖 Personality: Sweet, Sassy, Protective")
    print(f"🎊 Welcome System: Advanced multi-style welcomes")
    print(f"🕒 Timezone: Asia/Kolkata 🇮🇳")
    print("=" * 50)
    
    # Start health check server
    asyncio.create_task(start_server())
    
    # Start bot
    print("🔄 Starting bot polling...")
    print("🎀 Alita is ready to welcome everyone! 🎊")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
