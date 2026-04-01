from asyncio import create_task, sleep as asleep
from urllib.parse import urlparse
from Backend.logger import LOGGER
from Backend import db
from Backend.config import Telegram
from Backend.helper.custom_filter import CustomFilters
from Backend.helper.encrypt import decode_string
from Backend.helper.metadata import metadata
from Backend.helper.pyro import clean_filename, get_readable_file_size, remove_urls
from Backend.pyrofork import StreamBot
from pyrogram import filters, Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from os import path as ospath
from pyrogram.errors import FloodWait, UserNotParticipant
from pyrogram.enums.parse_mode import ParseMode
from themoviedb import aioTMDb
from asyncio import Queue, create_task
from os import execl as osexecl
from asyncio import create_subprocess_exec, gather
from sys import executable
from aiofiles import open as aiopen
from pyrogram import enums


tmdb = aioTMDb(key=Telegram.TMDB_API, language="en-US", region="US")
# Initialize database connection
import random
import string
from passlib.context import CryptContext
from datetime import datetime, timedelta

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def generate_password(length=10):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

@StreamBot.on_message(filters.command("user") & filters.private & CustomFilters.owner)
async def create_user(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 3:
            await message.reply_text("❌ Usage: `/user <username> <expiry_days>`", parse_mode=ParseMode.MARKDOWN)
            return

        username = args[1]
        expiry_days = int(args[2])

        users_collection = db.db["auth_users"]  # Use the Tracking database

        # Check if username already exists
        existing_user = await users_collection.find_one({"username": username})
        if existing_user:
            await message.reply_text(f"❌ User `{username}` already exists!", parse_mode=ParseMode.MARKDOWN)
            return

        password = generate_password()
        hashed_password = pwd_ctx.hash(password)
        expires_at = datetime.utcnow() + timedelta(days=expiry_days)

        user_data = {
            "username": username,
            "password": hashed_password,
            "expires_at": expires_at
        }
        await users_collection.insert_one(user_data)

        await message.reply_text(
            f"✅ User created!\n\n"
            f"👤 Username: `{username}`\n"
            f"🔑 Password: `{password}`\n"
            f"🕒 Expires in: `{expiry_days}` days\n"
            f"📅 Expiry Date: `{expires_at.strftime('%Y-%m-%d %H:%M:%S')} UTC`",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        LOGGER.error(f"Error in /user command: {e}")
        await message.reply_text("❌ An error occurred while creating the user.")

@StreamBot.on_message(filters.command('restart') & filters.private & CustomFilters.owner)
async def restart(bot: Client, message: Message):
    try:
        # Notify the user that the bot is restarting
        
        restart_message = await message.reply_text(
    '<blockquote>⚙️ Restarting Backend API... \n\n✨ Please wait as we bring everything back online! 🚀</blockquote>',
        quote=True,
        parse_mode=enums.ParseMode.HTML
        )
        LOGGER.info("Restart initiated by owner.")

        # Run the update script
        proc1 = await create_subprocess_exec('python3', 'update.py')
        await gather(proc1.wait())

        # Save restart message details for notification after restart
        async with aiopen(".restartmsg", "w") as f:
            await f.write(f"{restart_message.chat.id}\n{restart_message.id}\n")

        # Restart the bot process
        osexecl(executable, executable, "-m", "Backend")

    except Exception as e:
        LOGGER.error(f"Error during restart: {e}")
        await message.reply_text("**❌ Failed to restart. Check logs for details.**")




async def delete_messages_after_delay(messages):
    await asleep(300)  
    for msg in messages:
        try:
            await msg.delete()
        except Exception as e:
            LOGGER.error(f"Error deleting message {msg.id}: {e}")
        await asleep(2)  

@StreamBot.on_message(filters.command('start') & filters.private)
async def start(bot: Client, message: Message):
    LOGGER.info(f"Received command: {message.text}")
    
    # Force Subscribe Check
    settings = await db.get_settings()
    fsub_channel = settings.get("fsubChannel")
    
    if fsub_channel:
        try:
            await bot.get_chat_member(fsub_channel, message.from_user.id)
        except UserNotParticipant:
            try:
                chat = await bot.get_chat(fsub_channel)
                join_url = f"https://t.me/{chat.username}" if chat.username else (await bot.export_chat_invite_link(chat.id))
                
                # Check if there is data in start command to preserve
                start_data = message.text.split('start ')[-1] if 'start ' in message.text else ""
                verify_url = f"https://t.me/{(await bot.get_me()).username}?start={start_data}"
                
                return await message.reply_text(
                    f"👋 **Hello {message.from_user.first_name}!**\n\n"
                    f"To access the requested file, you must first join our update channel. "
                    f"This helps us keep you informed about new content and site updates.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📢 Join Channel", url=join_url)],
                        [InlineKeyboardButton("🔄 Verified - Try Again", url=verify_url)]
                    ])
                )
            except Exception as e:
                LOGGER.error(f"Error in FSub join logic: {e}")
        except Exception as e:
            LOGGER.error(f"Error checking FSub membership: {e}")

    command_part = message.text.split('start ')[-1]
    
    if command_part.startswith("file_"):
        usr_cmd = command_part[len("file_"):].strip()
        
        parts = usr_cmd.split("_")
        
        if len(parts) == 2:
            try:
                tmdb_id, quality = parts
                tmdb_id = int(tmdb_id)
                season = None
                quality_details = await db.get_quality_details(tmdb_id, quality)
            except ValueError:
                LOGGER.error(f"Error parsing movie command: {usr_cmd}")
                await message.reply_text("Invalid command format for movie.")
                return
        
        elif len(parts) == 3:
            try:
                tmdb_id, season, quality = parts
                tmdb_id = int(tmdb_id)
                season = int(season)
                quality_details = await db.get_quality_details(tmdb_id, quality, season)
            except ValueError:
                LOGGER.error(f"Error parsing TV show command: {usr_cmd}")
                await message.reply_text("Invalid command format for TV show.")
                return
        elif len(parts) == 4:
            try:
                tmdb_id, season, episode, quality = parts
                tmdb_id = int(tmdb_id)
                season = int(season)
                episode = int(episode)
                quality_details = await db.get_quality_details(tmdb_id, quality, season, episode)
            except ValueError:
                LOGGER.error(f"Error parsing TV show command: {usr_cmd}")
                await message.reply_text("Invalid command format for TV show.")
                return

        else:
            await message.reply_text("Invalid command format.")
            return

        sent_messages = []
        for detail in quality_details:
            decoded_data = await decode_string(detail['id'])
            channel = f"-100{decoded_data['chat_id']}"
            msg_id = decoded_data['msg_id']
            name = detail['name']
            if "\\n" in name and name.endswith(".mkv"):
                name = name.rsplit(".mkv", 1)[0].replace("\\n", "\n")
            try:
                file = await bot.get_messages(int(channel), int(msg_id))
                media = file.document or file.video
                if media:
                    sent_msg = await message.reply_cached_media(
                        file_id=media.file_id,
                        caption=f'{name}'
                    )
                    sent_messages.append(sent_msg)
                    await asleep(1)
            except FloodWait as e:
                LOGGER.info(f"Sleeping for {e.value}s")
                await asleep(e.value)
                await message.reply_text(f"Got Floodwait of {e.value}s")
            except Exception as e:
                LOGGER.error(f"Error retrieving/sending media: {e}")
                await message.reply_text("Error retrieving media.")

        if sent_messages:
            warning_msg = await message.reply_text(
                "Forward these files to your saved messages. These files will be deleted from the bot within 5 minutes."
            )
            sent_messages.append(warning_msg)
            create_task(delete_messages_after_delay(sent_messages))
    else:
        await message.reply_text("Hello 👋")



