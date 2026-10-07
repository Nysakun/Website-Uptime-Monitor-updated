"""A simple in-memory rate limiter: N requests per IP per time window."""

import time
from collections import defaultdict, deque
from threading import Lock

WINDOW_SECONDS = 60
MAX_REQUESTS = 30  # per IP, per window

_lock = Lock()
_hits = defaultdict(deque)


def is_allowed(client_ip):
    """Return True if this IP may make another request right now."""
    now = time.time()
    with _lock:
        hits = _hits[client_ip]
        while hits and hits[0] <= now - WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= MAX_REQUESTS:
            return False
        hits.append(now)
        return True 