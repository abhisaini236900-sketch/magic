import os
import logging
from collections import deque
from dotenv import load_dotenv
import requests
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    filters,
)

# ---- Load env vars -------------------------------------------------
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")

# ---- Logging -------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ---- Memory: last 20 msgs per chat ----------------------------------
chat_memory = {}   # chat_id -> deque(maxlen=20)

# ---- Helper: call Groq LLM -----------------------------------------
def groq_chat(prompt: str) -> str:
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    json_data = {
        "model": "mixtral-8x7b-32768",   # any Groq model you like
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
                         headers=headers, json=json_data, timeout=15)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

# ---- /help ---------------------------------------------------------
def help_cmd(update: Update, ctx: CallbackContext):
    help_text = (
        "/help – yeh help msg\n"
        "/kick @user – kick\n"
        "/ban @user – ban\n"
        "/unban @user – unban\n"
        "/mute @user – mute + ⚠️ warning\n"
        "/unmute @user – unmute\n"
        "/rules – group rules\n"
        "/game – 3 fun games\n"
        "/clear – memory clear\n"
        "/joke – Hinglish jokes\n"
        "/image <prompt> – create image"
    )
    update.message.reply_text(help_text)

# ---- Admin commands -------------------------------------------------
def kick_cmd(update: Update, ctx: CallbackContext):
    if not update.effective_chat.get_member(update.effective_user.id).status in ("creator", "administrator"):
        return
    if not ctx.args:
        return update.message.reply_text("Tag karo jise kick karna hai! 🙅")
    user = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not user:
        return update.message.reply_text("Reply karo us user ko ya @mention use karo.")
    ctx.bot.ban_chat_member(update.effective_chat.id, user.id)
    ctx.bot.unban_chat_member(update.effective_chat.id, user.id)
    update.message.reply_text(f"{user.first_name} ko kick kar diya! 👋")

def ban_cmd(update: Update, ctx: CallbackContext):
    if not update.effective_chat.get_member(update.effective_user.id).status in ("creator", "administrator"):
        return
    user = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not user:
        return update.message.reply_text("Reply karo us user ko.")
    ctx.bot.ban_chat_member(update.effective_chat.id, user.id)
    update.message.reply_text(f"{user.first_name} ko ban kar diya! 🚫")

def unban_cmd(update: Update, ctx: CallbackContext):
    if not update.effective_chat.get_member(update.effective_user.id).status in ("creator", "administrator"):
        return
    if not ctx.args:
        return update.message.reply_text("User ID ya @username do.")
    try:
        target = int(ctx.args[0]) if ctx.args[0].isdigit() else ctx.args[0]
        ctx.bot.unban_chat_member(update.effective_chat.id, target)
        update.message.reply_text("Unbanned! 🎉")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def mute_cmd(update: Update, ctx: CallbackContext):
    if not update.effective_chat.get_member(update.effective_user.id).status in ("creator", "administrator"):
        return
    user = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not user:
        return update.message.reply_text("Reply karo jise mute karna hai.")
    perms = ChatPermissions(can_send_messages=False)
    ctx.bot.restrict_chat_member(update.effective_chat.id, user.id, permissions=perms)
    update.message.reply_text(f"{user.first_name} ko mute kar diya! ⚠️")

def unmute_cmd(update: Update, ctx: CallbackContext):
    if not update.effective_chat.get_member(update.effective_user.id).status in ("creator", "administrator"):
        return
    user = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not user:
        return update.message.reply_text("Reply karo jise unmute karna hai.")
    perms = ChatPermissions(can_send_messages=True,
                            can_send_media_messages=True,
                            can_send_polls=True,
                            can_send_other_messages=True,
                            can_add_web_page_previews=True,
                            can_change_info=True,
                            can_invite_users=True,
                            can_pin_messages=True)
    ctx.bot.restrict_chat_member(update.effective_chat.id, user.id, permissions=perms)
    update.message.reply_text(f"{user.first_name} ko unmute kar diya! ✅")

def rules_cmd(update: Update, ctx: CallbackContext):
    rules = (
        "📜 *Group Rules*\n"
        "1️⃣ Spam mat karo.\n"
        "2️⃣ Respect sabko.\n"
        "3️⃣ No political fights.\n"
        "4️⃣ English/Hinglish dono chale.\n"
        "5️⃣ Bot ko abuse mat karo."
    )
    update.message.reply_markdown(rules)

# ---- /joke ---------------------------------------------------------
def joke_cmd(update: Update, ctx: CallbackContext):
    prompt = "Give me a short, funny Hinglish joke."
    try:
        joke = groq_chat(prompt)
        update.message.reply_text(joke)
    except Exception as e:
        update.message.reply_text("Joke fetch error 😅")

# ---- /image --------------------------------------------------------
def image_cmd(update: Update, ctx: CallbackContext):
    if not ctx.args:
        return update.message.reply_text("Prompt likho after /image 🚀")
    prompt = " ".join(ctx.args)
    # Placeholder – you can plug any image API (e.g., Stability AI)
    # Here we just echo the prompt as a dummy image URL.
    fake_url = f"https://dummyimage.com/600x400/000/fff&text={requests.utils.quote(prompt)}"
    update.message.reply_photo(fake_url, caption=f"🖼️ {prompt}")

