from config import users_col, groups_col, stickers_col, notes_col, reminders_col, afk_col, warnings_col
from datetime import datetime
from typing import Optional, List, Dict, Any

class Database:
    
    @staticmethod
    async def add_user(user_id: int, username: str = None, first_name: str = None):
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "joined_at": datetime.now(),
                "last_active": datetime.now()
            }},
            upsert=True
        )
    
    @staticmethod
    async def add_group(chat_id: int, title: str = None):
        await groups_col.update_one(
            {"chat_id": chat_id},
            {"$set": {
                "chat_id": chat_id,
                "title": title,
                "joined_at": datetime.now(),
                "settings": {
                    "welcome_enabled": True,
                    "goodbye_enabled": True,
                    "auto_mod_enabled": True,
                    "captcha_enabled": False,
                    "warn_limit": 3,
                    "custom_welcome": None,
                    "custom_goodbye": None
                }
            }},
            upsert=True
        )
    
    @staticmethod
    async def get_group_settings(chat_id: int) -> Dict:
        group = await groups_col.find_one({"chat_id": chat_id})
        if group:
            return group.get("settings", {})
        return {}
    
    @staticmethod
    async def update_group_settings(chat_id: int, settings: Dict):
        await groups_col.update_one(
            {"chat_id": chat_id},
            {"$set": {"settings": settings}}
        )
    
    @staticmethod
    async def save_sticker(file_id: str, added_by: int, tags: str = ""):
        await stickers_col.update_one(
            {"file_id": file_id},
            {"$set": {
                "file_id": file_id,
                "added_by": added_by,
                "added_at": datetime.now(),
                "tags": tags
            }},
            upsert=True
        )
    
    @staticmethod
    async def get_all_stickers() -> List[str]:
        stickers = await stickers_col.find().to_list(length=None)
        return [s["file_id"] for s in stickers]
    
    @staticmethod
    async def delete_sticker(file_id: str):
        await stickers_col.delete_one({"file_id": file_id})
    
    @staticmethod
    async def add_note(user_id: int, text: str):
        note = {
            "user_id": user_id,
            "text": text,
            "created_at": datetime.now()
        }
        await notes_col.insert_one(note)
    
    @staticmethod
    async def get_notes(user_id: int) -> List[Dict]:
        return await notes_col.find({"user_id": user_id}).sort("created_at", -1).to_list(length=50)
    
    @staticmethod
    async def add_reminder(user_id: int, text: str, remind_at: datetime):
        reminder = {
            "user_id": user_id,
            "text": text,
            "remind_at": remind_at,
            "created_at": datetime.now(),
            "done": False
        }
        result = await reminders_col.insert_one(reminder)
        return result.inserted_id
    
    @staticmethod
    async def get_pending_reminders():
        now = datetime.now()
        return await reminders_col.find({
            "remind_at": {"$lte": now},
            "done": False
        }).to_list(length=None)
    
    @staticmethod
    async def mark_reminder_done(reminder_id):
        await reminders_col.update_one(
            {"_id": reminder_id},
            {"$set": {"done": True}}
        )
    
    @staticmethod
    async def set_afk(user_id: int, reason: str):
        await afk_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "reason": reason,
                "since": datetime.now()
            }},
            upsert=True
        )
    
    @staticmethod
    async def remove_afk(user_id: int):
        await afk_col.delete_one({"user_id": user_id})
    
    @staticmethod
    async def get_afk(user_id: int) -> Optional[Dict]:
        return await afk_col.find_one({"user_id": user_id})
    
    @staticmethod
    async def add_warning(chat_id: int, user_id: int, reason: str):
        warning = {
            "chat_id": chat_id,
            "user_id": user_id,
            "reason": reason,
            "timestamp": datetime.now()
        }
        await warnings_col.insert_one(warning)
    
    @staticmethod
    async def get_warnings(chat_id: int, user_id: int) -> List[Dict]:
        return await warnings_col.find({
            "chat_id": chat_id,
            "user_id": user_id
        }).sort("timestamp", -1).to_list(length=None)
    
    @staticmethod
    async def clear_warnings(chat_id: int, user_id: int):
        await warnings_col.delete_many({
            "chat_id": chat_id,
            "user_id": user_id
        })

db = Database()
