import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv
import requests
from groq import Groq
import random

# Telegram Bot Imports
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ChatPermissions
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    filters,
    CallbackQueryHandler
)
from flask import Flask, jsonify

# Create Flask app for health check
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "ok", "service": "telegram-bot"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# Run Flask in separate thread
def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# Update main() to run both
import threading

def main():
    """Start the bot with Flask for health checks"""
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Create Telegram application
    application = Application.builder().token(TOKEN).build()
    
    # ... [rest of your bot setup] ...
    
    # Start bot polling
    logger.info("Bot starting in polling mode...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
)
# Load environment variables
load_dotenv()

# Configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.environ.get("PORT", 10000))

# Initialize Groq client
groq_client = Groq(api_key=GROQ_API_KEY)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Memory storage (for last 20 messages)
class ChatMemory:
    def __init__(self, max_messages=20):
        self.memory: Dict[str, List[Dict]] = {}
        self.max_messages = max_messages
    
    def add_message(self, chat_id: str, role: str, content: str):
        if chat_id not in self.memory:
            self.memory[chat_id] = []
        
        self.memory[chat_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now()
        })
        
        # Keep only last N messages
        if len(self.memory[chat_id]) > self.max_messages:
            self.memory[chat_id] = self.memory[chat_id][-self.max_messages:]
    
    def get_messages(self, chat_id: str) -> List[Dict]:
        return self.memory.get(chat_id, [])
    
    def clear_memory(self, chat_id: str):
        if chat_id in self.memory:
            self.memory[chat_id] = []

chat_memory = ChatMemory()

# Game definitions
GAMES = {
    "quiz": {
        "name": "🧠 Quick Quiz",
        "questions": [
            {"q": "Hinglish me kitne letters hote hain?", "a": "26"},
            {"q": "Aam ka English kya hota hai?", "a": "Mango"},
            {"q": "2 + 2 * 2 = ?", "a": "6"},
            {"q": "India ka capital kya hai?", "a": "New Delhi"},
            {"q": "Python kisne banaya?", "a": "Guido van Rossum"}
        ]
    },
    "riddle": {
        "name": "🤔 Riddle Challenge",
        "riddles": [
            {"q": "Aane ke baad kabhi nahi jata?", "a": "Umar"},
            {"q": "Chidiya ki do aankhen, par ek hi nazar aata hai?", "a": "Needle"},
            {"q": "Aisa kaun sa cheez hai jo sukha ho toh 2 kilo, geela ho toh 1 kilo?", "a": "Sukha"},
            {"q": "Mere paas khane wala hai, peene wala hai, par khata peeta koi nahi?", "a": "Khana-Pina"},
            {"q": "Ek ghar me 5 room hain, har room me 5 billi hain, har billi ke 5 bacche hain, total kitne legs?", "a": "0"}
        ]
    },
    "wordgame": {
        "name": "🔤 Word Chain",
        "rules": "Ek word do, mai uska last letter se naya word lunga!"
    }
}

# Jokes Database
JOKES = [
    "🤣 Teacher: Tumhare ghar me sabse smart kaun hai? Student: Wifi router! Kyuki sab use hi puchte hain!",
    "😂 Papa: Beta mobile chhodo, padhai karo. Beta: Papa, aap bhi to TV dekhte ho! Papa: Par main TV se shaadi nahi kar raha!",
    "😆 Doctor: Aapko diabetes hai. Patient: Kya khana chhodna hoga? Doctor: Nahi, aapka sugar chhodna hoga!",
    "😅 Dost: Tumhari girlfriend kitni cute hai! Me: Haan, uski akal bhi utni hi cute hai!",
    "🤪 Teacher: Agar tumhare paas 5 aam hain aur main 2 le lun, toh kitne bachenge? Student: Sir, aapke paas already 2 kyun hain?",
    "😜 Boyfriend: Tum meri life ki battery ho! Girlfriend: Toh charging khatam kyun ho jati hai?",
    "😁 Boss: Kal se late mat aana. Employee: Aaj hi late kyun bola? Kal bata dete!",
    "😄 Bhai: Behen, tum kyun ro rahi ho? Behen: Mera boyfriend mujhse break-up kar raha hai! Bhai: Uske liye ro rahi ho ya uske jaane ke baad free time ke liye?",
    "🤭 Customer: Yeh shampoo hair fall rokta hai? Shopkeeper: Nahi sir, hair fall hone par refund deta hai!"
]

