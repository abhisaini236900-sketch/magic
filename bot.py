import os
import logging
from flask import Flask
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq
from collections import deque

# Flask app for Render Port Binding
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

# Configurations
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# Memory storage: {chat_id: deque(maxlen=20)}
memory = {}

# System Prompt for Personality
SYSTEM_PROMPT = (
    "You are a smart, emotional, and moody AI. Use Hinglish + English. "
    "Be angry, happy, or crying based on the vibe. Use lots of emojis. "
    "Keep replies very short and concise. Don't yap. "
    "Remember the last 20 messages provided in context."
)

async def get_ai_response(chat_id, user_text):
    if chat_id not in memory:
        memory[chat_id] = deque(maxlen=20)
    
    # Context building
    history = "\n".join(list(memory[chat_id]))
    full_prompt = f"Context:\n{history}\nUser: {user_text}"
    
    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": full_prompt}
        ],
        model="llama-3-8b-8192",
    )
    response = chat_completion.choices[0].message.content
    memory[chat_id].append(f"User: {user_text}")
    memory[chat_id].append(f"Bot: {response}")
    return response

# Commands
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Oye! Main aa gaya. /help dekh le kya kya kar sakta hoon. 😎")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "/help - Ye list dikhane ke liye\n"
        "/kick - User ko bhagane ke liye\n"
        "/ban - Permanently ban\n"
        "/unban - Maafi dene ke liye\n"
        "/mute - Chup karane ke liye\n"
        "/unmute - Bolne dene ke liye\n"
        "/rules - Group ke naye niyam\n"
        "/game - Fun time!\n"
        "/clear - Meri memory saaf karo\n"
        "/joke - Hasne ke liye"
    )
    await update.message.reply_text(help_text)

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.message.reply_to_message.from_user
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await context.bot.unban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"Nikalgaya {user.first_name}! Tata bye bye. 👋😡")
    except: await update.message.reply_text("Reply to a user to kick them!")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.message.reply_to_message.from_user
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"Banned {user.first_name}! Dubara mat dikhna. 🚫🔥")
    except: await update.message.reply_text("Reply to someone to ban!")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.message.reply_to_message.from_user
        await context.bot.restrict_chat_member(update.effective_chat.id, user.id, permissions=ChatPermissions(can_send_messages=False))
        await update.message.reply_text(f"Warning! ⚠️ {user.first_name} ab tu chup rahega. 🤐")
    except: await update.message.reply_text("Reply to mute!")

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules_list = ["1. No bakwas.", "2. Respect the Bot (Me).", "3. Stay active or get kicked."]
    await update.message.reply_text(f"Naye Rules Sun Lo: \n" + "\n".join(rules_list) + " 📜✨")

async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = await get_ai_response(update.effective_chat.id, "Ek mast short Hinglish joke sunao")
    await update.message.reply_text(res)

async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memory[update.effective_chat.id] = deque(maxlen=20)
    await update.message.reply_text("Memory cleared! Sab bhool gaya main. 🧠🧹")

async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Select a game:\n1. /dice - Luck check\n2. /dart - Nishana lagao\n3. /slots - Jackpot try karo")

# ---- MESSAGE HANDLER ----
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Message text nikalna
    user_text = update.message.text
    if not user_text:
        return

    chat_id = update.effective_chat.id
    bot_username = context.bot.username

    # Conditions check karna: 
    # 1. Private chat ho
    # 2. Bot ko reply diya gaya ho
    # 3. Bot ka naam mention kiya gaya ho
    is_private = update.message.chat.type == 'private'
    is_reply_to_bot = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mentioned = f"@{bot_username}" in user_text

    if is_private or is_reply_to_bot or is_mentioned:
        # Groq se response mangwana
        try:
            resp = await get_ai_response(chat_id, user_text)
            await update.message.reply_text(resp)
        except Exception as e:
            print(f"Error: {e}")
            await update.message.reply_text("Yaar mera dimaag thoda garam hai (API Error), baad me baat karte hain! 😡")
    else:
        # Agar aap chahte hain ki bina mention ke bhi har msg pe bole, to niche wali line uncomment karein:
        # resp = await get_ai_response(chat_id, user_text
        await update.message.reply_text(resp)
        return


def main():
    token = os.getenv("BOT_TOKEN")
    app_bot = Application.builder().token(token).build()

    # Handlers
    app_bot.add_handler(CommandHandler("start", start_command))
    app_bot.add_handler(CommandHandler("help", help_command))
    app_bot.add_handler(CommandHandler("kick", kick))
    app_bot.add_handler(CommandHandler("ban", ban))
    app_bot.add_handler(CommandHandler("mute", mute))
    app_bot.add_handler(CommandHandler("rules", rules))
    app_bot.add_handler(CommandHandler("joke", joke))
    app_bot.add_handler(CommandHandler("clear", clear_memory))
    app_bot.add_handler(CommandHandler("game", game))
    app_bot.add_handler(CommandHandler("dice", lambda u, c: u.message.reply_dice(emoji='🎲')))
    app_bot.add_handler(CommandHandler("dart", lambda u, c: u.message.reply_dice(emoji='🎯')))
    app_bot.add_handler(CommandHandler("slots", lambda u, c: u.message.reply_dice(emoji='🎰')))
    
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run Flask and Bot
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))).start()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
