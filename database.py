"""Database layer. Uses SQLite by default, or MySQL when DB_ENGINE=mysql is set."""

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads the .env file into the environment, if it exists

DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite").lower()
SQLITE_PATH = Path(__file__).resolve().parent.parent / "uptime.db"

# Columns added after the first (SQLite-only) version of the project
NEW_COLUMNS = ("target_type", "resolved_ip", "checked_url", "error_kind")


# ---------- connecting ----------

def get_connection():
    """Open a database connection. Rows can always be read by column name."""
    if DB_ENGINE == "mysql":
        import pymysql

        return pymysql.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ["DB_NAME"],
            cursorclass=pymysql.cursors.DictCursor,  # rows come back as dicts
            autocommit=False,
        )

    conn = sqlite3.connect(SQLITE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _ph(count):
    """Return the right number of placeholders for the active engine.

    SQLite uses "?", MySQL uses "%s".
    """
    mark = "%s" if DB_ENGINE == "mysql" else "?"
    return ", ".join([mark] * count)


# ---------- setup ----------

def _init_sqlite(conn):
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                url              TEXT    NOT NULL,
                is_up            INTEGER NOT NULL,
                status_code      INTEGER,
                response_time_ms INTEGER,
                error            TEXT,
                checked_at       TEXT    NOT NULL,
                target_type      TEXT,
                resolved_ip      TEXT,
                checked_url      TEXT,
                error_kind       TEXT
            )
            """
        )
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(checks)")}
        for column in NEW_COLUMNS:
            if column not in existing:
                conn.execute(f"ALTER TABLE checks ADD COLUMN {column} TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_checks_url ON checks (url)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                target   TEXT PRIMARY KEY,
                added_at TEXT NOT NULL
            )
            """
        )


def _init_mysql(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS checks (
                id               INT AUTO_INCREMENT PRIMARY KEY,
                url              VARCHAR(500) NOT NULL,
                is_up            TINYINT(1)   NOT NULL,
                status_code      INT,
                response_time_ms INT,
                error            TEXT,
                checked_at       VARCHAR(40)  NOT NULL,
                target_type      VARCHAR(20),
                resolved_ip      VARCHAR(50),
                checked_url      VARCHAR(500),
                error_kind       VARCHAR(30),
                INDEX idx_checks_url (url(191))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                target   VARCHAR(500) PRIMARY KEY,
                added_at VARCHAR(40) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    conn.commit()


def init_db():
    """Create the tables if they don't exist yet."""
    with closing(get_connection()) as conn:
        if DB_ENGINE == "mysql":
            _init_mysql(conn)
        else:
            _init_sqlite(conn)


# ---------- checks ----------

def save_checks(results):
    """Save a list of result dictionaries (from checker.py) in one go."""
    sql = f"""
        INSERT INTO checks
            (url, is_up, status_code, response_time_ms, error, checked_at,
             target_type, resolved_ip, checked_url, error_kind)
        VALUES ({_ph(10)})
    """
    rows = [
        (
            r["url"], int(r["is_up"]), r["status_code"], r["response_time_ms"],
            r["error"], r["checked_at"], r["target_type"], r["resolved_ip"],
            r["checked_url"], r["error_kind"],
        )
        for r in results
    ]
    with closing(get_connection()) as conn:
        if DB_ENGINE == "mysql":
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            conn.commit()
        else:
            with conn:
                conn.executemany(sql, rows)


def get_history(url, limit=10):
    """Return the most recent checks for a website (newest first)."""
    sql = f"SELECT * FROM checks WHERE url = {_ph(1)} ORDER BY id DESC LIMIT {_ph(1)}"
    with closing(get_connection()) as conn:
        if DB_ENGINE == "mysql":
            with conn.cursor() as cur:
                cur.execute(sql, (url, limit))
                return cur.fetchall()  # list of dicts
        return conn.execute(sql, (url, limit)).fetchall()  # list of sqlite3.Row


# ---------- watchlist ----------

def add_to_watchlist(target):
    """Add a target. Returns True if it was added, False if it was already there."""
    added_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(get_connection()) as conn:
        if DB_ENGINE == "mysql":
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT IGNORE INTO watchlist (target, added_at) VALUES (%s, %s)",
                    (target, added_at),
                )
                added = cur.rowcount == 1
            conn.commit()
            return added
        with conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO watchlist (target, added_at) VALUES (?, ?)",
                (target, added_at),
            )
            return cursor.rowcount == 1


def remove_from_watchlist(target):
    """Remove a target (its history is kept). Returns True if it was removed."""
    sql = f"DELETE FROM watchlist WHERE target = {_ph(1)}"
    with closing(get_connection()) as conn:
        if DB_ENGINE == "mysql":
            with conn.cursor() as cur:
                cur.execute(sql, (target,))
                removed = cur.rowcount == 1
            conn.commit()
            return removed
        with conn:
            cursor = conn.execute(sql, (target,))
            return cursor.rowcount == 1


def get_watchlist():
    """Return all monitored targets, oldest first."""
    sql = "SELECT target FROM watchlist ORDER BY added_at, target"
    with closing(get_connection()) as conn:
        if DB_ENGINE == "mysql":
            with conn.cursor() as cur:
                cur.execute(sql)
                return [row["target"] for row in cur.fetchall()]
        rows = conn.execute(sql).fetchall()
    return [row["target"] for row in rows]


def is_watched(target):
    sql = f"SELECT 1 FROM watchlist WHERE target = {_ph(1)}"
    with closing(get_connection()) as conn:
        if DB_ENGINE == "mysql":
            with conn.cursor() as cur:
                cur.execute(sql, (target,))
                return cur.fetchone() is not None
        return conn.execute(sql, (target,)).fetchone() is not None 