# ---- /clear --------------------------------------------------------
def clear_cmd(update: Update, ctx: CallbackContext):
    chat_id = update.effective_chat.id
    chat_memory.pop(chat_id, None)
    update.message.reply_text("Memory cleared! 🧹")

# ---- /game ---------------------------------------------------------
GAMES = {
    "1": {"name": "Guess the Number", "desc": "1-10 tak ka number guess karo."},
    "2": {"name": "Rock Paper Scissors", "desc": "Rock, Paper ya Scissors choose karo."},
    "3": {"name": "Word Scramble", "desc": "Scrambled word ko solve karo."},
}

def game_cmd(update: Update, ctx: CallbackContext):
    buttons = [
        [InlineKeyboardButton(f"{g['name']}", callback_data=f"game_{key}")]
        for key, g in GAMES.items()
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    update.message.reply_text("Select a game 👇", reply_markup=reply_markup)

def button_handler(update: Update, ctx: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("game_"):
        gid = data.split("_")[1]
        game = GAMES.get(gid)
        if not game:
            return query.edit_message_text("Invalid game.")
        if gid == "1":
            query.edit_message_text("🤖 Guess a number between 1‑10 and type it.")
            ctx.user_data["game"] = ("guess", 1, 10)
        elif gid == "2":
            query.edit_message_text("✊ Paper ✋ Scissors ✌️ Rock – send your choice.")
            ctx.user_data["game"] = ("rps",)
        elif gid == "3":
            query.edit_message_text("🔤 Scrambled word: **'tca'** → send correct word.")
            ctx.user_data["game"] = ("scramble", "cat")
    elif data.startswith("rps_"):
        # you can expand with more inline flows if needed
        pass

def game_response(update: Update, ctx: CallbackContext):
    if "game" not in ctx.user_data:
        return
    game = ctx.user_data["game"]
    txt = update.message.text.lower()
    # ---- Guess the Number ------------------------------------------------
    if game[0] == "guess":
        try:
            guess = int(txt)
            target = 7  # static for demo; you can randomize and store per user
            if guess == target:
                update.message.reply_text("🎉 Sahi guess! Badhiya!")
            else:
                update.message.reply_text(f"❌ Galat. Correct number tha {target}.")
        except:
            update.message.reply_text("Number hi bhejo.")
        ctx.user_data.pop("game")
    # ---- Rock Paper Scissors ---------------------------------------------
    elif game[0] == "rps":
        bot_choice = "rock"
        if txt not in ("rock", "paper", "scissors"):
            return update.message.reply_text("rock / paper / scissors me se ek likho.")
        if txt == bot_choice:
            res = "Draw! 🤝"
        elif (txt, bot_choice) in [("paper", "rock"), ("scissors", "paper"), ("rock", "scissors")]:
            res = "You win! 🏆"
        else:
            res = "Bot wins! 🤖"
        update.message.reply_text(res)
        ctx.user_data.pop("game")
    # ---- Word Scramble ----------------------------------------------------
    elif game[0] == "scramble":
        answer = game[2]
        if txt == answer:
            update.message.reply_text("✅ Correct! Good job.")
        else:
            update.message.reply_text(f"❌ Nope. Answer was **{answer}**.")
        ctx.user_data.pop("game")

# ---- Main message handler (memory + LLM) ----------------------------
def text_handler(update: Update, ctx: CallbackContext):
    chat_id = update.effective_chat.id
    user = update.effective_user.first_name
    text = update.message.text

    # Store last 20 msgs
    mem = chat_memory.setdefault(chat_id, deque(maxlen=20))
    mem.append(f"{user}: {text}")

    # If bot is mentioned or reply to bot → use Groq
    if (update.message.reply_to_message and
        update.message.reply_to_message.from_user.id == ctx.bot.id) \
       or f"@{ctx.bot.username}" in text.lower():
        prompt = "\n".join(mem) + "\nBot reply in short, emotional tone:"
        try:
            reply = groq_chat(prompt)
            update.message.reply_text(reply)
        except Exception as e:
            update.message.reply_text("LLM error 😔")
    else:
        # normal chat – do nothing or short echo if you want
        pass

# ---- Application setup ----------------------------------------------
def main():
    app = ApplicationBuilder().token(TOKEN).read_timeout(20).write_timeout(20).build()

    # commands
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("kick", kick_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(CommandHandler("joke", joke_cmd))
    app.add_handler(CommandHandler("image", image_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("game", game_cmd))

    # callbacks & game logic
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, game_response))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.Regex("^/"), lambda u, c: None))  # ignore unknown /
    app.add_handler(MessageHandler(filters.ALL, lambda u, c: None))  # fallback

    # Inline buttons
    app.add_handler(MessageHandler(filters.ALL, button_handler))

    # start
    app.run_polling()

if __name__ == "__main__":
    main()
