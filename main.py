import os
import logging
from typing import Dict, List
from datetime import datetime, timedelta
from flask import Flask
from dotenv import load_dotenv
from groq import Groq
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler

# --- RENDER PORT BINDING ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Bot is Alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)
    
# Load environment
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

# Memory storage
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
        
        if len(self.memory[chat_id]) > self.max_messages:
            self.memory[chat_id] = self.memory[chat_id][-self.max_messages:]
    
    def get_messages(self, chat_id: str) -> List[Dict]:
        return self.memory.get(chat_id, [])
    
    def clear_memory(self, chat_id: str):
        if chat_id in self.memory:
            self.memory[chat_id] = []

chat_memory = ChatMemory()

# Games Database
GAMES = {
    "quiz": {
        "name": "🧠 Quiz Challenge",
        "questions": [
            {"q": "Hinglish me kitne letters?", "a": "26"},
            {"q": "Aam ka English?", "a": "Mango"},
            {"q": "2 + 2 * 2 = ?", "a": "6"},
            {"q": "India ka capital?", "a": "New Delhi"}
        ]
    },
    "riddle": {
        "name": "🤔 Riddle Game",
        "riddles": [
            {"q": "Aane ke baad kabhi nahi jata?", "a": "Umar"},
            {"q": "Chidiya ki do aankhen?", "a": "Needle"}
        ]
    },
    "wordgame": {
        "name": "🔤 Word Chain",
        "rules": "Ek word do, mai uska last letter se naya word lunga!"
    }
}

# Jokes Database
JOKES = [
    "🤣 Teacher: Tumhare ghar me sabse smart kaun? Student: Wifi router! Kyuki sab use hi puchte hain!",
    "😂 Papa: Beta mobile chhodo. Beta: Papa, aap bhi to TV dekhte ho! Papa: Par main TV se shaadi nahi kar raha!",
    "😆 Doctor: Aapko diabetes hai. Patient: Kya khana chhodna hoga? Doctor: Nahi, aapka sugar chhodna hoga!",
    "😅 Dost: Tumhari girlfriend kitni cute hai! Me: Haan, uski akal bhi utni hi cute hai!",
    "🤪 Teacher: Agar tumhare paas 5 aam hain aur main 2 le lun, toh kitne bachenge? Student: Sir, aapke paas already 2 kyun hain?",
    "😜 Boyfriend: Tum meri life ki battery ho! Girlfriend: Toh charging khatam kyun ho jati hai?",
    "😁 Boss: Kal se late mat aana. Employee: Aaj hi late kyun bola? Kal bata dete!",
    "😄 Bhai: Behen, tum kyun ro rahi ho? Behen: Mera boyfriend mujhse break-up kar raha hai! Bhai: Uske liye ro rahi ho ya uske jaane ke baad free time ke liye?",
    "🤭 Customer: Yeh shampoo hair fall rokta hai? Shopkeeper: Nahi sir, hair fall hone par refund deta hai!"
]

# Rules Templates
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

# Emotional Emojis
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
    if emotion_type in EMOTIONAL_RESPONSES:
        return random.choice(EMOTIONAL_RESPONSES[emotion_type])
    all_emojis = []
    for emos in EMOTIONAL_RESPONSES.values():
        all_emojis.extend(emos)
    return random.choice(all_emojis)

def generate_prompt_with_memory(chat_id: str, user_message: str):
    memory = chat_memory.get_messages(chat_id)
    
    system_prompt = f"""You are a bilingual Telegram assistant (Hinglish+English).
    Rules:
    1. Keep responses SHORT (2-3 lines max)
    2. Use emojis: {get_random_emotion()}
    3. Mix Hinglish and English
    4. Show emotions (happy, angry, crying)
    5. Be brief and helpful"""
    
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in memory[-10:]:
        messages.append(msg)
    
    messages.append({"role": "user", "content": user_message})
    return messages

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = str(update.effective_chat.id)
        message_text = update.message.text
        is_group = update.effective_chat.type in ['group', 'supergroup']
        
        if is_group:
            is_mentioned = False
            if context.bot.username:
                is_mentioned = f"@{context.bot.username}" in message_text
            is_reply = update.message.reply_to_message is not None
            
            if not (is_reply or is_mentioned):
                return
        
        chat_memory.add_message(chat_id, "user", message_text)
        
        messages = generate_prompt_with_memory(chat_id, message_text)
        
        try:
            response = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=messages,
                temperature=0.8,
                max_tokens=150,
            )
            ai_response = response.choices[0].message.content
            emotion = get_random_emotion()
            ai_response = f"{emotion} {ai_response}"
            
        except Exception as e:
            logger.error(f"Groq error: {e}")
            ai_response = f"😅 Oops! Thoda problem. Try again!"
        
        chat_memory.add_message(chat_id, "assistant", ai_response)
        await update.message.reply_text(ai_response)
        
    except Exception as e:
        logger.error(f"Message error: {e}")

# ========== COMMANDS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = f"""👋 **Namaste! Welcome!** {get_random_emotion('happy')}

*Mai hu aapka multilingual assistant!*
- Hinglish + English dono 💬
- Emotions 😊😠😢
- Games 🎮
- Jokes 🤣

