from __future__ import annotations

import random
import threading
import time
from typing import Any

import httpx


class TikHubError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        path: str = "",
        status_code: int | None = None,
        code: int | str | None = None,
        request_id: str = "",
        retriable: bool = False,
        response_text: str = "",
    ):
        super().__init__(message)
        self.path = path
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.retriable = retriable
        self.response_text = response_text

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "path": self.path,
            "status_code": self.status_code,
            "code": self.code,
            "request_id": self.request_id,
            "retriable": self.retriable,
            "response_text": self.response_text,
        }


class RateLimiter:
    def __init__(self, qps: float):
        self._min_interval = 1.0 / qps if qps > 0 else 0.0
        self._next_at = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                time.sleep(self._next_at - now)
                now = time.monotonic()
            self._next_at = max(now, self._next_at) + self._min_interval


class TikHubClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 30,
        qps: float = 10,
        retry_attempts: int = 3,
        retry_base_sleep_seconds: float = 1,
        retry_max_sleep_seconds: float = 8,
    ):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self._rate_limiter = RateLimiter(qps)
        self._retry_attempts = max(1, retry_attempts)
        self._retry_base_sleep_seconds = max(0.0, retry_base_sleep_seconds)
        self._retry_max_sleep_seconds = max(retry_base_sleep_seconds, retry_max_sleep_seconds)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TikHubClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._get(path, params)

    def search_notes(
        self,
        *,
        keyword: str,
        page: int,
        sort_type: str,
        note_type: str,
        time_filter: str,
        source: str,
        ai_mode: int,
        search_id: str | None = None,
        search_session_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "keyword": keyword,
            "page": page,
            "sort_type": sort_type,
            "note_type": note_type,
            "time_filter": time_filter,
            "source": source,
            "ai_mode": ai_mode,
        }
        if search_id:
            params["search_id"] = search_id
        if search_session_id:
            params["search_session_id"] = search_session_id
        return self._get("/api/v1/xiaohongshu/app_v2/search_notes", params)

    def search_notes_app(
        self,
        *,
        keyword: str,
        page: int,
        sort_type: str,
        filter_note_type: str,
        filter_note_time: str,
        search_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "keyword": keyword,
            "page": page,
            "sort_type": sort_type,
            "filter_note_type": filter_note_type,
            "filter_note_time": filter_note_time,
        }
        if search_id:
            params["search_id"] = search_id
        if session_id:
            params["session_id"] = session_id
        return self._get("/api/v1/xiaohongshu/app/search_notes", params)

    def get_image_note_detail(self, *, note_id: str) -> dict[str, Any]:
        return self._get(
            "/api/v1/xiaohongshu/app_v2/get_image_note_detail",
            {"note_id": note_id},
        )

    def get_video_note_detail(self, *, note_id: str) -> dict[str, Any]:
        return self._get(
            "/api/v1/xiaohongshu/app_v2/get_video_note_detail",
            {"note_id": note_id},
        )

    def get_note_comments(
        self,
        *,
        note_id: str,
        cursor: str = "",
        index: int = 0,
        page_area: str = "UNFOLDED",
        sort_strategy: str = "latest_v2",
    ) -> dict[str, Any]:
        return self._get(
            "/api/v1/xiaohongshu/app_v2/get_note_comments",
            {
                "note_id": note_id,
                "cursor": cursor,
                "index": index,
                "pageArea": page_area,
                "sort_strategy": sort_strategy,
            },
        )

    def get_note_comments_app(
        self,
        *,
        note_id: str,
        start: str = "",
        sort_strategy: int = 2,
    ) -> dict[str, Any]:
        return self._get(
            "/api/v1/xiaohongshu/app/get_note_comments",
            {
                "note_id": note_id,
                "start": start,
                "sort_strategy": sort_strategy,
            },
        )

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: TikHubError | None = None
        for attempt in range(1, self._retry_attempts + 1):
            self._rate_limiter.wait()
            try:
                response = self._client.get(path, params=params)
            except httpx.TimeoutException as exc:
                last_error = TikHubError(
                    f"TikHub timeout for {path}",
                    path=path,
                    retriable=True,
                )
                if attempt >= self._retry_attempts:
                    raise last_error from exc
                self._sleep_before_retry(attempt)
                continue
            except httpx.TransportError as exc:
                last_error = TikHubError(
                    f"TikHub transport error for {path}: {exc}",
                    path=path,
                    retriable=True,
                )
                if attempt >= self._retry_attempts:
                    raise last_error from exc
                self._sleep_before_retry(attempt)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                error = _error_from_response(path, response)
                if error.retriable and attempt < self._retry_attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise error from exc

            try:
                payload = response.json()
            except ValueError as exc:
                raise TikHubError(
                    f"TikHub returned non-JSON response for {path}",
                    path=path,
                    response_text=response.text[:1000],
                ) from exc
            if not isinstance(payload, dict):
                raise TikHubError(f"TikHub returned non-object response for {path}", path=path)
            code = payload.get("code")
            if code not in (None, 200):
                error = _error_from_payload(path, payload)
                if error.retriable and attempt < self._retry_attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise error
            return payload

        if last_error:
            raise last_error
        raise TikHubError(f"TikHub request failed for {path}", path=path)

    def _sleep_before_retry(self, attempt: int) -> None:
        if self._retry_base_sleep_seconds <= 0:
            return
        delay = min(
            self._retry_max_sleep_seconds,
            self._retry_base_sleep_seconds * (2 ** (attempt - 1)),
        )
        time.sleep(delay + random.uniform(0, min(delay * 0.1, 0.5)))


def _error_from_response(path: str, response: httpx.Response) -> TikHubError:
    retriable = response.status_code == 429 or 500 <= response.status_code <= 599
    return TikHubError(
        f"TikHub HTTP {response.status_code} for {path}: {response.text[:1000]}",
        path=path,
        status_code=response.status_code,
        retriable=retriable,
        response_text=response.text[:1000],
    )


def _error_from_payload(path: str, payload: dict[str, Any]) -> TikHubError:
    code = payload.get("code")
    message = str(payload.get("message_zh") or payload.get("message") or "unknown error")
    request_id = str(payload.get("request_id", ""))
    retriable = _is_retriable_payload_error(code, message)
    return TikHubError(
        f"TikHub error code={code} request_id={request_id}: {message}",
        path=path,
        code=code,
        request_id=request_id,
        retriable=retriable,
        response_text=str(payload)[:1000],
    )


def _is_retriable_payload_error(code: int | str | None, message: str) -> bool:
    if str(code) in {"408", "429", "500", "502", "503", "504"}:
        return True
    lowered = message.lower()
    return any(token in lowered for token in ("rate limit", "too many", "timeout", "temporarily"))