# Group Rules Templates
RULES_TEMPLATES = [
    """📜 **GROUP RULES** 📜

1. ✅ Respect everyone
2. ✅ No spam allowed
3. ✅ No adult content
4. ✅ No personal fights
5. ✅ Keep chat clean
6. ✅ Follow admin instructions
7. ✅ Help each other
8. ✅ Enjoy & have fun! 🎉

*Rules are made to protect you all!* 😊""",

    """⚖️ **COMMUNITY GUIDELINES** ⚖️

• Be kind and polite 🤗
• No hate speech ❌
• Share knowledge 📚
• No self-promotion without permission
• Use appropriate language
• Report issues to admins
• Keep discussions friendly

*Let's build a positive community!* 🌟""",

    """📋 **CHAT RULES** 📋

🔹 No bullying
🔹 No misinformation
🔹 Stay on topic
🔹 No excessive caps
🔹 Respect privacy
🔹 No illegal content
🔹 Use emojis wisely 😉

*Together we grow!* 🌱"""
]

# Emotional responses with emojis
EMOTIONAL_RESPONSES = {
    "happy": ["😊", "🎉", "🥳", "🌟", "✨", "👍", "💫", "😄", "😍"],
    "angry": ["😠", "👿", "💢", "🤬", "😤", "🔥", "⚡"],
    "crying": ["😢", "😭", "💔", "🥺", "😞", "🌧️"],
    "love": ["❤️", "💖", "💕", "🥰", "😘", "💋"],
    "funny": ["😂", "🤣", "😆", "😜", "🤪", "🎭"],
    "thinking": ["🤔", "💭", "🧠", "🔍", "💡"],
    "surprise": ["😲", "🤯", "🎊", "🎁", "💥"]
}

def get_random_emotion(emotion_type: str = None) -> str:
    """Get random emoji based on emotion"""
    if emotion_type and emotion_type in EMOTIONAL_RESPONSES:
        return random.choice(EMOTIONAL_RESPONSES[emotion_type])
    all_emojis = []
    for emos in EMOTIONAL_RESPONSES.values():
        all_emojis.extend(emos)
    return random.choice(all_emojis)

def generate_prompt_with_memory(chat_id: str, user_message: str) -> str:
    """Create prompt with chat memory"""
    memory = chat_memory.get_messages(chat_id)
    
    system_prompt = f"""You are a bilingual Telegram assistant who speaks both Hinglish (Hindi+English mix) and English. 
    Follow these rules STRICTLY:
    1. Keep responses SHORT and CONCISE - maximum 2-3 lines
    2. Use emojis naturally: {get_random_emotion()}
    3. Mix Hinglish and English based on user's language
    4. Show emotions appropriately (happy, angry, crying, excited)
    5. For group chats, only reply when mentioned or when replying to a message
    6. Be helpful but brief
    
    Current time: {datetime.now().strftime('%H:%M')}
    Emotion: {random.choice(['happy', 'excited', 'friendly'])}
    Style: Casual and friendly"""
    
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add memory if exists
    for msg in memory[-10:]:  # Last 10 messages from memory
        messages.append(msg)
    
    messages.append({"role": "user", "content": user_message})
    
    return messages

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all messages with memory"""
    try:
        chat_id = str(update.effective_chat.id)
        user_id = update.effective_user.id
        message_text = update.message.text
        is_group = update.effective_chat.type in ['group', 'supergroup']
        is_reply = update.message.reply_to_message is not None
        is_mentioned = False
        
        # Check if bot is mentioned in groups
        if is_group:
            if context.bot.username:
                is_mentioned = f"@{context.bot.username}" in message_text
            
            # Only respond in groups if: replied to bot OR bot is mentioned
            if not (is_reply or is_mentioned):
                return
        
        # Add user message to memory
        chat_memory.add_message(chat_id, "user", message_text)
        
        # Generate AI response
        messages = generate_prompt_with_memory(chat_id, message_text)
        
        try:
            response = groq_client.chat.completions.create(
                model="llama3-8b-8192",  # Fast and efficient
                messages=messages,
                temperature=0.8,
                max_tokens=150,
                top_p=0.9
            )
            
            ai_response = response.choices[0].message.content
            
            # Add emotion and shorten if too long
            emotion = get_random_emotion()
            ai_response = f"{emotion} {ai_response}"
            
            if len(ai_response) > 300:
                ai_response = ai_response[:297] + "..."
            
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            emotions = ["😅", "🤔", "😢", "⚡"]
            ai_response = f"{random.choice(emotions)} Oops! Thoda problem aa gaya. Ek minute ruko... Try again! {get_random_emotion('happy')}"
        
        # Add to memory and send
        chat_memory.add_message(chat_id, "assistant", ai_response)
        await update.message.reply_text(ai_response)
        
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")

# ========== COMMAND HANDLERS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_msg = f"""👋 **Namaste! Welcome!** {get_random_emotion('happy')}

