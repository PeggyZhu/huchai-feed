"""Polite read of the public fangdi yesterday-sell endpoint.

The client identifies itself, waits between the page and the API call, and
retries only network failures and HTTP 5xx. A 412/403 challenge is returned
immediately. Nothing here executes the site's JavaScript or forges a browser.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

from huchai.errors import SourceError
from huchai.parse import raise_if_blocked

USER_AGENT = (
    "huchai-feed/1.0 (+https://github.com/PeggyZhu/huchai-feed; "
    "public snapshot of Shanghai second-hand net-sign totals)"
)
PAGE_URL = "https://www.fangdi.com.cn/old_house/old_house.html"
API_URL = "https://www.fangdi.com.cn/oldhouse/getSHYesterdaySell.action"
ORIGIN = "https://www.fangdi.com.cn"
MAX_BYTES = 1_000_000
RETRY_STATUSES = {500, 502, 503, 504}


class UrllibTransport:
    def __init__(
        self,
        *,
        interval: float = 1.5,
        timeout: float = 25,
        attempts: int = 3,
        backoff: float = 2.0,
        sleep=time.sleep,
        opener=None,
        page_url: str = PAGE_URL,
        api_url: str = API_URL,
    ) -> None:
        self.interval = interval
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff
        self.sleep = sleep
        self.page_url = page_url
        self.api_url = api_url
        if opener is None:
            cookie_jar = CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        self.opener = opener

    def fetch_yesterday(self) -> dict:
        status, body = self._request("GET", self.page_url)
        raise_if_blocked(status, body, self.page_url)
        if status != 200:
            raise SourceError(f"GET {self.page_url} returned HTTP {status}")
        self.sleep(self.interval)
        status, body = self._request(
            "POST",
            self.api_url,
            data=b"",
            extra={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "Origin": ORIGIN,
                "Referer": self.page_url,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        raise_if_blocked(status, body, self.api_url)
        if status != 200:
            raise SourceError(f"POST {self.api_url} returned HTTP {status}")
        stripped = body.lstrip()
        if not stripped.startswith(("{", "[")):
            raise SourceError(f"POST {self.api_url} did not return JSON")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SourceError(f"POST {self.api_url} returned invalid JSON") from exc
        if not isinstance(payload, (dict, list)):
            raise SourceError("sell payload was not an object")
        return payload

    def _request(self, method: str, url: str, data: bytes | None = None, extra: dict | None = None):
        delay = self.backoff
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                status, body = self._once(method, url, data, extra)
            except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
                last_error = exc
                if attempt + 1 == self.attempts:
                    raise SourceError(f"{method} {url} failed: {exc}") from exc
                self.sleep(delay)
                delay *= 2
                continue
            if status in RETRY_STATUSES:
                last_error = SourceError(f"{method} {url} returned HTTP {status}")
                if attempt + 1 == self.attempts:
                    raise last_error
                self.sleep(delay)
                delay *= 2
                continue
            return status, body
        raise SourceError(f"{method} {url} failed: {last_error}")

    def _once(self, method: str, url: str, data: bytes | None, extra: dict | None):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if extra:
            headers.update(extra)
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BYTES)
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            raw = exc.read(MAX_BYTES)
            status = exc.code
        return status, _decode(raw)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SourceError("response was neither utf-8 nor gbk")
