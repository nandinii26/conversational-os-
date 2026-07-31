"""
database.py — PostgreSQL backend (psycopg2)

Swap from SQLite:  ? placeholders → %s
                   AUTOINCREMENT  → SERIAL
                   INSERT OR REPLACE → INSERT … ON CONFLICT … DO UPDATE
                   Per-call connections → ThreadedConnectionPool
"""

import os
import re
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

# ── Connection pool (2–10 connections) ─────────────────────────────────────
# ThreadedConnectionPool is safe to share across threads (FastAPI/uvicorn workers).
_pool: ThreadedConnectionPool | None = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), override=True)
        db_url = os.environ.get("DATABASE_URL")
        if not db_url or "HOST" in db_url or "USER:PASSWORD" in db_url:
            db_url = os.environ.get("Internal_Database_URL")
        
        if not db_url or "HOST" in db_url or "USER:PASSWORD" in db_url:
            raise RuntimeError(
                "DATABASE_URL is not configured properly!\n"
                "For PostgreSQL, set DATABASE_URL in your environment variables to a valid PostgreSQL connection string."
            )
            
        db_url = db_url.strip('"').strip("'")

        try:
            _pool = ThreadedConnectionPool(minconn=2, maxconn=10, dsn=db_url)
        except Exception as primary_exc:
            # If running locally with a Render internal connection string (dpg-xxxx-a), fallback to external domain
            if "@dpg-" in db_url and ".render.com" not in db_url:
                ext_url = re.sub(r'(@dpg-[^/]+)', r'\1.oregon-postgres.render.com', db_url)
                try:
                    _pool = ThreadedConnectionPool(minconn=2, maxconn=10, dsn=ext_url)
                except Exception:
                    raise primary_exc
            else:
                raise primary_exc
            
    return _pool


def _get_conn():
    """Borrow a connection from the pool."""
    return _get_pool().getconn()


def _put_conn(conn, close: bool = False):
    """Return a connection to the pool (or discard it on error)."""
    _get_pool().putconn(conn, close=close)


# Kept for backward-compat: api.py calls execute_query(DB_FILE) on startup.
# We ignore the argument and just run the schema migration.
DB_FILE = None  # not used for PostgreSQL


# ── Schema initialisation ───────────────────────────────────────────────────

def execute_query(_ignored=None):
    """Create tables if they don't exist. Called once on app startup."""
    conn = _get_conn()
    try:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          SERIAL PRIMARY KEY,
            session_id  TEXT        NOT NULL,
            sender      TEXT        NOT NULL,
            text        TEXT        NOT NULL,
            timestamp   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id          SERIAL PRIMARY KEY,
            session_id  TEXT        NOT NULL,
            step        TEXT        NOT NULL,
            timestamp   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id               SERIAL PRIMARY KEY,
            email            TEXT UNIQUE NOT NULL,
            hashed_password  TEXT        NOT NULL,
            name             TEXT,
            created_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.commit()
        print("PostgreSQL database initialized successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Error initialising database: {e}")
        raise
    finally:
        _put_conn(conn)


# ── Public API (same signatures as the old SQLite version) ─────────────────

def save_chat(session_id: str, sender: str, text: str) -> None:
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (session_id, sender, text) VALUES (%s, %s, %s)",
            (session_id, sender, text),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)


def get_chat(session_id: str) -> list:
    """Return list of (sender, text, timestamp) tuples ordered by time."""
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT sender, text, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp
            """,
            (session_id,),
        )
        return cursor.fetchall()
    finally:
        _put_conn(conn)


def save_steps(session_id: str, steps: list) -> None:
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        psycopg2.extras.execute_batch(
            cursor,
            "INSERT INTO activity_logs (session_id, step) VALUES (%s, %s)",
            [(session_id, step) for step in steps],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)


def create_user(email: str, hashed_password: str, name: str = None) -> None:
    """Insert or update a user row (upsert on email conflict)."""
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (email, hashed_password, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO UPDATE
                SET hashed_password = EXCLUDED.hashed_password,
                    name            = EXCLUDED.name
            """,
            (email, hashed_password, name),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)


def get_user_by_email(email: str) -> dict | None:
    conn = _get_conn()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            """
            SELECT email, hashed_password, name
            FROM users
            WHERE email = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (email,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        _put_conn(conn)


def session_list() -> list:
    """Return list of (session_id,) tuples for all distinct sessions."""
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT session_id FROM messages")
        return cursor.fetchall()
    finally:
        _put_conn(conn)


def get_session_first_messages() -> list[dict]:
    """Return the first user message for every session in a single query."""
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        # PostgreSQL DISTINCT ON — efficient single-pass query
        cursor.execute(
            """
            SELECT DISTINCT ON (session_id)
                session_id, text
            FROM messages
            WHERE sender = 'user'
            ORDER BY session_id, id ASC
            """
        )
        rows = cursor.fetchall()
        return [{"session_id": row[0], "first_message": row[1]} for row in rows]
    finally:
        _put_conn(conn)


def delete_session(session_id: str) -> None:
    """Delete all messages and activity logs for a given session."""
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
        cursor.execute("DELETE FROM activity_logs WHERE session_id = %s", (session_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)