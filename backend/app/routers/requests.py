from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.station import Station
from app.models.request import SongRequest
from app.schemas.request import (
    SongRequestCreate,
    SongRequestResponse,
    SongRequestStatusUpdate,
)
from app.services.websocket_hub import websocket_hub
from app.services.rate_limiter import rate_limit
from app.routers.stations import verify_dj_session

router = APIRouter(prefix="/api/stations", tags=["Song Requests"])


@router.get("/{slug}/requests", response_model=List[SongRequestResponse])
async def list_song_requests(slug: str, db: AsyncSession = Depends(get_db)):
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
            SongRequest.id,
            SongRequest.station_id,
            SongRequest.requester_name,
            SongRequest.spotify_track_id,
            SongRequest.track_title,
            SongRequest.track_artist,
            SongRequest.album_art_url,
            SongRequest.status,
            SongRequest.created_at
        )
        .where(SongRequest.station_id == station_row[0])
        .order_by(SongRequest.created_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for r in rows:
        items.append(
            SongRequestResponse(
                id=r.id,
                station_id=r.station_id,
                requester_name=r.requester_name,
                spotify_track_id=r.spotify_track_id,
                track_title=r.track_title,
                track_artist=r.track_artist,
                album_art_url=r.album_art_url,
                status=r.status,
                created_at=r.created_at
            )
        )
    return items


@router.post(
    "/{slug}/requests",
    response_model=SongRequestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(max_requests=10, window_seconds=300))]
)
async def submit_song_request(
    slug: str,
    req_in: SongRequestCreate,
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

    new_req = SongRequest(
        station_id=station_row[0],
        requester_name=req_in.requester_name,
        spotify_track_id=req_in.spotify_track_id,
        track_title=req_in.track_title,
        track_artist=req_in.track_artist,
        album_art_url=req_in.album_art_url,
        status="pending"
    )
    db.add(new_req)
    await db.commit()
    await db.refresh(new_req)

    response_data = SongRequestResponse.model_validate(new_req)

    await websocket_hub.broadcast_to_station(
        station_slug=slug,
        message={
            "type": "new_request",
            "data": response_data.model_dump(mode="json")
        }
    )

    return response_data


@router.patch("/{slug}/requests/{req_id}", response_model=SongRequestResponse)
async def update_song_request_status(
    slug: str,
    req_id: int,
    status_in: SongRequestStatusUpdate,
    _=Depends(verify_dj_session),
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

    stmt_req = select(SongRequest).where(
        SongRequest.id == req_id,
        SongRequest.station_id == station_row[0]
    )
    result = await db.execute(stmt_req)
    req_item = result.scalar_one_or_none()
    if not req_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Song request not found"
        )

    req_item.status = status_in.status
    await db.commit()
    await db.refresh(req_item)

    response_data = SongRequestResponse.model_validate(req_item)

    await websocket_hub.broadcast_to_station(
        station_slug=slug,
        message={
            "type": "request_status_changed",
            "data": response_data.model_dump(mode="json")
        }
    )

    return response_data
