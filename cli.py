"""Command-line interface: reads arguments and connects all the other modules."""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .checker import check_website
from .database import get_history, init_db, save_checks
from .stats import format_stats, get_all_stats, get_uptime_stats

DEFAULT_WEBSITES_FILE = "websites.txt"
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_HISTORY_LIMIT = 10
MAX_WORKERS = 10
MAX_URL_WIDTH = 45


# ---------- small helpers ----------

def to_local_time(iso_text):
    """Convert a stored UTC timestamp into local time for display."""
    local = datetime.fromisoformat(iso_text).astimezone()
    return local.strftime("%d %b %Y, %I:%M:%S %p")


def fmt_status(is_up):
    return "UP" if is_up else "DOWN"


def fmt_code(code):
    return str(code) if code is not None else "-"


def fmt_speed(ms):
    return f"{ms}ms" if ms is not None else "-"


def short(text, width):
    """Cut very long text so the table stays aligned."""
    return text if len(text) <= width else text[: width - 3] + "..."


def find_target(text):
    """Match what the user typed to a saved target (google.com or https://google.com)."""
    text = text.strip()
    for candidate in (text, "https://" + text, "http://" + text):
        if get_history(candidate, 1):
            return candidate
    return text


# ---------- loading and checking ----------

def load_websites(path):
    """Read targets from a text file (one per line, '#' lines are comments)."""
    file = Path(path)
    if not file.exists():
        print(f"Error: file '{path}' not found.")
        sys.exit(1)

    urls = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)

    urls = list(dict.fromkeys(urls))  # remove duplicates, keep order
    if not urls:
        print(f"Error: no websites found in '{path}'.")
        sys.exit(1)
    return urls


def check_all(urls):
    """Check all targets at the same time using threads."""
    workers = min(MAX_WORKERS, len(urls))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(check_website, urls))


# ---------- printing ----------

def print_results_table(results):
    """Show the results of one round as a neat table."""
    width = min(MAX_URL_WIDTH, max(len(r["url"]) for r in results))
    print(f"Checked at: {to_local_time(results[0]['checked_at'])}\n")
    print(
        f"{'TARGET':<{width}}  {'TYPE':<6}  {'STATUS':<6}  {'CODE':<5}  "
        f"{'TIME':<8}  {'IP':<15}  PROBLEM"
    )
    print("-" * (width + 75))
    for r in results:
        print(
            f"{short(r['url'], width):<{width}}  "
            f"{(r['target_type'] or '-'):<6}  "
            f"{fmt_status(r['is_up']):<6}  "
            f"{fmt_code(r['status_code']):<5}  "
            f"{fmt_speed(r['response_time_ms']):<8}  "
            f"{short(r['resolved_ip'] or '-', 15):<15}  "
            f"{r['error'] or '-'}"
        )


def run_once(urls):
    """Check every target one time, save and print the results."""
    results = check_all(urls)
    save_checks(results)
    print_results_table(results)

    up_count = sum(1 for r in results if r["is_up"])
    print(f"\nSummary: {up_count} of {len(results)} targets are UP")


def run_watch(urls, interval):
    """Keep checking forever, waiting `interval` seconds between rounds."""
    print(f"Watching {len(urls)} target(s) every {interval}s. Press Ctrl+C to stop.\n")
    try:
        while True:
            run_once(urls)
            print(f"\nNext check in {interval}s...\n" + "=" * 60 + "\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")


def show_history(url, limit):
    """Print the most recent checks for one target."""
    rows = get_history(url, limit)
    if not rows:
        print(f"No records found for {url}")
        return

    print(f"Last {len(rows)} check(s) for {url}\n")
    print(f"{'WHEN':<26}{'STATUS':<8}{'CODE':<6}{'TIME':<9}PROBLEM")
    print("-" * 75)
    for row in rows:
        print(
            f"{to_local_time(row['checked_at']):<26}"
            f"{fmt_status(row['is_up']):<8}"
            f"{fmt_code(row['status_code']):<6}"
            f"{fmt_speed(row['response_time_ms']):<9}"
            f"{row['error'] or '-'}"
        )


def show_stats(url):
    """Print the uptime percentage summary for one target."""
    stats = get_uptime_stats(url)
    if stats is None:
        print(f"No records found for {url}")
        return
    print(format_stats(stats))


def show_report():
    """Print one table with the uptime of ALL targets."""
    all_stats = get_all_stats()
    if not all_stats:
        print("No data yet. Run:  python main.py --once")
        return

    width = min(MAX_URL_WIDTH, max(len(s["url"]) for s in all_stats))
    print("UPTIME REPORT\n")
    print(
        f"{'TARGET':<{width}}  {'NOW':<5}  {'UPTIME':<8}  "
        f"{'CHECKS':<7}  {'FAILED':<7}  AVG SPEED"
    )
    print("-" * (width + 50))
    for s in all_stats:
        uptime = f"{s['uptime_percent']:.2f}%"
        avg = s["avg_response_ms"]
        avg_text = f"{avg:.0f}ms" if avg is not None else "-"
        print(
            f"{short(s['url'], width):<{width}}  "
            f"{fmt_status(s['last_is_up']):<5}  "
            f"{uptime:<8}  "
            f"{s['total']:<7}  "
            f"{s['failed']:<7}  "
            f"{avg_text}"
        )


# ---------- command-line arguments ----------

def build_parser():
    """Define all the command-line options."""
    parser = argparse.ArgumentParser(
        prog="uptime-monitor",
        description="Monitor domains, IPs and URLs and store the history in SQLite.",
    )

    # Pick ONE of these actions
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once", action="store_true",
        help="check all targets one time and exit",
    )
    mode.add_argument(
        "--watch", action="store_true",
        help="keep checking at a fixed interval (Ctrl+C to stop)",
    )
    mode.add_argument(
        "--history", metavar="TARGET",
        help="show recent checks for one domain/IP",
    )
    mode.add_argument(
        "--stats", metavar="TARGET",
        help="show detailed uptime percentage for one domain/IP",
    )

    # Can be combined with the actions above, e.g.  --once --report
    parser.add_argument(
        "--report", action="store_true",
        help="show uptime of ALL targets in one table",
    )
    parser.add_argument(
        "--file", default=DEFAULT_WEBSITES_FILE,
        help=f"file with targets to monitor (default: {DEFAULT_WEBSITES_FILE})",
    )
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL_SECONDS,
        help=f"seconds between checks in --watch mode (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_HISTORY_LIMIT,
        help=f"rows to show with --history (default: {DEFAULT_HISTORY_LIMIT})",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not (args.once or args.watch or args.report or args.history or args.stats):
        parser.error("choose one of: --once, --watch, --report, --history, --stats")
    if args.interval < 1:
        parser.error("--interval must be at least 1 second")
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    init_db()

    if args.once:
        run_once(load_websites(args.file))
    elif args.watch:
        run_watch(load_websites(args.file), args.interval)
    elif args.history:
        show_history(find_target(args.history), args.limit)
    elif args.stats:
        show_stats(find_target(args.stats))

    if args.report:
        if args.once or args.watch:
            print("\n" + "=" * 60 + "\n")
        show_report() 