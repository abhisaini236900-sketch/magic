import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from config import config, saved_stickers
from database import db
from handlers import commands, messages, callbacks
from tasks.background import setup_scheduler

# Initialize bot
bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# Include routers
dp.include_router(commands.router)
dp.include_router(callbacks.router)
dp.include_router(messages.router)  # Must be last (catches all)

# Web server for Render
async def handle_ping(request):
    return web.Response(text="🤖 Alita is Alive! 🎀")

async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    print(f"🌐 Health server started on port {config.PORT}")

async def main():
    print("=" * 60)
    print("🎀 ALITA - ULTRA ADVANCED GROUP MANAGEMENT BOT 🎀")
    print("=" * 60)
    
    # Load stickers
    global saved_stickers
    saved_stickers = await db.get_all_stickers()
    print(f"🎭 Loaded {len(saved_stickers)} stickers")
    
    # Get bot info
    bot_info = await bot.get_me()
    config.BOT_USERNAME = bot_info.username
    config.BOT_ID = bot_info.id
    print(f"🤖 Bot: @{bot_info.username}")
    print(f"👑 Owner ID: {config.ADMIN_ID}")
    
    # Start web server
    asyncio.create_task(start_server())
    
    # Setup background tasks
    setup_scheduler(bot)
    
    # Start polling
    print("🔄 Starting bot...")
    print("=" * 60)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
