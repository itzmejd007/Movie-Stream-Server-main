from os import getenv
import re
from datetime import datetime, timedelta
from time import time
from typing import Any, Dict, List, Optional, Union, Tuple
from Backend.helper.encrypt import decode_string
from fastapi import FastAPI, Query, Request, HTTPException
from pydantic import ValidationError
from passlib.context import CryptContext

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

from fastapi.responses import StreamingResponse, HTMLResponse
import urllib.parse
from urllib.parse import quote
from fastapi.templating import Jinja2Templates

import mimetypes
import secrets
import math
import json

from Backend.logger import LOGGER
from Backend.config import Telegram
from Backend.pyrofork import StreamBot, work_loads, multi_clients
from Backend.helper.exceptions import InvalidHash
from Backend.helper.custom_dl import ByteStreamer
from fastapi.middleware.cors import CORSMiddleware
from Backend.helper.pyro import get_readable_time, normalize_languages, get_channel_id_pair, remove_urls, clean_filename, get_readable_file_size
from Backend.helper.modal import SettingsSchema, MovieSchema, TVShowSchema
from Backend import StartTime, __version__, db
from Backend.helper.metadata import search_tmdb, search_imdb, get_external_details, fetch_movie_metadata, metadata as get_media_metadata
from Backend.helper.notification import send_log_report, send_bulk_log_report
import PTN
from bson import ObjectId


app = FastAPI()
class_cache = {}

templates = Jinja2Templates(directory="Backend/fastapi/templates")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




@app.get("/api/ping")
async def ping():
    return {"ping": "pong", "version": __version__, "db": str(db.db_name)}

@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Movie-Stream-Server",
        "version": __version__,
        "uptime": get_readable_time(time() - StartTime),
        "db": str(getattr(db, "db_name", "connected"))
    }

@app.get("/", response_model=Dict[str, Any])
async def get_bot_workloads():
    """
    Home route to list each bot's workload and total number of bots.
    """
    response = {
            "server_status": "running",
            "uptime": get_readable_time(time() - StartTime),
            "telegram_bot": "@" + StreamBot.username,
            "connected_bots": len(multi_clients),
            "loads": dict(
                ("bot" + str(c + 1), l)
                for c, (_, l) in enumerate(
                    sorted(work_loads.items(), key=lambda x: x[1], reverse=True)
                )
            ),
            "version": __version__,
        }
    return response



@app.get("/is_member")
async def is_member(user_id: int, channel: int):
    try:
        member = await StreamBot.get_chat_member(channel, user_id)
        if member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return {"is_member": True}
        else:
            return {"is_member": False}
    except Exception as e:
        return {"is_member": False}


@app.get("/watch/{tmdb_id}", response_class=HTMLResponse)
async def watch(
    request: Request, 
    tmdb_id: int, 
    season_number: Optional[int] = Query(None), 
    episode_number: Optional[int] = Query(None)
):
    """
    Serve the appropriate HTML template for watching a movie or a specific TV episode.

    :param request: The incoming HTTP request.
    :param tmdb_id: The TMDB ID of the movie or TV show.
    :param season_number: The season number (optional, only for TV shows).
    :param episode_number: The episode number (optional, only for TV shows).
    :return: The rendered HTML template.
    """

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "id": tmdb_id, 
            "season": season_number, 
            "episode": episode_number
        }
    )



@app.get("/api/tvshows", response_model=dict)
async def get_sorted_tv_shows(
    sort_by: List[str] = Query(default=["rating:desc"], description="List of fields to sort by. Format: field:direction"),
    page: int = Query(default=1, ge=1, description="Page number to return"),
    page_size: int = Query(default=10, ge=1, description="Number of TV shows per page"),
    genre: Optional[str] = Query(default=None, description="Optional genre to filter by"),
    year: Optional[str] = Query(default=None, description="Optional release year to filter by"),
    audio: Optional[str] = Query(default=None, description="Optional audio language to filter by")
):
    try:
        sort_params = [tuple(param.split(":")) for param in sort_by]
        sorted_tv_shows = await db.sort_tv_shows(sort_params, page, page_size, genre, year, audio)
        return sorted_tv_shows
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/tvs", response_model=dict)
async def get_sorted_tvs(
    sort_by: List[str] = Query(default=["rating:desc"]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1),
    genre: Optional[str] = Query(default=None),
    year: Optional[str] = Query(default=None),
    audio: Optional[str] = Query(default=None)
):
    return await get_sorted_tv_shows(sort_by, page, page_size, genre, year, audio)

@app.get("/api/movies", response_model=dict)
async def get_sorted_movies(
    sort_by: List[str] = Query(default=["rating:desc"], description="List of fields to sort by. Format: field:direction"),
    page: int = Query(default=1, ge=1, description="Page number to return"),
    page_size: int = Query(default=10, ge=1, description="Number of movies per page"),
    genre: Optional[str] = Query(default=None, description="Optional genre to filter by"),
    year: Optional[str] = Query(default=None, description="Optional release year to filter by"),
    audio: Optional[str] = Query(default=None, description="Optional audio language to filter by")
):
    try:
        sort_params = [tuple(param.split(":")) for param in sort_by]
        sorted_movies = await db.sort_movies(sort_params, page, page_size, genre, year, audio)
        return sorted_movies
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/movies/stream")
async def stream_movies(
    sort_by: Union[List[str], str] = Query(default="updated_on:desc"),
    genre: Optional[str] = Query(default=None),
    year: Optional[str] = Query(default=None),
    audio: Optional[str] = Query(default=None),
    limit: int = Query(default=60)
):
    try:
        if isinstance(sort_by, str):
            sort_params = [tuple(sort_by.split(":"))]
        else:
            sort_params = [tuple(p.split(":")) for p in sort_by]
            
        res = await db.sort_movies(sort_params, page=1, page_size=limit, genre=genre, year=year, audio=audio)
        movies = res.get("movies", [])
        
        async def generator():
            for m in movies:
                data = m if isinstance(m, dict) else m.dict()
                yield json.dumps(data, default=str) + "\n"
                
        return StreamingResponse(generator(), media_type="application/x-ndjson")
    except Exception as e:
        LOGGER.error(f"Error in stream_movies: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tvshows/stream")
