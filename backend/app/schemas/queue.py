from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class QueueItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    artist: str = Field(..., min_length=1, max_length=256)
    spotify_track_id: Optional[str] = Field(default=None, max_length=64)
    album: Optional[str] = Field(default=None, max_length=256)
    album_art_url: Optional[str] = Field(default=None, max_length=512)
    preview_url: Optional[str] = Field(default=None, max_length=512)
    duration_ms: int = Field(default=0, ge=0)


class QueueItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_id: int
    spotify_track_id: Optional[str] = None
    title: str
    artist: str
    album: Optional[str] = None
    album_art_url: Optional[str] = None
    preview_url: Optional[str] = None
    duration_ms: int
    order_index: int
    created_at: datetime


class QueueReorderRequest(BaseModel):
    item_ids: List[int] = Field(..., min_length=1)


class NowPlayingUpdateRequest(BaseModel):
    track: Optional[dict] = None


class StationQueueStateResponse(BaseModel):
    current_track: Optional[dict] = None
    queue: List[QueueItemResponse]
    up_next: Optional[QueueItemResponse] = None
