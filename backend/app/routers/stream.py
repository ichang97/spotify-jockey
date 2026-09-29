from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from app.database import async_session_factory
from app.models.station import Station
from app.services.audio_relay import audio_relay_service
from app.services.audio_mixer import audio_mixer_service

router = APIRouter(prefix="/api/stations", tags=["Audio Stream"])


@router.get("/{slug}/stream")
async def stream_station_audio(slug: str):
    async with async_session_factory() as db:
        stmt = select(Station.id, Station.is_live).where(Station.slug == slug)
        res = await db.execute(stmt)
        station_row = res.first()

    if not station_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    is_live = audio_relay_service.is_broadcasting(slug) or audio_mixer_service.is_active(slug)
    if not is_live:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Station is currently offline. Live stream is not active."
        )

    if audio_relay_service.get_listener_count(slug) >= 1000:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Station has reached maximum listener capacity."
        )

    return StreamingResponse(
        audio_relay_service.subscribe_listener(slug),
        media_type="audio/webm;codecs=opus",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
        }
    )


@router.get("/{slug}/stream/status")
async def get_stream_status(slug: str):
    async with async_session_factory() as db:
        stmt = select(Station.id, Station.is_live).where(Station.slug == slug)
        res = await db.execute(stmt)
        station_row = res.first()

    if not station_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    is_live = audio_relay_service.is_broadcasting(slug) or audio_mixer_service.is_active(slug)
    return {
        "slug": slug,
        "is_broadcasting": is_live,
        "listeners_count": audio_relay_service.get_listener_count(slug),
        "is_live_flag": bool(station_row[1])
    }


@router.get("/{slug}/monitor")
async def stream_dj_monitor(slug: str):
    async with async_session_factory() as db:
        stmt = select(Station.id).where(Station.slug == slug)
        res = await db.execute(stmt)
        station_row = res.first()

    if not station_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    if audio_relay_service.is_broadcasting(slug):
        stream_gen = audio_relay_service.subscribe_listener(slug)
    elif audio_mixer_service.is_active(slug):
        stream_gen = audio_mixer_service.subscribe_monitor(slug)
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Monitor stream is not active."
        )

    return StreamingResponse(
        stream_gen,
        media_type="audio/webm;codecs=opus",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
        }
    )
