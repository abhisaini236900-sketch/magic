import asyncio
import random
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config, saved_stickers, started_users
from database import db
from utils.helpers import get_indian_time, get_time_greeting, get_time_period

scheduler = AsyncIOScheduler()

async def send_time_greetings(bot):
    """Send time-based greetings to active chats"""
    greeting = get_time_greeting()
    period = get_time_period()
    
    # Send to active groups
    groups = await db.groups_col.find().to_list(length=None)
    for group in groups:
        try:
            settings = group.get("settings", {})
            if settings.get("greetings_enabled", True):
                await bot.send_message(group["chat_id"], greeting)
                await asyncio.sleep(0.5)
        except:
            pass
    
    # Send to active users (messaged in last 3 days)
    for user_id in list(started_users):
        try:
            await bot.send_message(user_id, greeting)
            await asyncio.sleep(0.5)
        except:
            pass

async def send_random_stickers(bot):
    """Send random stickers to active chats"""
    if not saved_stickers:
        return
    
    # Send to groups (20% chance)
    groups = await db.groups_col.find().to_list(length=None)
    for group in groups:
        if random.random() < 0.2:
            try:
                sticker = random.choice(saved_stickers)
                await bot.send_sticker(group["chat_id"], sticker)
                await asyncio.sleep(1)
            except:
                pass
    
    # Send to users (10% chance)
    for user_id in list(started_users):
        if random.random() < 0.1:
            try:
                sticker = random.choice(saved_stickers)
                await bot.send_sticker(user_id, sticker)
                await asyncio.sleep(1)
            except:
                pass

async def check_reminders(bot):
    """Check and send due reminders"""
    reminders = await db.get_pending_reminders()
    for rem in reminders:
        try:
            await bot.send_message(
                rem["user_id"],
                f"⏰ **Reminder!**\n\n{rem['text']}\n\n*Don't forget!* 💫"
            )
            await db.mark_reminder_done(rem["_id"])
        except:
            pass

async def send_daily_facts(bot):
    """Send daily facts to random users"""
    facts = [
        "🍯 Honey never spoils! Archaeologists found 3000-year-old honey still edible!",
        "🐙 Octopuses have 3 hearts! One stops when they swim!",
        "🍌 Bananas are berries, but strawberries aren't!",
        "🦈 Sharks existed before trees!",
        "🧠 The human brain uses 20% of body's energy!"
    ]
    
    fact = random.choice(facts)
    
    # Send to 20% of active users
    for user_id in list(started_users):
        if random.random() < 0.2:
            try:
                await bot.send_message(
                    user_id,
                    f"📚 **Daily Fact:**\n\n{fact}\n\n*Stay curious!* ✨"
                )
                await asyncio.sleep(0.5)
            except:
                pass

def setup_scheduler(bot):
    """Setup all background tasks"""
    
    # Time greetings - every 4 hours
    scheduler.add_job(
        send_time_greetings,
        'interval',
        hours=4,
        args=[bot],
        id='time_greetings'
    )
    
    # Random stickers - every 2 hours
    scheduler.add_job(
        send_random_stickers,
        'interval',
        hours=2,
        args=[bot],
        id='random_stickers'
    )
    
    # Check reminders - every minute
    scheduler.add_job(
        check_reminders,
        'interval',
        minutes=1,
        args=[bot],
        id='reminders'
    )
    
    # Daily facts - at 10 AM
    scheduler.add_job(
        send_daily_facts,
        CronTrigger(hour=10, minute=0, timezone=config.INDIAN_TZ),
        args=[bot],
        id='daily_facts'
    )
    
    scheduler.start()
    print("⏰ Background tasks started!")