@StreamBot.on_message(filters.command('log') & filters.private & CustomFilters.admin)
async def start(bot: Client, message: Message):
    try:
        path = ospath.abspath('log.txt')
        return await message.reply_document(
        document=path, quote=True, disable_notification=True
        )
    except Exception as e:
        print(f"An error occurred: {e}")




# Global queue for processing file updates
file_queue = Queue()

from asyncio import Lock

# Global lock for database access
db_lock = Lock()

from Backend.helper.notification import send_log_report

async def process_file():
    while True:
        metadata_info, hash, channel, msg_id, size, title = await file_queue.get()

        # Acquire the lock before updating the database
        async with db_lock:
            updated_id = await db.insert_media(metadata_info, hash=hash, channel=channel, msg_id=msg_id, size=size, name=title)

            if updated_id:
                LOGGER.info(f"{metadata_info['media_type']} updated with ID: {updated_id}")
                # Send log report
                await send_log_report(metadata_info, mode="Automatic")
            else:
                LOGGER.info("Update failed due to validation errors.")

        file_queue.task_done()



# Start the file processing tasks (adjust the number of workers as needed)
for _ in range(1):  # Two concurrent workers
    create_task(process_file())

@StreamBot.on_message(
    filters.channel
    & (
        filters.document
        | filters.video
    )
)
async def file_receive_handler(bot: Client, message: Message):
    chat_id_str = str(message.chat.id)
    is_auth = chat_id_str in Telegram.AUTH_CHANNEL
    is_manual = chat_id_str in Telegram.MANUAL_CHANNEL

    if is_auth or is_manual:
        try:
            if message.video or message.document:
                file = message.video or message.document
                if Telegram.USE_CAPTION and message.caption:
                    title = message.caption.replace("\n", "\\n")
                else:
                    title = file.file_name or file.file_id
                
                msg_id = message.id
                hash = file.file_unique_id[:6]
                size = get_readable_file_size(file.file_size)
                channel = chat_id_str.replace("-100","")
                
                # Improve file display name filtering for manual database
                display_name = remove_urls(title)
                display_name = clean_filename(display_name)
                
                if not display_name.lower().endswith('.mkv') and not display_name.lower().endswith('.mp4'):
                    display_name += '.mkv'

                if is_manual:
                    # Save to manual database for manual linking
                    manual_data = {
                        "chat_id": int(channel),
                        "msg_id": msg_id,
                        "hash": hash,
                        "size": size,
                        "name": display_name,
                        "original_name": title
                    }
                    await db.insert_manual_file(manual_data)

                if is_auth:
                    # Proceed with automatic fetch
                    metadata_info = await metadata(clean_filename(title), message)
                    if metadata_info is not None:
                        # Add file data to the queue for processing
                        # Use the same cleaned display_name for consistency
                        await file_queue.put((metadata_info, hash, int(channel), msg_id, size, display_name))

            else:
                await message.reply_text("Not supported")
        except FloodWait as e:
            LOGGER.info(f"Sleeping for {str(e.value)}s")
            await asleep(e.value)
            await message.reply_text(text=f"Got Floodwait of {str(e.value)}s",
                                disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(text="Channel is not in AUTH_CHANNEL")


@StreamBot.on_message(filters.command('caption') & filters.private & CustomFilters.admin)
async def toggle_caption(bot: Client, message: Message):
    try:
        Telegram.USE_CAPTION = not Telegram.USE_CAPTION
        await message.reply_text(f"Now Bot Uses {'Caption' if Telegram.USE_CAPTION else 'Filename'}")
    except Exception as e:
        print(f"An error occurred: {e}")

@StreamBot.on_message(filters.command('tmdb') & filters.private & CustomFilters.admin)
async def toggle_tmdb(bot: Client, message: Message):
    try:
        Telegram.USE_TMDB = not Telegram.USE_TMDB
        await message.reply_text(f"Now Bot Uses {'TMDB' if Telegram.USE_TMDB else 'IMDB'}")
    except Exception as e:
        print(f"An error occurred: {e}")

@StreamBot.on_message(filters.command('set') & filters.private & CustomFilters.admin)
async def set_id(bot: Client, message: Message):

    url_part = message.text.split()[1:]  # Skip the command itself

    try:
        if len(url_part) == 1:

            Telegram.USE_DEFAULT_ID = url_part[0]  # Get the first element
            await message.reply_text(f"Now Bot Uses Default URL: {Telegram.USE_DEFAULT_ID}")
        else:
            # Remove the default ID
            Telegram.USE_DEFAULT_ID = None
            await message.reply_text("Removed default ID.")
    except Exception as e:
        await message.reply_text(f"An error occurred: {e}")

@StreamBot.on_message(filters.command("fsub") & filters.private & CustomFilters.admin)
async def set_fsub(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) < 2:
            return await message.reply_text("❌ Usage: `/fsub <channel_id/username>` or `/fsub off`")
        
        target = args[1]
        
        if target.lower() == "off":
            settings = await db.get_settings()
            settings["fsubChannel"] = None
            from Backend.helper.modal import SettingsSchema
            await db.update_settings(SettingsSchema(**settings))
            return await message.reply_text("✅ Force-Subscribe has been disabled.")

        # Check if bot is admin in the channel
        try:
            chat = await bot.get_chat(target)
            member = await bot.get_chat_member(chat.id, "me")
            if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                return await message.reply_text("❌ Bot is not an admin in this channel. Make me admin first!")
            
            # Update settings
            settings = await db.get_settings()
            settings["fsubChannel"] = str(chat.id) if chat.username is None else chat.username
            from Backend.helper.modal import SettingsSchema
            await db.update_settings(SettingsSchema(**settings))
            
            await message.reply_text(f"✅ Force-Subscribe successfully set to **{chat.title}** ({settings['fsubChannel']})")
            
        except Exception as e:
            await message.reply_text(f"❌ Error accesssing channel: {str(e)}")

    except Exception as e:
        LOGGER.error(f"Error in /fsub: {e}")
        await message.reply_text("❌ An internal error occurred.")





@StreamBot.on_message(filters.command("convert") & filters.private & CustomFilters.admin)
async def convert_link(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) < 2:
            return await message.reply_text("❌ Usage: `/convert <telegram_link>`")
        
        link = args[1]
        # Example: https://t.me/c/12345678/123 or https://t.me/channel/123
        parts = link.split("/")
        if len(parts) < 5:
            return await message.reply_text("❌ Invalid Telegram link format.")
            
        msg_id = int(parts[-1])
        chat_id_part = parts[-2]
        
        # Resolve chat_id if it's a private channel (starts with c/)
        if parts[-3] == "c":
            chat_id = int("-100" + chat_id_part)
        else:
            chat_id = chat_id_part
            
        # Get the message to find the file
        try:
            tg_msg = await bot.get_messages(chat_id, msg_id)
            if tg_msg.empty or not (tg_msg.document or tg_msg.video):
                return await message.reply_text("❌ No file found in that message.")
                
            file = tg_msg.document or tg_msg.video
            file_hash = file.file_unique_id[:6]
            
            # Search in database for this file
            # In movies
            movie = await db.movie_collection.find_one({"telegram.id": {"$regex": file_hash}})
            if movie:
                # Find the specific quality from the telegram array
                quality_detail = next((q for q in movie["telegram"] if file_hash in q["id"]), None)
                if quality_detail:
                    start_link = f"https://t.me/{(await bot.get_me()).username}?start=file_{movie['tmdb_id']}_{quality_detail['quality']}"
                    return await message.reply_text(f"✅ **Converted Link:**\n\n`{start_link}`")
            
            # In TV shows
            tv = await db.tv_collection.find_one({"seasons.episodes.telegram.id": {"$regex": file_hash}})
            if tv:
                for season in tv.get("seasons", []):
                    for episode in season.get("episodes", []):
                        quality_detail = next((q for q in episode.get("telegram", []) if file_hash in q["id"]), None)
                        if quality_detail:
                            if "episode_number" in episode:
                                start_link = f"https://t.me/{(await bot.get_me()).username}?start=file_{tv['tmdb_id']}_{season['season_number']}_{episode['episode_number']}_{quality_detail['quality']}"
                            else:
                                start_link = f"https://t.me/{(await bot.get_me()).username}?start=file_{tv['tmdb_id']}_{season['season_number']}_{quality_detail['quality']}"
                            return await message.reply_text(f"✅ **Converted Link:**\n\n`{start_link}`")
            
            return await message.reply_text("❌ File found but it's not linked in the database.")
            
        except Exception as e:
            return await message.reply_text(f"❌ Error fetching message: {str(e)}")

    except Exception as e:
        LOGGER.error(f"Error in /convert: {e}")
        await message.reply_text(f"❌ An error occurred: {str(e)}")

@StreamBot.on_message(filters.command('delete') & filters.private & CustomFilters.admin)
async def delete(bot: Client, message: Message):
    try:
        split_text = message.text.split()
        if len(split_text) != 2:
            return await message.reply_text("Use this format: /delete https://domain/ser/3123")
        
        url = split_text[1]
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.split('/')
        
        if len(path_parts) >= 3 and path_parts[-2] in ('ser', 'mov') and path_parts[-1].isdigit():
            media_type = path_parts[-2]
            if media_type == "ser": media_type = "tv"
            tmdb_id = path_parts[-1]
            delete = await db.delete_document(media_type, int(tmdb_id))
            if delete:
                return await message.reply_text(f"{media_type} with ID {tmdb_id} has been deleted successfully.")
            else:
                return await message.reply_text(f"ID {tmdb_id} wasn't found in the database.")
        else:
            return await message.reply_text("The URL format is incorrect.")
    
    except Exception as e:
        await message.reply_text(f"An error occurred: {str(e)}")

@StreamBot.on_message(filters.command("admin") & filters.private & CustomFilters.admin)
async def admin_panel(bot: Client, message: Message):
    try:
        total_movies = await db.movie_collection.count_documents({})
        total_tv = await db.tv_collection.count_documents({})
        total_unlinked = await db.manual_collection.count_documents({"is_linked": {"$ne": True}})
        
        text = (
            "<b>🎛 Admin Control Panel</b>\n\n"
            f"<b>🎬 Total Movies:</b> <code>{total_movies}</code>\n"
            f"<b>📺 Total TV Shows:</b> <code>{total_tv}</code>\n"
            f"<b>📁 Unlinked Files:</b> <code>{total_unlinked}</code>\n"
        )
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
             InlineKeyboardButton("📜 Logs", callback_data="admin_logs")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings"),
             InlineKeyboardButton("🔄 Restart", callback_data="admin_restart")]
        ])
        
        await message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        LOGGER.error(f"Error in /admin: {e}")
        await message.reply_text("❌ Failed to load admin panel.")

