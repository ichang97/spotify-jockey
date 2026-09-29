from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class SongRequest(Base):
    __tablename__ = "song_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True)
    requester_name: Mapped[str] = mapped_column(String(64), nullable=False)
    spotify_track_id: Mapped[str] = mapped_column(String(64), nullable=False)
    track_title: Mapped[str] = mapped_column(String(256), nullable=False)
    track_artist: Mapped[str] = mapped_column(String(256), nullable=False)
    album_art_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    station: Mapped["Station"] = relationship("Station", back_populates="requests")
