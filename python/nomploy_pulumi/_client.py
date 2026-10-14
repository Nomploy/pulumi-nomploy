"""Minimal REST client for the nomploy API (stdlib only).

The API is the tRPC router surface served over HTTP by ``@dokploy/trpc-openapi``
at ``<endpoint>/api/<router>.<procedure>``: GET for queries (input flattened into
query params), POST for mutations (JSON body). Auth is the ``x-api-key`` header.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


def _url(endpoint: str, proc: str) -> str:
    return endpoint.rstrip("/") + "/api/" + proc


def _headers(api_key: str) -> dict:
    return {"x-api-key": api_key, "content-type": "application/json"}


def call(conn: dict, proc: str, data: Optional[dict], method: str) -> Any:
    """Call a tRPC procedure over REST. Raises on a non-2xx response."""
    url = _url(conn["endpoint"], proc)
    if method == "GET":
        if data:
            qs = urllib.parse.urlencode(
                {k: v for k, v in data.items() if v is not None}
            )
            if qs:
                url = f"{url}?{qs}"
        req = urllib.request.Request(url, headers=_headers(conn["apiKey"]), method="GET")
    else:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            url, data=body, headers=_headers(conn["apiKey"]), method="POST"
        )
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise Exception(
            f"nomploy {method} {proc} failed: {e.code} {e.reason} - {detail}"
        ) from None
    return json.loads(text) if text else None


def trigger(conn: dict, proc: str, data: dict, wait: int = 120) -> None:
    """Fire a long-running action (e.g. a deploy) and wait up to ``wait`` seconds.

    Some deploy endpoints (notably the databases' ``<engine>.deploy``) run the
    deployment synchronously, so the request can stay open a while. A timeout is
    treated as best-effort ("triggered, left running"); HTTP errors still raise.
    """
    url = _url(conn["endpoint"], proc)
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(
        url, data=body, headers=_headers(conn["apiKey"]), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=wait) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise Exception(f"nomploy POST {proc} failed: {e.code} {e.reason} - {detail}") from None
    except (socket.timeout, urllib.error.URLError, TimeoutError):
        # Long-running deploy — the server keeps going after we stop waiting.
        return
