import os
import shutil
import asyncio
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class LibrespotService:
    def __init__(self) -> None:
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._device_ids: Dict[str, str] = {}
        self._active_tracks: Dict[str, Dict[str, Any]] = {}
        self._auth_urls: Dict[str, str] = {}
        self._ports: Dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._base_port = 8898

    def _resolve_binary(self) -> Optional[str]:
        candidates = [
            "/usr/local/bin/librespot",
            "/usr/bin/librespot",
            shutil.which("librespot")
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def get_pipe_path(self, station_slug: str) -> str:
        base_dir = os.environ.get("DATA_DIR", "/app/data")
        station_dir = os.path.join(base_dir, "stations", station_slug)
        os.makedirs(station_dir, exist_ok=True)
        return os.path.join(station_dir, "audio.pipe")

    def get_cache_dir(self, station_slug: str) -> str:
        base_dir = os.environ.get("DATA_DIR", "/app/data")
        cache_dir = os.path.join(base_dir, "stations", station_slug, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _ensure_fifo(self, pipe_path: str) -> None:
        if hasattr(os, "mkfifo"):
            if os.path.exists(pipe_path):
                if not os.path.isdir(pipe_path) and not os.path.islink(pipe_path):
                    pass
            else:
                os.mkfifo(pipe_path)

    async def start_station_daemon(self, station_slug: str) -> bool:
        async with self._lock:
            existing_proc = self._processes.get(station_slug)
            if existing_proc and existing_proc.returncode is None:
                return True

            binary = self._resolve_binary()
            if not binary:
                logger.warning(f"librespot binary not found on system for station {station_slug}")
                return False

            pipe_path = self.get_pipe_path(station_slug)
            self._ensure_fifo(pipe_path)
            cache_dir = self.get_cache_dir(station_slug)

            port = self._base_port + (abs(hash(station_slug)) % 100)
            self._ports[station_slug] = port
            device_name = f"SpotifyJockey-{station_slug}"

            cmd = [
                binary,
                "--name", device_name,
                "--device", pipe_path,
                "--backend", "pipe",
                "--bitrate", "320",
                "--initial-volume", "100",
                "--cache", cache_dir,
                "--enable-oauth",
                "--oauth-port", str(port),
                "--disable-audio-cache"
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                self._processes[station_slug] = proc
                task = asyncio.create_task(self._monitor_process(station_slug, proc))
                self._tasks[station_slug] = task
                return True
            except Exception as e:
                logger.error(f"Failed to start librespot for {station_slug}: {e}")
                return False

    async def _monitor_process(self, station_slug: str, proc: asyncio.subprocess.Process) -> None:
        async def read_stream(stream, is_stderr=False):
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if is_stderr:
                    logger.debug(f"[librespot:{station_slug}:err] {line}")
                else:
                    logger.info(f"[librespot:{station_slug}] {line}")

                if "Device ID:" in line:
                    parts = line.split("Device ID:", 1)
                    if len(parts) > 1:
                        dev_id = parts[1].strip().split()[0]
                        self._device_ids[station_slug] = dev_id
                elif "device_id" in line.lower():
                    words = line.split()
                    for w in words:
                        if len(w) == 40 and w.isalnum():
                            self._device_ids[station_slug] = w

                if "http" in line and ("authorize" in line or "login" in line or "spotify.com" in line or "127.0.0.1" in line):
                    self._auth_urls[station_slug] = line

        if proc.stdout and proc.stderr:
            await asyncio.gather(
                read_stream(proc.stdout, False),
                read_stream(proc.stderr, True),
                return_exceptions=True
            )
        await proc.wait()
        async with self._lock:
            if self._processes.get(station_slug) == proc:
                self._processes.pop(station_slug, None)
                self._tasks.pop(station_slug, None)

    async def stop_station_daemon(self, station_slug: str) -> None:
        async with self._lock:
            proc = self._processes.pop(station_slug, None)
            task = self._tasks.pop(station_slug, None)
            if task:
                task.cancel()
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except Exception:
                    proc.kill()
            self._device_ids.pop(station_slug, None)
            self._auth_urls.pop(station_slug, None)

    def is_running(self, station_slug: str) -> bool:
        proc = self._processes.get(station_slug)
        return bool(proc and proc.returncode is None)

    def get_status(self, station_slug: str) -> Dict[str, Any]:
        running = self.is_running(station_slug)
        cache_dir = self.get_cache_dir(station_slug)
        has_credentials = os.path.isfile(os.path.join(cache_dir, "credentials.json"))
        return {
            "slug": station_slug,
            "is_running": running,
            "device_name": f"SpotifyJockey-{station_slug}",
            "device_id": self._device_ids.get(station_slug),
            "oauth_port": self._ports.get(station_slug),
            "auth_url": self._auth_urls.get(station_slug),
            "has_credentials": has_credentials,
            "active_track": self._active_tracks.get(station_slug)
        }


librespot_service = LibrespotService()
