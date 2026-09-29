from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.station import Station
from app.models.queue import StationQueueItem
from app.schemas.queue import (
    QueueItemCreate,
    QueueItemResponse,
    QueueReorderRequest,
    NowPlayingUpdateRequest,
    StationQueueStateResponse,
)
from app.services.websocket_hub import websocket_hub
from app.routers.stations import verify_dj_session

router = APIRouter(prefix="/api/stations", tags=["Station Queue"])


@router.get("/{slug}/queue", response_model=StationQueueStateResponse)
async def get_station_queue(slug: str, db: AsyncSession = Depends(get_db)):
    stmt_station = select(Station.id, Station.current_track).where(Station.slug == slug)
    res_station = await db.execute(stmt_station)
    station_row = res_station.first()
    if not station_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )
    station_id, current_track = station_row

    stmt_items = (
        select(
            StationQueueItem.id,
            StationQueueItem.station_id,
            StationQueueItem.spotify_track_id,
            StationQueueItem.title,
            StationQueueItem.artist,
            StationQueueItem.album,
            StationQueueItem.album_art_url,
            StationQueueItem.preview_url,
            StationQueueItem.duration_ms,
            StationQueueItem.order_index,
            StationQueueItem.created_at,
        )
        .where(StationQueueItem.station_id == station_id)
        .order_by(StationQueueItem.order_index.asc())
    )
    res_items = await db.execute(stmt_items)
    rows = res_items.all()

    items: List[QueueItemResponse] = [
        QueueItemResponse(
            id=r.id,
            station_id=r.station_id,
            spotify_track_id=r.spotify_track_id,
            title=r.title,
            artist=r.artist,
            album=r.album,
            album_art_url=r.album_art_url,
            preview_url=r.preview_url,
            duration_ms=r.duration_ms,
            order_index=r.order_index,
            created_at=r.created_at,
        )
        for r in rows
    ]

    up_next = items[0] if items else None
    return StationQueueStateResponse(
        current_track=current_track,
        queue=items,
        up_next=up_next
    )


