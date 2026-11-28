"""Polite reads of public notice pages.

The client identifies itself, waits between requests, and retries only
network failures and HTTP 5xx. A 403/412 challenge is returned immediately
and is not solved. fangdi.cn is refused here so notice collection cannot
drift into the net-sign crawler.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


USER_AGENT = (
    "huchai-feed/1.0 (+https://github.com/PeggyZhu/huchai-feed; "
    "public reader of Shanghai expropriation notices)"
)
MAX_BYTES = 6_000_000
RETRY_STATUSES = {500, 502, 503, 504}
BLOCK_STATUSES = {401, 403, 412, 429}


class FetchError(RuntimeError):
    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason


def assert_not_fangdi(url: str) -> None:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host == "fangdi.com.cn" or host.endswith(".fangdi.com.cn"):
        raise FetchError(url, "不访问 fangdi.cn")


class UrllibNoticeTransport:
    def __init__(self, *, timeout: float = 30, attempts: int = 3, backoff: float = 1.5, sleep=time.sleep) -> None:
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff
        self.sleep = sleep

    def post_json(self, url: str, payload: dict, *, referer: str) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status, raw = self._request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "Accept": "application/json",
                "Referer": referer,
            },
        )
        if status != 200:
            raise FetchError(url, f"HTTP {status}")
        try:
            loaded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchError(url, f"不是 JSON ({exc})") from exc
        if not isinstance(loaded, dict):
            raise FetchError(url, "JSON 不是对象")
        return loaded

    def get_text(self, url: str, *, referer: str | None = None) -> str:
        headers = {"Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}
        if referer:
            headers["Referer"] = referer
        status, raw = self._request(url, headers=headers)
        if status != 200:
            raise FetchError(url, f"HTTP {status}")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FetchError(url, f"不是 UTF-8 ({exc})") from exc

    def _request(self, url: str, *, data: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
        assert_not_fangdi(url)
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    status = getattr(response, "status", 200)
                    raw = response.read(MAX_BYTES + 1)
            except urllib.error.HTTPError as exc:
                status = exc.code
                raw = exc.read(MAX_BYTES + 1) if exc.fp is not None else b""
                if status in BLOCK_STATUSES or status not in RETRY_STATUSES:
                    return status, raw
                last_error = exc
            except urllib.error.URLError as exc:
                last_error = exc
                status = 0
                raw = b""
            else:
                if len(raw) > MAX_BYTES:
                    raise FetchError(url, "响应超过大小上限")
                return status, raw
            if attempt + 1 < self.attempts:
                self.sleep(self.backoff * (attempt + 1))
        raise FetchError(url, f"网络失败 ({last_error})")
