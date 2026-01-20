import json
import asyncio
from aiogram import types
from bot import bot, dp

async def process_update(update_data: dict):
    update = types.Update(**update_data)
    await dp.feed_update(bot, update)

def handler(request):
    try:
        update_data = json.loads(request.body)
        asyncio.run(process_update(update_data))
        return {
            "statusCode": 200,
            "body": "ok"
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": str(e)
        }
