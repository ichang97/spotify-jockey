from typing import List, Optional
from pydantic import BaseModel, Field


class SpotifyTrack(BaseModel):
    id: str
    title: str
    artist: str
    album: Optional[str] = None
    album_art_url: Optional[str] = None
    duration_ms: int = 0
    uri: Optional[str] = None
    preview_url: Optional[str] = None


class SpotifySearchResult(BaseModel):
    query: str
    tracks: List[SpotifyTrack] = Field(default_factory=list)


class SpotifyAuthUrlResponse(BaseModel):
    auth_url: str
    state: str


class NowPlayingUpdate(BaseModel):
    track: Optional[SpotifyTrack] = None
    is_playing: bool = False
    progress_ms: int = 0
    timestamp: int = 0


class SpotifyPlayRequest(BaseModel):
    uri: Optional[str] = None
    uris: Optional[List[str]] = None
    context_uri: Optional[str] = None
    device_id: Optional[str] = None
    position_ms: int = 0
