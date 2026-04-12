from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
from bson import ObjectId
from fastapi import HTTPException
import motor.motor_asyncio
from pydantic import ValidationError
from pymongo import ASCENDING, DESCENDING

from Backend.logger import LOGGER
from Backend.config import Telegram
from Backend.helper.encrypt import encode_string
from Backend.helper.modal import Episode, MovieSchema, QualityDetail, Season, TVShowSchema, SettingsSchema


# Mapping for expanding language codes to multiple variations for filtering
AUDIO_MAP = {
    "ta": ["ta", "tam", "tamil"],
    "hi": ["hi", "hin", "hindi"],
    "en": ["en", "eng", "english"],
    "te": ["te", "tel", "telugu"],
    "ml": ["ml", "mal", "malayalam"],
    "kn": ["kn", "kan", "kannada"],
    "bn": ["bn", "ben", "bengali"],
    "mr": ["mr", "mar", "marathi"],
    "gu": ["gu", "guj", "gujarati"],
    "pa": ["pa", "pun", "punjabi"],
    "ja": ["ja", "jap", "japanese"],
    "ko": ["ko", "kor", "korean"],
    "es": ["es", "spa", "spanish"],
    "fr": ["fr", "fra", "fre", "french"],
    "de": ["de", "ger", "german"]
}


