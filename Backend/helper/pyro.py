import pycountry
from pyrogram.file_id import FileId
from typing import Optional, Union, List, Tuple
from Backend.logger import LOGGER
from Backend import __version__, now, timezone
from Backend.config import Telegram
from Backend.helper.exceptions import FIleNotFound
from asyncio import create_subprocess_exec, create_subprocess_shell
from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, remove as aioremove
from asyncio.subprocess import PIPE
from pyrogram import Client
from Backend.pyrofork import StreamBot
import re

from pyrogram import enums


def is_media(message):
    return next((getattr(message, attr) for attr in ["document", "photo", "video", "audio", "voice", "video_note", "sticker", "animation"] if getattr(message, attr)), None)

async def get_file_ids(client: Client, chat_id: int, message_id: int) -> Optional[FileId]:
    chat_str = str(chat_id).strip()
    if not chat_str.startswith("-"):
        chat_id = int(f"-100{chat_str}")
    message = await client.get_messages(chat_id, message_id)
    if message.empty:
        raise FIleNotFound
    file_id = file_unique_id = None
    if media := is_media(message):
        file_id, file_unique_id = FileId.decode(
            media.file_id), media.file_unique_id
    setattr(file_id, 'file_name', getattr(media, 'file_name', ''))
    setattr(file_id, 'file_size', getattr(media, 'file_size', 0))
    setattr(file_id, 'mime_type', getattr(media, 'mime_type', ''))
    setattr(file_id, 'unique_id', file_unique_id)
    return file_id

def get_readable_file_size(size_in_bytes):
    size_in_bytes = int(size_in_bytes) if str(size_in_bytes).isdigit() else 0
    if not size_in_bytes:
        return '0B'
    index, SIZE_UNITS = 0, ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

    while size_in_bytes >= 1024 and index < len(SIZE_UNITS) - 1:
        size_in_bytes /= 1024
        index += 1
    return f'{size_in_bytes:.2f}{SIZE_UNITS[index]}' if index > 0 else f'{size_in_bytes:.2f}B'


def get_channel_id_pair(raw_id: Union[int, str]) -> Tuple[str, str]:
    """Return both ('-100...', '...') string forms of a Telegram channel/chat ID stripped of quotes."""
    cleaned = str(raw_id).strip().strip("'\"")
    digits = re.sub(r'^-?100', '', cleaned).lstrip('-')
    if not digits:
        return cleaned, cleaned
    return f"-100{digits}", digits


def clean_filename(filename):
    # Pattern to match any @value with optional surrounding symbols and spaces
    pattern = r'_@[A-Za-z0-9]+_|@[A-Za-z0-9]+_|[\[\]\s@]*@[^.\s\[\]]+[\]\[\s@]*'
    
    # Substitute the matched pattern with an empty string
    cleaned_filename = re.sub(pattern, '', filename)
    # Remove technical tags - much more aggressive
    tech_tags = r'org|AMZN|DDP|DD|NF|AAC|TVDL|5\.1|2\.1|2\.0|7\.0|7\.1|5\.0|~|\b\w+kbps\b|\bx264\b|\bx265\b|\b10bit\b|\bHEVC\b|\bHDRip\b|\bWebRip\b|\bWEB-DL\b|\bBlu-ray\b|\bTamil\b|\bTelugu\b|\bHindi\b|\bKannada\b|\bMalayalam\b|\bDual Audio\b|\bMulti Audio\b|\bHQ\b|\bESub\b|\bMSub\b|\b\d+MB\b|\b\d+GB\b|\bHEVC\b|\b10-bit\b'
    cleaned_filename = re.sub(rf'(?i)(?<=\W)({tech_tags})(?=\W)', '', cleaned_filename)
    
    # Remove emojis
    cleaned_filename = cleaned_filename.encode('ascii', 'ignore').decode('ascii')

    # Remove anything after common indicators of channel promotions
    promotional_indicators = [r'Download\s*:', r'Join\s*:', r'Uploaded\s*by', r'https?://', r't\.me']
    for indicator in promotional_indicators:
        cleaned_filename = re.split(indicator, cleaned_filename, flags=re.IGNORECASE)[0]

    # Remove non-filesystem-friendly characters
    cleaned_filename = re.sub(r'[^\w\s\.\-\(\)\[\]]', ' ', cleaned_filename)
    
    # Final cleanup of multiple spaces, dots and dashes
    cleaned_filename = re.sub(r'[\s\._\-]{2,}', ' ', cleaned_filename)
    cleaned_filename = re.sub(r'\s+', ' ', cleaned_filename).strip()
    return cleaned_filename



def get_readable_time(seconds: int) -> str:
    count = 0
    readable_time = ""
    time_list = []
    time_suffix_list = ["s", "m", "h", " days"]
    while count < 4:
        count += 1
        if count < 3:
            remainder, result = divmod(seconds, 60)
        else:
            remainder, result = divmod(seconds, 24)
        if seconds == 0 and remainder == 0:
            break
        time_list.append(int(result))
        seconds = int(remainder)
    for x in range(len(time_list)):
        time_list[x] = str(time_list[x]) + time_suffix_list[x]
    if len(time_list) == 4:
        readable_time += time_list.pop() + ", "
    time_list.reverse()
    readable_time += ": ".join(time_list)
    return readable_time



