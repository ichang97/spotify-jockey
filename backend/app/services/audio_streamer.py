import time
import asyncio
import logging
from typing import Optional, Dict, Tuple
from httpx import AsyncClient

logger = logging.getLogger(__name__)


class AudioStreamerService:
    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[str, float]] = {}
        self._lock = asyncio.Lock()
        self._cache_ttl = 7200

    def _get_cached_url(self, key: str) -> Optional[str]:
        item = self._cache.get(key)
        if item:
            url, expires_at = item
            if time.time() < expires_at:
                return url
            self._cache.pop(key, None)
        return None

    def _set_cached_url(self, key: str, url: str) -> None:
        self._cache[key] = (url, time.time() + self._cache_ttl)

    async def resolve_stream_url(
        self,
        title: str,
        artist: str,
        track_id: Optional[str] = None
    ) -> Optional[str]:
        cache_key = track_id or f"{title}:{artist}".lower().strip()
        cached = self._get_cached_url(cache_key)
        if cached:
            return cached

        url = await self._resolve_via_ytdlp(f"{title} - {artist}")
        if not url:
            url = await self._resolve_via_ytdlp(f"{title} {artist}".strip())
        if not url:
            url = await self._resolve_via_piped(f"{title} {artist}".strip())

        if url:
            self._set_cached_url(cache_key, url)
        return url

    async def _resolve_via_ytdlp(self, query: str) -> Optional[str]:
        def extract():
            try:
                import yt_dlp
                ydl_opts = {
                    "format": "bestaudio/best",
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "default_search": "ytsearch1",
                    "extract_flat": False,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"ytsearch1:{query} official audio", download=False)
                    if not info or not info.get("entries"):
                        info = ydl.extract_info(f"ytsearch1:{query} audio", download=False)
                    if not info:
                        return None
                    entries = info.get("entries", [])
                    target = entries[0] if entries else info
                    formats = target.get("formats", [])
                    audio_formats = [
                        f for f in formats
                        if f.get("url") and f.get("acodec") != "none" and (f.get("vcodec") == "none" or not f.get("vcodec"))
                    ]
                    if audio_formats:
                        audio_formats.sort(key=lambda x: (x.get("abr") or 0, x.get("tbr") or 0), reverse=True)
                        return audio_formats[0].get("url")

                    direct_url = target.get("url")
                    if direct_url and "youtube.com/watch" not in direct_url and "youtu.be/" not in direct_url:
                        return direct_url

                    for f in reversed(formats):
                        if f.get("url") and f.get("acodec") != "none":
                            return f["url"]
                    return None
            except ImportError:
                return None
            except Exception as e:
                logger.error(f"yt-dlp resolution error for '{query}': {e}")
                return None

        return await asyncio.to_thread(extract)

    async def _resolve_via_piped(self, query: str) -> Optional[str]:
        instances = [
            "https://pipedapi.kavin.rocks",
            "https://api.piped.private.coffee",
            "https://piped-api.lunar.icu",
        ]
        for base in instances:
            try:
                async with AsyncClient(timeout=4.0) as client:
                    search_res = await client.get(
                        f"{base}/search",
                        params={"q": query, "filter": "music_songs"}
                    )
                    if search_res.status_code != 200:
                        continue
                    search_data = search_res.json()
                    items = search_data.get("items", [])
                    if not items:
                        continue
                    video_url = items[0].get("url")
                    if not video_url:
                        continue
                    video_id = video_url.split("=")[-1] if "=" in video_url else video_url.split("/")[-1]

                    stream_res = await client.get(f"{base}/streams/{video_id}")
                    if stream_res.status_code != 200:
                        continue
                    stream_data = stream_res.json()
                    audio_streams = stream_data.get("audioStreams", [])
                    if audio_streams:
                        sorted_streams = sorted(audio_streams, key=lambda x: x.get("bitrate", 0), reverse=True)
                        return sorted_streams[0].get("url")
            except Exception:
                continue
        return None


audio_streamer_service = AudioStreamerService()
