from shlex import split as ssplit
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, path as aiopath, mkdir
from os import path as ospath
from Backend.helper.pyro import cmd_exec
from Backend.pyrofork import StreamBot
from re import search as re_search
import json
from Backend.logger import LOGGER



async def get_media_quality(message=None):
    des_path = None
    try:
        if not message:
            return None
        media = message.video or message.document
        path = "Mediainfo/"
        if not await aiopath.isdir(path):
            await mkdir(path)
        des_path = ospath.join(path, media.file_name)

        async for chunk in StreamBot.stream_media(message, limit=1):

            async with aiopen(des_path, "ab") as f:
                await f.write(chunk)

        # Get mediainfo output
        stdout, stderr, code = await cmd_exec(ssplit(f'hachoir-metadata "{des_path}"'))
        if code != 0:
            raise RuntimeError(f"hachoir-metadata command failed: {stderr}")


        quality = parse_quality(stdout)

        return quality

    except Exception as e:
        LOGGER.error(f"Failed to get media quality: {e}")
        return None

    finally:
        if des_path and await aiopath.exists(des_path):
            try:
                await aioremove(des_path)
            except Exception as cleanup_error:
                LOGGER.warning(f"Failed to clean up {des_path}: {cleanup_error}")

async def get_media_languages(message=None):
    des_path = None
    try:
        if not message:
            return None
            
        media = message.video or message.document
        path = "Mediainfo/"
        if not await aiopath.isdir(path):
            await mkdir(path)
        des_path = ospath.join(path, media.file_name)

        # Download chunk if it doesn't already exist (stream.py deletes it though)
        if not await aiopath.exists(des_path):
            async for chunk in StreamBot.stream_media(message, limit=1):
                async with aiopen(des_path, "ab") as f:
                    await f.write(chunk)

        # Execute ffprobe to extract audio streams JSON with optimized parameters for speed
        command = f'ffprobe -v error -probesize 5000000 -analyzeduration 5000000 -select_streams a -show_entries stream=index:stream_tags=language -of json "{des_path}"'
        stdout, stderr, code = await cmd_exec(ssplit(command))
        
        if code != 0:
            if "No such file or directory" in stderr or "not found" in stderr.lower():
                LOGGER.error("ffprobe not found! Please install ffmpeg (sudo apt install ffmpeg)")
            else:
                LOGGER.error(f"ffprobe failed: {stderr}")
            return None

        # Parse JSON output to extract languages array
        probe_data = json.loads(stdout)
        streams = probe_data.get('streams', [])
        
        languages = []
        for stream in streams:
            tags = stream.get('tags', {})
            lang = tags.get('language')
            if lang and lang.lower() not in ['und', 'unknown']:
                languages.append(lang.lower())
                
        # Deduplicate while preserving order
        unique_langs = list(dict.fromkeys(languages))
        
        if unique_langs:
            return unique_langs
        return None

    except Exception as e:
        LOGGER.error(f"Error parsing media languages: {e}")
        return None
    finally:
        if des_path and await aiopath.exists(des_path):
            try:
                await aioremove(des_path)
            except Exception as cleanup_error:
                LOGGER.warning(f"Failed to clean up {des_path}: {cleanup_error}")

def parse_quality(stdout):

    for line in stdout.split('\n'):

        if "Image height" in line:
            match = re_search(r'(\d+)', line)  
            if match:
                height = int(match.group())

                quality = f"{360 if height <= 360 else 480 if height <= 480 else 540 if height <= 540 else 720 if height <= 720 else 1080 if height <= 1080 else 2160 if height <= 2160 else 4320 if height <= 4320 else 8640}p"
                return quality
    return None