def extract_tmdb_id(url):
    # Match TMDB URLs
    tmdb_match = re.search(r'/(movie|tv)/(\d+)', url)
    if tmdb_match:
        return tmdb_match.group(2)  # Returns the TMDB ID

    # Match IMDb URLs
    imdb_match = re.search(r'/title/(tt\d+)', url)
    if imdb_match:
        return imdb_match.group(1)  # Returns the IMDb ID

    return None

def remove_urls(text):
    # Handle everything from normal text to encoded newlines
    text = text.replace('\\n', '\n').replace('%5Cn', '\n')
    
    # Remove lines containing common bot/channel promotion emojis or text
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        # skip if line contains links, bots, or promo indicators
        if re.search(r'https?://|t\.me/|@', line, re.I):
            continue
        # ignore lines that look like emojis or symbols only
        if len(re.sub(r'[^\w]', '', line)) <= 2:
            continue
        cleaned_lines.append(line)
    
    cleaned_text = ' '.join(cleaned_lines)
    # Strip emojis
    cleaned_text = cleaned_text.encode('ascii', 'ignore').decode('ascii')
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    return cleaned_text



def normalize_languages(language: Union[str, List[str]]) -> List[str]:
    """
    Normalize the language input(s) to a list of ISO 639-1 codes using pycountry and common mappings.
    """
    if not language:
        return []

    if isinstance(language, str):
        language = [language]

    # Pre-defined common mapping for Indian languages and variations
    common_map = {
        "tamil": "ta", "tam": "ta", "தமிழ்": "ta",
        "telugu": "te", "tel": "te", "తెలుగు": "te",
        "hindi": "hi", "hin": "hi", "हिन्दी": "hi",
        "malayalam": "ml", "mal": "ml", "മലയാളം": "ml",
        "kannada": "kn", "kan": "kn", "ಕನ್ನಡ": "kn",
        "english": "en", "eng": "en", "en-us": "en", "en-gb": "en",
        "bengali": "bn", "ben": "bn", "বাংলা": "bn",
        "marathi": "mr", "mar": "mr", "मराठी": "mr",
        "gujarati": "gu", "guj": "gu", "ગુજરાતી": "gu",
        "punjabi": "pa", "pun": "pa", "ਪੰਜਾਬੀ": "pa",
        "french": "fr", "fra": "fr", "fre": "fr",
        "spanish": "es", "spa": "es",
        "dual": "hi", # Common convention in some trackers for Hindi + English
        "multi": "hi",
        "jap": "ja", "japanese": "ja",
        "kor": "ko", "korean": "ko"
    }

    normalized_languages = []
    for lang in language:
        if not lang: continue
        lang_clean = lang.strip().lower()
        
        # Check common map first
        if lang_clean in common_map:
            normalized_languages.append(common_map[lang_clean])
            continue
            
        try:
            # Try exact alpha codes first for speed
            if len(lang_clean) == 2:
                match = pycountry.languages.get(alpha_2=lang_clean)
            elif len(lang_clean) == 3:
                match = pycountry.languages.get(alpha_3=lang_clean)
            else:
                # Try by name (case-insensitive search in pycountry can be tricky, so we check name)
                # pycountry's .get(name=...) is exact. We can iterate for fuzzy match if needed.
                match = None
                for l in pycountry.languages:
                    if hasattr(l, 'name') and l.name.lower() == lang_clean:
                        match = l
                        break
            
            if match:
                if hasattr(match, 'alpha_2'):
                    normalized_languages.append(match.alpha_2)
                elif hasattr(match, 'alpha_3'):
                    normalized_languages.append(match.alpha_3[:2])
            else:
                # Last resort: just keep first 2 letters if it looks like a code, but better to skip if unsure
                pass
        except Exception:
            pass

    return list(sorted(set(normalized_languages)))


async def cmd_exec(cmd, shell=False):
    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await proc.communicate()
    stdout = stdout.decode(errors='ignore').strip()
    stderr = stderr.decode(errors='ignore').strip()
    return stdout, stderr, proc.returncode



async def restart_notification():
    chat_id, msg_id = 0, 0

    try:
        # Check if the restart message file exists
        if await aiopath.exists(".restartmsg"):
            async with aiopen(".restartmsg", "r") as f:
                # Read the chat ID and message ID from the file
                data = await f.readlines()
                chat_id, msg_id = map(int, data)

            try:
                repo = Telegram.UPSTREAM_REPO.split('/')
                UPSTREAM_REPO = f"https://github.com/{repo[-2]}/{repo[-1]}"
                await StreamBot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"<blockquote>♻️ Restart Successfully...! \n\nDate: {now.strftime('%d/%m/%y')}\nTime: {now.strftime('%I:%M:%S %p')}\nTimeZone: {timezone.zone}\n\nRepo: {UPSTREAM_REPO}\nBranch: {Telegram.UPSTREAM_BRANCH}\nVersion: {__version__}</blockquote>",
                parse_mode=enums.ParseMode.HTML
            )

            except Exception as e:
                LOGGER.error(f"Failed to edit restart message: {e}")

            # Remove the restart message file
            await aioremove(".restartmsg")

    except Exception as e:
        LOGGER.error(f"Error in restart_notification: {e}")
