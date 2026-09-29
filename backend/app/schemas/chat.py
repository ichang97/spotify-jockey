from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ChatMessageCreate(BaseModel):
    sender_name: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=1000)


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_id: int
    sender_name: str
    is_dj: bool
    message: str
    created_at: datetime
