from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode
from datetime import datetime, timedelta
import random
import asyncio

from config import config, saved_stickers, started_users
from database import db
from utils.helpers import (
    is_admin, is_creator, can_restrict, can_delete,
    get_indian_time, get_time_period, get_emotion, get_girl_response,
    contains_bad_words, contains_adult_content, contains_group_link,
    send_random_sticker, get_time_greeting
)
from utils.ai import get_ai_response

router = Router()

# ========== BASIC COMMANDS ==========

@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot):
    """Start command - works everywhere"""
    user = message.from_user
    chat = message.chat
    
    # Save user
    await db.add_user(user.id, user.username, user.first_name)
    started_users.add(user.id)
    
    # Save group if in group
    if chat.type in ["group", "supergroup"]:
        await db.add_group(chat.id, chat.title)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 HOME", url="https://t.me/abhi0w0")],
        [
            InlineKeyboardButton(text="📱 Utilities", callback_data="menu_utilities"),
            InlineKeyboardButton(text="🎭 Fun", callback_data="menu_fun")
        ],
        [
            InlineKeyboardButton(text="🛡️ Safety", callback_data="menu_safety"),
            InlineKeyboardButton(text="⚙️ Settings", callback_data="menu_settings")
        ],
        [InlineKeyboardButton(text="💬 Talk to Alita", callback_data="talk_alita")]
    ])
    
    welcome_text = (
        f"{get_emotion('love')} <b>Hii! I'm Alita 🎀</b>\n\n"
        f"✨ <b>Welcome to my magical world!</b> ✨\n\n"
        f"💖 <i>Main hu Alita... Ek sweet, aur protective girl!</i> 😊\n\n"
        f"🌟 <b>My Superpowers:</b>\n"
        f"• Advanced AI Conversations 🧠\n"
        f"• Image Generation 🎨\n"
        f"• Real Weather Updates 🌤️\n"
        f"• Auto-moderation 👮\n"
        f"• Daily Facts & Motivation 📚\n\n"
        f"• <b>MY HOME:</b> @abhi0w0\n\n"
        f"Type /help for all commands 💕"
    )
    
    image_url = "https://i.postimg.cc/yYWbPVQ4/1769349715111-result-image.png"
    
    await message.answer_photo(
        photo=image_url,
        caption=welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Help command - works everywhere"""
    started_users.add(message.from_user.id)
    
    help_text = (
        f"{get_emotion('happy')} **Hello! I'm Alita 🎀** 👧\n\n"
        
        f"🧠 **AI & CHAT:**\n"
        f"• /start - Start the bot\n"
        f"• /ask [question] - Ask AI anything\n"
        f"• /clear - Clear chat memory\n\n"
        
        f"🎨 **CREATIVE:**\n"
        f"• /imagine [prompt] - AI image generation\n"
        f"• /meme - Random meme text\n"
        f"• /joke - Random joke\n"
        f"• /fact - Daily fact\n"
        f"• /roast - Roast someone (reply)\n"
        f"• /horoscope [sign] - Daily horoscope\n\n"
        
        f"🌤️ **UTILITIES:**\n"
        f"• /weather [city] - Weather info\n"
        f"• /time - Indian time\n"
        f"• /date - Today's date\n"
        f"• /qr [text] - Generate QR code\n"
        f"• /password [len] - Secure password\n"
        f"• /short [url] - Shorten URL\n"
        f"• /calc [expr] - Calculator\n"
        f"• /translate [lang] [text] - Translate\n\n"
        
        f"📝 **PERSONAL:**\n"
        f"• /note [text] - Save a note\n"
        f"• /notes - View your notes\n"
        f"• /remind [time] [text] - Set reminder\n"
        f"• /reminders - View reminders\n"
        f"• /afk [reason] - Set AFK status\n"
        f"• /id - Get your info\n"
        f"• /info - Get user info (reply)\n\n"
        
        f"🎵 **MUSIC:**\n"
        f"• /lyrics [song] - Get song lyrics\n"
        f"• /song [name] - Search song info\n\n"
        
        f"🛡️ **ADMIN COMMANDS:**\n"
        f"• /adminlist - List all admins\n"
        f"• /warn [reason] - Warn user (reply)\n"
        f"• /kick - Kick user (reply)\n"
        f"• /ban - Ban user permanently (reply)\n"
        f"• /unban - Unban user (reply)\n"
        f"• /mute [time] - Mute user (reply)\n"
        f"• /unmute - Unmute user (reply)\n"
        f"• /purge [n] - Delete messages\n"
        f"• /pin - Pin message (reply)\n"
        f"• /unpin - Unpin last message\n"
        f"• /slowmode [sec] - Set slow mode\n"
        f"• /lock - Lock group chat\n"
        f"• /unlock - Unlock group chat\n"
        f"• /setwelcome [text] - Custom welcome\n"
        f"• /setgoodbye [text] - Custom goodbye\n"
        f"• /tagall - Mention all members\n"
        f"• /rules - Show group rules\n\n"
        
        f"👑 **OWNER COMMANDS:**\n"
        f"• /sendall - Reply any msg\n"
        f"• /broadcast - Broadcast msg\n"
        f"• /savesticker - Save sticker\n"
        f"• /stickerstatus - Count stickers\n"
        f"• /deletesticker - Delete sticker\n\n"
        
        f"**MY HOME:** @abhi0w0 💫"
    )
    await message.reply(help_text, parse_mode=ParseMode.MARKDOWN)

# ========== AI COMMANDS ==========

@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject, bot: Bot):
    """Ask AI anything - works in private and groups"""
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Usage:** `/ask [your question]`\n\n"
            f"Example: `/ask What is the capital of India?`"
        )
        return
    
    # Show typing
    await bot.send_chat_action(message.chat.id, "typing")
    
    # Get response
    response = await get_ai_response(
        chat_id=message.chat.id,
        user_text=command.args,
        user_id=message.from_user.id,
        user_name=message.from_user.first_name
    )
    
    await message.reply(response, parse_mode=ParseMode.MARKDOWN)

@router.message(Command("clear"))
async def cmd_clear(message: Message):
    """Clear chat memory"""
    from config import chat_memory
    if message.chat.id in chat_memory:
        chat_memory[message.chat.id].clear()
    await message.reply(f"{get_emotion('happy')} **Memory cleared!** 🧹")

# ========== CREATIVE COMMANDS ==========

@router.message(Command("joke"))
async def cmd_joke(message: Message):
    """Random joke"""
    jokes = [
        "🤣 Teacher: Tumhare ghar me sabse smart kaun hai? Student: Wifi router!",
        "😂 Papa: Beta mobile chhodo. Beta: Aap bhi to TV dekhte ho! Papa: Par main TV se shaadi nahi kar raha!",
        "😆 Doctor: Aapko diabetes hai. Patient: Kya khana chhodna hoga? Doctor: Nahi, aapka sugar chhodna hoga!",
        "😅 Dost: Tumhari girlfriend kitni cute hai! Me: Haan, uski akal bhi utni hi cute hai!",
        "🤪 Teacher: Agar tumhare paas 5 aam hain? Student: Sir, aapke paas already 2 kyun hain?"
    ]
    await message.reply(f"{get_emotion('funny')} {random.choice(jokes)}")

@router.message(Command("meme"))
async def cmd_meme(message: Message):
    """Generate random meme text"""
    templates = [
        {"text": "When you realize it's Monday tomorrow", "emoji": "😭"},
        {"text": "Me trying to be productive", "emoji": "🤡"},
        {"text": "When code finally works after 100 tries", "emoji": "🎉"},
        {"text": "When mom calls you by your full name", "emoji": "😰"},
        {"text": "My bank account after online shopping", "emoji": "💸"}
    ]
    meme = random.choice(templates)
    await message.reply(f"{get_emotion('funny')} **{meme['emoji']} {meme['text']}**")

@router.message(Command("fact"))
async def cmd_fact(message: Message):
    """Daily fact"""
    facts = [
        "🍯 Honey never spoils! Archaeologists found 3000-year-old honey still edible!",
        "🐙 Octopuses have 3 hearts! One stops when they swim!",
        "🍌 Bananas are berries, but strawberries aren't! Mind blown?",
        "🦈 Sharks existed before trees! Trees appeared 350 million years ago!",
        "🧠 The human brain uses 20% of body's energy! Even when resting!"
    ]
    await message.reply(f"{get_emotion('thinking')} {random.choice(facts)}")

@router.message(Command("roast"))
async def cmd_roast(message: Message):
    """Roast someone"""
    roasts = [
        "Tumhari baaton se toh mere kaan bhi sharminda hain! 👂😳",
        "Itni bakwas toh mere phone ki auto-correct bhi nahi karta! 📱",
        "Agar overthinking Olympic sport hota, toh tum gold medal le jaate! 🏅",
        "Tumhare dimaag mein itna khaali hai, wahan echo aata hoga! 🎤",
        "Tum itne slow ho, turtle bhi tumse race jeet jaaye! 🐢"
    ]
    
    if message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
        await message.reply(f"{get_emotion('sassy')} **Roasting {target}!** 🔥\n\n{random.choice(roasts)}")
    else:
        await message.reply(f"{get_emotion('sassy')} **Self-roast!** 😂\n\n{random.choice(roasts)}")

@router.message(Command("horoscope"))
async def cmd_horoscope(message: Message, command: CommandObject):
    """Daily horoscope"""
    signs = {
        "aries": "♈", "taurus": "♉", "gemini": "♊", "cancer": "♋",
        "leo": "♌", "virgo": "♍", "libra": "♎", "scorpio": "♏",
        "sagittarius": "♐", "capricorn": "♑", "aquarius": "♒", "pisces": "♓"
    }
    
    if not command.args:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(f"{emoji} {sign.title()}", callback_data=f"horo_{sign}")]
            for sign, emoji in list(signs.items())[:6]
        ] + [
            [InlineKeyboardButton(f"{emoji} {sign.title()}", callback_data=f"horo_{sign}")]
            for sign, emoji in list(signs.items())[6:]
        ])
        await message.reply("Choose your zodiac sign:", reply_markup=keyboard)
        return
    
    sign = command.args.lower()
    horoscopes = {
        "aries": "Today brings energy and passion! Take charge of new projects. 💪",
        "taurus": "Financial opportunities await. Stay grounded and practical. 💰",
        "gemini": "Communication is key today. Express yourself clearly. 💬",
        "cancer": "Focus on home and family. Emotional connections deepen. 🏠",
        "leo": "Your charisma shines! Leadership opportunities arise. 👑",
        "virgo": "Attention to detail pays off. Organization brings success. 📋",
        "libra": "Balance is essential. Harmony in relationships matters. ⚖️",
        "scorpio": "Intuition guides you. Trust your instincts. 🔮",
        "sagittarius": "Adventure calls! Explore new horizons. 🌍",
        "capricorn": "Hard work yields results. Stay disciplined. 🏔️",
        "aquarius": "Innovation flows. Think outside the box. 💡",
        "pisces": "Creativity blooms. Express your artistic side. 🎨"
    }
    
    emoji = signs.get(sign, "🌟")
    reading = horoscopes.get(sign, "Stars align for new beginnings! ✨")
    await message.reply(f"{get_emotion('love')} {emoji} **{sign.title()} Horoscope**\n\n{reading}")

# ========== UTILITY COMMANDS ==========

@router.message(Command("time"))
async def cmd_time(message: Message):
    """Indian time"""
    indian_time = get_indian_time()
    time_str = indian_time.strftime("%I:%M %p")
    date_str = indian_time.strftime("%A, %d %B %Y")
    
    await message.reply(
        f"🕒 **Indian Standard Time (IST)**\n"
        f"• Time: {time_str}\n"
        f"• Date: {date_str}\n"
        f"• Timezone: Asia/Kolkata 🇮🇳"
    )

@router.message(Command("date"))
async def cmd_date(message: Message):
    """Today's date"""
    indian_time = get_indian_time()
    await message.reply(
        f"{get_emotion('happy')} **📅 Today's Date**\n"
        f"• {indian_time.strftime('%A, %d %B %Y')}\n"
        f"• Day: {indian_time.strftime('%A')}\n"
        f"• Indian Standard Time 🇮🇳"
    )

@router.message(Command("weather"))
async def cmd_weather(message: Message, command: CommandObject, bot: Bot):
    """Weather info"""
    if not command.args:
        await message.reply(
            f"{get_emotion('thinking')} **Usage:** `/weather [city name]`\n\n"
            f"Example: `/weather Mumbai`"
        )
        return
    
    await bot.send_chat_action(message.chat.id, "typing")
    
    # Use real weather API or mock
    city = command.args
    # Implementation in utils/weather.py
    from utils.weather import get_weather
    weather_info = await get_weather(city)
    await message.reply(weather_info, parse_mode=ParseMode.MARKDOWN)

@router.message(Command("id"))
async def cmd_id(message: Message):
    """Get user info"""
    user = message.from_user
    chat = message.chat
    
    text = (
        f"{get_emotion('happy')} **Your Information** 🆔\n\n"
        f"👤 **User ID:** `{user.id}`\n"
        f"📛 **Name:** {user.full_name}\n"
        f"📱 **Username:** @{user.username or 'N/A'}\n"
        f"💬 **Chat ID:** `{chat.id}`\n"
        f"🏷️ **Chat Type:** {chat.type}"
    )
    
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        text += (
            f"\n\n🎯 **Replied User:**\n"
            f"👤 **User ID:** `{target.id}`\n"
            f"📛 **Name:** {target.full_name}\n"
            f"📱 **Username:** @{target.username or 'N/A'}"
        )
    
    await message.reply(text, parse_mode=ParseMode.MARKDOWN)

@router.message(Command("info"))
async def cmd_info(message: Message, bot: Bot):
    """Get detailed user info"""
    if message.reply_to_message:
        target = message.reply_to_message.from_user
    else:
        target = message.from_user
    
    try:
        # Get chat member info if in group
        status = "N/A"
        if message.chat.type in ["group", "supergroup"]:
            member = await bot.get_chat_member(message.chat.id, target.id)
            status_map = {
                "creator": "👑 Creator",
                "administrator": "🛡️ Admin", 
                "member": "👤 Member",
                "restricted": "⚠️ Restricted",
                "left": "👋 Left",
                "kicked": "🚫 Kicked"
            }
            status = status_map.get(member.status, member.status)
        
        text = (
            f"{get_emotion('thinking')} **User Information** 👤\n\n"
            f"🆔 **ID:** `{target.id}`\n"
            f"👤 **Name:** {target.full_name}\n"
            f"📱 **Username:** @{target.username or 'None'}\n"
            f"🌐 **Language:** {target.language_code or 'Unknown'}\n"
            f"🤖 **Is Bot:** {'Yes' if target.is_bot else 'No'}\n"
        )
        
        if status != "N/A":
            text += f"🏷️ **Status:** {status}\n"
        
        await message.reply(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

# ========== PERSONAL COMMANDS ==========

@router.message(Command("note"))
async def cmd_note(message: Message, command: CommandObject):
    """Save a note"""
    if not command.args:
        await message.reply("Usage: /note [your note text]")
        return
    
    await db.add_note(message.from_user.id, command.args)
    await message.reply(f"{get_emotion('happy')} **Note saved!** 📝")

@router.message(Command("notes"))
async def cmd_notes(message: Message):
    """View your notes"""
    notes = await db.get_notes(message.from_user.id)
    
    if not notes:
        await message.reply(f"{get_emotion('crying')} No notes found!")
        return
    
    text = f"{get_emotion('thinking')} **Your Notes:** 📋\n\n"
    for i, note in enumerate(notes[:10], 1):
        time_str = note['created_at'].strftime('%d/%m %I:%M %p')
        text += f"{i}. {note['text']} ({time_str})\n"
    
    await message.reply(text)

@router.message(Command("afk"))
async def cmd_afk(message: Message, command: CommandObject):
    """Set AFK status"""
    reason = command.args or "AFK"
    await db.set_afk(message.from_user.id, reason)
    await message.reply(
        f"{get_emotion('sleepy')} **AFK Mode Activated** 😴\n\n"
        f"💤 Reason: {reason}\n"
        f"⏰ Since: {datetime.now().strftime('%I:%M %p')}"
    )

# ========== ADMIN COMMANDS ==========

@router.message(Command("adminlist"))
async def cmd_adminlist(message: Message, bot: Bot):
    """List all admins - works in groups"""
    if message.chat.type == "private":
        await message.reply("This command only works in groups!")
        return
    
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        
        admin_list = []
        for admin in admins:
            user = admin.user
            status = "👑 Creator" if admin.status == "creator" else "🛡️ Admin"
            name = f"{user.first_name} {user.last_name or ''}".strip()
            username = f"(@{user.username})" if user.username else ""
            admin_list.append(f"{status} - {name} {username}")
        
        text = f"{get_emotion('protective')} **Group Administrators** 👑\n\n" + "\n".join(admin_list)
        await message.reply(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

@router.message(Command("rules"))
async def cmd_rules(message: Message):
    """Show group rules"""
    rules = (
        f"{get_emotion('protective')} **📜 GROUP RULES & SAFETY 🛡️**\n\n"
        f"✅ **DOs:**\n"
        f"1. Be respectful to everyone 🤝\n"
        f"2. Keep chat friendly and positive 🌟\n"
        f"3. Help each other grow 📚\n"
        f"4. Follow admin instructions 👮\n\n"
        f"🚫 **DON'Ts:**\n"
        f"1. No spam or flooding ⚠️\n"
        f"2. No group links sharing 🔗\n"
        f"3. No bad language 🚫\n"
        f"4. No adult/NSFW content 🚷\n"
        f"5. No fake/suspicious links 🚫"
    )
    await message.reply(rules, parse_mode=ParseMode.MARKDOWN)

@router.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject, bot: Bot):
    """Warn user"""
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to a user to warn them!")
        return
    
    target = message.reply_to_message.from_user
    reason = command.args or "Rule violation"
    
    await db.add_warning(message.chat.id, target.id, reason)
    warnings = await db.get_warnings(message.chat.id, target.id)
    count = len(warnings)
    
    text = (
        f"⚠️ **Warning {count}/3** 🚨\n"
        f"{target.first_name}, please don't {reason}!"
    )
    
    if count >= 3:
        # Mute user
        try:
            until = datetime.now() + timedelta(hours=1)
            await bot.restrict_chat_member(
                message.chat.id,
                target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            await db.clear_warnings(message.chat.id, target.id)
            text += f"\n\n🚫 **MUTED for 1 hour!** Too many warnings!"
        except Exception as e:
            text += f"\n\nFailed to mute: {str(e)}"
    
    await message.reply(text)

@router.message(Command("kick"))
async def cmd_kick(message: Message, bot: Bot):
    """Kick user"""
    if not await can_restrict(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} You don't have permission!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to a user to kick them!")
        return
    
    target = message.reply_to_message.from_user
    
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"{get_emotion('angry')} **Kicked!** {target.first_name} has been removed!")
    except Exception as e:
        await message.reply(f"Failed to kick: {str(e)}")

@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot):
    """Ban user permanently"""
    if not await can_restrict(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} You don't have permission!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to a user to ban them!")
        return
    
    target = message.reply_to_message.from_user
    
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await message.reply(f"{get_emotion('angry')} **Banned!** {target.first_name} is permanently banned!")
    except Exception as e:
        await message.reply(f"Failed to ban: {str(e)}")

@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot):
    """Unban user"""
    if not await can_restrict(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} You don't have permission!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to a user's message to unban them!")
        return
    
    target = message.reply_to_message.from_user
    
    try:
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"{get_emotion('happy')} **Unbanned!** {target.first_name} can rejoin now!")
    except Exception as e:
        await message.reply(f"Failed to unban: {str(e)}")

