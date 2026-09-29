from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

HEX_COLOR_REGEX = r"^#[0-9a-fA-F]{6}$"


class PaletteConfig(BaseModel):
    bg_base: str = Field(default="#0a0c10", pattern=HEX_COLOR_REGEX)
    bg_surface: str = Field(default="#13161f", pattern=HEX_COLOR_REGEX)
    bg_card: str = Field(default="#1c202b", pattern=HEX_COLOR_REGEX)
    border: str = Field(default="#2a3040", pattern=HEX_COLOR_REGEX)
    text_main: str = Field(default="#f8fafc", pattern=HEX_COLOR_REGEX)
    text_muted: str = Field(default="#94a3b8", pattern=HEX_COLOR_REGEX)
    accent: str = Field(default="#10b981", pattern=HEX_COLOR_REGEX)
    accent_hover: str = Field(default="#059669", pattern=HEX_COLOR_REGEX)
    live: str = Field(default="#ef4444", pattern=HEX_COLOR_REGEX)


class StationBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    description: Optional[str] = Field(default=None, max_length=1000)
    palette_config: PaletteConfig = Field(default_factory=PaletteConfig)


class StationCreate(StationBase):
    slug: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    passcode: Optional[str] = Field(default=None, min_length=4, max_length=64)


class StationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=128)
    description: Optional[str] = Field(default=None, max_length=1000)
    palette_config: Optional[PaletteConfig] = None
    is_live: Optional[bool] = None
    passcode: Optional[str] = Field(default=None, min_length=4, max_length=64)


class StationResponse(StationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    is_live: bool
    current_listeners: int
    created_at: datetime
    is_spotify_connected: bool = False
    has_passcode: bool = True


class StationAuthVerify(BaseModel):
    passcode: str = Field(..., min_length=1, max_length=64)


class StationAuthToken(BaseModel):
    token: str
    expires_in: int
