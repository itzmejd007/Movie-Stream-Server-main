from Backend.config import Telegram
from Backend.helper.imdb import get_detail, get_season, search_title
from Backend.helper.mediainfo import get_media_quality, get_media_languages
import PTN
from themoviedb import aioTMDb

from Backend.helper.pyro import extract_tmdb_id, normalize_languages

tmdb = aioTMDb(api_key=Telegram.TMDB_API, language="en-US", region="US")

async def metadata(filename, message):

    # Parse the filename using PTN
    data = PTN.parse(filename)
    if 'excess' in data and any('combined' in item.lower() for item in data['excess']):
        print(f"Skipping {filename} due to 'combined' in excess")
        return None
    title = data.get('title')
    season = data.get('season')
    episode = data.get('episode')
    year = data.get('year')
    quality = data.get('resolution')
    if quality is None:
        quality = await get_media_quality(message)
    if quality is None:
        quality = "Unknown"

    languages = normalize_languages(data.get('language'))
    if not languages:
        languages = await get_media_languages(message)
    rip = data.get('quality')

    print("Current USE_DEFAULT_ID:", Telegram.USE_DEFAULT_ID)
    
    if Telegram.USE_DEFAULT_ID is None:
        default_id = extract_tmdb_id(filename)
        print("Extracted default_id:", default_id)
    else:
        default_id = extract_tmdb_id(Telegram.USE_DEFAULT_ID)
        print("Using USE_DEFAULT_ID:", default_id)

    if title:
        if season and episode:
            try:
            # Fetch TV show details
                if default_id is None:
                    if Telegram.USE_TMDB:
                        tv_shows = await tmdb.search().tv(query=title)
                        tv_show = tv_shows[0].id  # Get first result
                        tv_show_details = await tmdb.tv(tv_show).details()
                    
                    # Try fetching episode details, fallback to default
                        try:
                            episode_details = await tmdb.episode(tv_show, season, episode).details()
                            episode_title = episode_details.name or f"S{season}E{episode}"
                            episode_backdrop = (
                               f"https://image.tmdb.org/t/p/original{episode_details.still_path}"
                                if episode_details.still_path else ''
                                 )
                        except Exception:
                            print(f"Episode S{season}E{episode} not found. Using default values.")
                            episode_title = f"S{season}E{episode}"
                            episode_backdrop = ''
                    else:
                        tv_shows = await search_title(query=title, type="tvSeries")
                        tvshow = tv_shows['id']
                        tv_show_details = await get_detail(imdb_id=tvshow)
                    
                    # Try fetching episode details, fallback to default
                        try:
                            episode_details = await get_season(imdb_id=tvshow, season_id=season, episode_id=episode)
                            if episode_details != None:
                                episode_title = episode_details.get('title', f"S{season}E{episode}")
                                episode_backdrop = episode_details.get('image', '')
                            else:
                                episode_title = f"S{season}E{episode}"
                                episode_backdrop = ''
                        except Exception:
                            print(f"Episode S{season}E{episode} not found in IMDb. Using default values.")
                            episode_title = f"S{season}E{episode}"
                            episode_backdrop = ''
                else:
                    if default_id.startswith("tt"):
                        tv_show_details = await get_detail(imdb_id=default_id)
                    
                    # Try fetching episode details, fallback to default
                        try:
                            episode_details = await get_season(imdb_id=default_id, season_id=season, episode_id=episode)
                            episode_title = episode_details.get('title', f"S{season}E{episode}")
                            episode_backdrop = episode_details.get('image', '')
                        except Exception:
                            print(f"Episode S{season}E{episode} not found in IMDb. Using default values.")
                            episode_title = f"S{season}E{episode}"
                            episode_backdrop = ''
                    else:
                        tv_show_details = await tmdb.tv(int(default_id)).details()
                    
                    # Try fetching episode details, fallback to default
                        try:
                            episode_details = await tmdb.episode(int(default_id), season, episode).details()
                            episode_title = episode_details.name
                            episode_backdrop = f"https://image.tmdb.org/t/p/original{episode_details.still_path}" if episode_details.still_path else ''
                        except Exception:
                            print(f"Episode S{season}E{episode} not found. Using default values.")
                            episode_title = f"S{season}E{episode}"
                            episode_backdrop = ''

                # Extract relevant TV show metadata
                tmdb_id = int(tv_show_details.id) if Telegram.USE_TMDB else int(str(tv_show_details['id']).replace("tt", ""))
                title = tv_show_details.name if Telegram.USE_TMDB else tv_show_details['title']
                year = tv_show_details.first_air_date.year if Telegram.USE_TMDB else tv_show_details['releaseDetailed']['year']
                rate = tv_show_details.vote_average if Telegram.USE_TMDB else tv_show_details['rating']['star']
                description = tv_show_details.overview if Telegram.USE_TMDB else tv_show_details['plot']
                total_seasons = tv_show_details.number_of_seasons if Telegram.USE_TMDB else len(tv_show_details['all_seasons'])
                total_episodes = tv_show_details.number_of_episodes if Telegram.USE_TMDB else ' '.join(str(len(season['episodes']) * total_seasons) for season in tv_show_details['seasons'])
                poster = f"https://image.tmdb.org/t/p/w500{tv_show_details.poster_path}" if Telegram.USE_TMDB else tv_show_details['image']



                if Telegram.USE_TMDB:
                    backdrop = f"https://image.tmdb.org/t/p/original{tv_show_details.backdrop_path}"
                    status = tv_show_details.status
                else:
                    tv_shows = await tmdb.search().tv(query=title)
                    tv_show = tv_shows[0].id  # Get first result
                    tv_show_details_force = await tmdb.tv(tv_show).details()
                    backdrop = f"https://image.tmdb.org/t/p/original{tv_show_details_force.backdrop_path}"
                    status = tv_show_details_force.status
                
            
                genres = [genre.name for genre in tv_show_details.genres] if Telegram.USE_TMDB else tv_show_details['genre']
                media_type = "tv"

            # Return the TV show metadata
                return {
                "tmdb_id": tmdb_id,
                "title": title,
                "year": year,
                "rate": rate or 0,
                "description": description,
                "total_seasons": total_seasons,
                "total_episodes": total_episodes,
                "poster": poster or '',
                "backdrop": backdrop or '',
                "status": status,
                "genres": genres,
                "media_type": media_type,
                "season_number": season,
                "episode_number": episode,
                "episode_title": episode_title,
                "episode_backdrop": episode_backdrop,
                "quality": quality or "Unknown",
                "languages": languages or ['hi'],
                "rip": rip or 'Blu-ray'
                }

            except Exception as e:
                print(f"Error fetching TV show details: {e}")
                return None  # Or handle error as needed
        else:
            return await fetch_movie_metadata(title, year, quality, default_id, languages, rip)

