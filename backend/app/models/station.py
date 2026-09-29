from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import Integer, String, Text, Boolean, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.auth import StationAuth
    from app.models.request import SongRequest
    from app.models.chat import ChatMessage
    from app.models.queue import StationQueueItem


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    passcode_hash: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    palette_config: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: {
            "bg_base": "#0a0c10",
            "bg_surface": "#13161f",
            "bg_card": "#1c202b",
            "border": "#2a3040",
            "text_main": "#f8fafc",
            "text_muted": "#94a3b8",
            "accent": "#10b981",
            "accent_hover": "#059669",
            "live": "#ef4444"
        },
        nullable=False
    )
    is_live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_listeners: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_track: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    auth: Mapped[Optional["StationAuth"]] = relationship("StationAuth", back_populates="station", uselist=False, cascade="all, delete-orphan")
    requests: Mapped[List["SongRequest"]] = relationship("SongRequest", back_populates="station", cascade="all, delete-orphan")
    chat_messages: Mapped[List["ChatMessage"]] = relationship("ChatMessage", back_populates="station", cascade="all, delete-orphan")
    queue_items: Mapped[List["StationQueueItem"]] = relationship("StationQueueItem", back_populates="station", cascade="all, delete-orphan", order_by="StationQueueItem.order_index")
