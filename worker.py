"""Background worker: checks every target in the watchlist at a fixed interval."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

from .checker import check_website
from .database import get_watchlist, save_checks
from .safety import is_allowed

# Seconds between rounds. Change with:  $env:MONITOR_INTERVAL = "15"   (minimum 10)
CHECK_INTERVAL_SECONDS = max(10, int(os.environ.get("MONITOR_INTERVAL", "60")))
MAX_WORKERS = 10

_stop = threading.Event()
_thread = None


def run_round():
    """Check every allowed target in the watchlist once and save the results."""
    targets = [t for t in get_watchlist() if is_allowed(t)]
    if not targets:
        return

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(targets))) as executor:
        results = list(executor.map(check_website, targets))

    save_checks(results)
    up = sum(1 for r in results if r["is_up"])
    print(f"[worker] checked {len(results)} target(s): {up} up, {len(results) - up} down")


def _loop():
    while not _stop.is_set():
        try:
            run_round()
        except Exception as exc:  # the worker must never die because of one bad round
            print(f"[worker] round failed: {exc}")
        _stop.wait(CHECK_INTERVAL_SECONDS)  # sleeps, but wakes up at once on stop


def start_worker():
    """Start the background thread (does nothing if it is already running)."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="uptime-worker", daemon=True)
    _thread.start()


def stop_worker():
    _stop.set() 