@router.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject, bot: Bot):
    """Mute user"""
    if not await can_restrict(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} You don't have permission!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to a user to mute them!")
        return
    
    target = message.reply_to_message.from_user
    
    # Parse duration
    duration = command.args
    if duration:
        if duration.endswith('h'):
            hours = int(duration[:-1])
            mute_until = datetime.now() + timedelta(hours=hours)
            duration_str = f"{hours} hour(s)"
        elif duration.endswith('m'):
            minutes = int(duration[:-1])
            mute_until = datetime.now() + timedelta(minutes=minutes)
            duration_str = f"{minutes} minute(s)"
        else:
            mute_until = datetime.now() + timedelta(hours=1)
            duration_str = "1 hour"
    else:
        mute_until = datetime.now() + timedelta(hours=1)
        duration_str = "1 hour"
    
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=mute_until
        )
        await message.reply(f"{get_emotion('angry')} **Muted!** {target.first_name} muted for {duration_str}!")
    except Exception as e:
        await message.reply(f"Failed to mute: {str(e)}")

@router.message(Command("unmute"))
async def cmd_unmute(message: Message, bot: Bot):
    """Unmute user"""
    if not await can_restrict(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} You don't have permission!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to a user to unmute them!")
        return
    
    target = message.reply_to_message.from_user
    
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_invite_users=True
            )
        )
        await message.reply(f"{get_emotion('happy')} **Unmuted!** {target.first_name} can speak again!")
    except Exception as e:
        await message.reply(f"Failed to unmute: {str(e)}")

