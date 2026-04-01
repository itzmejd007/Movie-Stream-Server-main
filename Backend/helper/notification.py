from Backend.config import Telegram
from Backend import db
from Backend.pyrofork import StreamBot
from pyrogram.enums import ParseMode
from Backend.logger import LOGGER

async def send_log_report(metadata_info, mode="Automatic"):
    """
    Sends a two-part log report to the configured log channel.
    """
    settings = await db.get_settings()
    log_channel = settings.get("logChannel") or Telegram.REPORT_CHANNEL
    
    if not log_channel:
        LOGGER.warning("No log channel configured for notifications.")
        return

    try:
        title = metadata_info.get("title")
        year = metadata_info.get("year")
        rate = metadata_info.get("rate", 0)
        genres = ", ".join(metadata_info.get("genres", []))
        tmdb_id = metadata_info.get("tmdb_id")
        media_type = metadata_info.get("media_type")
        poster = metadata_info.get("poster")
        
        # Determine the link based on media type
        path_type = "mov" if media_type == "movie" else "ser"
        movie_link = f"{Telegram.FRONTEND_LINK}/{path_type}/{tmdb_id}"

        # Message 1: Upload Details
        # For simplicity in 'number of files', we assume 1 since it's per-file addition
        # If it's a bulk link, the caller might need to handle it differently, 
        # but for individual additions, this works.
        msg1 = (
            f"<b>📁 New File Added</b>\n\n"
            f"<b>🆔 ID:</b> <code>{tmdb_id}</code>\n"
            f"<b>📝 Caption:</b> <code>{title}</code>\n"
            f"<b>🚀 Mode:</b> <code>{mode}</code>"
        )
        
        # Message 2: Movie Info
        msg2 = (
            f"<b>🎬 {title} ({year})</b>\n\n"
            f"<b>⭐ Rating:</b> {rate}\n"
            f"<b>🎭 Genres:</b> {genres}\n\n"
            f"<b>🔗 Link:</b> {movie_link}"
        )

        # Send Message 1
        await StreamBot.send_message(
            chat_id=log_channel,
            text=msg1,
            parse_mode=ParseMode.HTML
        )

        # Send Message 2 with photo (poster) if available
        if poster:
            await StreamBot.send_photo(
                chat_id=log_channel,
                photo=poster,
                caption=msg2,
                parse_mode=ParseMode.HTML
            )
        else:
            await StreamBot.send_message(
                chat_id=log_channel,
                text=msg2,
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        LOGGER.error(f"Error sending log report: {e}")

async def send_bulk_log_report(metadata_info, file_count, mode="Manual Bulk"):
    """
    Sends a summary report for bulk additions.
    """
    settings = await db.get_settings()
    log_channel = settings.get("logChannel") or Telegram.REPORT_CHANNEL
    
    if not log_channel:
        return

    try:
        title = metadata_info.get("title")
        tmdb_id = metadata_info.get("tmdb_id")
        media_type = metadata_info.get("media_type")
        
        path_type = "mov" if media_type == "movie" else "ser"
        movie_link = f"{Telegram.FRONTEND_LINK}/{path_type}/{tmdb_id}"

        msg1 = (
            f"<b>📦 Bulk Addition Complete</b>\n\n"
            f"<b>🔢 Number of Files:</b> <code>{file_count}</code>\n"
            f"<b>🆔 ID:</b> <code>{tmdb_id}</code>\n"
            f"<b>📝 Title:</b> <code>{title}</code>\n"
            f"<b>🚀 Mode:</b> <code>{mode}</code>"
        )
        
        await StreamBot.send_message(
            chat_id=log_channel,
            text=msg1,
            parse_mode=ParseMode.HTML
        )
        
        # We can also send the standard info message
        await send_log_report(metadata_info, mode=mode)

    except Exception as e:
        LOGGER.error(f"Error sending bulk log report: {e}")