async def fetch_movie_metadata(title, year=None, quality=None, default_id=None, languages=None, rip=None):
    query = f"{title} {year}" if year else title

    if title:
        try:
            if default_id is None:
                if Telegram.USE_TMDB:
                    movies = await tmdb.search().movies(query=title, year=year if year else None)
                    movie_id = movies[0].id
                    movies_details = await tmdb.movie(int(movie_id)).details()
                else:
                    movies = await search_title(query=query, type="movie")
                    movie_id = movies['id']
                    movies_details = await get_detail(imdb_id=movie_id)
            else:
                if default_id.startswith("tt"):
                    movies_details = await get_detail(imdb_id=default_id)
                else:
                    movies_details = await tmdb.movie(int(default_id)).details()

            # Extract relevant movie metadata
            tmdb_id = int(movies_details.id) if Telegram.USE_TMDB else int(movies_details['id'].replace("tt", ""))
            title = movies_details.title if Telegram.USE_TMDB else movies_details['title']
            year = movies_details.release_date.year if Telegram.USE_TMDB else movies_details['releaseDetailed']['year']
            rate = movies_details.vote_average if Telegram.USE_TMDB else movies_details['rating']['star']
            description = movies_details.overview if Telegram.USE_TMDB else movies_details['plot']
            poster = f"https://image.tmdb.org/t/p/w500{movies_details.poster_path}" if Telegram.USE_TMDB else movies_details['image']
            backdrop = f"https://image.tmdb.org/t/p/original{movies_details.backdrop_path}" if Telegram.USE_TMDB else None
            
            if not backdrop:
                movies = await tmdb.search().movies(query=title, year=year)
                movie = movies[0].id
                movies_details_force = await tmdb.movie(movie).details()
                backdrop = f"https://image.tmdb.org/t/p/original{movies_details_force.backdrop_path}"

            runtime = movies_details.runtime if Telegram.USE_TMDB else movies_details['runtimeSeconds'] // 60
            media_type = "movie"
            genres = [genre.name for genre in movies_details.genres] if Telegram.USE_TMDB else movies_details['genre']

            # Return the movie metadata
            return {
                "tmdb_id": tmdb_id,
                "title": title,
                "year": year,
                "rate": rate or 0,
                "description": description,
                "poster": poster or '',
                "backdrop": backdrop or '',
                "media_type": media_type,
                "genres": genres,
                "runtime": runtime or 0,
                "quality": quality or "Unknown",
                "languages": languages or ['hi'],
                "rip": rip or 'Blu-ray'
            }

        except Exception as e:
            print(f"Error fetching movie details: {e}")
            return None  # Or handle error as needed

