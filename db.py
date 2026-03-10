import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "taste_buddy.db"

VALID_TYPES = {"movie", "book", "series", "comic"}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                title   TEXT NOT NULL,
                type    TEXT NOT NULL CHECK(type IN ('movie','book','series','comic')),
                review  TEXT,
                date    TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS profile (
                id          INTEGER PRIMARY KEY CHECK(id = 1),
                content     TEXT,
                updated_at  TEXT
            )
        """)
        conn.commit()


def get_all(type_filter=None):
    query = "SELECT * FROM entries WHERE 1=1"
    params = []
    if type_filter:
        query += " AND type = ?"
        params.append(type_filter)
    query += " ORDER BY date DESC, id DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_one(entry_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None


def create(title, type_, review, entry_date=None):
    entry_date = entry_date or str(date.today().year)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entries (title, type, review, date) VALUES (?, ?, ?, ?)",
            (title, type_, review, entry_date),
        )
        conn.commit()
        return get_one(cur.lastrowid)


def update(entry_id, **fields):
    allowed = {"title", "type", "review", "date"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not fields:
        return get_one(entry_id)
    sets = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE entries SET {sets} WHERE id = ?", (*fields.values(), entry_id))
        conn.commit()
    return get_one(entry_id)


def delete(entry_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        conn.commit()


def get_all_with_reviews(type_filter=None):
    query = ("SELECT title, type, review, date FROM entries "
             "WHERE review IS NOT NULL AND review != ''")
    params = []
    if type_filter:
        query += " AND type = ?"
        params.append(type_filter)
    query += " ORDER BY date DESC, id DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


# ── Profile ──

def get_profile():
    with get_conn() as conn:
        row = conn.execute("SELECT content, updated_at FROM profile WHERE id = 1").fetchone()
        return dict(row) if row else {"content": None, "updated_at": None}


def save_profile(content):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO profile (id, content, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
            (content, now),
        )
        conn.commit()
    return get_profile()
