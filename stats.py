"""Calculates uptime percentage and other statistics from saved history."""

from contextlib import closing

from .database import DB_ENGINE, get_connection

if DB_ENGINE == "mysql":
    STATS_QUERY = """
        SELECT
            c1.url                                                  AS url,
            COUNT(*)                                                AS total,
            SUM(c1.is_up)                                           AS successful,
            AVG(CASE WHEN c1.is_up = 1 THEN c1.response_time_ms END) AS avg_response,
            (SELECT c2.is_up FROM checks c2
              WHERE c2.url = c1.url ORDER BY c2.id DESC LIMIT 1)     AS last_is_up
        FROM checks c1
    """
else:
    STATS_QUERY = """
        SELECT
            c1.url                                                  AS url,
            COUNT(*)                                                AS total,
            SUM(c1.is_up)                                           AS successful,
            AVG(CASE WHEN c1.is_up = 1 THEN c1.response_time_ms END) AS avg_response,
            (SELECT c2.is_up FROM checks c2
              WHERE c2.url = c1.url ORDER BY c2.id DESC LIMIT 1)     AS last_is_up
        FROM checks c1
    """


def _row_to_stats(row):
    """Turn one database row into a friendly dictionary."""
    total = row["total"]
    successful = row["successful"] or 0
    return {
        "url": row["url"],
        "total": total,
        "successful": successful,
        "failed": total - successful,
        "uptime_percent": (successful / total * 100) if total else 0.0,
        "avg_response_ms": float(row["avg_response"]) if row["avg_response"] is not None else None,
        "last_is_up": bool(row["last_is_up"]) if row["last_is_up"] is not None else False,
    }


def _run(sql, params=()):
    """Run a SELECT and return all rows as dict-like objects, for either engine."""
    with closing(get_connection()) as conn:
        if DB_ENGINE == "mysql":
            sql = sql.replace("?", "%s")
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()  # list of dicts
        return conn.execute(sql, params).fetchall()  # list of sqlite3.Row


def get_uptime_stats(url):
    """Return stats for one website, or None if it has no records."""
    rows = _run(STATS_QUERY + " WHERE c1.url = ? GROUP BY c1.url", (url,))
    return _row_to_stats(rows[0]) if rows else None


def get_all_stats():
    """Return stats for every website in the database."""
    rows = _run(STATS_QUERY + " GROUP BY c1.url ORDER BY c1.url")
    return [_row_to_stats(row) for row in rows]


def format_stats(stats):
    """Turn the stats dictionary into a nicely aligned text block."""
    avg = stats["avg_response_ms"]
    avg_text = f"{avg:.0f}ms" if avg is not None else "N/A"

    return (
        f"Website: {stats['url']}\n\n"
        f"Uptime:       {stats['uptime_percent']:.2f}%\n"
        f"Checks:       {stats['total']:,}\n"
        f"Successful:   {stats['successful']:,}\n"
        f"Failed:       {stats['failed']:,}\n"
        f"Avg Response: {avg_text}"
    ) 