async def stream_tvshows(
    sort_by: Union[List[str], str] = Query(default="updated_on:desc"),
    genre: Optional[str] = Query(default=None),
    year: Optional[str] = Query(default=None),
    audio: Optional[str] = Query(default=None),
    limit: int = Query(default=60)
):
    try:
        if isinstance(sort_by, str):
            sort_params = [tuple(sort_by.split(":"))]
        else:
            sort_params = [tuple(p.split(":")) for p in sort_by]
            
        res = await db.sort_tv_shows(sort_params, page=1, page_size=limit, genre=genre, year=year, audio=audio)
        tv_shows = res.get("tv_shows", [])
        
        async def generator():
            for t in tv_shows:
                data = t if isinstance(t, dict) else t.dict()
                data["media_type"] = "tv"
                yield json.dumps(data, default=str) + "\n"
                
        return StreamingResponse(generator(), media_type="application/x-ndjson")
    except Exception as e:
        LOGGER.error(f"Error in stream_tvshows: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/trending", response_model=dict)
async def get_trending_media(
    page: int = Query(default=1, ge=1, description="Page number to return"),
    page_size: int = Query(default=10, ge=1, description="Number of items per page")
):
    try:
        trending_media = await db.get_trending_media(page, page_size)
        return trending_media
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/view/{media_type}/{tmdb_id}")
async def increment_media_view(request: Request, media_type: str, tmdb_id: Union[int, str]):
    try:
        client_ip = request.client.host
        success = await db.increment_view(media_type, tmdb_id, identifier=client_ip)
        if success:
            return {"message": "View incremented"}
        else:
            return {"message": "View already counted or media not found"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/settings", response_model=dict)
async def get_site_settings():
    try:
        settings = await db.get_settings()
        return settings
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/settings")
async def update_site_settings(settings: SettingsSchema):
    try:
        success = await db.update_settings(settings)
        if success:
            return {"message": "Settings updated globally"}
        else:
            raise HTTPException(status_code=500, detail="Failed to update settings")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/admin/analytics")
async def admin_analytics(period: str = Query("week")):
    try:
        stats = await db.get_analytics()
        graph_data = await db.get_view_graph_data(period)
        return {**stats, "graph_data": graph_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/manual/sync")
async def admin_sync_manual_files():
    """Verify manual files exist on Telegram and remove deleted ones."""
    files = await db.manual_collection.find({"is_linked": {"$ne": True}}).to_list(None)
    
    deleted_count = 0
    # Group by chat_id for efficiency
    chat_groups = {}
    for f in files:
        cid = f["chat_id"]
        if cid not in chat_groups: chat_groups[cid] = []
        chat_groups[cid].append(f)

    for cid, g_files in chat_groups.items():
        # Telegram chat_id usually starts with -100 for channels
        actual_chat_id = int(f"-100{cid}")
        msg_ids = [f["msg_id"] for f in g_files]
        
        # Batch get messages
        for i in range(0, len(msg_ids), 200):
            batch_ids = msg_ids[i:i+200]
            try:
                tg_msgs = await StreamBot.get_messages(actual_chat_id, batch_ids)
                if not isinstance(tg_msgs, list): tg_msgs = [tg_msgs]
                
                for idx, msg in enumerate(tg_msgs):
                    if i+idx >= len(g_files): break
                    if msg.empty or not (msg.video or msg.document):
                        await db.delete_manual_file(str(g_files[i+idx]["_id"]))
                        deleted_count += 1
            except Exception as e:
                LOGGER.error(f"Sync error for chat {cid}: {e}")

    return {"message": f"Sync complete. Removed {deleted_count} stale files."}
 
# --- Home Sections Endpoints ---
@app.get("/api/home-sections")
async def get_home_sections_endpoint():
    try:
        sections = await db.get_home_sections()
        return sections
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/home-sections")
async def create_home_section_endpoint(request: Request):
    try:
        data = await request.json()
        new_sec = await db.create_home_section(data)
        return new_sec
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/home-sections/{section_id}")
async def update_home_section_endpoint(section_id: str, request: Request):
    try:
        data = await request.json()
        success = await db.update_home_section(section_id, data)
        if success:
            return {"message": "Section updated"}
        raise HTTPException(status_code=404, detail="Section not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/home-sections/{section_id}")
async def delete_home_section_endpoint(section_id: str):
    try:
        success = await db.delete_home_section(section_id)
        if success:
            return {"message": "Section deleted"}
        raise HTTPException(status_code=404, detail="Section not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/home-sections/reorder")
async def reorder_home_sections_endpoint(request: Request):
    try:
        body = await request.json()
        section_ids = body.get("section_ids", [])
        success = await db.reorder_home_sections(section_ids)
        if success:
            return {"message": "Order updated"}
        raise HTTPException(status_code=400, detail="Failed to reorder")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/home-sections/{section_id}/items")
async def get_home_section_items_endpoint(section_id: str):
    try:
        items = await db.get_home_section_items(section_id)
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#Homepage:------
# hero = http://localhost:8000/api/tvshows?sort_by=rating:desc&sort_by=release_year:desc&page=1&page_size=10
# latest movies = http://localhost:8000/api/movies?sort_by=updated_on:desc&page=1&page_size=20
# latest tvshows = http://localhost:8000/api/tvshows?sort_by=updated_on:desc&page=1&page_size=20

#Movies:----------
# latest movies = http://localhost:8000/api/movies?sort_by=updated_on:desc&page=1&page_size=40

#Tvshow:----------
# latest tvshows = http://localhost:8000/api/tvshows?sort_by=updated_on:desc&page=1&page_size=40



@app.get("/api/id/{tmdb_id}", response_model=dict)
async def get_media_details(
    tmdb_id: str, 
    season_number: Optional[int] = Query(None), 
    episode_number: Optional[int] = Query(None),
    title: Optional[str] = Query(None),
    slug: Optional[str] = Query(None)
) -> Union[dict, None]:
    tmdb_id_val = int(tmdb_id) if tmdb_id.isdigit() else tmdb_id
    search_title = slug or title
    details = await db.get_media_details(
        tmdb_id=tmdb_id_val, 
        season_number=season_number, 
        episode_number=episode_number,
        title=search_title
    )

    if not details:
        raise HTTPException(status_code=404, detail="Requested details not found")
    
    return details



@app.get("/api/similar/")
async def get_similar_media(
    tmdb_id: int,
    media_type: str = Query(..., pattern="^(movie|tvshow)$"),
    page: int = Query(default=1, ge=1, description="Page number to return"),
    page_size: int = Query(default=10, ge=1, description="Number of similar media per page")
):
    """
    FastAPI endpoint to get similar movies or TV shows based on the parent tmdb_id, sorted by the number of genre matches and rating.
    
    :param tmdb_id: The TMDB ID of the parent movie or TV show.
    :param media_type: The media type ('movie' or 'tvshow').
    :param page: The page number to return.
    :param page_size: The number of similar media per page.
    :return: A dictionary containing the total count and a list of similar movies or TV shows.
    """
    similar_media = await db.find_similar_media(tmdb_id=tmdb_id, media_type=media_type, page=page, page_size=page_size)
    return similar_media


# moviepage = http://127.0.0.1:8000/api/similar/?tmdb_id=695962&media_type=movie&limit=10
# similar movie tab = http://127.0.0.1:8000/api/similar/?tmdb_id=695962&media_type=movie&limit=40

# tvshowpage = http://127.0.0.1:8000/api/similar/?tmdb_id=695962&media_type=tvshow&limit=10
# similar tvshow tab = http://127.0.0.1:8000/api/similar/?tmdb_id=695962&media_type=tvshow&limit=40



@app.get("/api/search/", response_model=dict)
async def search_documents_endpoint(
    query: str = Query(..., description="Search query string"),
    page: int = Query(default=1, ge=1, description="Page number to return"),
    page_size: int = Query(default=10, ge=1, description="Number of documents per page")
):
    """
    FastAPI endpoint to search documents by title across TV and Movie collections,
    with pagination and total count.

    :param query: The search query string.
    :param page: The page number to return.
    :param page_size: The number of documents per page.
    :return: A dictionary containing the total count and a list of search results.
    """
    try:
        search_results = await db.search_documents(query=query, page=page, page_size=page_size)
        return search_results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# search popup = http://127.0.0.1:8000/api/search/?query=the%20boys&page=1&page_size=10
# search tab = http://127.0.0.1:8000/api/search/?query=the%20boys&page=1&page_size=40

@app.get('/download/{id}/{name}')
async def download_handler(request: Request, id: str, name: str):
    decoded_data = await decode_string(id)
    if not decoded_data.get('msg_id') or not decoded_data.get('hash'):
        raise HTTPException(status_code=400, detail="Missing id or hash")
    raw_cid = str(decoded_data['chat_id'])
    chat_id = int(raw_cid) if raw_cid.startswith("-") else int(f"-100{raw_cid}")
    return await media_streamer(request, chat_id, int(decoded_data['msg_id']), decoded_data['hash'], download=True)


@app.get('/stream/{id}/{name}')
async def stream_handler(request: Request, id: str, name: str):
    decoded_data = await decode_string(id)
    if not decoded_data.get('msg_id') or not decoded_data.get('hash'):
        raise HTTPException(status_code=400, detail="Missing id or hash")
    raw_cid = str(decoded_data['chat_id'])
    chat_id = int(raw_cid) if raw_cid.startswith("-") else int(f"-100{raw_cid}")
    return await media_streamer(request, chat_id, int(decoded_data['msg_id']), decoded_data['hash'])

@app.get('/dl/{id}/{name}')
async def dl_handler(request: Request, id: str, name: str):
    return await stream_handler(request, id, name)



async def media_streamer(request: Request, chat_id: int, msg_id: int, secure_hash: str, download: bool = False):
    range_header = request.headers.get("Range")
    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]
    if Telegram.MULTI_CLIENT:
        LOGGER.debug(f"Client {index} is now serving {request.client.host}")
    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        LOGGER.debug(f"Using cached ByteStreamer object for client {index}")
    else:
        LOGGER.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
    try:
        file_id = await tg_connect.get_file_properties(chat_id=chat_id, message_id=msg_id)
    except Exception as e:
        LOGGER.warning(f"Error getting file properties for msg {msg_id}: {e}. Retrying with fresh fetch...")
        try:
            tg_connect._ByteStreamer__cached_file_ids.pop(msg_id, None)
            file_id = await tg_connect.get_file_properties(chat_id=chat_id, message_id=msg_id)
        except Exception as retry_err:
            LOGGER.error(f"Failed to get file properties on retry for msg {msg_id}: {retry_err}")
            raise HTTPException(status_code=404, detail="Media file not found or expired on Telegram storage")

    if file_id.unique_id[:6] != secure_hash:
        LOGGER.debug(f"Invalid hash for message with ID {msg_id}")
        raise InvalidHash
    file_size = file_id.file_size
    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = 0
        until_bytes = file_size - 1
    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return StreamingResponse(
            content=(f"416: Range not satisfiable",),
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    # 1MB chunk size ensures highest speed & throughput on Telegram MTProto
    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1

    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil((until_bytes - offset + 1) / chunk_size)
    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size, chat_id=chat_id, message_id=msg_id
    )
    mime_type = file_id.mime_type
    file_name = file_id.file_name
    disposition = "inline"

    if mime_type:
        if not file_name:
            try:
                file_name = f"{secrets.token_hex(2)}.{mime_type.split('/')[1]}"
            except (IndexError, AttributeError):
                file_name = f"{secrets.token_hex(2)}.unknown"
    else:
        if file_name:
            mime_type = mimetypes.guess_type(file_name)[0]
        else:
            mime_type = "application/octet-stream"
    if download:
        mime_type = "application/octet-stream"
    else:
        fn_lower = (file_name or "").lower()
        if fn_lower.endswith(".webm"):
            mime_type = "video/webm"
        elif fn_lower.endswith((".mp4", ".mkv", ".m4v", ".ts", ".avi")):
            mime_type = "video/mp4"
        elif not mime_type or not mime_type.startswith("video/"):
            mime_type = "video/mp4"

    LOGGER.info(f"{mime_type}, {file_name}, {disposition}")
    headers = {
        "Connection": "keep-alive",
        "Accept-Ranges": "bytes",
        "Content-Length": str(req_length),
        "Cache-Control": "public, max-age=31536000, immutable",
        "Expires": "86400",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        "X-Content-Type-Options": "nosniff",
    }

    if range_header:
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"

    if download:
        encoded_filename = quote(file_name)
        headers["Content-Disposition"] = (
            f'attachment; filename="{file_name.encode("latin-1", "ignore").decode()}"; '
            f"filename*=UTF-8''{encoded_filename}"
        )
        headers["Content-Type"] = "application/octet-stream"
    else:
        headers["Content-Type"] = mime_type

    return StreamingResponse(
        status_code=206 if range_header else 200,
        content=body,
        headers=headers,
        media_type="application/octet-stream" if download else mime_type,
    )

# --- Admin Authentication & Management Endpoints ---

@app.post("/api/admin/login")
async def admin_login(payload: Dict[str, Any]):
    username = (payload.get("username") or "").strip()
    password = (payload.get("password") or "").strip()

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    admin_doc = None
    if db.db is not None:
        try:
            admin_doc = await db.db["admin_credentials"].find_one({"username": username})
            if not admin_doc:
                active_doc = await db.db["admin_credentials"].find_one({"_id": "active_admin"})
                if active_doc and active_doc.get("username") == username:
                    admin_doc = active_doc
        except Exception as e:
            LOGGER.error(f"Error checking admin_credentials: {e}")

    if not admin_doc and db.db is not None:
        try:
            admin_doc = await db.db["auth_users"].find_one({"username": username})
        except Exception as e:
            LOGGER.error(f"Error checking auth_users: {e}")

    is_valid = False
    if admin_doc:
        hashed_pass = admin_doc.get("password")
        plain_pass = admin_doc.get("plain_password")

        if hashed_pass:
            try:
                if pwd_ctx.verify(password, hashed_pass):
                    is_valid = True
            except Exception:
                pass

        if not is_valid and (password == hashed_pass or password == plain_pass):
            is_valid = True
    else:
        env_user = getenv("ADMIN_USER") or getenv("VITE_ADMIN_USER") or "admin"
        env_pass = getenv("ADMIN_PASS") or getenv("VITE_ADMIN_PASS") or "admin123"
        if username == env_user and password == env_pass:
            is_valid = True

    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = secrets.token_hex(32)
    return {
        "status": "success",
        "token": token,
        "username": username,
        "message": "Login successful"
    }

@app.get("/api/admin/verify")
async def admin_verify():
    return {"status": "authenticated"}

@app.get("/api/admin/external/search")
async def admin_external_search(
    query: str = Query(...),
    media_type: str = Query(..., pattern="^(movie|tv)$"),
    source: str = Query("tmdb", pattern="^(tmdb|imdb)$")
):
    if source == "tmdb":
        return await search_tmdb(query, media_type)
    else:
        return await search_imdb(query, media_type)

@app.get("/api/admin/external/details")
async def admin_external_details(
    id: str = Query(...),
    media_type: str = Query(..., pattern="^(movie|tv)$"),
    source: str = Query("tmdb", pattern="^(tmdb|imdb)$")
):
    details = await get_external_details(id, media_type, source)
    if not details:
        raise HTTPException(status_code=404, detail="External details not found")
    return details

@app.post("/api/admin/media/add")
async def admin_add_media(media_data: Dict[str, Any]):
    try:
        if media_data.get("media_type") == "movie":
            # Using update_movie which handles upsert
            doc = MovieSchema(**media_data)
            res = await db.update_movie(doc)
        else:
            doc = TVShowSchema(**media_data)
            res = await db.update_tv_show(doc)
        
        if res:
            return {"message": "Media added/updated successfully", "id": str(res)}
        else:
            raise HTTPException(status_code=500, detail="Failed to add media")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/media/{media_type}/{tmdb_id}")
@app.post("/api/admin/media/{media_type}/{tmdb_id}/delete")
async def admin_delete_media(
    media_type: str, 
    tmdb_id: str, 
    title: Optional[str] = Query(None),
    doc_id: Optional[str] = Query(None)
):
    try:
        tmdb_id_val = int(tmdb_id) if tmdb_id.isdigit() else tmdb_id
        success = await db.delete_document(media_type, tmdb_id_val, title, doc_id)
        if success:
            return {"message": "Media deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Media not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/media/{media_type}/{tmdb_id}/details")
async def admin_update_media_details(media_type: str, tmdb_id: str, updated_data: Dict[str, Any]):
    try:
        tmdb_id_val = int(tmdb_id) if tmdb_id.isdigit() else tmdb_id
        success = await db.update_media_details(media_type, tmdb_id_val, updated_data)
        if success:
            return {"message": "Media details updated"}
        else:
            raise HTTPException(status_code=404, detail="Media not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/media/{media_type}/{tmdb_id}/quality/{quality_id}")
@app.post("/api/admin/media/{media_type}/{tmdb_id}/quality/{quality_id}/delete")
async def admin_delete_quality(
    media_type: str, 
    tmdb_id: str, 
    quality_id: str,
    season: Optional[int] = Query(None),
    episode: Optional[int] = Query(None),
    title: Optional[str] = Query(None),
    doc_id: Optional[str] = Query(None)
):
    tmdb_id_val = int(tmdb_id) if tmdb_id.isdigit() else tmdb_id
    success = await db.delete_quality_link(media_type, tmdb_id_val, quality_id, season, episode, title, doc_id)
    if success:
        return {"message": "Quality link deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Quality link not found")

@app.put("/api/admin/media/{media_type}/{tmdb_id}/quality/{quality_id}")
async def admin_update_quality(
    media_type: str, 
    tmdb_id: str, 
    quality_id: str,
    updated_data: Dict[str, Any],
    season: Optional[int] = Query(None),
    episode: Optional[int] = Query(None)
):
    tmdb_id_val = int(tmdb_id) if tmdb_id.isdigit() else tmdb_id
    success = await db.update_quality_link(media_type, tmdb_id_val, quality_id, updated_data, season, episode)
    if success:
        return {"message": "Quality link updated successfully"}
    else:
        raise HTTPException(status_code=404, detail="Quality link not found")

@app.delete("/api/admin/media/tv/{tmdb_id}/season/{season_number}")
async def admin_delete_season(tmdb_id: str, season_number: int):
    tmdb_id_val = int(tmdb_id) if tmdb_id.isdigit() else tmdb_id
    success = await db.delete_season(tmdb_id_val, season_number)
    if success:
        return {"message": f"Season {season_number} deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Season not found")

@app.delete("/api/admin/media/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}")
async def admin_delete_episode(tmdb_id: str, season_number: int, episode_number: int):
    tmdb_id_val = int(tmdb_id) if tmdb_id.isdigit() else tmdb_id
    success = await db.delete_episode(tmdb_id_val, season_number, episode_number)
    if success:
        return {"message": f"Episode {episode_number} deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Episode not found")

@app.put("/api/admin/media/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}")
async def admin_update_episode(tmdb_id: str, season_number: int, episode_number: int, updated_data: Dict[str, Any]):
    tmdb_id_val = int(tmdb_id) if tmdb_id.isdigit() else tmdb_id
    success = await db.update_episode(tmdb_id_val, season_number, episode_number, updated_data)
    if success:
        return {"message": "Episode updated successfully"}
    else:
        raise HTTPException(status_code=404, detail="Episode not found")

@app.delete("/api/admin/manual/files/{file_id}")
async def admin_delete_manual_file(file_id: str):
    success = await db.delete_manual_file(file_id)
    if success:
        return {"message": "Manual file removed"}
    else:
        raise HTTPException(status_code=404, detail="File not found")

@app.delete("/api/admin/manual/bulk_delete")
async def admin_bulk_delete_manual_files(payload: Dict[str, Any]):
    file_ids = payload.get("file_ids", [])
    deleted = 0
    for fid in file_ids:
        if await db.delete_manual_file(fid):
            deleted += 1
    return {"message": f"Deleted {deleted} files."}

def extract_season_episode(filename: str, parsed: Optional[dict] = None) -> Tuple[int, int]:
    """Robustly extract season and episode numbers from filename, with anime-safe fallbacks."""
    if parsed is None:
        try:
            parsed = PTN.parse(filename)
        except Exception:
            parsed = {}

    # 1. Season detection
    season = parsed.get("season")
    if season is None:
        # Check filename for Season patterns: S01, S1, Season 1, etc.
        s_match = re.search(r'\b(?:s|season)[.\s_-]*(\d{1,2})\b', filename, re.IGNORECASE)
        if s_match:
            try:
                season = int(s_match.group(1))
            except Exception:
                season = 1
        else:
            # Default season to 1 for anime / series when omitted
            season = 1
    elif isinstance(season, list):
        season = season[0]

    try:
        season_num = int(season)
    except (ValueError, TypeError):
        season_num = 1

    # 2. Episode detection
    episode = parsed.get("episode")
    if episode is None:
        # Regex patterns for anime and series episode detection
        patterns = [
            # S01E02 or E02 or Ep 02 or Episode 2 or Ep.2
            r'\b(?:e|ep|episode)[.\s_#-]*(\d{1,4})\b',
            # " - 02 " or " - 002 " (common in anime release groups: SubsPlease, Erai-raws, etc.)
            r'[\s_]+-\s*(\d{1,4})(?:v\d+)?(?:[\s_\.\[\()]|$)',
            # " 02 " preceded by space and followed by resolution or bracket, e.g. "Title 02 [1080p]"
            r'\s+(\d{1,4})\s+(?:\(|\[|\d{3,4}p|mkv|mp4)',
            # Number right before file extension, e.g. "Title_02.mkv" or "Title - 02.mkv"
            r'[\s_.-](\d{1,4})\.(?:mkv|mp4|webm|avi)',
            # Standalone 1-4 digit number
            r'\b(\d{1,4})\b'
        ]
        for pat in patterns:
            match = re.search(pat, filename, re.IGNORECASE)
            if match:
                val = match.group(1)
                try:
                    int_val = int(val)
                    # Ignore resolutions or release years
                    if int_val in [360, 480, 540, 720, 1080, 2160] or (1900 <= int_val <= 2099):
                        continue
                    episode = int_val
                    break
                except Exception:
                    continue
    elif isinstance(episode, list):
        episode = episode[0]

    try:
        episode_num = int(episode) if episode is not None else 1
    except (ValueError, TypeError):
        episode_num = 1

    return season_num, episode_num


@app.get("/api/admin/manual/files")
async def admin_get_manual_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
    query: Optional[str] = Query(None)
):
    res = await db.get_unlinked_files(page, page_size, query)
    for file in res.get("files", []):
        filename = file.get("name", "")
        parsed = PTN.parse(filename)
        det_s, det_e = extract_season_episode(filename, parsed)
        file["detected"] = {
            "quality": parsed.get("resolution") or "Unknown",
            "season": det_s,
            "episode": det_e,
            "title": parsed.get("title")
        }
    return res

