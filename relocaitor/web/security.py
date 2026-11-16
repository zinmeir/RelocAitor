"""
relocaitor/web/security.py — request logging, rate limiting and security headers for the Flask app.

    RELOC_RATE_LIMIT      requests per minute per client on /api/* (default 240; 0 disables)
    RELOC_LOG_JSON=1      one JSON line per request on stderr (method, path, status, ms) for log
                          collectors; never logs bodies, so no profile data reaches the logs

The limiter keeps counters in memory, which is right for one process. Behind several workers or
machines, put a shared limiter (e.g. Redis or the platform's) in front; the interface stays the same.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections import defaultdict, deque

from flask import Flask, g, jsonify, request

log = logging.getLogger("relocaitor")

# Stricter limits where a request is expensive or sensitive.
SPECIAL = {"/api/me/login": 10, "/api/me/register": 5, "/api/assistant": 30, "/api/ask": 30}


class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


limiter = RateLimiter()


def client_id() -> str:
    # Behind a proxy, set the platform's trusted proxy count (werkzeug ProxyFix) so remote_addr is the client.
    return request.remote_addr or "unknown"


def install(app: Flask) -> None:
    if os.environ.get("RELOC_LOG_JSON") == "1" and not log.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)

    @app.before_request
    def _start():
        g.t0 = time.perf_counter()
        if not request.path.startswith("/api/") or request.path == "/api/health":
            return None
        base = int(os.environ.get("RELOC_RATE_LIMIT", "240"))
        if base <= 0:
            return None
        limit = SPECIAL.get(request.path, base)
        if not limiter.allow(f"{client_id()}|{request.path if request.path in SPECIAL else '*'}", limit):
            return jsonify({"error": "Too many requests; wait a minute and try again."}), 429
        return None

    @app.after_request
    def _finish(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=(self)")
        if request.path.startswith("/api/me"):
            resp.headers["Cache-Control"] = "no-store"
        if os.environ.get("RELOC_LOG_JSON") == "1":
            ms = int((time.perf_counter() - g.get("t0", time.perf_counter())) * 1000)
            log.info(json.dumps({"method": request.method, "path": request.path, "status": resp.status_code, "ms": ms}))
        return resp