async def search_tmdb(query: str, media_type: str):
    try:
        if media_type == "movie":
            results = await tmdb.search().movies(query=query)
        else:
            results = await tmdb.search().tv(query=query)
        
        parsed_results = []
        for r in results:
            parsed_results.append({
                "tmdb_id": r.id,
                "title": r.title if media_type == "movie" else r.name,
                "year": r.release_date.year if media_type == "movie" and r.release_date else (r.first_air_date.year if media_type == "tv" and r.first_air_date else None),
                "poster": f"https://image.tmdb.org/t/p/w500{r.poster_path}" if r.poster_path else None,
                "rating": r.vote_average
            })
        return parsed_results
    except Exception as e:
        print(f"Error searching TMDB: {e}")
        return []

async def search_imdb(query: str, media_type: str):
    try:
        # media_type from frontend is 'movie' or 'tv'
        imdb_type = "movie" if media_type == "movie" else "tvSeries"
        results = await search_title(query=query, type=imdb_type)
        if not results:
            return []
        
        # search_title returns a single result (first match) in current implementation
        # To make it consistent with search_tmdb, we'll return a list
        # But wait, search_title in helper/imdb.py only returns ONE result.
        # Let's fix that or work with it. 
        # Actually, let's look at imdb.py again.
        return [{
            "tmdb_id": results['id'], # This is actually imdb_id
            "title": results['title'],
            "year": results.get('releaseDetailed', {}).get('year'),
            "poster": results.get('image'),
            "rating": results.get('rating', {}).get('star')
        }]
    except Exception as e:
        print(f"Error searching IMDb: {e}")
        return []

async def get_external_details(external_id: str, media_type: str, source: str = "tmdb"):
    if source == "tmdb":
        try:
            tmdb_id = int(external_id)
            if media_type == "movie":
                details = await tmdb.movie(tmdb_id).details()
                return {
                    "tmdb_id": details.id,
                    "title": details.title,
                    "genres": [g.name for g in details.genres],
                    "description": details.overview,
                    "rating": details.vote_average,
                    "release_year": details.release_date.year if details.release_date else None,
                    "poster": f"https://image.tmdb.org/t/p/w500{details.poster_path}" if details.poster_path else '',
                    "backdrop": f"https://image.tmdb.org/t/p/original{details.backdrop_path}" if details.backdrop_path else '',
                    "runtime": details.runtime or 0,
                    "media_type": "movie",
                    "rip": "Blu-ray",
                    "languages": ["hi"],
                    "telegram": []
                }
            else:
                details = await tmdb.tv(tmdb_id).details()
                return {
                    "tmdb_id": details.id,
                    "title": details.name,
                    "genres": [g.name for g in details.genres],
                    "description": details.overview,
                    "rating": details.vote_average,
                    "release_year": details.first_air_date.year if details.first_air_date else None,
                    "poster": f"https://image.tmdb.org/t/p/w500{details.poster_path}" if details.poster_path else '',
                    "backdrop": f"https://image.tmdb.org/t/p/original{details.backdrop_path}" if details.backdrop_path else '',
                    "total_seasons": details.number_of_seasons,
                    "total_episodes": details.number_of_episodes,
                    "status": details.status,
                    "media_type": "tv",
                    "rip": "Blu-ray",
                    "languages": ["hi"],
                    "seasons": []
                }
        except Exception as e:
            print(f"Error fetching TMDB details: {e}")
            return None
    else:
        # IMDb source
        try:
            details = await get_detail(imdb_id=external_id)
            if media_type == "movie":
                return {
                    "tmdb_id": int(external_id.replace("tt", "")), 
                    "title": details['title'],
                    "genres": details.get('genre', []),
                    "description": details.get('plot', ''),
                    "rating": details.get('rating', {}).get('star', 0),
                    "release_year": details.get('releaseDetailed', {}).get('year'),
                    "poster": details.get('image', ''),
                    "backdrop": '', # Imdb doesn't easily provide backdrops in this helper
                    "runtime": details.get('runtimeSeconds', 0) // 60,
                    "media_type": "movie",
                    "rip": "Blu-ray",
                    "languages": ["hi"],
                    "telegram": []
                }
            else:
                return {
                    "tmdb_id": int(external_id.replace("tt", "")),
                    "title": details['title'],
                    "genres": details.get('genre', []),
                    "description": details.get('plot', ''),
                    "rating": details.get('rating', {}).get('star', 0),
                    "release_year": details.get('releaseDetailed', {}).get('year'),
                    "poster": details.get('image', ''),
                    "backdrop": '',
                    "total_seasons": len(details.get('all_seasons', [])),
                    "total_episodes": 0, # Hard to calculate easily without more calls
                    "status": "Unknown",
                    "media_type": "tv",
                    "rip": "Blu-ray",
                    "languages": ["hi"],
                    "seasons": []
                }
        except Exception as e:
            print(f"Error fetching IMDb details: {e}")
            return None