Type /help for commands!
Chalo shuru karte hain! 🚀"""
    await update.message.reply_text(welcome, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = f"""🛠️ **ALL COMMANDS** {get_random_emotion('happy')}

*Group Management:*
/kick [reply] - User ko kick
/ban [reply] - User ko ban
/unban [user_id] - User unban
/mute [reply] - User mute
/unmute [reply] - User unmute
/rules - Group rules

*Fun Commands:*
/game - Games khelo 🎮
/joke - Funny jokes 🤣
/clear - Memory clear

*Utility:*
/help - Yeh message
/start - Bot shuru

*Note:* Admin commands ke liye admin hona chahiye!"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        reply = update.message.reply_to_message
        
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Admins only! {get_random_emotion('angry')}")
            return
        
        if not reply:
            await update.message.reply_text(f"⚠️ Reply to user! {get_random_emotion('thinking')}")
            return
        
        target = reply.from_user
        await chat.ban_member(target.id)
        await chat.unban_member(target.id)
        
        await update.message.reply_text(f"👢 {target.first_name} kicked! {get_random_emotion('angry')}")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error! {get_random_emotion('crying')}")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        reply = update.message.reply_to_message
        
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Admins only!")
            return
        
        if not reply:
            await update.message.reply_text(f"⚠️ Reply to user!")
            return
        
        target = reply.from_user
        await chat.ban_member(target.id)
        
        await update.message.reply_text(f"🔨 {target.first_name} banned! {get_random_emotion('angry')}")
        
    except Exception:
        await update.message.reply_text(f"❌ Failed!")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Admin access needed!")
            return
        
        if not context.args:
            await update.message.reply_text(f"⚠️ Use: /unban [user_id]")
            return
        
        target_id = int(context.args[0])
        await chat.unban_member(target_id)
        
        await update.message.reply_text(f"✅ User {target_id} unbanned! {get_random_emotion('happy')}")
        
    except Exception:
        await update.message.reply_text(f"❌ Error!")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        reply = update.message.reply_to_message
        
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Admin only!")
            return
        
        if not reply:
            await update.message.reply_text(f"⚠️ Reply to user!")
            return
        
        target = reply.from_user
        permissions = ChatPermissions(can_send_messages=False)
        mute_until = datetime.now() + timedelta(hours=1)
        
        await chat.restrict_member(target.id, permissions, until_date=mute_until)
        
        warning = f"""⚠️ **WARNING** ⚠️

{target.first_name}, you are MUTED for 1 hour!

*Reason:* Rule violation
*By:* {user.first_name}"""
        
        await update.message.reply_text(warning, parse_mode='Markdown')
        
    except Exception:
        await update.message.reply_text(f"❌ Mute failed!")

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        reply = update.message.reply_to_message
        
        member = await chat.get_member(user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text(f"❌ Admin only!")
            return
        
        if not reply:
            await update.message.reply_text(f"⚠️ Reply to user!")
            return
        
        target = reply.from_user
        permissions = ChatPermissions(can_send_messages=True)
        await chat.restrict_member(target.id, permissions)
        
        await update.message.reply_text(f"🔊 {target.first_name} unmuted! {get_random_emotion('happy')}")
        
    except Exception:
        await update.message.reply_text(f"❌ Failed!")

async def group_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules = random.choice(RULES_TEMPLATES)
    await update.message.reply_text(f"{get_random_emotion('happy')} {rules}", parse_mode='Markdown')

async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(GAMES["quiz"]["name"], callback_data="game_quiz")],
        [InlineKeyboardButton(GAMES["riddle"]["name"], callback_data="game_riddle")],
        [InlineKeyboardButton(GAMES["wordgame"]["name"], callback_data="game_wordgame")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🎮 **GAME ZONE** {get_random_emotion('happy')}\n\nChoose a game! 👇",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    game_type = query.data.split("_")[1]
    
    if game_type == "quiz":
        question = random.choice(GAMES["quiz"]["questions"])
        context.user_data["quiz_answer"] = question["a"]
        await query.edit_message_text(f"🧠 Question: {question['q']}\n\nReply with answer!")
    
    elif game_type == "riddle":
        riddle = random.choice(GAMES["riddle"]["riddles"])
        context.user_data["riddle_answer"] = riddle["a"]
        await query.edit_message_text(f"🤔 Riddle: {riddle['q']}\n\nCan you solve it?")
    
    elif game_type == "wordgame":
        await query.edit_message_text(f"🔤 Word Chain!\n{GAMES['wordgame']['rules']}\n\nStart with a word!")

async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    chat_memory.clear_memory(chat_id)
    await update.message.reply_text(f"🧹 Memory cleared! {get_random_emotion('happy')}")

async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    joke = random.choice(JOKES)
    await update.message.reply_text(joke)

# ========== MAIN ==========

def main():
    # 1. Start Flask in background
    Thread(target=run_flask).start()

    
    
    # Create application with polling
    app = Application.builder().token(TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("kick", kick_user))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))
    app.add_handler(CommandHandler("rules", group_rules))
    app.add_handler(CommandHandler("game", game_command))
    app.add_handler(CommandHandler("clear", clear_memory))
    app.add_handler(CommandHandler("joke", joke_command))
    
    app.add_handler(CallbackQueryHandler(game_callback, pattern="^game_"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Bot is live on Render!")
    app.run_polling()

if __name__ == '__main__':
    main()