@StreamBot.on_callback_query()
async def callback_handler(bot: Client, query):
    if not await CustomFilters.admin_filter(bot, query):
        return await query.answer("❌ You are not an admin!", show_alert=True)
        
    data = query.data
    
    if data == "admin_stats":
        total_movies = await db.movie_collection.count_documents({})
        total_tv = await db.tv_collection.count_documents({})
        total_unlinked = await db.manual_collection.count_documents({"is_linked": {"$ne": True}})
        
        text = (
            "<b>📊 Detailed Statistics</b>\n\n"
            f"<b>🎥 Movies:</b> {total_movies}\n"
            f"<b>📺 TV Series:</b> {total_tv}\n"
            f"<b>📂 Orphan Files:</b> {total_unlinked}\n"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]]), parse_mode=ParseMode.HTML)
        
    elif data == "admin_logs":
        await query.answer("Sending logs...")
        path = ospath.abspath('log.txt')
        if ospath.exists(path):
            await bot.send_document(query.message.chat.id, path, caption="Current Log File")
        else:
            await query.answer("Log file not found!", show_alert=True)
            
    elif data == "admin_settings":
        text = "<b>⚙️ Bot Settings</b>\n\nToggle various bot features below:"
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"Caption: {'✅' if Telegram.USE_CAPTION else '❌'}", callback_data="toggle_caption")],
            [InlineKeyboardButton(f"TMDB/IMDB: {'TMDB' if Telegram.USE_TMDB else 'IMDB'}", callback_data="toggle_tmdb")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    elif data == "admin_restart":
        if not await CustomFilters.owner_filter(bot, query):
            return await query.answer("❌ Only owner can restart the bot!", show_alert=True)
        await query.answer("Restarting...")
        # Re-use existing restart logic
        await restart(bot, query.message)
        
    elif data == "admin_back":
        await admin_panel(bot, query.message)
        
    elif data == "toggle_caption":
        Telegram.USE_CAPTION = not Telegram.USE_CAPTION
        await callback_handler(bot, type('obj', (object,), {'data': 'admin_settings', 'message': query.message, 'answer': query.answer, 'edit_message_text': query.edit_message_text}))
        
    elif data == "toggle_tmdb":
        Telegram.USE_TMDB = not Telegram.USE_TMDB
        await callback_handler(bot, type('obj', (object,), {'data': 'admin_settings', 'message': query.message, 'answer': query.answer, 'edit_message_text': query.edit_message_text}))

@StreamBot.on_message(filters.command("add_admin") & filters.private & CustomFilters.owner)
async def add_admin(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 2:
            return await message.reply_text("❌ Usage: `/add_admin <user_id>`")
        
        user_id = int(args[1])
        if await db.add_bot_admin(user_id):
            await message.reply_text(f"✅ User ID `{user_id}` successfully added as bot administrator.")
        else:
            await message.reply_text("❌ Failed to add admin.")
    except ValueError:
        await message.reply_text("❌ User ID must be a number.")
    except Exception as e:
        LOGGER.error(f"Error in /add_admin: {e}")
        await message.reply_text(f"❌ An error occurred: {e}")

@StreamBot.on_message(filters.command("remove_admin") & filters.private & CustomFilters.owner)
async def remove_admin(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 2:
            return await message.reply_text("❌ Usage: `/remove_admin <user_id>`")
        
        user_id = int(args[1])
        if await db.remove_bot_admin(user_id):
            await message.reply_text(f"✅ User ID `{user_id}` removed from administrators.")
        else:
            await message.reply_text("❌ Failed to remove admin.")
    except ValueError:
        await message.reply_text("❌ User ID must be a number.")
    except Exception as e:
        LOGGER.error(f"Error in /remove_admin: {e}")
        await message.reply_text(f"❌ An error occurred: {e}")

@StreamBot.on_message(filters.command("admins") & filters.private & CustomFilters.owner)
async def list_admins(bot: Client, message: Message):
    try:
        admins = await db.get_bot_admins()
        if not admins:
            return await message.reply_text(f"👑 **Owner:** `{Telegram.OWNER_ID}`\n\nNo additional administrators added.")
        
        text = f"👑 **Owner:** `{Telegram.OWNER_ID}`\n\n"
        text += "👮 **Administrators:**\n"
        for uid in admins:
            text += f"- `{uid}`\n"
        
        await message.reply_text(text)
    except Exception as e:
        LOGGER.error(f"Error in /admins: {e}")
        await message.reply_text("❌ Failed to fetch admin list.")