@router.message(Command("purge"))
async def cmd_purge(message: Message, command: CommandObject, bot: Bot):
    """Delete multiple messages"""
    if not await can_delete(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} You don't have permission!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to the oldest message you want to delete!")
        return
    
    try:
        count = int(command.args) if command.args else 10
        if count > 100:
            count = 100
        
        # Delete messages
        msg_id = message.message_id
        reply_id = message.reply_to_message.message_id
        
        deleted = 0
        for i in range(reply_id, min(reply_id + count, msg_id)):
            try:
                await bot.delete_message(message.chat.id, i)
                deleted += 1
                await asyncio.sleep(0.1)
            except:
                pass
        
        await message.reply(f"{get_emotion('happy')} **Purged!** Deleted {deleted} messages!")
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

@router.message(Command("pin"))
async def cmd_pin(message: Message, bot: Bot):
    """Pin a message"""
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to a message to pin it!")
        return
    
    try:
        await bot.pin_chat_message(
            message.chat.id,
            message.reply_to_message.message_id,
            disable_notification=False
        )
        await message.reply(f"{get_emotion('happy')} **Pinned!** 📌")
    except Exception as e:
        await message.reply(f"Failed to pin: {str(e)}")

@router.message(Command("unpin"))
async def cmd_unpin(message: Message, bot: Bot):
    """Unpin message"""
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this!")
        return
    
    try:
        await bot.unpin_chat_message(message.chat.id)
        await message.reply(f"{get_emotion('happy')} **Unpinned!** 📍")
    except Exception as e:
        await message.reply(f"Failed to unpin: {str(e)}")

