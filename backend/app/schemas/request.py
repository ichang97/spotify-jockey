from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

TRACK_ID_REGEX = r"^[a-zA-Z0-9]{1,64}$"
URL_REGEX = r"^https?://.+"


class SongRequestCreate(BaseModel):
    requester_name: str = Field(..., min_length=1, max_length=64)
    spotify_track_id: str = Field(..., min_length=1, max_length=64, pattern=TRACK_ID_REGEX)
    track_title: str = Field(..., min_length=1, max_length=256)
    track_artist: str = Field(..., min_length=1, max_length=256)
    album_art_url: Optional[str] = Field(default=None, max_length=512, pattern=URL_REGEX)


class SongRequestStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(pending|accepted|rejected|played)$")


class SongRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_id: int
    requester_name: str
    spotify_track_id: str
    track_title: str
    track_artist: str
    album_art_url: Optional[str]
    status: str
    created_at: datetime