*Mai hu aapka multilingual assistant!* 
- Hinglish + English dono mein baat karta hu 💬
- Emotions dikhata hu 😊😠😢
- Games khel sakte ho 🎮
- Aur bahut kuch!

Type /help for all commands!
*Chalo shuru karte hain!* 🚀"""
    
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = f"""🛠️ **ALL COMMANDS** {get_random_emotion('happy')}

*Group Management:*
/kick [reply] - User ko kick kare
/ban [reply] - User ko ban kare
/unban [user_id] - User ko unban kare
/mute [reply] - User ko mute kare (warning ke saath)
/unmute [reply] - User ko unmute kare
/rules - Group rules dikhaye

*Fun Commands:*
/game - Games khelo! 🎮
/joke - Funny jokes suno! 🤣
/clear - Chat memory clear kare

*Utility:*
/help - Yeh message dikhaye
/start - Bot shuru kare

*Note:* Sab commands admins ke liye hain!
{get_random_emotion('thinking')}"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /kick command"""
    try:
        chat = update.effective_chat
        user = update.effective_user
        reply_msg = update.message.reply_to_message
        
        # Check admin permissions
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Sorry! Only admins can use this command! {get_random_emotion('angry')}")
            return
        
        if not reply_msg:
            await update.message.reply_text(f"⚠️ Please reply to a user's message to kick! {get_random_emotion('thinking')}")
            return
        
        target_user = reply_msg.from_user
        if target_user.id == context.bot.id:
            await update.message.reply_text(f"😅 Mujhe kick nahi kar sakte! {get_random_emotion('funny')}")
            return
        
        await chat.ban_member(target_user.id)
        await chat.unban_member(target_user.id)
        
        await update.message.reply_text(
            f"👢 {target_user.first_name} has been kicked! {get_random_emotion('angry')}\n"
            f"*By:* {user.first_name}"
        , parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Kick error: {e}")
        await update.message.reply_text(f"❌ Error! {get_random_emotion('crying')}")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ban command"""
    try:
        chat = update.effective_chat
        user = update.effective_user
        reply_msg = update.message.reply_to_message
        
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Admins only! {get_random_emotion('angry')}")
            return
        
        if not reply_msg:
            await update.message.reply_text(f"⚠️ Reply to user's message! {get_random_emotion('thinking')}")
            return
        
        target_user = reply_msg.from_user
        if target_user.id == context.bot.id:
            await update.message.reply_text(f"😜 Aap mujhse pyaar karte ho kya? {get_random_emotion('funny')}")
            return
        
        await chat.ban_member(target_user.id)
        
        await update.message.reply_text(
            f"🔨 {target_user.first_name} has been BANNED! {get_random_emotion('angry')}\n"
            f"*By:* {user.first_name}"
        , parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ban error: {e}")
        await update.message.reply_text(f"❌ Failed! {get_random_emotion('crying')}")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unban command"""
    try:
        chat = update.effective_chat
        user = update.effective_user
        
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Admin access needed! {get_random_emotion('angry')}")
            return
        
        if not context.args:
            await update.message.reply_text(f"⚠️ Usage: /unban [user_id] {get_random_emotion('thinking')}")
            return
        
        target_id = int(context.args[0])
        await chat.unban_member(target_id)
        
        await update.message.reply_text(
            f"✅ User ID {target_id} has been UNBANNED! {get_random_emotion('happy')}\n"
            f"*By:* {user.first_name}"
        , parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Unban error: {e}")
        await update.message.reply_text(f"❌ Error! Check user ID. {get_random_emotion('crying')}")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mute command"""
    try:
        chat = update.effective_chat
        user = update.effective_user
        reply_msg = update.message.reply_to_message
        
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Admin command only! {get_random_emotion('angry')}")
            return
        
        if not reply_msg:
            await update.message.reply_text(f"⚠️ Reply to user's message! {get_random_emotion('thinking')}")
            return
        
        target_user = reply_msg.from_user
        
        # Set permissions (no messages)
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False
        )
        
        # Mute for 1 hour
        mute_until = datetime.now() + timedelta(hours=1)
        await chat.restrict_member(target_user.id, permissions, until_date=mute_until)
        
        warning_msg = f"""⚠️ **WARNING** ⚠️

{target_user.first_name}, you have been MUTED for 1 hour!

*Reason:* Rule violation
*By:* {user.first_name}

Please follow group rules! {get_random_emotion('angry')}"""
        
        await update.message.reply_text(warning_msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Mute error: {e}")
        await update.message.reply_text(f"❌ Mute failed! {get_random_emotion('crying')}")

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unmute command"""
    try:
        chat = update.effective_chat
        user = update.effective_user
        reply_msg = update.message.reply_to_message
        
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Admin only! {get_random_emotion('angry')}")
            return
        
        if not reply_msg:
            await update.message.reply_text(f"⚠️ Reply to user! {get_random_emotion('thinking')}")
            return
        
        target_user = reply_msg.from_user
        
        # Restore all permissions
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False
        )
        
        await chat.restrict_member(target_user.id, permissions)
        
        await update.message.reply_text(
            f"🔊 {target_user.first_name} has been UNMUTED! {get_random_emotion('happy')}\n"
            f"*By:* {user.first_name}"
        , parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Unmute error: {e}")
        await update.message.reply_text(f"❌ Failed! {get_random_emotion('crying')}")

async def group_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /rules command"""
    rules = random.choice(RULES_TEMPLATES)
    emotion = get_random_emotion('happy')
    await update.message.reply_text(f"{emotion} {rules}", parse_mode='Markdown')

async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /game command"""
    keyboard = [
        [InlineKeyboardButton(GAMES["quiz"]["name"], callback_data="game_quiz")],
        [InlineKeyboardButton(GAMES["riddle"]["name"], callback_data="game_riddle")],
        [InlineKeyboardButton(GAMES["wordgame"]["name"], callback_data="game_wordgame")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🎮 **GAME ZONE** {get_random_emotion('happy')}\n\n"
        "Choose a game to play:\n"
        "1. Quiz Challenge 🧠\n"
        "2. Riddle Solver 🤔\n"
        "3. Word Chain 🔤\n\n"
        "Click a button below! 👇",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle game callbacks"""
    query = update.callback_query
    await query.answer()
    
    game_type = query.data.split("_")[1]
    
    if game_type == "quiz":
        question = random.choice(GAMES["quiz"]["questions"])
        context.user_data["quiz_answer"] = question["a"]
        
        await query.edit_message_text(
            f"🧠 **QUIZ TIME** {get_random_emotion('thinking')}\n\n"
            f"Question: {question['q']}\n\n"
            "Reply with your answer! ⏳"
        )
    
    elif game_type == "riddle":
        riddle = random.choice(GAMES["riddle"]["riddles"])
        context.user_data["riddle_answer"] = riddle["a"]
        
        await query.edit_message_text(
            f"🤔 **RIDDLE CHALLENGE** {get_random_emotion('thinking')}\n\n"
            f"Riddle: {riddle['q']}\n\n"
            "Can you solve it? 💭"
        )
    
    elif game_type == "wordgame":
        await query.edit_message_text(
            f"🔤 **WORD CHAIN** {get_random_emotion('happy')}\n\n"
            f"{GAMES['wordgame']['rules']}\n\n"
            "Start with a word! Example: 'Apple' 🍎"
        )
        context.user_data["last_word"] = "apple"

async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command"""
    chat_id = str(update.effective_chat.id)
    chat_memory.clear_memory(chat_id)
    
    await update.message.reply_text(
        f"🧹 **Memory Cleared!** {get_random_emotion('happy')}\n\n"
        "Maine sab puri baatein bhool di hain!\n"
        "Naye se shuru karte hain! 🚀"
    )

async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /joke command"""
    joke = random.choice(JOKES)
    emotion = get_random_emotion('funny')
    
    await update.message.reply_text(f"{emotion} {joke}")

# ========== MAIN FUNCTION ==========

def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("kick", kick_user))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("mute", mute_user))
    application.add_handler(CommandHandler("unmute", unmute_user))
    application.add_handler(CommandHandler("rules", group_rules))
    application.add_handler(CommandHandler("game", game_command))
    application.add_handler(CommandHandler("clear", clear_memory))
    application.add_handler(CommandHandler("joke", joke_command))
    application.add_handler(CommandHandler("image", generate_image))
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(game_callback, pattern="^game_"))
    
    # Add message handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_message
    ))
    
    # Start webhook for Render
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://your-bot-name.onrender.com/{TOKEN}"
    )

if __name__ == "__main__":
    main()
