import base64
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Header, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.database import get_db
from app.models.station import Station
from app.models.auth import StationAuth
from app.schemas.spotify import SpotifyAuthUrlResponse
from app.services.spotify import SpotifyService
from app.services.token_vault import TokenVaultService
from app.services.librespot_service import librespot_service
from app.services.audio_mixer import audio_mixer_service
from app.routers.stations import verify_dj_session
from app.security import create_oauth_state, verify_oauth_state

settings = get_settings()
router = APIRouter(prefix="/api/auth/spotify", tags=["Spotify Auth"])


@router.get("/login", response_model=SpotifyAuthUrlResponse)
async def spotify_login(
    station_slug: str = Query(...),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    await verify_dj_session(station_slug, authorization)
    stmt = select(Station.id).where(Station.slug == station_slug)
    res = await db.execute(stmt)
    if not res.first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    signed_state = create_oauth_state(station_slug, expires_in_seconds=600)
    auth_url = SpotifyService.get_authorization_url(signed_state)
    return SpotifyAuthUrlResponse(auth_url=auth_url, state=signed_state)


@router.get("/callback")
async def spotify_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    base_url = settings.FRONTEND_PUBLIC_URL.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(
            url=f"{base_url}/?error=spotify_auth_failed",
            status_code=status.HTTP_302_FOUND
        )

    try:
        decoded = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
        station_slug = decoded.split(":")[0]
    except Exception:
        return RedirectResponse(
            url=f"{base_url}/?error=invalid_state_format",
            status_code=status.HTTP_302_FOUND
        )

    if not verify_oauth_state(state, station_slug):
        return RedirectResponse(
            url=f"{base_url}/?error=oauth_csrf_rejected",
            status_code=status.HTTP_302_FOUND
        )

    stmt = select(Station.id).where(Station.slug == station_slug)
    res = await db.execute(stmt)
    station_row = res.first()
    if not station_row:
        return RedirectResponse(
            url=f"{base_url}/?error=station_not_found",
            status_code=status.HTTP_302_FOUND
        )

    station_id = station_row[0]

    try:
        token_data = await SpotifyService.exchange_code_for_tokens(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        spotify_user_id = None
        try:
            profile = await SpotifyService.get_current_user_profile(access_token)
            spotify_user_id = profile.get("id")
        except Exception:
            pass

        await TokenVaultService.save_station_tokens(
            db=db,
            station_id=station_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            spotify_user_id=spotify_user_id
        )

        try:
            await librespot_service.start_station_daemon(station_slug)
            pipe_path = librespot_service.get_pipe_path(station_slug)
            await audio_mixer_service.start_mixer(station_slug, pipe_path)
        except Exception:
            pass

        return RedirectResponse(
            url=f"{base_url}/studio/{station_slug}?connected=true",
            status_code=status.HTTP_302_FOUND
        )
    except Exception:
        return RedirectResponse(
            url=f"{base_url}/studio/{station_slug}?error=token_exchange_failed",
            status_code=status.HTTP_302_FOUND
        )


@router.get("/status/{slug}")
async def get_spotify_status(slug: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(StationAuth.id, StationAuth.spotify_user_id, StationAuth.token_expires_at)
        .join(Station, Station.id == StationAuth.station_id)
        .where(Station.slug == slug)
    )
    res = await db.execute(stmt)
    row = res.first()
    if not row:
        return {"connected": False}

    return {
        "connected": True,
        "spotify_user_id": row[1],
        "expires_at": row[2]
    }


@router.post("/disconnect/{slug}")
async def disconnect_spotify(
    slug: str,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Station.id).where(Station.slug == slug)
    res = await db.execute(stmt)
    station_row = res.first()
    if not station_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    await TokenVaultService.delete_station_tokens(db, station_row[0])
    try:
        await audio_mixer_service.stop_mixer(slug)
        await librespot_service.stop_station_daemon(slug)
    except Exception:
        pass
    return {"message": "Spotify disconnected successfully"}
