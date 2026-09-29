import logging
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from httpx import AsyncClient, BasicAuth
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.models.track import TrackCache
from app.schemas.spotify import SpotifyTrack, SpotifySearchResult
from app.services.token_vault import TokenVaultService

logger = logging.getLogger(__name__)
settings = get_settings()


class SpotifyService:
    SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
    SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
    SPOTIFY_API_BASE = "https://api.spotify.com/v1"

    SCOPES = [
        "streaming",
        "user-read-email",
        "user-read-private",
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
    ]

    @classmethod
    def get_authorization_url(cls, state: str) -> str:
        params = {
            "client_id": settings.SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
            "scope": " ".join(cls.SCOPES),
            "state": state,
            "show_dialog": "true",
        }
        return f"{cls.SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}"

    @classmethod
    async def exchange_code_for_tokens(cls, code: str) -> Dict[str, Any]:
        async with AsyncClient() as client:
            auth = BasicAuth(settings.SPOTIFY_CLIENT_ID, settings.SPOTIFY_CLIENT_SECRET)
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
            }
            response = await client.post(cls.SPOTIFY_TOKEN_URL, data=data, auth=auth)
            response.raise_for_status()
            return response.json()

    @classmethod
    async def refresh_access_token(cls, refresh_token: str) -> Dict[str, Any]:
        async with AsyncClient() as client:
            auth = BasicAuth(settings.SPOTIFY_CLIENT_ID, settings.SPOTIFY_CLIENT_SECRET)
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
            response = await client.post(cls.SPOTIFY_TOKEN_URL, data=data, auth=auth)
            response.raise_for_status()
            return response.json()

    @classmethod
    async def get_valid_access_token(
        cls,
        db: AsyncSession,
        station_id: int
    ) -> Optional[str]:
        tokens = await TokenVaultService.get_station_tokens(db, station_id)
        if not tokens:
            return None

        access_token, refresh_token, expires_at = tokens
        now = datetime.now(timezone.utc)

        if expires_at:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > (now + timedelta(minutes=5)):
                return access_token

        if not refresh_token:
            if expires_at and expires_at <= now:
                return None
            return access_token

        try:
            refreshed = await cls.refresh_access_token(refresh_token)
            new_access_token = refreshed["access_token"]
            expires_in = refreshed.get("expires_in", 3600)
            new_expires_at = now + timedelta(seconds=expires_in)
            new_refresh = refreshed.get("refresh_token", refresh_token)

            await TokenVaultService.save_station_tokens(
                db=db,
                station_id=station_id,
                access_token=new_access_token,
                refresh_token=new_refresh,
                expires_at=new_expires_at
            )
            return new_access_token
        except Exception as err:
            logger.error(f"Failed to refresh Spotify token for station {station_id}: {err}")
            if expires_at and expires_at <= now:
                return None
            return access_token

    @classmethod
    async def get_current_user_profile(cls, access_token: str) -> Dict[str, Any]:
        async with AsyncClient() as client:
            headers = {"Authorization": f"Bearer {access_token}"}
            response = await client.get(f"{cls.SPOTIFY_API_BASE}/me", headers=headers)
            response.raise_for_status()
            return response.json()


    @classmethod
    async def search_tracks(
        cls,
        db: AsyncSession,
        access_token: str,
        query: str,
        limit: int = 10
    ) -> SpotifySearchResult:
        clean_query = query.strip()
        if not clean_query:
            return SpotifySearchResult(query=query, tracks=[])

        effective_limit = min(max(1, limit), 10)
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {
            "q": clean_query,
            "type": "track",
            "limit": effective_limit
        }

        async with AsyncClient() as client:
            response = await client.get(
                f"{cls.SPOTIFY_API_BASE}/search",
                headers=headers,
                params=params
            )
            if response.status_code != 200:
                logger.error(f"Spotify search API error: {response.status_code} - {response.text}")
            response.raise_for_status()
            payload = response.json()

        items = payload.get("tracks", {}).get("items", [])
        tracks: List[SpotifyTrack] = []

        seen_ids = set()
        for item in items:
            if not item:
                continue
            track_id = item.get("id")
            title = item.get("name", "Unknown Title")
            artists = ", ".join([a.get("name", "") for a in item.get("artists", [])])
            album_info = item.get("album", {})
            album_name = album_info.get("name")
            images = album_info.get("images", [])
            album_art_url = images[0]["url"] if images else None
            duration_ms = item.get("duration_ms", 0)
            uri = item.get("uri")
            preview_url = item.get("preview_url")

            track_obj = SpotifyTrack(
                id=track_id,
                title=title,
                artist=artists,
                album=album_name,
                album_art_url=album_art_url,
                duration_ms=duration_ms,
                uri=uri,
                preview_url=preview_url
            )
            tracks.append(track_obj)

            if track_id and track_id not in seen_ids:
                seen_ids.add(track_id)
                cache_stmt = select(TrackCache.spotify_id).where(TrackCache.spotify_id == track_id)
                existing_cache = await db.execute(cache_stmt)
                if not existing_cache.first():
                    new_cache = TrackCache(
                        spotify_id=track_id,
                        title=title,
                        artist=artists,
                        album=album_name,
                        album_art_url=album_art_url,
                        duration_ms=duration_ms,
                        cached_at=datetime.now(timezone.utc)
                    )
                    db.add(new_cache)

        try:
            await db.commit()
        except Exception:
            await db.rollback()

        return SpotifySearchResult(query=clean_query, tracks=tracks)

    @classmethod
    async def get_track_by_id(
        cls,
        db: AsyncSession,
        access_token: str,
        track_id: str
    ) -> Optional[SpotifyTrack]:
        stmt = (
            select(
                TrackCache.spotify_id,
                TrackCache.title,
                TrackCache.artist,
                TrackCache.album,
                TrackCache.album_art_url,
                TrackCache.duration_ms
            )
            .where(TrackCache.spotify_id == track_id)
        )
        cache_row = (await db.execute(stmt)).first()

        if cache_row:
            return SpotifyTrack(
                id=cache_row[0],
                title=cache_row[1],
                artist=cache_row[2],
                album=cache_row[3],
                album_art_url=cache_row[4],
                duration_ms=cache_row[5],
                uri=f"spotify:track:{cache_row[0]}",
                preview_url=None
            )

        headers = {"Authorization": f"Bearer {access_token}"}
        async with AsyncClient() as client:
            response = await client.get(f"{cls.SPOTIFY_API_BASE}/tracks/{track_id}", headers=headers)
            if response.status_code != 200:
                return None
            item = response.json()

        title = item.get("name", "Unknown Title")
        artists = ", ".join([a.get("name", "") for a in item.get("artists", [])])
        album_info = item.get("album", {})
        album_name = album_info.get("name")
        images = album_info.get("images", [])
        album_art_url = images[0]["url"] if images else None
        duration_ms = item.get("duration_ms", 0)

        new_cache = TrackCache(
            spotify_id=track_id,
            title=title,
            artist=artists,
            album=album_name,
            album_art_url=album_art_url,
            duration_ms=duration_ms,
            cached_at=datetime.now(timezone.utc)
        )
        db.add(new_cache)
        try:
            await db.commit()
        except Exception:
            await db.rollback()

        preview_url = item.get("preview_url")

        return SpotifyTrack(
            id=track_id,
            title=title,
            artist=artists,
            album=album_name,
            album_art_url=album_art_url,
            duration_ms=duration_ms,
            uri=item.get("uri"),
            preview_url=preview_url
        )

    @classmethod
    async def get_user_devices(cls, access_token: str) -> List[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with AsyncClient() as client:
            response = await client.get(f"{cls.SPOTIFY_API_BASE}/me/player/devices", headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("devices", [])
            return []

    @classmethod
    async def transfer_playback(cls, access_token: str, device_id: str, play: bool = True) -> bool:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {"device_ids": [device_id], "play": play}
        async with AsyncClient() as client:
            response = await client.put(f"{cls.SPOTIFY_API_BASE}/me/player", headers=headers, json=payload)
            return response.status_code in (200, 202, 204)

    @classmethod
    async def play_track(
        cls,
        access_token: str,
        device_id: Optional[str] = None,
        uris: Optional[List[str]] = None,
        context_uri: Optional[str] = None,
        position_ms: int = 0
    ) -> bool:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        params = {}
        if device_id:
            params["device_id"] = device_id
        payload: Dict[str, Any] = {}
        if uris:
            payload["uris"] = uris
        elif context_uri:
            payload["context_uri"] = context_uri
        if position_ms > 0:
            payload["position_ms"] = position_ms

        async with AsyncClient() as client:
            response = await client.put(
                f"{cls.SPOTIFY_API_BASE}/me/player/play",
                headers=headers,
                params=params,
                json=payload if payload else None
            )
            return response.status_code in (200, 202, 204)

    @classmethod
    async def pause_playback(cls, access_token: str, device_id: Optional[str] = None) -> bool:
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"device_id": device_id} if device_id else {}
        async with AsyncClient() as client:
            response = await client.put(f"{cls.SPOTIFY_API_BASE}/me/player/pause", headers=headers, params=params)
            return response.status_code in (200, 202, 204)

    @classmethod
    async def resume_playback(cls, access_token: str, device_id: Optional[str] = None) -> bool:
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"device_id": device_id} if device_id else {}
        async with AsyncClient() as client:
            response = await client.put(f"{cls.SPOTIFY_API_BASE}/me/player/play", headers=headers, params=params)
            return response.status_code in (200, 202, 204)

    @classmethod
    async def get_playback_state(cls, access_token: str) -> Optional[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with AsyncClient() as client:
            response = await client.get(f"{cls.SPOTIFY_API_BASE}/me/player", headers=headers)
            if response.status_code == 200:
                return response.json()
            return None
