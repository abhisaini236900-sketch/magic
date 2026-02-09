from aiogram import Router, Bot
from aiogram.types import CallbackQuery
from utils.helpers import get_emotion, get_girl_response

router = Router()

@router.callback_query()
async def handle_callback(callback: CallbackQuery, bot: Bot):
    """Handle all callbacks"""
    data = callback.data
    
    if data == "menu_utilities":
        text = (
            f"{get_emotion('happy')} **📱 Utilities Menu**\n\n"
            f"• /time - Current time\n"
            f"• /date - Today's date\n"
            f"• /weather [city] - Weather info\n"
            f"• /qr [text] - QR Code\n"
            f"• /password [len] - Password\n"
            f"• /short [url] - Shorten URL\n"
            f"• /translate - Translate\n"
            f"• /calc - Calculator\n"
            f"• /id - Get IDs"
        )
        await callback.message.edit_text(text)
    
    elif data == "menu_fun":
        text = (
            f"{get_emotion('funny')} **🎭 Fun Menu**\n\n"
            f"• /joke - Random joke\n"
            f"• /meme - Generate meme\n"
            f"• /fact - Daily fact\n"
            f"• /horoscope - Horoscope\n"
            f"• /roast - Roast someone\n"
            f"• /imagine - AI Image Gen\n"
            f"• /lyrics - Song lyrics"
        )
        await callback.message.edit_text(text)
    
    elif data == "menu_safety":
        text = (
            f"{get_emotion('protective')} **🛡️ Safety Features**\n\n"
            f"• Spam detection 🔍\n"
            f"• Group link blocking 🚫\n"
            f"• Bad word filtering ⚔️\n"
            f"• Adult content detection 🔞\n"
            f"• Auto-warnings ⚠️\n"
            f"• Auto-mute system 🔇"
        )
        await callback.message.edit_text(text)
    
    elif data == "menu_settings":
        text = (
            f"{get_emotion('thinking')} **⚙️ Settings**\n\n"
            f"Admin commands:\n"
            f"• /setwelcome - Custom welcome\n"
            f"• /setgoodbye - Custom goodbye\n"
            f"• /slowmode - Slow mode\n"
            f"• /lock - Lock chat\n"
            f"• /unlock - Unlock chat\n"
            f"• /adminlist - List admins\n"
            f"• /tagall - Mention all"
        )
        await callback.message.edit_text(text)
    
    elif data == "talk_alita":
        await callback.message.reply(
            f"{get_emotion('love')} **Hi! I'm Alita!** 🎀\n\n"
            f"Just type anything or use /ask [question] to chat with me! 💕"
        )
    
    elif data.startswith("horo_"):
        sign = data.split("_")[1]
        horoscopes = {
            "aries": "Today brings energy and passion! 💪",
            "taurus": "Financial opportunities await. 💰",
            "gemini": "Communication is key today. 💬",
            "cancer": "Focus on home and family. 🏠",
            "leo": "Your charisma shines! 👑",
            "virgo": "Attention to detail pays off. 📋",
            "libra": "Balance is essential. ⚖️",
            "scorpio": "Intuition guides you. 🔮",
            "sagittarius": "Adventure calls! 🌍",
            "capricorn": "Hard work yields results. 🏔️",
            "aquarius": "Innovation flows. 💡",
            "pisces": "Creativity blooms. 🎨"
        }
        reading = horoscopes.get(sign, "Stars align for new beginnings! ✨")
        await callback.message.reply(
            f"{get_emotion('love')} **{sign.title()} Horoscope**\n\n{reading}"
        )
    
    await callback.answer()
