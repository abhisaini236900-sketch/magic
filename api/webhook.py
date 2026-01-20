import os
import asyncio
from aiogram import types
from bot import bot, dp

async def handler(request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return {"status": "ok"}

def main(request):
    return asyncio.run(handler(request))
