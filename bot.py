import os
import asyncio
import random
from collections import deque
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ChatMemberUpdated
from groq import Groq

# Configuration
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", 10000))

client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Memory Storage: {chat_id: deque(maxlen=20)}
chat_memory = {}

# --- SYSTEM PROMPT (Bot Personality) ---
SYSTEM_PROMPT = (
    "You are a Hinglish chatbot. Mood: Emotional, can get angry, happy, or cry. "
    "Use emojis freely. Keep replies VERY SHORT. Stay authentic. "
    "Talk naturally like a human friend."
)

def get_ai_response(chat_id, user_text):
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=20)
    
    # Add user msg to memory
    chat_memory[chat_id].append({"role": "user", "content": user_text})
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(chat_memory[chat_id])
    
    completion = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=messages,
        max_tokens=150
    )
    
    ai_reply = completion.choices[0].message.content
    chat_memory[chat_id].append({"role": "assistant", "content": ai_reply})
    return ai_reply

# --- COMMANDS ---

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📜 **My Commands:**\n"
        "/help - Show this list\n/kick - Kick user\n/ban - Ban user\n"
        "/unban - Unban user\n/mute - Mute & Warn\n/unmute - Unmute\n"
        "/rules - Group rules\n/game - Play games\n/clear - Clear my memory\n/joke - Get a joke"
    )
    await message.reply(help_text, parse_mode="Markdown")

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules = [
        "1. No spamming 🚫", "2. Respect everyone 🙏", 
        "3. No links allowed 🔗", "4. Be happy! 😊"
    ]
    random.shuffle(rules)
    await message.reply(f"Group Rules:\n" + "\n".join(rules))

@dp.message(Command("joke"))
async def cmd_joke(message: Message):
    jokes = [
        "Teacher: Kal kyun nahi aaye? Student: Sir gir gaya tha. Teacher: Kahan? Student: Bed pe aur neend aa gayi. 😂",
        "Pappu: Yaar meri biwi ne mujhe ghar se nikaal diya. Friend: Kyun? Pappu: Usne pucha kaisa lag raha hoon, maine bol diya 'bhains' jaisa. 😭"
    ]
    await message.reply(random.choice(jokes))

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    chat_memory[message.chat.id] = deque(maxlen=20)
    await message.reply("Memory cleared! Sab bhool gaya main. ✨")

@dp.message(Command("game"))
async def cmd_game(message: Message):
    await message.reply("🎮 **Select a Game:**\n1. /dice - Luck test\n2. /slot - Casino vibes\n3. /football - Goal marna hai!")

@dp.message(Command("dice", "slot", "football"))
async def play_games(message: Message):
    emoji_map = {"dice": "🎲", "slot": "🎰", "football": "⚽"}
    cmd = message.text.split()[0][1:]
    await bot.send_dice(message.chat.id, emoji=emoji_map.get(cmd, "🎲"))

# --- ADMIN COMMANDS ---

@dp.message(Command("kick", "ban", "unban", "mute", "unmute"))
async def admin_cmds(message: Message):
    if not message.reply_to_message:
        return await message.reply("Reply to someone to use this!")
    
    user_id = message.reply_to_message.from_user.id
    cmd = message.text.split()[0][1:]
    
    try:
        if cmd == "kick":
            await bot.ban_chat_member(message.chat.id, user_id)
            await bot.unban_chat_member(message.chat.id, user_id)
            await message.reply(f"Kicked! Nikal gaya 🏃💨")
        elif cmd == "ban":
            await bot.ban_chat_member(message.chat.id, user_id)
            await message.reply(f"Banned! Dubara mat aana 🚫")
        elif cmd == "mute":
            await bot.restrict_chat_member(message.chat.id, user_id, permissions={"can_send_messages": False})
            await message.reply(f"Chup! ⚠️ Warning mil gayi.")
        elif cmd == "unmute":
            await bot.restrict_chat_member(message.chat.id, user_id, permissions={"can_send_messages": True})
            await message.reply(f"Theek hai, ab bol sakte ho.")
    except Exception as e:
        await message.reply(f"Error: Admin power nahi hai mere paas ya user admin hai!")

# --- WELCOME & CHAT ---

@dp.chat_member()
async def welcome_member(event: ChatMemberUpdated):
    if event.new_chat_member.status == "member":
        welcomes = ["Aao ji", "Welcome", "Swagat hai", "Hello"]
        name = event.new_chat_member.user.first_name
        await bot.send_message(event.chat.id, f"{random.choice(welcomes)} @{name}! 🎉 Kaise ho?")

@dp.message()
async def handle_chat(message: Message):
    # Handle DMs or Mentions or Replies
    is_private = message.chat.type == "private"
    is_mention = message.text and (f"@{bot._me.username}" in message.text)
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot.id

    if is_private or is_mention or is_reply:
        response = get_ai_response(message.chat.id, message.text)
        await message.reply(response)

# --- DEPLOYMENT WEBHOOK (For Render) ---
from aiohttp import web

async def on_startup(bot: Bot):
    await bot.set_webhook(url=f"{os.getenv('RENDER_EXTERNAL_URL')}/webhook")

def main():
    app = web.Application()
    app.router.add_post("/webhook", lambda request: dp.feed_update(bot, request))
    # Dummy server for Render port check
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
