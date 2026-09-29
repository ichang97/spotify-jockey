import os
import shutil
import asyncio
import logging
from typing import Dict, Optional, AsyncGenerator
from app.services.audio_relay import audio_relay_service

logger = logging.getLogger(__name__)


class AudioMixerService:
    def __init__(self) -> None:
        self._pipe_readers: Dict[str, asyncio.Task] = {}
        self._ffmpeg_procs: Dict[str, asyncio.subprocess.Process] = {}
        self._mic_queues: Dict[str, asyncio.Queue[bytes]] = {}
        self._monitor_listeners: Dict[str, set] = {}
        self._ducking_enabled: Dict[str, bool] = {}
        self._current_ducking_gain: Dict[str, float] = {}
        self._is_active: Dict[str, bool] = {}
        self._lock = asyncio.Lock()

    def _resolve_ffmpeg(self) -> Optional[str]:
        candidates = [
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            shutil.which("ffmpeg")
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    async def start_mixer(self, station_slug: str, pipe_path: str) -> bool:
        async with self._lock:
            if self._is_active.get(station_slug):
                return True

            ffmpeg_bin = self._resolve_ffmpeg()
            if not ffmpeg_bin:
                logger.warning(f"FFmpeg not found. Cannot start audio mixer for {station_slug}")
                return False

            cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel", "error",
                "-f", "s16le",
                "-ar", "44100",
                "-ac", "2",
                "-i", "pipe:0",
                "-c:a", "libopus",
                "-b:a", "320k",
                "-vbr", "on",
                "-application", "audio",
                "-f", "webm",
                "-cluster_size_limit", "16384",
                "-cluster_time_limit", "250",
                "pipe:1"
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL
                )
            except Exception as e:
                logger.error(f"Failed to launch FFmpeg encoder for {station_slug}: {e}")
                return False

            self._ffmpeg_procs[station_slug] = proc
            self._is_active[station_slug] = True
            self._ducking_enabled[station_slug] = True
            self._current_ducking_gain[station_slug] = 1.0
            self._mic_queues[station_slug] = asyncio.Queue(maxsize=100)
            self._monitor_listeners[station_slug] = set()
            await audio_relay_service.register_dj(station_slug, "mixer")

            task = asyncio.create_task(self._run_mixing_loop(station_slug, pipe_path, proc))
            self._pipe_readers[station_slug] = task
            return True

    async def _run_mixing_loop(
        self,
        station_slug: str,
        pipe_path: str,
        proc: asyncio.subprocess.Process
    ) -> None:
        async def forward_ffmpeg_output():
            header_accum = b""
            while self._is_active.get(station_slug) and proc.stdout:
                try:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    await audio_relay_service.broadcast_chunk(station_slug, chunk)

                    listeners = self._monitor_listeners.get(station_slug, set())
                    dead = set()
                    for q in list(listeners):
                        try:
                            if q.qsize() > 50:
                                try:
                                    q.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                            q.put_nowait(chunk)
                        except Exception:
                            dead.add(q)
                    if dead:
                        async with self._lock:
                            for d in dead:
                                listeners.discard(d)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error reading ffmpeg output for {station_slug}: {e}")
                    break

        output_task = asyncio.create_task(forward_ffmpeg_output())

        reader = None
        chunk_size = 4096
        target_gain = 1.0

        try:
            while self._is_active.get(station_slug):
                if not os.path.exists(pipe_path):
                    await asyncio.sleep(0.5)
                    continue

                if reader is None:
                    try:
                        reader = await asyncio.to_thread(open, pipe_path, "rb")
                    except Exception:
                        await asyncio.sleep(0.5)
                        continue

                pcm_data = await asyncio.to_thread(reader.read, chunk_size)
                if not pcm_data:
                    await asyncio.sleep(0.05)
                    continue

                mic_queue = self._mic_queues.get(station_slug)
                has_mic_voice = False
                if mic_queue and not mic_queue.empty():
                    has_mic_voice = True

                if self._ducking_enabled.get(station_slug, True):
                    target_gain = 0.2 if has_mic_voice else 1.0
                else:
                    target_gain = 1.0

                current_gain = self._current_ducking_gain.get(station_slug, 1.0)
                if abs(current_gain - target_gain) > 0.05:
                    if current_gain > target_gain:
                        current_gain = max(target_gain, current_gain - 0.15)
                    else:
                        current_gain = min(target_gain, current_gain + 0.08)
                    self._current_ducking_gain[station_slug] = current_gain

                if proc.stdin and not proc.stdin.is_closing():
                    try:
                        if abs(current_gain - 1.0) > 0.01:
                            import audioop
                            pcm_data = audioop.mul(pcm_data, 2, current_gain)
                        proc.stdin.write(pcm_data)
                        await proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Mixing loop error for {station_slug}: {e}")
        finally:
            if reader:
                try:
                    await asyncio.to_thread(reader.close)
                except Exception:
                    pass
            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            output_task.cancel()

    async def push_mic_chunk(self, station_slug: str, chunk: bytes) -> None:
        queue = self._mic_queues.get(station_slug)
        if queue:
            try:
                if queue.qsize() > 20:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(chunk)
            except Exception:
                pass

    def set_ducking(self, station_slug: str, enabled: bool) -> None:
        self._ducking_enabled[station_slug] = enabled

    async def subscribe_monitor(self, station_slug: str) -> AsyncGenerator[bytes, None]:
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        async with self._lock:
            if station_slug not in self._monitor_listeners:
                self._monitor_listeners[station_slug] = set()
            self._monitor_listeners[station_slug].add(q)

        try:
            while self._is_active.get(station_slug):
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=10.0)
                    if not chunk:
                        break
                    yield chunk
                except asyncio.TimeoutError:
                    if not self._is_active.get(station_slug):
                        break
        except asyncio.CancelledError:
            pass
        finally:
            async with self._lock:
                if station_slug in self._monitor_listeners:
                    self._monitor_listeners[station_slug].discard(q)

    async def stop_mixer(self, station_slug: str) -> None:
        async with self._lock:
            self._is_active[station_slug] = False
            await audio_relay_service.unregister_dj(station_slug, "mixer")
            task = self._pipe_readers.pop(station_slug, None)
            if task:
                task.cancel()
            proc = self._ffmpeg_procs.pop(station_slug, None)
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except Exception:
                    proc.kill()
            self._mic_queues.pop(station_slug, None)
            listeners = self._monitor_listeners.pop(station_slug, set())
            for l in listeners:
                try:
                    l.put_nowait(b"")
                except Exception:
                    pass

    def is_active(self, station_slug: str) -> bool:
        return bool(self._is_active.get(station_slug))


audio_mixer_service = AudioMixerService()
