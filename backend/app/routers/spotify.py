from urllib.parse import urlparse, quote
from typing import Optional
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Header, status
from fastapi.responses import StreamingResponse
from httpx import HTTPStatusError, AsyncClient, Timeout
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.station import Station
from app.schemas.spotify import SpotifySearchResult, SpotifyTrack, SpotifyPlayRequest
from app.services.spotify import SpotifyService
from app.services.librespot_service import librespot_service
from app.services.audio_mixer import audio_mixer_service
from app.services.audio_streamer import audio_streamer_service
from app.services.rate_limiter import rate_limit
from app.routers.stations import verify_dj_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/spotify", tags=["Spotify Operations"])

ALLOWED_AUDIO_DOMAINS = {
    "p.scdn.co",
    "audio-ssl.itunes.apple.com",
    "audio.itunes.apple.com",
    "cdns-preview-d.dzcdn.net",
    "cdns-preview-a.dzcdn.net",
    "cdns-preview-b.dzcdn.net",
    "cdns-preview-c.dzcdn.net",
}


def is_allowed_audio_domain(domain: str) -> bool:
    d = domain.lower()
    if d in ALLOWED_AUDIO_DOMAINS:
        return True
    if d.endswith(".dzcdn.net") or d.endswith(".scdn.co") or d.endswith(".itunes.apple.com") or d.endswith(".apple.com"):
        return True
    return False



async def get_station_id_and_token(slug: str, db: AsyncSession):
    stmt = select(Station.id).where(Station.slug == slug)
    res = await db.execute(stmt)
    station_row = res.first()
    if not station_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )
    station_id = station_row[0]
    token = await SpotifyService.get_valid_access_token(db, station_id)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Station has not connected Spotify yet or token expired"
        )
    return station_id, token


@router.get("/{slug}/token")
async def get_client_playback_token(
    slug: str,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    _, token = await get_station_id_and_token(slug, db)
    return {"access_token": token}


@router.get(
    "/{slug}/search",
    response_model=SpotifySearchResult,
    dependencies=[Depends(rate_limit(max_requests=30, window_seconds=60))]
)
async def search_spotify_tracks(
    slug: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=10),
    db: AsyncSession = Depends(get_db)
):
    _, token = await get_station_id_and_token(slug, db)
    try:
        results = await SpotifyService.search_tracks(
            db=db,
            access_token=token,
            query=q,
            limit=limit
        )
        return results
    except HTTPStatusError as http_err:
        logger.error(f"Spotify HTTP error during search: {http_err.response.status_code} - {http_err.response.text}")
        if http_err.response.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Spotify access token expired or invalid. Please reconnect Spotify in settings."
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Spotify API error ({http_err.response.status_code}): {http_err.response.text}"
        )
    except Exception as exc:
        logger.error(f"Unexpected search error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Spotify search error: {str(exc)}"
        )


@router.get("/{slug}/track/{track_id}", response_model=SpotifyTrack)
async def get_spotify_track(
    slug: str,
    track_id: str = Path(..., pattern=r"^[a-zA-Z0-9]{1,64}$"),
    db: AsyncSession = Depends(get_db)
):
    _, token = await get_station_id_and_token(slug, db)
    try:
        track = await SpotifyService.get_track_by_id(
            db=db,
            access_token=token,
            track_id=track_id
        )
        if not track:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Track not found"
            )
        return track
    except HTTPException:
        raise
    except HTTPStatusError as http_err:
        logger.error(f"Spotify HTTP error getting track: {http_err.response.status_code} - {http_err.response.text}")
        if http_err.response.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Spotify access token expired or invalid. Please reconnect Spotify in settings."
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Spotify API error ({http_err.response.status_code})"
        )
    except Exception as exc:
        logger.error(f"Unexpected error getting track: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc)
        )


@router.get("/{slug}/preview-proxy")
async def proxy_audio_preview(
    slug: str,
    url: str = Query(..., min_length=10)
):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not is_allowed_audio_domain(parsed.netloc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid audio source domain"
        )

    client = AsyncClient(timeout=15.0)
    try:
        req = client.build_request("GET", url)
        resp = await client.send(req, stream=True)
    except Exception:
        await client.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch remote audio preview"
        )

    async def stream_audio():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Cache-Control": "public, max-age=86400",
    }
    content_type = resp.headers.get("content-type", "audio/mp4")
    content_length = resp.headers.get("content-length")
    if content_length:
        headers["Content-Length"] = content_length

    return StreamingResponse(
        stream_audio(),
        media_type=content_type,
        status_code=resp.status_code,
        headers=headers
    )


