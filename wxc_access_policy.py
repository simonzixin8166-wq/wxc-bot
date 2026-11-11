#!/usr/bin/env python3
"""Wenxuecity access pause (Owner 2026-11-11): the site refuses MyAlpha (403/429 since 2026-11-01), so no request
of any kind goes to *.wenxuecity.com until PAUSE_UNTIL ("at least six months"). This replaces the once-a-day retry.

Owner exports and forwards (the Telegram bot) keep working: they never contact the site.
To resume early, the Owner changes PAUSE_UNTIL in a reviewed PR. There is no environment override.

Two layers:
- every Wenxuecity fetch helper checks paused() and returns None without sleeping or retrying;
- guard(session) mounts an adapter that refuses any Wenxuecity URL on that session, so a direct
  session.get() (image download, diagnostics) cannot reach the site either.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

PAUSE_UNTIL = "2027-05-11"
REASON = "Owner 2026-11-11: Wenxuecity refuses MyAlpha; no requests for at least six months"


def is_wenxuecity(url: str | None) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return host == "wenxuecity.com" or host.endswith(".wenxuecity.com")


def paused(url: str | None = None, today: date | None = None) -> bool:
    """True while the pause is in force (for a Wenxuecity URL, or in general when url is None)."""
    today = today or datetime.now(timezone.utc).date()
    if today >= date.fromisoformat(PAUSE_UNTIL):
        return False
    return url is None or is_wenxuecity(url)


def status() -> dict:
    return {"status": "paused_by_owner", "paused_until": PAUSE_UNTIL, "reason": REASON}


class PausedError(requests.exceptions.ConnectionError):
    pass


class _GuardAdapter(HTTPAdapter):
    def send(self, request, **kwargs):  # noqa: D401
        if paused(request.url):
            raise PausedError(f"wenxuecity access paused until {PAUSE_UNTIL} ({REASON})")
        return super().send(request, **kwargs)


def guard(session: requests.Session) -> requests.Session:
    a = _GuardAdapter()
    session.mount("https://", a)
    session.mount("http://", a)
    return session