class Database:
    def __init__(self, connection_uri: str = Telegram.DATABASE, db_name: str = "projectS"):
        self._conn = None
        self.db = None
        self.tv_collection = None
        self.movie_collection = None
        self.settings_collection = None
        self.deploy_config = None
        self.view_analytics = None
        self.connection_uri = connection_uri
        self.db_name = db_name

    async def connect(self):
        """Establish a connection to the database."""
        try:
            if self._conn is not None:
                await self._conn.close()

            self._conn = motor.motor_asyncio.AsyncIOMotorClient(self.connection_uri)
            self.db = self._conn[self.db_name]

            # Ensure collections are assigned
            self.tv_collection = self.db["tv"]
            self.movie_collection = self.db["movie"]
            self.settings_collection = self.db["settings"]
            self.deploy_config = self.db["deploy_config"]
            self.manual_collection = self.db["manual_files"]
            self.view_analytics = self.db["view_analytics"]

            LOGGER.info("Database connection established")
        
            # Debug: Print available collections
           # collections = await self.db.list_collection_names()
           # LOGGER.info(f"Available collections: {collections}")

        except Exception as e:
            LOGGER.error(f"Error connecting to the database: {e}")
            self._conn = None
            self.db = None
        

    async def disconnect(self):
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            LOGGER.info("Database connection closed")
        self._conn = None
        self.db = None
        self.tv_collection = None
        self.movie_collection = None
        self.settings_collection = None

    @staticmethod
    def _convert_object_id(document: dict) -> dict:
        """Convert MongoDB ObjectId to string."""
        if "_id" in document:
            document["_id"] = str(document["_id"])
        return document

    async def get_settings(self) -> dict:
        """Fetch the global settings document (returning empty dict if not found)."""
        settings = await self.settings_collection.find_one({"_id": "global_settings"})
        if settings:
            return settings
        return {}

    async def update_settings(self, settings_data: SettingsSchema) -> bool:
        """Upsert the global settings document."""
        try:
            settings_dict = settings_data.dict(exclude_unset=True)
            settings_dict["updated_on"] = datetime.utcnow()
            
            await self.settings_collection.update_one(
                {"_id": "global_settings"},
                {"$set": settings_dict},
                upsert=True
            )
            return True
        except Exception as e:
            LOGGER.error(f"Error updating settings: {e}")
            return False

    
    async def update_tv_show(self, tv_show_data: TVShowSchema) -> Optional[ObjectId]:
        try:
            tv_show_dict = tv_show_data.dict()
            # Ensure tmdb_id is an int
            tv_show_dict["tmdb_id"] = int(tv_show_dict["tmdb_id"])
        except (ValidationError, ValueError) as e:
            LOGGER.error(f"Validation error: {e}")
            return None

        existing_media = await self.tv_collection.find_one({
            "tmdb_id": int(tv_show_dict["tmdb_id"]),
            "title": tv_show_dict["title"]
        })

        if not existing_media:
            result = await self.tv_collection.insert_one(tv_show_dict)
            return result.inserted_id

        # Update metadata
        fields_to_update = ["genres", "description", "rating", "poster", "backdrop", "total_seasons", "total_episodes", "status", "rip"]
        for field in fields_to_update:
            if field in tv_show_dict:
                existing_media[field] = tv_show_dict[field]

        # Merge languages
        if "languages" in tv_show_dict:
            existing_langs = set(existing_media.get("languages") or [])
            new_langs = set(tv_show_dict["languages"] or [])
            existing_media["languages"] = list(existing_langs.union(new_langs))

        # Merge seasons
        updated = True # Always update metadata at least
        for new_season in tv_show_dict.get("seasons", []):
            existing_season = next((s for s in existing_media.get("seasons", []) if s["season_number"] == new_season["season_number"]), None)
            
            if not existing_season:
                existing_media.setdefault("seasons", []).append(new_season)
                continue
            
            # Merge episodes
            for new_episode in new_season.get("episodes", []):
                existing_episode = next((e for e in existing_season.get("episodes", []) if e["episode_number"] == new_episode["episode_number"]), None)
                
                if not existing_episode:
                    existing_season.setdefault("episodes", []).append(new_episode)
                    continue
                
                # Merge telegram streams by ID
                for new_q in new_episode.get("telegram", []):
                    existing_q = next((q for q in existing_episode.get("telegram", []) if q["id"] == new_q["id"]), None)
                    if existing_q:
                        existing_q.update(new_q)
                    else:
                        existing_episode.setdefault("telegram", []).append(new_q)

        existing_media["updated_on"] = datetime.utcnow()
        await self.tv_collection.replace_one({"_id": existing_media["_id"]}, existing_media)
        return existing_media["_id"]

    async def update_movie(self, movie_data: MovieSchema) -> Optional[ObjectId]:
        if self.movie_collection is None:
            LOGGER.error("Database collection is not initialized.")
            return None
        try:
            movie_dict = movie_data.dict()
            movie_dict["tmdb_id"] = int(movie_dict["tmdb_id"])
        except (ValidationError, ValueError) as e:
            LOGGER.error(f"Validation error: {e}")
            return None

        # Match by both ID and Title to allow intentional duplicates with different names
        existing_media = await self.movie_collection.find_one({
            "tmdb_id": movie_dict["tmdb_id"],
            "title": movie_dict["title"]
        })

        if not existing_media:
            result = await self.movie_collection.insert_one(movie_dict)
            return result.inserted_id

        # Update metadata
        fields_to_update = ["genres", "description", "rating", "poster", "backdrop", "runtime", "rip"]
        for field in fields_to_update:
            if field in movie_dict:
                existing_media[field] = movie_dict[field]

        # Merge languages
        if "languages" in movie_dict:
            existing_langs = set(existing_media.get("languages") or [])
            new_langs = set(movie_dict["languages"] or [])
            existing_media["languages"] = list(existing_langs.union(new_langs))

        # Merge telegram streams
        for new_q in movie_dict.get("telegram", []):
            existing_q = next((q for q in existing_media.get("telegram", []) if q["id"] == new_q["id"]), None)
            if existing_q:
                existing_q.update(new_q)
            else:
                existing_media.setdefault("telegram", []).append(new_q)

        existing_media["updated_on"] = datetime.utcnow()
        await self.movie_collection.replace_one({"_id": existing_media["_id"]}, existing_media)
        return existing_media["_id"]

    async def insert_media(
        self,
        metadata_info: dict,
        hash: str,
        channel: int,
        msg_id: int,
        size: str,
        name: str
    ) -> Optional[ObjectId]:
        data = {"chat_id": channel, "msg_id": msg_id, "hash": hash}
        encoded_string = await encode_string(data)

        if metadata_info['media_type'] == "movie":
            media = MovieSchema(
                tmdb_id=metadata_info['tmdb_id'],
                title=metadata_info['title'],
                genres=metadata_info['genres'],
                description=metadata_info['description'],
                rating=metadata_info['rate'],
                release_year=metadata_info['year'],
                poster=metadata_info['poster'],
                backdrop=metadata_info['backdrop'],
                runtime=metadata_info['runtime'],
                media_type=metadata_info['media_type'],
                languages=metadata_info['languages'],
                rip=metadata_info['rip'],
                views=0, # Initial views
                telegram=[
                    QualityDetail(
                        quality=metadata_info.get('quality') or 'Unknown',
                        id=encoded_string,
                        name=name,
                        size=size
                    )]
            )
            return await self.update_movie(media)
        else:
            tv_show = TVShowSchema(
                tmdb_id=metadata_info['tmdb_id'],
                title=metadata_info['title'],
                genres=metadata_info['genres'],
                description=metadata_info['description'],
                rating=metadata_info['rate'],
                release_year=metadata_info['year'],
                poster=metadata_info['poster'],
                backdrop=metadata_info['backdrop'],
                media_type=metadata_info['media_type'],
                status=metadata_info['status'],
                total_seasons=metadata_info['total_seasons'],
                total_episodes=metadata_info['total_episodes'],
                languages=metadata_info['languages'],
                rip=metadata_info['rip'],
                views=0, # Initial views
                seasons=[
                    Season(
                        season_number=metadata_info['season_number'],
                        episodes=[
                            Episode(
                                episode_number=metadata_info['episode_number'],
                                title=metadata_info['episode_title'],
                                episode_backdrop=metadata_info['episode_backdrop'],
                                telegram=[
                                    QualityDetail(
                                        quality=metadata_info.get('quality') or 'Unknown',
                                        id=encoded_string,
                                        name=name,
                                        size=size
                                    )
                                ]
                            )
                        ]
                    )
                ]
            )
            return await self.update_tv_show(tv_show)

    async def sort_tv_shows(
        self, 
        sort_params: List[Tuple[str, str]], 
        page: int, 
        page_size: int,
        genre: Optional[str] = None,
        year: Optional[str] = None,
        audio: Optional[str] = None
    ) -> dict:
        skip = (page - 1) * page_size
        sort_criteria = [(field, ASCENDING if direction == "asc" else DESCENDING) 
                        for field, direction in sort_params]
        
        match_stage = {}
        if genre and genre.strip().lower() != "all":
            # Match if the genre array contains a case-insensitive version of the requested genre
            match_stage["genres"] = {"$regex": f"^{genre}$", "$options": "i"}
        if year and year.strip().lower() != "all":
            try:
                match_stage["release_year"] = int(year)
            except ValueError:
                pass
        if audio and audio.strip().lower() != "all":
            audio_low = audio.strip().lower()
            if audio_low in AUDIO_MAP:
                # Expand to multiple variations using regex OR
                variations = AUDIO_MAP[audio_low]
                pattern = f"^({'|'.join(variations)})$"
                match_stage["languages"] = {"$regex": pattern, "$options": "i"}
            else:
                match_stage["languages"] = {"$regex": f"^{audio}$", "$options": "i"}
        
        pipeline = []
        if match_stage:
            pipeline.append({"$match": match_stage})

        pipeline.extend([
            {"$sort": dict(sort_criteria)},
            {"$facet": {
                "metadata": [{"$count": "total_count"}],
                "data": [{"$skip": skip}, {"$limit": page_size}]
            }}
        ])
        
        result = await self.tv_collection.aggregate(pipeline).to_list(1)
        total_count = result[0]["metadata"][0]["total_count"] if result[0]["metadata"] else 0
        
        sorted_tv_shows = []
        for doc in result[0]["data"]:
            try:
                sorted_tv_shows.append(TVShowSchema(**self._convert_object_id(doc)))
            except Exception as e:
                LOGGER.error(f"Validation error for TV show document {doc.get('_id')}: {e}")
                continue
                
        return {"total_count": total_count, "tv_shows": sorted_tv_shows}

    async def sort_movies(
        self, 
        sort_params: List[Tuple[str, str]], 
        page: int, 
        page_size: int,
        genre: Optional[str] = None,
        year: Optional[str] = None,
        audio: Optional[str] = None
    ) -> dict:
        skip = (page - 1) * page_size
        sort_criteria = [(field, ASCENDING if direction == "asc" else DESCENDING) 
                        for field, direction in sort_params]
        
        match_stage = {}
        if genre and genre.strip().lower() != "all":
            match_stage["genres"] = {"$regex": f"^{genre}$", "$options": "i"}
        if year and year.strip().lower() != "all":
            try:
                match_stage["release_year"] = int(year)
            except ValueError:
                pass
        if audio and audio.strip().lower() != "all":
            audio_low = audio.strip().lower()
            if audio_low in AUDIO_MAP:
                # Expand to multiple variations using regex OR
                variations = AUDIO_MAP[audio_low]
                pattern = f"^({'|'.join(variations)})$"
                match_stage["languages"] = {"$regex": pattern, "$options": "i"}
            else:
                match_stage["languages"] = {"$regex": f"^{audio}$", "$options": "i"}

        pipeline = []
        if match_stage:
            pipeline.append({"$match": match_stage})

        pipeline.extend([
            {"$sort": dict(sort_criteria)},
            {"$facet": {
                "metadata": [{"$count": "total_count"}],
                "data": [{"$skip": skip}, {"$limit": page_size}]
            }}
        ])
        
        result = await self.movie_collection.aggregate(pipeline).to_list(1)
        total_count = result[0]["metadata"][0]["total_count"] if result[0]["metadata"] else 0
        
        sorted_movies = []
        for doc in result[0]["data"]:
            try:
                sorted_movies.append(MovieSchema(**self._convert_object_id(doc)))
            except Exception as e:
                LOGGER.error(f"Validation error for movie document {doc.get('_id')}: {e}")
                continue
                
        return {"total_count": total_count, "movies": sorted_movies}

    async def get_trending_media(
        self,
        page: int = 1,
        page_size: int = 10
    ) -> dict:
        """
        Fetches the latest mixed media (Movies + TV Shows) sorted by updated_on descending.
        """
        skip = (page - 1) * page_size
        
        # Pipeline to get the latest from both collections
        # We increase the limit slightly to ensure we have enough for merging
        pipeline = [
            {"$sort": {"updated_on": DESCENDING}},
            {"$limit": skip + page_size * 2} 
        ]

        movie_results = await self.movie_collection.aggregate(pipeline).to_list(None)
        tv_results = await self.tv_collection.aggregate(pipeline).to_list(None)

        # Merge, sort by updated_on, and paginate
        combined = movie_results + tv_results
        
        # Robust sort handles cases where updated_on might be None or missing
        combined.sort(
            key=lambda x: x.get("updated_on") if isinstance(x.get("updated_on"), datetime) else datetime.min, 
            reverse=True
        )
        
        paginated_results = combined[skip:skip+page_size]

        # Total count should be correctly calculated or estimated
        total_movies = await self.movie_collection.count_documents({})
        total_tv = await self.tv_collection.count_documents({})

        # Ensure consistent data structure for frontend (rating, media_type, etc.)
        validated_results = []
        for doc in paginated_results:
            try:
                # Modifying the document from _convert_object_id which returns a string ID
                processed_doc = self._convert_object_id(doc)
                
                # Coerce rating to float to avoid toFixed errors in frontend
                if "rating" in processed_doc:
                    try:
                        processed_doc["rating"] = float(processed_doc["rating"])
                    except (TypeError, ValueError):
                        processed_doc["rating"] = 0.0
                else:
                    processed_doc["rating"] = 0.0
                
                # Ensure media_type is present for HomeHero.jsx
                if "media_type" not in processed_doc:
                    processed_doc["media_type"] = "tv" if "seasons" in processed_doc else "movie"
                
                validated_results.append(processed_doc)
            except Exception as e:
                LOGGER.error(f"Error processing trending result: {e}")
                validated_results.append(self._convert_object_id(doc))

        return {
            "total_count": total_movies + total_tv,
            "results": validated_results
        }

    async def find_similar_media(
        self,
        tmdb_id: int,
        media_type: str,
        page: int = 1,
        page_size: int = 10
    ) -> dict:
        collection = self.movie_collection if media_type == "movie" else self.tv_collection
        parent_media = await collection.find_one({"tmdb_id": tmdb_id})
        
        if not parent_media:
            raise HTTPException(status_code=404, detail="Media not found")
        
        parent_genres = parent_media.get("genres", [])
        if not parent_genres:
            return {"total_count": 0, "similar_media": []}

        skip = (page - 1) * page_size
        pipeline = [
            {"$match": {
                "tmdb_id": {"$ne": tmdb_id},
                "genres": {"$in": parent_genres}
            }},
            {"$addFields": {
                "genreMatchCount": {"$size": {"$setIntersection": ["$genres", parent_genres]}}
            }},
            {"$sort": {"genreMatchCount": -1, "rating": -1}},
            {"$facet": {
                "metadata": [{"$count": "total_count"}],
                "data": [{"$skip": skip}, {"$limit": page_size}]
            }}
        ]
        
        result = await collection.aggregate(pipeline).to_list(1)
        total_count = result[0]["metadata"][0]["total_count"] if result[0]["metadata"] else 0
        similar_media = [self._convert_object_id(doc) for doc in result[0]["data"]]
        return {"total_count": total_count, "similar_media": similar_media}

    async def search_documents(
        self, 
        query: str, 
        page: int, 
        page_size: int
    ) -> dict:
        skip = (page - 1) * page_size
        words = query.split()
        regex_query = {'$regex': '.*' + '.*'.join(words) + '.*', '$options': 'i'}
        
        tv_pipeline = [
            {"$match": {"$or": [
                {"title": regex_query},
                {"seasons.episodes.telegram.name": regex_query}
            ]}},
            {"$project": {
                "_id": 1, "tmdb_id": 1, "title": 1, "genres": 1, "rating": 1,
                "release_year": 1, "poster": 1, "backdrop": 1, "description": 1,
                "total_seasons": 1, "total_episodes": 1, "media_type": 1
            }}
        ]
        
        movie_pipeline = [
            {"$match": {"$or": [
                {"title": regex_query},
                {"telegram.name": regex_query}
            ]}},
            {"$project": {
                "_id": 1, "tmdb_id": 1, "title": 1, "genres": 1, "rating": 1,
                "release_year": 1, "poster": 1, "backdrop": 1, "description": 1,
                "media_type": 1
            }}
        ]
        
        tv_results = await self.tv_collection.aggregate(tv_pipeline).to_list(None)
        movie_results = await self.movie_collection.aggregate(movie_pipeline).to_list(None)
        combined = tv_results + movie_results
        
        return {
            "total_count": len(combined),
            "results": [self._convert_object_id(doc) for doc in combined[skip:skip+page_size]]
        }

    async def get_media_details(
        self,
        tmdb_id: Union[int, str],
        season_number: Optional[int] = None,
        episode_number: Optional[int] = None,
        title: Optional[str] = None
    ) -> Optional[dict]:
        query = {"tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}}
        if title:
            query["title"] = title

        if episode_number is not None and season_number is not None:
            tv_show = await self.tv_collection.find_one(query)
            if not tv_show:
                return None
            for season in tv_show.get("seasons", []):
                if season.get("season_number") == season_number:
                    for episode in season.get("episodes", []):
                        if episode.get("episode_number") == episode_number:
                            details = self._convert_object_id(episode)
                            details.update({
                                "tmdb_id": tmdb_id,
                                "type": "tv",
                                "season_number": season_number,
                                "episode_number": episode_number,
                                "backdrop": episode.get("episode_backdrop"),
                                "media_type": "tv" # Added for frontend clarity
                            })
                            return details
            return None

        elif season_number is not None:
            tv_show = await self.tv_collection.find_one(query)
            if not tv_show:
                return None
            for season in tv_show.get("seasons", []):
                if season.get("season_number") == season_number:
                    details = self._convert_object_id(season)
                    details.update({
                        "tmdb_id": tmdb_id,
                        "type": "tv",
                        "season_number": season_number,
                        "media_type": "tv"
                    })
                    return details
            return None

        else:
            tv_doc = await self.tv_collection.find_one(query)
            if tv_doc:
                tv_doc = self._convert_object_id(tv_doc)
                tv_doc["type"] = "tv"
                tv_doc["media_type"] = "tv"
                return tv_doc
            
            movie_doc = await self.movie_collection.find_one(query)
            if movie_doc:
                movie_doc = self._convert_object_id(movie_doc)
                movie_doc["type"] = "movie"
                movie_doc["media_type"] = "movie"
                return movie_doc
            
            return None

    async def get_quality_details(
        self,
        tmdb_id: int,
        quality: str,
        season: Optional[int] = None,
        episode: Optional[int] = None
    ) -> List[Dict[str, int]]:
        if season is None:
            # Movie case
            doc = await self.movie_collection.find_one(
                {"tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}},
                {"telegram": 1}
            )
            if not doc:
                return []
            return [
                {"id": item["id"], "name": item["name"]}
                for item in doc.get("telegram", [])
                if item["quality"] == quality
            ]
        else:
            # TV show case
            doc = await self.tv_collection.find_one(
                {"tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}},
                {"seasons": 1}
            )
            if not doc:
                return []
            
            results = []
            for s in doc.get("seasons", []):
                if s["season_number"] == season:
                    episodes = s.get("episodes", [])
                    
                    # Filter by specific episode if provided
                    if episode is not None:
                        episodes = [ep for ep in episodes if ep["episode_number"] == episode]
                    
                    for ep in episodes:
                        results.extend([
                            {"id": t["id"], "name": t["name"]}
                            for t in ep.get("telegram", [])
                            if t["quality"] == quality
                        ])
            return results


    async def delete_document(
        self,
        media_type: str,
        tmdb_id: Union[int, str],
        title: Optional[str] = None,
        doc_id: Optional[str] = None
    ) -> bool:
        collection = self.movie_collection if media_type in ["mov", "movie"] else self.tv_collection
        
        # Prioritize deletion by unique MongoDB ID
        if doc_id:
            try:
                result = await collection.delete_one({"_id": ObjectId(doc_id)})
                if result.deleted_count > 0:
                    LOGGER.info(f"Deleted document by ID: {doc_id}")
                    return True
            except Exception as e:
                LOGGER.error(f"Error deleting by doc_id {doc_id}: {e}")

        # Fallback to query-based deletion
        query = {"tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}}
        if title:
            query["title"] = title
            
        result = await collection.delete_many(query)
        
        if result.deleted_count > 0:
            LOGGER.info(f"{media_type} deleted successfully ({result.deleted_count} docs).")
            return True
        LOGGER.info(f"No document found for {query}.")
        return False

    async def delete_quality_link(
        self,
        media_type: str,
        tmdb_id: Union[int, str],
        quality_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        title: Optional[str] = None,
        doc_id: Optional[str] = None
    ) -> bool:
        collection = self.movie_collection if media_type in ["mov", "movie"] else self.tv_collection
        
        # Build precise query
        query = {"tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}}
        if doc_id: query = {"_id": ObjectId(doc_id)}
        elif title: query["title"] = title

        LOGGER.info(f"Quality delete: type={media_type}, query={query}, quality_id={quality_id}")

        if media_type in ["mov", "movie"]:
            result = await self.movie_collection.update_one(
                query,
                {"$pull": {"telegram": {"id": quality_id}}}
            )
            success = result.modified_count > 0
            LOGGER.info(f"Movie quality delete success: {success} (modified: {result.modified_count})")
            return success
        else:
            # TV show case
            # We need to find the specific episode and pull from its telegram array
            result = await self.tv_collection.update_one(
                {
                    **query,
                    "seasons.season_number": season,
                    "seasons.episodes.episode_number": episode
                },
                {"$pull": {"seasons.$[s].episodes.$[e].telegram": {"id": quality_id}}},
                array_filters=[{"s.season_number": season}, {"e.episode_number": episode}]
            )
            success = result.modified_count > 0
            LOGGER.info(f"TV quality delete success: {success} (modified: {result.modified_count})")
            return success

    async def update_quality_link(
        self,
        media_type: str,
        tmdb_id: Union[int, str],
        quality_id: str,
        updated_data: dict,
        season: Optional[int] = None,
        episode: Optional[int] = None
    ) -> bool:
        # updated_data might contain: quality, name, size
        if media_type in ["mov", "movie"]:
            # Construct the $set object for the specific quality item
            set_query = {}
            for key, value in updated_data.items():
                set_query[f"telegram.$.{key}"] = value

            result = await self.movie_collection.update_one(
                {"tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}, "telegram.id": quality_id},
                {"$set": set_query}
            )
            return result.matched_count > 0
        else:
            set_query = {}
            for key, value in updated_data.items():
                set_query[f"seasons.$[s].episodes.$[e].telegram.$[t].{key}"] = value

            result = await self.tv_collection.update_one(
                {
                    "tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}
                },
                {"$set": set_query},
                array_filters=[
                    {"s.season_number": season},
                    {"e.episode_number": episode},
                    {"t.id": quality_id}
                ]
            )
            return result.matched_count > 0

    async def delete_season(self, tmdb_id: int, season_number: int) -> bool:
        result = await self.tv_collection.update_one(
            {"tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}},
            {"$pull": {"seasons": {"season_number": season_number}}}
        )
        return result.matched_count > 0

    async def delete_episode(self, tmdb_id: int, season_number: int, episode_number: int) -> bool:
        result = await self.tv_collection.update_one(
            {"tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}, "seasons.season_number": season_number},
            {"$pull": {"seasons.$.episodes": {"episode_number": episode_number}}}
        )
        return result.matched_count > 0

    async def update_episode(self, tmdb_id: int, season_number: int, episode_number: int, updated_data: dict) -> bool:
        # updated_data: title, episode_backdrop
        set_query = {}
        for key, value in updated_data.items():
            set_query[f"seasons.$[s].episodes.$[e].{key}"] = value

        result = await self.tv_collection.update_one(
            {"tmdb_id": tmdb_id},
            {"$set": set_query},
            array_filters=[
                {"s.season_number": season_number},
                {"e.episode_number": episode_number}
            ]
        )
        return result.modified_count > 0

    async def get_unlinked_files(self, page: int = 1, page_size: int = 20, query: Optional[str] = None) -> dict:
        skip = (page - 1) * page_size
        
        match_stage = {"is_linked": {"$ne": True}}
        if query:
            match_stage["name"] = {"$regex": query, "$options": "i"}

        pipeline = [
            {"$match": match_stage},
            {"$sort": {"received_at": DESCENDING}},
            {"$facet": {
                "metadata": [{"$count": "total_count"}],
                "data": [{"$skip": skip}, {"$limit": page_size}]
            }}
        ]
        result = await self.manual_collection.aggregate(pipeline).to_list(1)
        total_count = result[0]["metadata"][0]["total_count"] if result[0]["metadata"] else 0
        files = [self._convert_object_id(doc) for doc in result[0]["data"]]
        return {"total_count": total_count, "files": files}

    async def insert_manual_file(self, file_data: dict) -> bool:
        """Insert a file received from AUTH_CHANNEL into manual_files collection if not exists."""
        # Use a combination of chat_id and msg_id as unique identifier
        existing = await self.manual_collection.find_one({
            "chat_id": file_data["chat_id"],
            "msg_id": file_data["msg_id"]
        })
        if not existing:
            file_data["is_linked"] = False
            file_data["received_at"] = datetime.utcnow()
            await self.manual_collection.insert_one(file_data)
            return True
        return False

    async def link_manual_file(self, file_id: str) -> bool:
        """Mark a manual file as linked."""
        result = await self.manual_collection.update_one(
            {"_id": ObjectId(file_id)},
            {"$set": {"is_linked": True, "linked_at": datetime.utcnow()}}
        )
        return result.modified_count > 0

    async def delete_manual_file(self, file_id: str) -> bool:
        """Delete a manual file entry."""
        result = await self.manual_collection.delete_one({"_id": ObjectId(file_id)})
        return result.deleted_count > 0
    async def get_analytics(self) -> dict:
        """Fetch general library statistics and view analytics."""
        total_movies = await self.movie_collection.count_documents({})
        total_tv = await self.tv_collection.count_documents({})
        total_manual = await self.manual_collection.count_documents({"is_linked": {"$ne": True}})

        # Latest entries
        latest_movies = await self.movie_collection.find().sort("updated_on", DESCENDING).limit(5).to_list(None)
        latest_tv = await self.tv_collection.find().sort("updated_on", DESCENDING).limit(5).to_list(None)

        # View statistics
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        month_start = today_start - timedelta(days=30)
        
        today_views = await self.view_analytics.count_documents({"timestamp": {"$gte": today_start}})
        yesterday_views = await self.view_analytics.count_documents({"timestamp": {"$gte": yesterday_start, "$lt": today_start}})
        monthly_views = await self.view_analytics.count_documents({"timestamp": {"$gte": month_start}})
        total_views_all = await self.view_analytics.count_documents({})

        # Top Viewed
        top_movies = await self.movie_collection.find().sort("views", DESCENDING).limit(5).to_list(None)
        top_tv = await self.tv_collection.find().sort("views", DESCENDING).limit(5).to_list(None)

        return {
            "stats": {
                "movies": total_movies,
                "tv_shows": total_tv,
                "manual_files": total_manual,
                "total_content": total_movies + total_tv,
                "today_views": today_views,
                "yesterday_views": yesterday_views,
                "monthly_views": monthly_views,
                "total_views": total_views_all
            },
            "recent": {
                "movies": [MovieSchema(**self._convert_object_id(m)) for m in latest_movies],
                "tv_shows": [TVShowSchema(**self._convert_object_id(t)) for t in latest_tv]
            },
            "top_viewed": {
                "movies": [MovieSchema(**self._convert_object_id(m)) for m in top_movies],
                "tv_shows": [TVShowSchema(**self._convert_object_id(t)) for t in top_tv]
            }
        }

    async def get_view_graph_data(self, period: str = "week") -> List[dict]:
        """Fetch daily view counts for the given period."""
        from datetime import timedelta
        end_date = datetime.utcnow()
        if period == "yesterday":
            start_date = end_date - timedelta(days=2)
        elif period == "week":
            start_date = end_date - timedelta(days=7)
        elif period == "month":
            start_date = end_date - timedelta(days=30)
        elif period == "year":
            start_date = end_date - timedelta(days=365)
        else: # max
            start_date = datetime(2025, 1, 1) # Arbitrary start

        pipeline = [
            {"$match": {"timestamp": {"$gte": start_date}}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": 1}}
        ]
        results = await self.view_analytics.aggregate(pipeline).to_list(None)
        return [{"date": r["_id"], "views": r["count"]} for r in results]

    async def increment_view(self, media_type: str, tmdb_id: Union[int, str], identifier: str = None) -> bool:
        """Increment view count and log to analytics (unique per ID per day)."""
        collection = self.movie_collection if media_type in ["mov", "movie"] else self.tv_collection
        
        # Unique check: Check if this identifier viewed this content today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        if identifier:
            exists = await self.view_analytics.find_one({
                "tmdb_id": int(tmdb_id),
                "identifier": identifier,
                "timestamp": {"$gte": today_start}
            })
            if exists:
                return False

        # Update total views
        result = await collection.update_one(
            {"tmdb_id": {"$in": [int(tmdb_id), str(tmdb_id)]}},
            {"$inc": {"views": 1}}
        )
        
        if result.matched_count > 0:
            # Log to time-series analytics
            await self.view_analytics.insert_one({
                "media_type": media_type,
                "tmdb_id": int(tmdb_id),
                "identifier": identifier,
                "timestamp": datetime.utcnow()
            })
            return True
        return False

    async def update_media_details(self, media_type: str, tmdb_id: Union[int, str], updated_data: dict) -> bool:
        """Update core metadata for a movie or TV show using optional originalTitle for versioning."""
        collection = self.movie_collection if media_type in ["mov", "movie"] else self.tv_collection
        
        orig_title = updated_data.pop("originalTitle", None)
        if "_id" in updated_data: del updated_data["_id"]
        
        query = {"tmdb_id": {"$in": [tmdb_id, str(tmdb_id)]}}
        if orig_title:
            query["title"] = orig_title
            
        updated_data["updated_on"] = datetime.utcnow()
        result = await collection.update_one(
            query,
            {"$set": updated_data}
        )
        return result.matched_count > 0

    async def get_all_data(self) -> dict:
        """Fetch all documents from core collections for backup."""
        collections = {
            "movie": self.movie_collection,
            "tv": self.tv_collection,
            "settings": self.settings_collection,
            "manual_files": self.manual_collection,
            "deploy_config": self.deploy_config
        }
        
        backup_data = {}
        for name, collection in collections.items():
            if collection is not None:
                docs = await collection.find().to_list(None)
                backup_data[name] = [self._convert_object_id(doc) for doc in docs]
            else:
                backup_data[name] = []
        
        return backup_data

    async def restore_all_data(self, backup_data: dict) -> bool:
        """Clear and re-populate core collections from backup data."""
        collections = {
            "movie": self.movie_collection,
            "tv": self.tv_collection,
            "settings": self.settings_collection,
            "manual_files": self.manual_collection,
            "deploy_config": self.deploy_config
        }
        
        try:
            for name, collection in collections.items():
                if collection is not None and name in backup_data:
                    # Clear current collection
                    await collection.delete_many({})
                    
                    docs = backup_data[name]
                    if docs:
                        # For the settings collection, we want to keep the string _id as is.
                        # For others, if they have an _id that looks like a 24-char hex string, 
                        # we could convert to ObjectId, but keeping as string is safer for JSON round-trips 
                        # unless the app specifically expects ObjectId types.
                        # Given _convert_object_id was used, we just insert as they are.
                        await collection.insert_many(docs)
                
            return True
        except Exception as e:
            LOGGER.error(f"Error restoring from backup: {e}")
            return False

    async def add_bot_admin(self, user_id: int) -> bool:
        """Add a user to the bot_admins collection."""
        try:
            await self.db["bot_admins"].update_one(
                {"user_id": user_id},
                {"$set": {"user_id": user_id, "added_on": datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            LOGGER.error(f"Error adding bot admin: {e}")
            return False

    async def remove_bot_admin(self, user_id: int) -> bool:
        """Remove a user from the bot_admins collection."""
        try:
            await self.db["bot_admins"].delete_one({"user_id": user_id})
            return True
        except Exception as e:
            LOGGER.error(f"Error removing bot admin: {e}")
            return False

    async def get_bot_admins(self) -> List[int]:
        """Get all user IDs from the bot_admins collection."""
        try:
            admins = await self.db["bot_admins"].find({}).to_list(None)
            return [a["user_id"] for a in admins]
        except Exception as e:
            LOGGER.error(f"Error fetching bot admins: {e}")
            return []

    async def is_bot_admin(self, user_id: int) -> bool:
        """Check if a user is an admin or owner."""
        if user_id == Telegram.OWNER_ID:
            return True
        admin = await self.db["bot_admins"].find_one({"user_id": user_id})
        return admin is not None