@app.post("/api/admin/manual/sync")
async def admin_sync_manual_files():
    try:
        synced_manual = 0
        synced_auto = 0

        # Set of auth channel ids
        auth_set = set()
        for c in Telegram.AUTH_CHANNEL:
            f, d = get_channel_id_pair(c)
            auth_set.add(f)
            auth_set.add(d)

        channels_to_scan = []
        for c in Telegram.MANUAL_CHANNEL + Telegram.AUTH_CHANNEL:
            f, d = get_channel_id_pair(c)
            try:
                val = int(f)
                if val not in channels_to_scan:
                    channels_to_scan.append(val)
            except Exception:
                pass

        LOGGER.info(f"Synchronizing repository from channels: {channels_to_scan}")

        for channel_id in channels_to_scan:
            full_id, digit_id = get_channel_id_pair(channel_id)
            is_auth_channel = (full_id in auth_set) or (digit_id in auth_set)
            
            try:
                LOGGER.info(f"Scanning channel history for chat_id={channel_id} (is_auth={is_auth_channel})...")
                async for msg in StreamBot.get_chat_history(channel_id, limit=100):
                    file = msg.video or msg.document or msg.audio
                    if not file:
                        continue

                    caption = (msg.caption or "").strip()
                    if Telegram.USE_CAPTION and caption:
                        title = re.sub(r'[\r\n]+', ' ', caption).strip()
                    else:
                        title = getattr(file, "file_name", None) or f"{file.file_unique_id}.mkv"

                    msg_id = msg.id
                    file_hash = file.file_unique_id[:6]
                    size = get_readable_file_size(file.file_size)
                    ch_num = int(digit_id)

                    display_name = remove_urls(title)
                    display_name = clean_filename(display_name)
                    if not display_name.lower().endswith(('.mkv', '.mp4', '.webm')):
                        display_name += '.mkv'

                    # If it's an AUTH channel, attempt automatic metadata & indexing first!
                    if is_auth_channel:
                        try:
                            cleaned_name = clean_filename(title)
                            metadata_info = await get_media_metadata(cleaned_name, msg)
                            if metadata_info is None and Telegram.USE_CAPTION and getattr(file, "file_name", None):
                                raw_fallback = clean_filename(file.file_name)
                                if raw_fallback != cleaned_name:
                                    metadata_info = await get_media_metadata(raw_fallback, msg)
                                    if metadata_info:
                                        display_name = raw_fallback
                            
                            if metadata_info is not None:
                                updated_id = await db.insert_media(
                                    metadata_info, hash=file_hash, channel=ch_num, msg_id=msg_id, size=size, name=display_name
                                )
                                if updated_id:
                                    synced_auto += 1
                                    LOGGER.info(f"Auto-synced {title} to website library (ID: {updated_id})")
                                    continue
                        except Exception as auto_err:
                            LOGGER.error(f"Error auto-syncing file {title}: {auto_err}")

                    # Manual channel OR auth fallback: Save to manual_files
                    manual_data = {
                        "chat_id": ch_num,
                        "msg_id": msg_id,
                        "hash": file_hash,
                        "size": size,
                        "name": display_name,
                        "original_name": title
                    }
                    if await db.insert_manual_file(manual_data):
                        synced_manual += 1
            except Exception as ch_err:
                LOGGER.error(f"Error reading channel history for {channel_id}: {ch_err}")

        LOGGER.info(f"Sync complete: {synced_manual} manual file(s) indexed, {synced_auto} auto file(s) indexed.")
        msg = f"Repository synchronized successfully! {synced_manual} manual file(s) added to Orphan Hub"
        if synced_auto > 0:
            msg += f", {synced_auto} file(s) automatically added to Website Library."
        return {"message": msg}
    except Exception as e:
        LOGGER.error(f"Error in admin_sync_manual_files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Sync error: {str(e)}")