@router.get("/{slug}/librespot/status")
async def get_librespot_status(slug: str):
    return librespot_service.get_status(slug)


@router.post("/{slug}/librespot/start")
async def start_librespot(
    slug: str,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    _, token = await get_station_id_and_token(slug, db)
    started = await librespot_service.start_station_daemon(slug)
    pipe_path = librespot_service.get_pipe_path(slug)
    await audio_mixer_service.start_mixer(slug, pipe_path)
    return {"started": started, "status": librespot_service.get_status(slug)}


@router.post("/{slug}/librespot/stop")
async def stop_librespot(
    slug: str,
    _=Depends(verify_dj_session)
):
    await audio_mixer_service.stop_mixer(slug)
    await librespot_service.stop_station_daemon(slug)
    return {"message": "librespot stopped"}


@router.get("/{slug}/devices")
async def get_spotify_devices(
    slug: str,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    _, token = await get_station_id_and_token(slug, db)
    devices = await SpotifyService.get_user_devices(token)
    target_name = f"SpotifyJockey-{slug}"
    enriched = []
    for d in devices:
        item = dict(d)
        item["is_station_device"] = (d.get("name") == target_name)
        enriched.append(item)
    return {"devices": enriched}


@router.post("/{slug}/play")
async def play_spotify_track(
    slug: str,
    req: SpotifyPlayRequest,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    _, token = await get_station_id_and_token(slug, db)

    if not librespot_service.is_running(slug):
        await librespot_service.start_station_daemon(slug)
        pipe_path = librespot_service.get_pipe_path(slug)
        await audio_mixer_service.start_mixer(slug, pipe_path)

    device_id = req.device_id
    if not device_id:
        devices = await SpotifyService.get_user_devices(token)
        target_name = f"SpotifyJockey-{slug}"
        for d in devices:
            if d.get("name") == target_name:
                device_id = d.get("id")
                break
        if not device_id and devices:
            for d in devices:
                if d.get("is_active"):
                    device_id = d.get("id")
                    break

    uris = req.uris
    if not uris and req.uri:
        uris = [req.uri]

    success = await SpotifyService.play_track(
        access_token=token,
        device_id=device_id,
        uris=uris,
        context_uri=req.context_uri,
        position_ms=req.position_ms
    )
    return {"success": success, "device_id": device_id}


@router.post("/{slug}/pause")
async def pause_spotify_track(
    slug: str,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    _, token = await get_station_id_and_token(slug, db)
    success = await SpotifyService.pause_playback(token)
    return {"success": success}


@router.post("/{slug}/resume")
async def resume_spotify_track(
    slug: str,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    _, token = await get_station_id_and_token(slug, db)
    success = await SpotifyService.resume_playback(token)
    return {"success": success}


@router.get("/{slug}/player")
async def get_player_state(
    slug: str,
    db: AsyncSession = Depends(get_db)
):
    _, token = await get_station_id_and_token(slug, db)
    state = await SpotifyService.get_playback_state(token)
    return {"state": state}


@router.get("/{slug}/stream-url")
async def get_track_stream_url(
    slug: str,
    title: str = Query(..., min_length=1),
    artist: str = Query(..., min_length=1),
    track_id: Optional[str] = Query(None)
):
    stream_url = await audio_streamer_service.resolve_stream_url(title, artist, track_id)
    if not stream_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unable to resolve full audio stream for this track"
        )
    return {
        "stream_url": stream_url,
        "proxy_url": f"/api/spotify/{slug}/audio-proxy?url={quote(stream_url, safe='')}"
    }


@router.get("/{slug}/audio-proxy")
async def proxy_full_audio_stream(
    slug: str,
    url: str = Query(..., min_length=10),
    range_header: Optional[str] = Header(None, alias="Range")
):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }
    if range_header:
        headers["Range"] = range_header

    client = AsyncClient(timeout=Timeout(None, connect=15.0), follow_redirects=True)
    try:
        req = client.build_request("GET", url, headers=headers)
        resp = await client.send(req, stream=True)
    except Exception:
        await client.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch remote audio stream"
        )

    async def stream_audio():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    response_headers = {
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    }
    for k in ("Content-Range", "Content-Length", "Content-Type"):
        v = resp.headers.get(k)
        if v:
            response_headers[k] = v

    return StreamingResponse(
        stream_audio(),
        status_code=resp.status_code,
        media_type=resp.headers.get("Content-Type", "audio/webm"),
        headers=response_headers
    )
