from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

class AdminUI:
    @staticmethod
    def back_button(callback_data: str):
        return [InlineKeyboardButton("⬅️ Back", callback_data=callback_data)]

    @staticmethod
    def home_button():
        return [InlineKeyboardButton("🏠 Main Menu", callback_data="admin_main")]

    @staticmethod
    def close_button():
        return [InlineKeyboardButton("❌ Close", callback_data="admin_close")]

    @staticmethod
    def paginate_buttons(current_page: int, total_pages: int, prefix: str):
        buttons = []
        if current_page > 1:
            buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}_{current_page - 1}"))
        if current_page < total_pages:
            buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}_{current_page + 1}"))
        return buttons

def format_stats(stats: dict):
    return (
        "<b>📊 System Statistics</b>\n\n"
        f"🎬 <b>Movies:</b> <code>{stats.get('movies', 0)}</code>\n"
        f"📺 <b>TV Shows:</b> <code>{stats.get('tv_shows', 0)}</code>\n"
        f"📁 <b>Unlinked Files:</b> <code>{stats.get('manual_files', 0)}</code>\n\n"
        f"📈 <b>Today's Views:</b> <code>{stats.get('today_views', 0)}</code>\n"
        f"📉 <b>Yesterday's Views:</b> <code>{stats.get('yesterday_views', 0)}</code>\n"
        f"📅 <b>Monthly Views:</b> <code>{stats.get('monthly_views', 0)}</code>\n"
        f"🌍 <b>Total Views:</b> <code>{stats.get('total_views', 0)}</code>"
    )