@app.post("/api/admin/manual/link")
async def admin_link_manual_file(payload: Dict[str, Any], send_report: bool = True):
    # payload: { file_id, tmdb_id, media_type, season, episode, quality, title, doc_id }
    try:
        file_id = payload.get("file_id")
        tmdb_id = payload.get("tmdb_id")
        media_type = payload.get("media_type")
        title = payload.get("title")
        doc_id = payload.get("doc_id")
        
        # Fetch file details from manual_files
        file_doc = await db.manual_collection.find_one({"_id": ObjectId(file_id)})
        if not file_doc:
            raise HTTPException(status_code=404, detail="File not found in manual database")
        
        # Smart metadata extraction from filename
        filename = file_doc.get("name", "")
        parsed = PTN.parse(filename)
        
        # 1. Detect Languages (PTN first, then fallback to filename scan)
        raw_langs = parsed.get("language")
        if not raw_langs:
            possible_langs = ["tamil", "telugu", "hindi", "malayalam", "kannada", "english", "bengali", "marathi", "gujarati", "punjabi", "french", "spanish", "jap", "kor", "tam", "tel", "hin", "mal", "kan", "eng", "ben", "mar", "guj", "pun", "fra", "spa"]
            filename_lower = filename.lower()
            raw_langs = [lang for lang in possible_langs if lang in filename_lower]
            
        detected_languages = normalize_languages(raw_langs)
        
        # 2. Detect Quality (Payload first, then PTN, then default)
        detected_quality = payload.get("quality") or parsed.get("resolution") or "Unknown"

        LOGGER.info(f"Manual Link Detection: file={filename}, langs={detected_languages}, quality={detected_quality}")

        from Backend.helper.encrypt import encode_string
        # Check for required fields to avoid 500 error
        if not all(k in file_doc for k in ["chat_id", "msg_id", "hash"]):
            raise HTTPException(status_code=400, detail="Incomplete file record (missing chat_id, msg_id, or hash). Try Synchronizing Repository.")
            
        data = {"chat_id": file_doc["chat_id"], "msg_id": file_doc["msg_id"], "hash": file_doc["hash"]}
        encoded_id = await encode_string(data)
        quality_detail = {
            "quality": detected_quality,
            "id": encoded_id,
            "name": filename,
            "size": file_doc["size"]
        }
        
        # Find target document reliably
        tmdb_variants = []
        if tmdb_id is not None:
            tmdb_variants.extend([tmdb_id, str(tmdb_id)])
            try:
                tmdb_variants.append(int(tmdb_id))
            except (ValueError, TypeError):
                pass

        target_collection = db.movie_collection if media_type == "movie" else db.tv_collection
        target_doc = None

        if doc_id:
            try:
                target_doc = await target_collection.find_one({"_id": ObjectId(doc_id)})
            except Exception:
                pass
        
        if not target_doc and tmdb_variants:
            target_doc = await target_collection.find_one({"tmdb_id": {"$in": tmdb_variants}})

        if not target_doc and title:
            target_doc = await target_collection.find_one({"title": title})

        # Self-healing fallback: Check opposite collection if user selected wrong type tab
        if not target_doc:
            alt_collection = db.tv_collection if media_type == "movie" else db.movie_collection
            if doc_id:
                try:
                    target_doc = await alt_collection.find_one({"_id": ObjectId(doc_id)})
                except Exception:
                    pass
            if not target_doc and tmdb_variants:
                target_doc = await alt_collection.find_one({"tmdb_id": {"$in": tmdb_variants}})
            if not target_doc and title:
                target_doc = await alt_collection.find_one({"title": title})
            if target_doc:
                target_collection = alt_collection
                media_type = "tv" if alt_collection == db.tv_collection else "movie"

        if not target_doc:
            raise HTTPException(status_code=400, detail=f"Target media not found in database (tmdb_id: {tmdb_id}, title: {title})")

        media_id = target_doc["_id"]
        actual_tmdb_id = target_doc.get("tmdb_id", tmdb_id)

        if media_type == "movie":
            update_op = {
                "$push": {"telegram": quality_detail},
                "$set": {"updated_on": datetime.utcnow()}
            }
            if detected_languages:
                update_op["$addToSet"] = {"languages": {"$each": detected_languages}}

            result = await db.movie_collection.update_one({"_id": media_id}, update_op)
        else:
            # Safe Season & Episode extraction
            season_val = payload.get("season")
            episode_val = payload.get("episode")

            if season_val is None or episode_val is None:
                detected_s, detected_e = extract_season_episode(filename, parsed)
                if season_val is None:
                    season_val = detected_s
                if episode_val is None:
                    episode_val = detected_e

            if isinstance(season_val, list):
                season_val = season_val[0]
            if isinstance(episode_val, list):
                episode_val = episode_val[0]

            try:
                season_num = int(season_val) if season_val is not None else 1
            except (ValueError, TypeError):
                season_num = 1

            try:
                episode_num = int(episode_val) if episode_val is not None else 1
            except (ValueError, TypeError):
                episode_num = 1

            # 1. Ensure Season exists in TV show
            season_exists = await db.tv_collection.find_one({
                "_id": media_id,
                "seasons.season_number": season_num
            })
            if not season_exists:
                await db.tv_collection.update_one(
                    {"_id": media_id},
                    {"$push": {"seasons": {"season_number": season_num, "episodes": []}}}
                )

            # 2. Ensure Episode exists in that season
            episode_exists = await db.tv_collection.find_one({
                "_id": media_id,
                "seasons": {
                    "$elemMatch": {
                        "season_number": season_num,
                        "episodes.episode_number": episode_num
                    }
                }
            })
            if not episode_exists:
                await db.tv_collection.update_one(
                    {
                        "_id": media_id,
                        "seasons.season_number": season_num
                    },
                    {"$push": {"seasons.$.episodes": {
                        "episode_number": episode_num, 
                        "title": f"Episode {episode_num}", 
                        "episode_backdrop": "", 
                        "telegram": []
                    }}}
                )

            # 3. Push stream into episode & update timestamp
            update_op = {
                "$push": {"seasons.$[s].episodes.$[e].telegram": quality_detail},
                "$set": {"updated_on": datetime.utcnow()}
            }
            if detected_languages:
                update_op["$addToSet"] = {"languages": {"$each": detected_languages}}

            result = await db.tv_collection.update_one(
                {"_id": media_id},
                update_op,
                array_filters=[
                    {"s.season_number": season_num},
                    {"e.episode_number": episode_num}
                ]
            )
        
        if result.modified_count > 0:
            await db.link_manual_file(file_id)
            # Send notification
            if send_report:
                metadata_info = await db.get_media_details(tmdb_id=actual_tmdb_id, media_type=media_type)
                if metadata_info:
                    try:
                        await send_log_report(metadata_info, mode="Manual")
                    except Exception as log_err:
                        LOGGER.error(f"Error sending log report: {log_err}")
            return {"message": "File linked successfully"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to link. Target media (ID: {actual_tmdb_id}) could not be updated.")
    except HTTPException:
        raise
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid data types in request: {str(e)}")
    except Exception as e:
        LOGGER.error(f"Link error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@app.post("/api/admin/manual/bulk_link")
async def admin_bulk_link_manual_files(payload: Dict[str, Any]):
    # payload: { file_ids: [], tmdb_id, media_type, title, quality, season, episode, doc_id }
    file_ids = payload.get("file_ids", [])
    tmdb_id = payload.get("tmdb_id")
    media_type = payload.get("media_type")
    title = payload.get("title")
    doc_id = payload.get("doc_id")
    
    success_count = 0
    errors = []
    
    for fid in file_ids:
        try:
            file_doc = await db.manual_collection.find_one({"_id": ObjectId(fid)})
            if not file_doc:
                errors.append(f"File {fid}: File not found in manual database")
                continue
            
            filename = file_doc.get("name", "")
            parsed = PTN.parse(filename)
            detected_s, detected_e = extract_season_episode(filename, parsed)
            
            f_season = payload.get("season") or detected_s
            f_episode = payload.get("episode") or detected_e
            f_quality = payload.get("quality") or parsed.get("resolution") or "Unknown"
            
            link_payload = {
                "file_id": fid,
                "tmdb_id": tmdb_id,
                "media_type": media_type,
                "title": title,
                "doc_id": doc_id,
                "quality": f_quality,
                "season": f_season,
                "episode": f_episode
            }
            
            res = await admin_link_manual_file(link_payload, send_report=False)
            success_count += 1
        except HTTPException as he:
            errors.append(f"File {fid}: {he.status_code}: {he.detail}")
        except Exception as e:
            errors.append(f"File {fid}: {str(e)}")
            LOGGER.error(f"Error bulk linking file {fid}: {e}", exc_info=True)
            
    if success_count > 1:
        metadata_info = await db.get_media_details(tmdb_id=tmdb_id, media_type=media_type)
        if metadata_info:
            try:
                await send_bulk_log_report(metadata_info, success_count, mode="Manual Bulk")
            except Exception as log_err:
                LOGGER.error(f"Error sending bulk log report: {log_err}")
    elif success_count == 1:
        metadata_info = await db.get_media_details(tmdb_id=tmdb_id, media_type=media_type)
        if metadata_info:
            try:
                await send_log_report(metadata_info, mode="Manual")
            except Exception as log_err:
                LOGGER.error(f"Error sending log report: {log_err}")

    return {"message": f"Successfully linked {success_count} files.", "errors": errors}

@app.get("/api/admin/backup")
async def admin_backup():
    try:
        data = await db.get_all_data()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/restore")
async def admin_restore(data: dict):
    try:
        success = await db.restore_all_data(data)
        if success:
            return {"message": "Database restored successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to restore database")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
