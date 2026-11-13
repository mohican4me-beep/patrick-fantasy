"""Minimal HTTP client for the three documented sources. Standard library only."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = "patrick-fantasy/0.3 (personal, non-commercial)"
FORBIDDEN_HOSTS = ("uefa.com",)


class SourceError(RuntimeError):
    """A source could not be fetched or returned something unusable."""


@dataclass(frozen=True)
class Response:
    status: int
    text: str
    headers: dict[str, str]


def get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30.0) -> Response:
    """GET a URL. Refuses any UEFA host: Fantasy data is never fetched automatically."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if any(host == h or host.endswith("." + h) for h in FORBIDDEN_HOSTS):
        raise SourceError(
            f"Refusing to contact {host}: UEFA sites are never fetched automatically."
        )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:  # noqa: S310
            body = reply.read().decode("utf-8", errors="replace")
            return Response(reply.status, body, {k.lower(): v for k, v in reply.headers.items()})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise SourceError(f"HTTP {exc.code} from {host}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(f"Could not reach {host}: {exc}") from None


def redact(url: str) -> str:
    """Remove secret query parameters before a URL is stored or printed."""
    parts = urllib.parse.urlsplit(url)
    query = [
        (k, "REDACTED" if k.lower() in {"apikey", "api_key", "token", "key"} else v)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
