from datetime import datetime
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional

class QualityDetail(BaseModel):
    quality: str = Field(..., description="Quality of the video (e.g., 1080p, 720p)")
    id: str = Field(..., description="Unique hash for the video")
    name: str = Field(..., description="Original Filename of telegram file")
    size: str = Field(..., description="Size of the File")

class Episode(BaseModel):
    episode_number: int = Field(..., description="Episode number within the season")
    title: str = Field(..., description="Title of the episode")
    episode_backdrop: str = Field(..., description="Backdrop of Episode")
    telegram: Optional[List[QualityDetail]] = Field(None, description="List of available quality details")

class Season(BaseModel):
    season_number: int = Field(..., description="Season number within the TV show")
    episodes: List[Episode] = Field(..., description="List of episodes in the season")

class TVShowSchema(BaseModel):
    tmdb_id: int = Field(..., description="The TMDB ID of the TV show")
    title: str = Field(..., description="Title of the TV show")
    genres: List[str] = Field(..., description="List of genres associated with the TV show")
    description: str = Field(..., description="Brief description of the TV show")
    rating: float = Field(..., description="Average rating of the TV show")
    release_year: int = Field(..., description="Release year of the TV show")
    poster: str = Field(..., description="URL to the poster image")
    backdrop: str = Field(..., description="URL to the backdrop image")
    total_seasons: int = Field(..., description="Total Season of tv show")
    total_episodes: int = Field(..., description="Total Episode of tv show")
    media_type: str = Field(..., description="Media Type of the file")
    status: str = Field(..., description="Status update of tv show")
    updated_on: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the last update")
    languages: List[str] = Field(..., description="List of languages associated with the Movie")
    rip: str = Field(..., description="Media rip of the file")
    seasons: List[Season] = Field(..., description="List of seasons in the TV show")



class MovieSchema(BaseModel):
    tmdb_id: int = Field(..., description="The TMDB ID of the Movie")
    title: str = Field(..., description="Title of the Movie")
    genres: List[str] = Field(..., description="List of genres associated with the Movie")
    description: str = Field(..., description="Brief description of the Movie")
    rating: float = Field(..., description="Average rating of the Movie")
    release_year: int = Field(..., description="Release year of the Movie")
    poster: str = Field(..., description="URL to the poster image")
    backdrop: str = Field(..., description="URL to the backdrop image")
    media_type: str = Field(..., description="Media Type of the file")
    runtime: int = Field(..., description="runtime of the movie")
    updated_on: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the last update")
    languages: List[str] = Field(..., description="List of languages associated with the Movie")
    rip: str = Field(..., description="Media rip of the file")
    telegram: Optional[List[QualityDetail]] = Field(None, description="List of available quality details")

class SettingsSchema(BaseModel):
    buttonColor: Optional[str] = Field(None, description="Primary button color")
    buttonHoverColor: Optional[str] = Field(None, description="Hover color for buttons")
    defaultTheme: Optional[str] = Field(None, description="Default theme (light/dark/system)")
    structuralTheme: Optional[str] = Field(None, description="Global structural architecture theme")
    showThemeToggle: Optional[bool] = Field(None, description="Whether to show the theme toggle button")
    showAds: Optional[bool] = Field(False, description="Global toggle to show or hide ads")
    adHeader: Optional[str] = Field(None, description="HTML/JS snippet for Header Ad")
    adFooter: Optional[str] = Field(None, description="HTML/JS snippet for Footer Ad")
    adSidebar: Optional[str] = Field(None, description="HTML/JS snippet for Sidebar Ad")
    adPopup: Optional[str] = Field(None, description="HTML/JS snippet for Popup/Interstitial Ad")
    adBanner: Optional[str] = Field(None, description="HTML/JS snippet for Top Wide Banner Ad")
    adInFeed: Optional[str] = Field(None, description="HTML/JS snippet for In-Feed Grid Ad")
    adPlayerBottom: Optional[str] = Field(None, description="HTML/JS snippet for Below Player Ad")
    adTop: Optional[str] = Field(None, description="HTML/JS snippet for Top Navbar Ad")
    siteName: Optional[str] = Field(None, description="Site name for display")
    telegramUrl: Optional[str] = Field(None, description="Telegram community URL")