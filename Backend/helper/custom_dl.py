import asyncio
from typing import Dict, Union, Optional
from pyrogram import utils, raw, Client
from pyrogram.errors import AuthBytesInvalid, FloodWait
try:
    from pyrogram.errors import FileReferenceExpired
except ImportError:
    class FileReferenceExpired(Exception):
        pass
from pyrogram.file_id import FileId, FileType, ThumbnailSource
from pyrogram.session import Session, Auth
from Backend.logger import LOGGER
from Backend.helper.exceptions import FIleNotFound
from Backend.helper.pyro import get_file_ids
from Backend.pyrofork import work_loads


class ByteStreamer:
    def __init__(self, client: Client):
        self.clean_timer = 30 * 60
        self.client: Client = client
        self.__cached_file_ids: Dict[int, FileId] = {}
        asyncio.create_task(self.clean_cache())

    async def get_file_properties(self, chat_id: int, message_id: int) -> FileId:
        if message_id not in self.__cached_file_ids:
            file_id = await get_file_ids(self.client, int(chat_id), int(message_id))
            if not file_id:
                LOGGER.info('Message with ID %s not found!', message_id)
                raise FIleNotFound
            self.__cached_file_ids[message_id] = file_id
        return self.__cached_file_ids[message_id]

    async def get_or_create_media_session(self, client: Client, file_id: FileId) -> Session:
        """Fetch an existing active media session or establish a new connected one."""
        media_session = client.media_sessions.get(file_id.dc_id, None)
        if media_session is not None and not getattr(media_session, "is_connected", True):
            LOGGER.info(f"Media session for DC {file_id.dc_id} is disconnected. Resetting...")
            try:
                await media_session.stop()
            except Exception:
                pass
            client.media_sessions.pop(file_id.dc_id, None)
            media_session = None

        if media_session is None:
            media_session = await self.generate_media_session(client, file_id)
        return media_session

    async def yield_file(
        self,
        file_id: FileId,
        index: int,
        offset: int,
        first_part_cut: int,
        last_part_cut: int,
        part_count: int,
        chunk_size: int,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None
    ):
        """
        Stream or download file chunks from Telegram MTProto using an asynchronous
        producer-consumer queue (prefetching 3 chunks). Includes exponential backoff,
        session renewal, and retry logic to prevent stream stalls.
        """
        client = self.client
        work_loads[index] += 1
        LOGGER.info(f"Starting file stream/download on client {index}. Total parts: {part_count}, Offset: {offset}, Chunk size: {chunk_size}")

        queue = asyncio.Queue(maxsize=3)
        stop_event = asyncio.Event()

        async def producer():
            curr_offset = offset
            curr_part = 1
            curr_file_id = file_id
            location = await self.get_location(curr_file_id)
            media_session = await self.get_or_create_media_session(client, curr_file_id)

            try:
                while curr_part <= part_count and not stop_event.is_set():
                    chunk_bytes = None
                    max_retries = 6

                    for attempt in range(max_retries):
                        if stop_event.is_set():
                            break
                        try:
                            if not getattr(media_session, "is_connected", True):
                                media_session = await self.get_or_create_media_session(client, curr_file_id)

                            r = await asyncio.wait_for(
                                media_session.send(
                                    raw.functions.upload.GetFile(
                                        location=location,
                                        offset=curr_offset,
                                        limit=chunk_size
                                    )
                                ),
                                timeout=25.0
                            )

                            if isinstance(r, raw.types.upload.File):
                                chunk_bytes = r.bytes
                                break
                            elif isinstance(r, raw.types.upload.FileCdnRedirect):
                                LOGGER.warning(f"Telegram returned FileCdnRedirect for part {curr_part}")
                                break
                            else:
                                LOGGER.warning(f"Unexpected response type {type(r)} at part {curr_part}")
                        except FloodWait as e:
                            LOGGER.warning(f"Telegram FloodWait of {e.value}s at part {curr_part}/{part_count}")
                            await asyncio.sleep(e.value + 1)
                        except FileReferenceExpired:
                            LOGGER.warning(f"FileReferenceExpired at part {curr_part}. Refreshing file location...")
                            if chat_id and message_id:
                                try:
                                    curr_file_id = await get_file_ids(client, int(chat_id), int(message_id))
                                    location = await self.get_location(curr_file_id)
                                    self.__cached_file_ids[message_id] = curr_file_id
                                except Exception as ref_err:
                                    LOGGER.error(f"Failed to refresh file_id: {ref_err}")
                            await asyncio.sleep(1)
                        except (asyncio.TimeoutError, TimeoutError):
                            LOGGER.warning(f"Timeout fetching part {curr_part}/{part_count} (attempt {attempt + 1}/{max_retries})")
                            await asyncio.sleep(0.5 * (attempt + 1))
                        except (OSError, ConnectionError, AttributeError) as e:
                            LOGGER.warning(f"Connection issue at part {curr_part}/{part_count}: {e}. Reconnecting session...")
                            try:
                                client.media_sessions.pop(curr_file_id.dc_id, None)
                                media_session = await self.generate_media_session(client, curr_file_id)
                            except Exception:
                                pass
                            await asyncio.sleep(1.0)
                        except Exception as e:
                            LOGGER.error(f"Error fetching part {curr_part}/{part_count} (attempt {attempt + 1}/{max_retries}): {e}")
                            await asyncio.sleep(1.0)

                    if chunk_bytes is None:
                        LOGGER.error(f"Failed to retrieve part {curr_part}/{part_count} after {max_retries} retries. Ending stream.")
                        break

                    if not chunk_bytes:
                        break

                    # Slicing chunk accurately according to range request
                    if part_count == 1:
                        yield_data = chunk_bytes[first_part_cut:last_part_cut]
                    elif curr_part == 1:
                        yield_data = chunk_bytes[first_part_cut:]
                    elif curr_part == part_count:
                        yield_data = chunk_bytes[:last_part_cut]
                    else:
                        yield_data = chunk_bytes

                    await queue.put(yield_data)
                    curr_part += 1
                    curr_offset += chunk_size

            except Exception as e:
                LOGGER.error(f"Unexpected error in stream producer: {e}")
            finally:
                await queue.put(None)

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            stop_event.set()
            producer_task.cancel()
            try:
                await producer_task
            except (asyncio.CancelledError, Exception):
                pass
            LOGGER.info(f"Finished yielding file stream for client {index}.")
            work_loads[index] = max(0, work_loads[index] - 1)

    async def generate_media_session(self, client: Client, file_id: FileId) -> Session:
        media_session = client.media_sessions.get(file_id.dc_id, None)
        if media_session is None:
            if file_id.dc_id != await client.storage.dc_id():
                media_session = Session(
                    client,
                    file_id.dc_id,
                    await Auth(client, file_id.dc_id, await client.storage.test_mode()).create(),
                    await client.storage.test_mode(),
                    is_media=True,
                )
                await media_session.start()
                for _ in range(6):
                    exported_auth = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=file_id.dc_id))
                    try:
                        await media_session.send(raw.functions.auth.ImportAuthorization(id=exported_auth.id, bytes=exported_auth.bytes))
                        break
                    except AuthBytesInvalid:
                        LOGGER.debug(f"Invalid authorization bytes for DC {file_id.dc_id}, retrying...")
                    except OSError:
                        LOGGER.debug(f"Connection error, retrying...")
                        await asyncio.sleep(2)
                else:
                    await media_session.stop()
                    LOGGER.debug(f"Failed to establish media session for DC {file_id.dc_id} after multiple retries")
                    return None 
            else:
                media_session = Session(
                    client,
                    file_id.dc_id,
                    await client.storage.auth_key(),
                    await client.storage.test_mode(),
                    is_media=True,
                )
                await media_session.start()
            LOGGER.debug(f"Created media session for DC {file_id.dc_id}")
            client.media_sessions[file_id.dc_id] = media_session
        else:
            LOGGER.debug(f"Using cached media session for DC {file_id.dc_id}")
        return media_session


    @staticmethod
    async def get_location(file_id: FileId) -> Union[raw.types.InputPhotoFileLocation, raw.types.InputDocumentFileLocation, raw.types.InputPeerPhotoFileLocation]:
        file_type = file_id.file_type
        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=file_id.chat_id, access_hash=file_id.chat_access_hash)
            else:
                if file_id.chat_access_hash == 0:
                    peer = raw.types.InputPeerChat(chat_id=-file_id.chat_id)
                else:
                    peer = raw.types.InputPeerChannel(channel_id=utils.get_channel_id(
                        file_id.chat_id), access_hash=file_id.chat_access_hash)
            location = raw.types.InputPeerPhotoFileLocation(peer=peer,
                                                            volume_id=file_id.volume_id,
                                                            local_id=file_id.local_id,
                                                            big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG)
        elif file_type == FileType.PHOTO:
            location = raw.types.InputPhotoFileLocation(id=file_id.media_id,
                                                        access_hash=file_id.access_hash,
                                                        file_reference=file_id.file_reference,
                                                        thumb_size=file_id.thumbnail_size)
        else:
            location = raw.types.InputDocumentFileLocation(id=file_id.media_id,
                                                           access_hash=file_id.access_hash,
                                                           file_reference=file_id.file_reference,
                                                           thumb_size=file_id.thumbnail_size)
        return location

    async def clean_cache(self) -> None:
        """
        function to clean the cache to reduce memory usage
        """
        while True:
            await asyncio.sleep(self.clean_timer)
            self.__cached_file_ids.clear()
            LOGGER.debug("Cleaned the cache")