@router.message(Command("slowmode"))
async def cmd_slowmode(message: Message, command: CommandObject, bot: Bot):
    """Set slow mode"""
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this!")
        return
    
    try:
        delay = int(command.args) if command.args else 0
        await bot.set_chat_slow_mode_delay(message.chat.id, delay)
        
        if delay == 0:
            await message.reply(f"{get_emotion('happy')} **Slow mode disabled!** 🚀")
        else:
            await message.reply(f"{get_emotion('happy')} **Slow mode enabled!** {delay} seconds between messages.")
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

@router.message(Command("lock"))
async def cmd_lock(message: Message, bot: Bot):
    """Lock chat"""
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this!")
        return
    
    try:
        await bot.set_chat_permissions(
            message.chat.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False
            )
        )
        await message.reply(f"{get_emotion('protective')} **Chat Locked!** 🔒 Only admins can send messages.")
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

@router.message(Command("unlock"))
async def cmd_unlock(message: Message, bot: Bot):
    """Unlock chat"""
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this!")
        return
    
    try:
        await bot.set_chat_permissions(
            message.chat.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_invite_users=True
            )
        )
        await message.reply(f"{get_emotion('happy')} **Chat Unlocked!** 🔓 Everyone can send messages.")
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

@router.message(Command("tagall"))
async def cmd_tagall(message: Message, bot: Bot):
    """Mention all members"""
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(f"{get_emotion('angry')} Only admins can use this!")
        return
    
    if message.chat.type == "private":
        await message.reply("This only works in groups!")
        return
    
    try:
        members = []
        async for member in bot.get_chat_members(message.chat.id):
            if not member.user.is_bot:
                if member.user.username:
                    members.append(f"@{member.user.username}")
                else:
                    members.append(member.user.first_name)
        
        if not members:
            await message.reply("No members found!")
            return
        
        # Split into chunks
        chunk_size = 5
        for i in range(0, len(members), chunk_size):
            chunk = members[i:i + chunk_size]
            await message.reply(" ".join(chunk))
            await asyncio.sleep(1)
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

