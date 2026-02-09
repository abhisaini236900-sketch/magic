from aiogram import Router, Bot, F
from aiogram.types import Message
from datetime import datetime
import random
import asyncio

from config import config, saved_stickers, started_users, chat_memory
from database import db
from utils.helpers import (
    is_admin, contains_bad_words, contains_adult_content, contains_group_link,
    get_emotion, get_girl_response, send_random_sticker, get_indian_time
)
from utils.ai import get_ai_response

router = Router()

# Spam tracking
spam_tracker = {}  # {chat_id: {user_id: [timestamps]}}

async def check_spam(chat_id: int, user_id: int) -> bool:
    """Check if user is spamming"""
    now = datetime.now()
    
    if chat_id not in spam_tracker:
        spam_tracker[chat_id] = {}
    
    if user_id not in spam_tracker[chat_id]:
        spam_tracker[chat_id][user_id] = []
    
    # Add timestamp
    spam_tracker[chat_id][user_id].append(now)
    
    # Keep only last 30 seconds
    spam_tracker[chat_id][user_id] = [
        ts for ts in spam_tracker[chat_id][user_id]
        if (now - ts).seconds <= 30
    ]
    
    # Check limit (7 messages in 30 seconds)
    return len(spam_tracker[chat_id][user_id]) > 7

@router.message()
async def handle_message(message: Message, bot: Bot):
    """Handle all messages - THE MAIN ROUTER"""
    
    if not message.from_user:
        return
    
    user = message.from_user
    chat = message.chat
    user_id = user.id
    chat_id = chat.id
    
    # Ignore bots
    if user.is_bot:
        return
    
    # Add to tracking
    started_users.add(user_id)
    
    # Initialize memory
    if chat_id not in chat_memory:
        chat_memory[chat_id] = []
    
    # Check AFK
    afk_data = await db.get_afk(user_id)
    if afk_data and message.text and not message.text.startswith("/"):
        await db.remove_afk(user_id)
        await message.reply(f"{get_emotion('happy')} Welcome back! AFK removed! 👋")
        return
    
    # Check if someone mentioned AFK user
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mentioned = message.text[entity.offset:entity.offset + entity.length]
                # Find user by username
                # This is simplified - you'd need to track username mappings
    
    # AUTO-MODERATION FOR GROUPS
    if chat.type in ["group", "supergroup"]:
        settings = await db.get_group_settings(chat_id)
        
        if settings.get("auto_mod_enabled", True):
            text = message.text or message.caption or ""
            
            # Check adult content (immediate ban)
            if contains_adult_content(text):
                if await is_admin(bot, chat_id, user_id):
                    return  # Don't ban admins
                
                try:
                    await message.delete()
                    await bot.ban_chat_member(chat_id, user_id)
                    await message.answer(
                        f"{get_emotion('angry')} **BANNED!** 🚫\n"
                        f"{user.first_name} banned for adult content!"
                    )
                    return
                except:
                    pass
            
            # Check bad words
            if contains_bad_words(text):
                try:
                    await message.delete()
                    await message.answer(
                        f"{get_emotion('angry')} **Warning!** {user.first_name}, "
                        f"bad words not allowed! 😠"
                    )
                    return
                except:
                    pass
            
            # Check group links
            if contains_group_link(text):
                try:
                    await message.delete()
                    await message.answer(
                        f"{get_emotion('angry')} **Warning!** {user.first_name}, "
                        f"no group links allowed! 🔗"
                    )
                    return
                except:
                    pass
            
            # Check spam
            if await check_spam(chat_id, user_id):
                try:
                    await message.delete()
                    # Mute for 5 minutes
                    until = datetime.now() + timedelta(minutes=5)
                    await bot.restrict_chat_member(
                        chat_id, user_id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=until
                    )
                    await message.answer(
                        f"{get_emotion('angry')} **Spam detected!** "
                        f"{user.first_name} muted for 5 minutes! 🔇"
                    )
                    return
                except:
                    pass
    
    # Handle non-text messages
    if not message.text:
        if message.sticker and random.random() < 0.3:
            # Respond to sticker with sticker or text
            if saved_stickers and random.random() < 0.5:
                await send_random_sticker(bot, chat_id)
            else:
                responses = [
                    f"{get_emotion('love')} Cute sticker! 😍",
                    f"{get_emotion('happy')} Aww, I love this! 💖",
                    f"{get_emotion('funny)} Nice one! 😄"
                ]
                await message.reply(random.choice(responses))
        return
    
    # ===== MAIN CHAT LOGIC =====
    text = message.text
    text_lower = text.lower()
    
    # Get bot info
    bot_info = await bot.get_me()
    bot_username = bot_info.username.lower()
    
    # Determine if we should respond
    is_private = chat.type == "private"
    is_mention = f"@{bot_username}" in text_lower
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    # Clean text for AI
    clean_text = text
    if bot_username and f"@{bot_username}" in clean_text.lower():
        clean_text = text_lower.replace(f"@{bot_username}", "").strip()
    
    should_respond = False
    
    if is_private:
        # Always respond in private
        should_respond = True
    elif is_mention or is_reply_to_bot:
        # Respond when mentioned or replied in groups
        should_respond = True
    
    if should_respond:
        # Show typing
        await bot.send_chat_action(chat_id, "typing")
        
        # Random delay for human feel
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        # Random sticker before response (25% chance)
        if random.random() < 0.25 and saved_stickers:
            await send_random_sticker(bot, chat_id)
            await asyncio.sleep(0.5)
        
        # Get AI response
        response = await get_ai_response(
            chat_id=chat_id,
            user_text=clean_text,
            user_id=user_id,
            user_name=user.first_name
        )
        
        await message.reply(response)
        
        # Random sticker after (15% chance)
        if random.random() < 0.15 and saved_stickers:
            await asyncio.sleep(0.5)
            await send_random_sticker(bot, chat_id)
