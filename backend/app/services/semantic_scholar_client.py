"""Reliable Semantic Scholar Graph API helpers.

All project-side Semantic Scholar GETs should go through ``ss_get`` so API-key
headers, process-local rate limiting, retry/backoff, and short-lived disk cache
stay consistent across crawl and portfolio refresh jobs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.config import (
    DATA_DIR,
    SEMANTIC_SCHOLAR_API_KEY,
    SEMANTIC_SCHOLAR_RPS,
)

logger = logging.getLogger(__name__)

_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0
_COOLDOWN_UNTIL = 0.0
_CACHE_DIR = DATA_DIR / "ss_cache"
_CACHE_DIR.mkdir(exist_ok=True)


def _headers(extra: dict | None = None) -> dict:
    headers = dict(extra or {})
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    return headers


def ss_headers(extra: dict | None = None) -> dict:
    """Return headers for non-GET Semantic Scholar calls."""
    return _headers(extra)


async def _throttle() -> None:
    global _LAST_REQUEST_AT
    rps = max(float(SEMANTIC_SCHOLAR_RPS or 1.0), 0.05)
    min_interval = 1.0 / rps
    async with _LOCK:
        now = time.monotonic()
        wait = max(_LAST_REQUEST_AT + min_interval, _COOLDOWN_UNTIL) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_REQUEST_AT = time.monotonic()


async def _set_global_cooldown(seconds: float) -> None:
    global _COOLDOWN_UNTIL
    if seconds <= 0:
        return
    async with _LOCK:
        _COOLDOWN_UNTIL = max(_COOLDOWN_UNTIL, time.monotonic() + seconds)


def _cache_key(url: str, params: dict | None) -> Path:
    encoded = urlencode(sorted((params or {}).items()), doseq=True)
    digest = hashlib.sha256(f"{url}?{encoded}".encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{digest}.json"


def _read_cache(url: str, params: dict | None, ttl_seconds: int) -> httpx.Response | None:
    if ttl_seconds <= 0:
        return None
    path = _cache_key(url, params)
    if not path.exists() or time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return httpx.Response(
            status_code=payload["status_code"],
            headers=payload.get("headers") or {},
            content=payload.get("content", "").encode("utf-8"),
            request=httpx.Request("GET", url, params=params),
        )
    except Exception as exc:
        logger.debug("Semantic Scholar cache read failed: %s", exc)
        return None


def _write_cache(url: str, params: dict | None, resp: httpx.Response) -> None:
    if resp.status_code != 200:
        return
    path = _cache_key(url, params)
    try:
        path.write_text(
            json.dumps(
                {
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "content": resp.text,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("Semantic Scholar cache write failed: %s", exc)


def _retry_after_seconds(resp: httpx.Response | None) -> float | None:
    if resp is None:
        return None
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(raw).timestamp() - time.time())
        except Exception:
            return None


async def ss_get(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    *,
    max_retries: int = 6,
    timeout: float = 30.0,
    cache_ttl_seconds: int = 7 * 24 * 3600,
    headers: dict | None = None,
) -> httpx.Response | None:
    """GET with API-key header, global throttling, cache, and backoff.

    Returns ``None`` only after all retry attempts are exhausted. Non-retryable
    HTTP statuses are returned to the caller for domain-specific handling.
    """
    cached = _read_cache(url, params, cache_ttl_seconds)
    if cached is not None:
        return cached

    delay = 2.0
    last_resp: httpx.Response | None = None
    for attempt in range(max_retries):
        try:
            await _throttle()
            resp = await client.get(
                url,
                params=params,
                timeout=timeout,
                headers=_headers(headers),
            )
            last_resp = resp
            if resp.status_code == 200:
                _write_cache(url, params, resp)
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = _retry_after_seconds(resp)
                wait = retry_after if retry_after is not None else delay + random.uniform(0, 0.75)
                if resp.status_code == 429:
                    # Apply 429 backoff process-wide so concurrent crawl workers
                    # do not continue sending requests while one task is cooling
                    # down. Unauthenticated SS limits can be stricter than 1 RPS
                    # from shared networks, so keep the floor intentionally high.
                    wait = max(wait, 30.0)
                    await _set_global_cooldown(wait)
                logger.info(
                    "Semantic Scholar HTTP %s for %s; retrying in %.1fs (%d/%d)",
                    resp.status_code,
                    url,
                    wait,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(wait)
                delay = min(delay * 2, 60)
                continue
            return resp
        except Exception as exc:
            wait = delay + random.uniform(0, 0.75)
            logger.debug("Semantic Scholar request failed: %s; retrying in %.1fs", exc, wait)
            await asyncio.sleep(wait)
            delay = min(delay * 2, 60)

    if last_resp is not None:
        logger.warning("Semantic Scholar exhausted retries: HTTP %s %s", last_resp.status_code, url)
    return None
