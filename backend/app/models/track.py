from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TrackCache(Base):
    __tablename__ = "track_cache"

    spotify_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    artist: Mapped[str] = mapped_column(String(256), nullable=False)
    album: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    album_art_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
