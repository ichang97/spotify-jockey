import ipaddress
import time
from typing import Dict, List, Callable
from fastapi import Request, HTTPException, status


def _is_trusted_proxy(host: str) -> bool:
    if host in {"localhost", "testclient"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


class RateLimiter:
    def __init__(self) -> None:
        self._records: Dict[str, List[float]] = {}

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - window_seconds

        if len(self._records) > 2000:
            self._purge_stale(now)

        timestamps = self._records.get(key, [])
        valid_timestamps = [t for t in timestamps if t > cutoff]

        if len(valid_timestamps) >= max_requests:
            self._records[key] = valid_timestamps
            return False

        valid_timestamps.append(now)
        self._records[key] = valid_timestamps
        return True

    def _purge_stale(self, now: float) -> None:
        stale_keys = [k for k, v in self._records.items() if not v or (now - v[-1] > 3600)]
        for k in stale_keys:
            self._records.pop(k, None)


rate_limiter = RateLimiter()


def rate_limit(max_requests: int, window_seconds: int) -> Callable:
    async def dependency(request: Request) -> None:
        client_host = request.client.host if request.client else "127.0.0.1"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded and _is_trusted_proxy(client_host):
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = client_host

        key = f"{client_ip}:{request.url.path}"
        if not rate_limiter.is_allowed(key, max_requests, window_seconds):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": str(window_seconds)}
            )
    return dependency