# ========== OWNER COMMANDS ==========

@router.message(Command("sendall"))
async def cmd_sendall(message: Message, bot: Bot):
    """Broadcast to all (Owner only)"""
    if message.from_user.id != config.ADMIN_ID:
        await message.reply("❌ Owner only!")
        return
    
    if not message.reply_to_message:
        await message.reply("Reply to a message to broadcast!")
        return
    
    status = await message.reply("📤 Broadcasting...")
    
    # Get all users and groups
    users = await users_col.find().to_list(length=None)
    groups = await groups_col.find().to_list(length=None)
    
    sent = 0
    failed = 0
    
    # Send to users
    for user in users:
        try:
            await bot.copy_message(
                chat_id=user["user_id"],
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id
            )
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    # Send to groups
    for group in groups:
        try:
            await bot.copy_message(
                chat_id=group["chat_id"],
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id
            )
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await status.edit_text(f"✅ Broadcast Complete!\n\nSent: {sent}\nFailed: {failed}")

@router.message(Command("savesticker"))
async def cmd_savesticker(message: Message, bot: Bot):
    """Save sticker to database (Owner only)"""
    if message.from_user.id != config.ADMIN_ID:
        await message.reply(f"{get_emotion('angry')} Only owner can use this!")
        return
    
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply("Reply to a sticker to save it!")
        return
    
    sticker = message.reply_to_message.sticker
    await db.save_sticker(sticker.file_id, message.from_user.id)
    
    # Reload stickers
    global saved_stickers
    saved_stickers = await db.get_all_stickers()
    
    await message.reply(f"{get_emotion('love')} **Sticker saved!** Total: {len(saved_stickers)}")

@router.message(Command("stickerstatus"))
async def cmd_stickerstatus(message: Message):
    """Show sticker count"""
    count = len(saved_stickers)
    await message.reply(f"{get_emotion('happy')} **Sticker Database:** {count} stickers saved!")

@router.message(Command("deletesticker"))
async def cmd_deletesticker(message: Message, bot: Bot):
    """Delete sticker (Owner only)"""
    if message.from_user.id != config.ADMIN_ID:
        await message.reply(f"{get_emotion('angry')} Only owner can use this!")
        return
    
    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply("Reply to a sticker to delete it!")
        return
    
    sticker_id = message.reply_to_message.sticker.file_id
    await db.delete_sticker(sticker_id)
    
    # Reload
    global saved_stickers
    saved_stickers = await db.get_all_stickers()
    
    await message.reply(f"{get_emotion('happy')} **Sticker deleted!** Remaining: {len(saved_stickers)}")
