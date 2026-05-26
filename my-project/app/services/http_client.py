from __future__ import annotations

import gzip
import logging
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "FirstProjectBot/1.0 (+https://example.com/bot; respectful-scraper)"
)
DEFAULT_TIMEOUT = 15.0


class HttpError(Exception):
    pass


class HttpTimeoutError(HttpError):
    pass


class HttpServerError(HttpError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Server error {status}: {message}")
        self.status = status


class HttpClientError(HttpError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Client error {status}: {message}")
        self.status = status


class HttpConnectionError(HttpError):
    pass


@dataclass
class HttpResponse:
    status: int
    body: bytes
    url: str

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")


def get(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = DEFAULT_USER_AGENT,
    extra_headers: Optional[dict] = None,
) -> HttpResponse:
    headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Encoding": "gzip",
    }
    if extra_headers:
        headers.update(extra_headers)

    request = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            return HttpResponse(
                status=response.status,
                body=raw,
                url=response.geturl(),
            )

    except urllib.error.HTTPError as exc:
        body_preview = ""
        try:
            body_preview = exc.read(500).decode("utf-8", errors="replace")
        except Exception:
            pass
        if 500 <= exc.code < 600:
            raise HttpServerError(exc.code, body_preview) from exc
        raise HttpClientError(exc.code, body_preview) from exc

    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            raise HttpTimeoutError(f"Timed out fetching {url}") from exc
        raise HttpConnectionError(f"Could not reach {url}: {exc.reason}") from exc

    except socket.timeout as exc:
        raise HttpTimeoutError(f"Timed out fetching {url}") from exc
