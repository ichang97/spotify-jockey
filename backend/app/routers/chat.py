import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.station import Station
from app.models.chat import ChatMessage
from app.schemas.chat import ChatMessageCreate, ChatMessageResponse
from app.services.websocket_hub import websocket_hub
from app.services.rate_limiter import rate_limit
from app.security import verify_dj_session_token

router = APIRouter(prefix="/api/stations", tags=["Chat"])


@router.get("/{slug}/chat", response_model=List[ChatMessageResponse])
async def get_station_chat(slug: str, db: AsyncSession = Depends(get_db)):
    stmt_station = select(Station.id).where(Station.slug == slug)
    res_station = await db.execute(stmt_station)
    station_row = res_station.first()
    if not station_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    stmt = (
        select(
            ChatMessage.id,
            ChatMessage.station_id,
            ChatMessage.sender_name,
            ChatMessage.is_dj,
            ChatMessage.message,
            ChatMessage.created_at
        )
        .where(ChatMessage.station_id == station_row[0])
        .order_by(ChatMessage.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    rows = result.all()

    messages = []
    for r in reversed(rows):
        messages.append(
            ChatMessageResponse(
                id=r.id,
                station_id=r.station_id,
                sender_name=r.sender_name,
                is_dj=r.is_dj,
                message=r.message,
                created_at=r.created_at
            )
        )
    return messages


@router.post(
    "/{slug}/chat",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(max_requests=20, window_seconds=60))]
)
async def post_chat_message(
    slug: str,
    chat_in: ChatMessageCreate,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    stmt_station = select(Station.id).where(Station.slug == slug)
    res_station = await db.execute(stmt_station)
    station_row = res_station.first()
    if not station_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    is_verified_dj = False
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if verify_dj_session_token(token, slug):
            is_verified_dj = True

    if is_verified_dj:
        final_sender_name = chat_in.sender_name.strip() or "DJ"
    else:
        clean_name = re.sub(r"(?i)\b(dj|admin|host|mod|moderator)\b|[🎧🎙️📻]", "", chat_in.sender_name).strip()
        final_sender_name = clean_name if len(clean_name) >= 1 else "Listener"

    new_msg = ChatMessage(
        station_id=station_row[0],
        sender_name=final_sender_name,
        is_dj=is_verified_dj,
        message=chat_in.message
    )
    db.add(new_msg)
    await db.commit()
    await db.refresh(new_msg)

    response_data = ChatMessageResponse.model_validate(new_msg)

    await websocket_hub.broadcast_to_station(
        station_slug=slug,
        message={
            "type": "chat_message",
            "data": response_data.model_dump(mode="json")
        }
    )

    return response_data
