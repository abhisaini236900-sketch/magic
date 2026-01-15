import os
import asyncio
import random
from collections import deque
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ChatMemberUpdated
from groq import AsyncGroq  # Async version use kar rahe hain
from aiohttp import web

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", 10000))

# Initialize Clients
client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Memory: {chat_id: deque}
chat_memory = {}

SYSTEM_PROMPT = (
    "You are a Hinglish chatbot. Mood: Emotional, can get angry, happy, or cry. "
    "Use emojis freely. Keep replies VERY SHORT. Stay authentic. "
    "Talk naturally like a human friend."
)

# --- AI LOGIC (Updated Model Name) ---
async def get_ai_response(chat_id, user_text):
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=20)
    
    chat_memory[chat_id].append({"role": "user", "content": user_text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(chat_memory[chat_id])
    
    try:
        completion = await client.chat.completions.create(
            
            model="llama-3.3-70b-versatile", 
            messages=messages,
            max_tokens=150
        )
        ai_reply = completion.choices[0].message.content
        chat_memory[chat_id].append({"role": "assistant", "content": ai_reply})
        return ai_reply
    except Exception as e:
        
        try:
            completion = await client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                max_tokens=150
            )
            return completion.choices[0].message.content
        except:
            return f"Arre yaar, Groq mana kar raha hai! (Error: {str(e)})"
            

# --- COMMANDS ---
@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📜 **Commands List:**\n"
        "/help - Ye list dikhaye\n/kick - User ko nikalne ke liye\n"
        "/ban - Block karne ke liye\n/unban - Unblock karne ke liye\n"
        "/mute - Chup karwane ke liye\n/unmute - Bolne dene ke liye\n"
        "/rules - Group ke asool\n/game - Masti maza\n"
        "/clear - Meri yaadasht saaf karein\n/joke - Hasne ke liye"
    )
    await message.reply(help_text, parse_mode="Markdown")

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules = [⚖️ **COMMUNITY GUIDELINES** ⚖️

• Be kind and polite 🤗
• No hate speech ❌
• Share knowledge 📚
• No self-promotion without permission
• Use appropriate language
• Report issues to admins
• Keep discussions friendly

*Let's build a positive community!* 🌟]
    random.shuffle(rules)
    await message.reply(f"📜 **Group Rules:**\n" + "\n".join(rules))

@dp.message(Command("joke"))
async def cmd_joke(message: Message):
    jokes = [
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
    await message.reply(random.choice(jokes))

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    if message.chat.id in chat_memory:
        chat_memory[message.chat.id].clear()
    await message.reply("Memory saaf! ✨ Ab hum ajnabee hain.")

@dp.message(Command("game"))
async def cmd_game(message: Message):
    await message.reply("🎮 **Khel Shuru Karein?**\n\n1. /dice - Luck test\n2. /slot - Casino\n3. /football - Goal marna hai!")

@dp.message(Command("dice", "slot", "football"))
async def play_games(message: Message):
    emoji_map = {"dice": "🎲", "slot": "🎰", "football": "⚽"}
    cmd = message.text.split()[0][1:]
    await bot.send_dice(message.chat.id, emoji=emoji_map.get(cmd, "🎲"))

# --- ADMIN ACTIONS ---
@dp.message(Command("kick", "ban", "unban", "mute", "unmute"))
async def admin_cmds(message: Message):
    if not message.reply_to_message:
        return await message.reply("Kisi ke message par reply karke command do!")
    
    uid = message.reply_to_message.from_user.id
    cmd = message.text.split()[0][1:]
    try:
        if cmd == "kick":
            await bot.ban_chat_member(message.chat.id, uid)
            await bot.unban_chat_member(message.chat.id, uid)
            await message.reply("Nikal gaya! 🏃💨")
        elif cmd == "ban":
            await bot.ban_chat_member(message.chat.id, uid)
            await message.reply("Banned! 🚫 Khatam tata bye bye.")
        elif cmd == "mute":
            await bot.restrict_chat_member(message.chat.id, uid, permissions={"can_send_messages": False})
            await message.reply("Chup! ⚠️ Bolna band.")
        elif cmd == "unmute":
            await bot.restrict_chat_member(message.chat.id, uid, permissions={"can_send_messages": True})
            await message.reply("Theek hai, ab bol lo. 🎤")
    except:
        await message.reply("Mere paas powers nahi hain ya wo admin hai! ❌")

# --- EVENTS ---
@dp.chat_member()
async def welcome_member(event: ChatMemberUpdated):
    if event.new_chat_member.status == "member":
        welcomes = ["Swagat hai", "Aao ji", "Welcome", "Namaste"]
        await bot.send_message(event.chat.id, f"{random.choice(welcomes)} @{event.new_chat_member.user.first_name}! 🎉")

@dp.message()
async def handle_chat(message: Message):
    if not message.text: return
    is_private = message.chat.type == "private"
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot.id
    is_mention = f"@{ (await bot.get_me()).username }" in message.text

    if is_private or is_reply or is_mention:
        # Bot ko mention ya reply karne par hi AI bolega groups mein
        clean_text = message.text.replace(f"@{ (await bot.get_me()).username }", "").strip()
        response = await get_ai_response(message.chat.id, clean_text)
        await message.reply(response)

# --- DEPLOYMENT HANDLER ---
async def handle_ping(request):
    return web.Response(text="Bot is Alive!")

async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

async def main():
    # Start background dummy server for Render
    asyncio.create_task(start_server())
    # Start Bot Polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
