from pyrogram.filters import create
from Backend.config import Telegram

class CustomFilters:

    @staticmethod
    async def owner_filter(client, message):
        user = message.from_user or message.sender_chat
        if not user: return False
        uid = user.id
        return uid == Telegram.OWNER_ID

    @staticmethod
    async def admin_filter(client, message):
        from Backend import db
        user = message.from_user or message.sender_chat
        if not user: return False
        uid = user.id
        return await db.is_bot_admin(uid)

    owner = create(owner_filter)
    admin = create(admin_filter)