@router.post("/{slug}/queue", response_model=QueueItemResponse, status_code=status.HTTP_201_CREATED)
async def add_item_to_queue(
    slug: str,
    item_in: QueueItemCreate,
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
    station_id = station_row[0]

    stmt_max = select(func.coalesce(func.max(StationQueueItem.order_index), -1)).where(
        StationQueueItem.station_id == station_id
    )
    res_max = await db.execute(stmt_max)
    max_idx = res_max.scalar_one()

    new_item = StationQueueItem(
        station_id=station_id,
        spotify_track_id=item_in.spotify_track_id,
        title=item_in.title,
        artist=item_in.artist,
        album=item_in.album,
        album_art_url=item_in.album_art_url,
        preview_url=item_in.preview_url,
        duration_ms=item_in.duration_ms,
        order_index=max_idx + 1,
    )
    db.add(new_item)
    await db.commit()
    await db.refresh(new_item)

    response_data = QueueItemResponse.model_validate(new_item)
    await websocket_hub.broadcast_to_station(
        slug,
        {
            "type": "queue_updated",
            "data": {"action": "add", "item": response_data.model_dump(mode="json")}
        }
    )
    return response_data


@router.delete("/{slug}/queue/{item_id}")
async def remove_item_from_queue(
    slug: str,
    item_id: int,
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
    station_id = station_row[0]

    stmt_item = select(StationQueueItem).where(
        StationQueueItem.id == item_id,
        StationQueueItem.station_id == station_id
    )
    res_item = await db.execute(stmt_item)
    target = res_item.scalar_one_or_none()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Queue item not found"
        )

    await db.delete(target)
    await db.commit()

    stmt_remaining = (
        select(StationQueueItem)
        .where(StationQueueItem.station_id == station_id)
        .order_by(StationQueueItem.order_index.asc())
    )
    res_remaining = await db.execute(stmt_remaining)
    remaining_items = res_remaining.scalars().all()
    for idx, item in enumerate(remaining_items):
        item.order_index = idx
    await db.commit()

    await websocket_hub.broadcast_to_station(
        slug,
        {
            "type": "queue_updated",
            "data": {"action": "remove", "id": item_id}
        }
    )
    return {"status": "ok", "deleted_id": item_id}


@router.put("/{slug}/queue/reorder")
async def reorder_queue(
    slug: str,
    body: QueueReorderRequest,
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
    station_id = station_row[0]

    stmt_items = select(StationQueueItem).where(
        StationQueueItem.station_id == station_id
    )
    res_items = await db.execute(stmt_items)
    items = {item.id: item for item in res_items.scalars().all()}

    for order_pos, item_id in enumerate(body.item_ids):
        if item_id in items:
            items[item_id].order_index = order_pos

    await db.commit()
    await websocket_hub.broadcast_to_station(
        slug,
        {
            "type": "queue_updated",
            "data": {"action": "reorder"}
        }
    )
    return {"status": "ok"}


@router.delete("/{slug}/queue")
async def clear_queue(
    slug: str,
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
    station_id = station_row[0]

    stmt_del = delete(StationQueueItem).where(StationQueueItem.station_id == station_id)
    await db.execute(stmt_del)
    await db.commit()

    await websocket_hub.broadcast_to_station(
        slug,
        {
            "type": "queue_updated",
            "data": {"action": "clear"}
        }
    )
    return {"status": "ok", "cleared": True}


@router.post("/{slug}/queue/next")
async def play_next_in_queue(
    slug: str,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    stmt_station = select(Station).where(Station.slug == slug)
    res_station = await db.execute(stmt_station)
    station = res_station.scalar_one_or_none()
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    stmt_next = (
        select(StationQueueItem)
        .where(StationQueueItem.station_id == station.id)
        .order_by(StationQueueItem.order_index.asc())
        .limit(1)
    )
    res_next = await db.execute(stmt_next)
    next_item = res_next.scalar_one_or_none()
    if not next_item:
        station.current_track = None
        await db.commit()
        await websocket_hub.broadcast_to_station(
            slug,
            {
                "type": "now_playing",
                "data": {"track": None, "is_playing": False, "progress_ms": 0, "timestamp": 0}
            }
        )
        return {"track": None}

    next_track = {
        "id": next_item.spotify_track_id,
        "title": next_item.title,
        "artist": next_item.artist,
        "album": next_item.album,
        "album_art_url": next_item.album_art_url,
        "preview_url": next_item.preview_url,
        "duration_ms": next_item.duration_ms,
    }
    station.current_track = next_track
    await db.delete(next_item)
    await db.commit()

    stmt_remaining = (
        select(StationQueueItem)
        .where(StationQueueItem.station_id == station.id)
        .order_by(StationQueueItem.order_index.asc())
    )
    res_remaining = await db.execute(stmt_remaining)
    remaining_items = res_remaining.scalars().all()
    for idx, item in enumerate(remaining_items):
        item.order_index = idx
    await db.commit()

    await websocket_hub.broadcast_to_station(
        slug,
        {
            "type": "queue_updated",
            "data": {"action": "next", "track": next_track}
        }
    )
    return {"track": next_track}


@router.put("/{slug}/now-playing")
async def update_now_playing(
    slug: str,
    body: NowPlayingUpdateRequest,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    stmt_station = select(Station).where(Station.slug == slug)
    res_station = await db.execute(stmt_station)
    station = res_station.scalar_one_or_none()
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    station.current_track = body.track
    await db.commit()

    await websocket_hub.broadcast_to_station(
        slug,
        {
            "type": "now_playing",
            "data": {
                "track": body.track,
                "is_playing": False,
                "progress_ms": 0,
                "timestamp": 0
            }
        }
    )
    return {"status": "ok", "current_track": station.current_track}
