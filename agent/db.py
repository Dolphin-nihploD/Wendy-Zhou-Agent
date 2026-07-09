"""
agent/db.py
===========
Persistent storage for Wendy: conversations, messages, memories, and to-dos.

Uses PostgreSQL when DATABASE_URL is set (Railway provides this automatically
when you add a Postgres plugin to your project). Falls back to a local SQLite
file (wendy.db) when DATABASE_URL is not set, so everything still works on
your machine with zero setup.

Tables:
    conversations(id, title, created_at, updated_at, pinned)
    messages(id, conversation_id, role, content, images_json, artifact_json, created_at)
    memories(id, content, category, created_at)
    todos(id, content, done, created_at)
"""

import os
import json
import sqlite3
import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "wendy.db")

_IS_PG = DATABASE_URL.startswith("postgres")

# ---------------------------------------------------- instance identity ----
# Railway sets several RAILWAY_* env vars automatically on every deploy; a
# plain local `python app.py` run never has any of them. That makes this a
# reliable, zero-config way to tell "this is the cloud instance" apart from
# "this is running on the user's own machine" — used to tag activity-log
# entries (see below) so each side can tell which of them did what. Override
# with WENDY_INSTANCE=local|cloud in .env if you ever need to force it.
_forced_instance = os.environ.get("WENDY_INSTANCE", "").strip().lower()
if _forced_instance in ("local", "cloud"):
    INSTANCE_SOURCE = _forced_instance
else:
    INSTANCE_SOURCE = "cloud" if any(k.startswith("RAILWAY_") for k in os.environ) else "local"


def _connect():
    if _IS_PG:
        import psycopg2
        import psycopg2.extras
        # Railway's DATABASE_URL sometimes uses postgres:// which psycopg2 accepts fine
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def _ph():
    """Parameter placeholder — psycopg2 uses %s, sqlite uses ?"""
    return "%s" if _IS_PG else "?"


def _column_exists(cur, table, column):
    """Return True if `column` already exists on `table`.

    Works for both backends:
      - Postgres: query information_schema.columns
      - SQLite:   PRAGMA table_info(<table>)  (column name is at index 1)

    This lets init_db() check BEFORE attempting an ALTER TABLE, instead of
    running the ALTER blindly and swallowing every exception — see init_db().
    """
    if _IS_PG:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            (table, column),
        )
        return cur.fetchone() is not None
    else:
        cur.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cur.fetchall())


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    conn = _connect()
    cur = conn.cursor()
    if _IS_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New chat',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                images_json TEXT,
                artifact_json TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                fired INTEGER NOT NULL DEFAULT 0,
                recurrence TEXT NOT NULL DEFAULT 'none',
                kind TEXT NOT NULL DEFAULT 'reminder',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT 'New chat',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                images_json TEXT,
                artifact_json TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                fired INTEGER NOT NULL DEFAULT 0,
                recurrence TEXT NOT NULL DEFAULT 'none',
                kind TEXT NOT NULL DEFAULT 'reminder',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
    conn.commit()

    if not _IS_PG:
        print("[db] No DATABASE_URL set — running on local SQLite. The activity "
              "log (Phase 9) will be LOCAL-ONLY until DATABASE_URL here points at "
              "the same Postgres database your Railway deployment uses (Railway → "
              "your Postgres plugin → Connect tab → public connection URL).")

    # --- Schema migrations --------------------------------------------------
    # Older databases (created before these columns existed) need them added.
    #
    # We check whether each column is already present FIRST, then only run
    # ALTER TABLE when it's actually missing. The previous version wrapped a
    # blind ALTER TABLE in a bare `except Exception: rollback()`, which assumed
    # ANY error meant "column already exists" — it couldn't tell that apart
    # from a real failure (bad connection, permissions, locked DB), so genuine
    # startup problems were swallowed silently. By checking first, any error
    # that ALTER TABLE now raises is a real one and is allowed to propagate.
    if not _column_exists(cur, "messages", "artifact_json"):
        cur.execute("ALTER TABLE messages ADD COLUMN artifact_json TEXT")
        conn.commit()

    if not _column_exists(cur, "conversations", "pinned"):
        cur.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        conn.commit()

    if not _column_exists(cur, "reminders", "recurrence"):
        cur.execute("ALTER TABLE reminders ADD COLUMN recurrence TEXT NOT NULL DEFAULT 'none'")
        conn.commit()

    if not _column_exists(cur, "reminders", "kind"):
        cur.execute("ALTER TABLE reminders ADD COLUMN kind TEXT NOT NULL DEFAULT 'reminder'")
        conn.commit()

    cur.close()
    conn.close()


# ---------------------------------------------------------------- memories --
def add_memory(content, category="general"):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"INSERT INTO memories (content, category) VALUES ({p}, {p})", (content, category))
    conn.commit()
    cur.close(); conn.close()


def list_memories():
    conn = _connect(); cur = conn.cursor()
    cur.execute("SELECT id, content, category, created_at FROM memories ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def delete_memory(memory_id):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"DELETE FROM memories WHERE id = {p}", (memory_id,))
    conn.commit()
    cur.close(); conn.close()


def memories_as_text(limit=50):
    """Compact text block of memories for injecting into the system prompt."""
    mems = list_memories()[:limit]
    if not mems:
        return ""
    lines = [f"- [{m['category']}] {m['content']}" for m in mems]
    return "\n".join(lines)


# ------------------------------------------------------------------- todos --
# A simple to-do list stored in Wendy's own DB. Same add/list/delete pattern
# as memories, plus a done toggle. No Google Calendar / OAuth dependency —
# this works immediately and can sync with Calendar later once that's built.
def add_todo(content):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    if _IS_PG:
        cur.execute(f"INSERT INTO todos (content) VALUES ({p}) RETURNING id", (content,))
        new_id = cur.fetchone()["id"]
    else:
        cur.execute(f"INSERT INTO todos (content) VALUES ({p})", (content,))
        new_id = cur.lastrowid
    conn.commit()
    cur.close(); conn.close()
    return new_id


def list_todos():
    conn = _connect(); cur = conn.cursor()
    # unfinished first, then most-recent first
    cur.execute("SELECT id, content, done, created_at FROM todos ORDER BY done ASC, created_at DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def set_todo_done(todo_id, done):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"UPDATE todos SET done = {p} WHERE id = {p}", (1 if done else 0, todo_id))
    conn.commit()
    cur.close(); conn.close()


def delete_todo(todo_id):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"DELETE FROM todos WHERE id = {p}", (todo_id,))
    conn.commit()
    cur.close(); conn.close()


# --------------------------------------------------------------- reminders --
# Time-based reminders. remind_at is a LOCAL ISO datetime string
# ("YYYY-MM-DDTHH:MM"), computed in the user's local time. The "due" check
# compares it against a local "now" the browser sends, so it works no matter
# what timezone the server runs in (e.g. UTC on Railway).
def add_reminder(text, remind_at, recurrence="none", kind="reminder"):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cols = f"(text, remind_at, recurrence, kind) VALUES ({p},{p},{p},{p})"
    vals = (text, remind_at, recurrence or "none", kind or "reminder")
    if _IS_PG:
        cur.execute(f"INSERT INTO reminders {cols} RETURNING id", vals)
        new_id = cur.fetchone()["id"]
    else:
        cur.execute(f"INSERT INTO reminders {cols}", vals)
        new_id = cur.lastrowid
    conn.commit()
    cur.close(); conn.close()
    return new_id


def list_reminders(include_fired=False):
    conn = _connect(); cur = conn.cursor()
    cols = "id, text, remind_at, fired, recurrence, kind, created_at"
    if include_fired:
        cur.execute(f"SELECT {cols} FROM reminders ORDER BY remind_at ASC")
    else:
        cur.execute(f"SELECT {cols} FROM reminders WHERE fired = 0 ORDER BY remind_at ASC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def due_reminders(now_iso):
    """Not-yet-fired reminders whose time is at or before the given local 'now'."""
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(
        f"SELECT id, text, remind_at, recurrence, kind FROM reminders "
        f"WHERE fired = 0 AND remind_at <= {p} ORDER BY remind_at ASC",
        (now_iso,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def mark_reminder_fired(reminder_id):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"UPDATE reminders SET fired = 1 WHERE id = {p}", (reminder_id,))
    conn.commit()
    cur.close(); conn.close()


def advance_reminder(reminder_id, next_at):
    """For a recurring reminder: move its time to the next occurrence (keeps it
    active instead of marking it fired)."""
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"UPDATE reminders SET remind_at = {p} WHERE id = {p}", (next_at, reminder_id))
    conn.commit()
    cur.close(); conn.close()


def delete_reminder(reminder_id):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"DELETE FROM reminders WHERE id = {p}", (reminder_id,))
    conn.commit()
    cur.close(); conn.close()


# ----------------------------------------------------------- conversations --
def create_conversation(title="New chat"):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    if _IS_PG:
        cur.execute(f"INSERT INTO conversations (title) VALUES ({p}) RETURNING id", (title,))
        new_id = cur.fetchone()["id"]
    else:
        cur.execute(f"INSERT INTO conversations (title) VALUES ({p})", (title,))
        new_id = cur.lastrowid
    conn.commit()
    cur.close(); conn.close()
    return new_id


def list_conversations():
    conn = _connect(); cur = conn.cursor()
    cur.execute("SELECT id, title, pinned, created_at, updated_at FROM conversations ORDER BY pinned DESC, updated_at DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def rename_conversation(conv_id, title):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    now = "NOW()" if _IS_PG else "datetime('now')"
    cur.execute(f"UPDATE conversations SET title = {p}, updated_at = {now} WHERE id = {p}", (title, conv_id))
    conn.commit()
    cur.close(); conn.close()


def pin_conversation(conv_id, pinned):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"UPDATE conversations SET pinned = {p} WHERE id = {p}", (1 if pinned else 0, conv_id))
    conn.commit()
    cur.close(); conn.close()


def touch_conversation(conv_id):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    now = "NOW()" if _IS_PG else "datetime('now')"
    cur.execute(f"UPDATE conversations SET updated_at = {now} WHERE id = {p}", (conv_id,))
    conn.commit()
    cur.close(); conn.close()


def delete_conversation(conv_id):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"DELETE FROM messages WHERE conversation_id = {p}", (conv_id,))
    cur.execute(f"DELETE FROM conversations WHERE id = {p}", (conv_id,))
    conn.commit()
    cur.close(); conn.close()


def add_message(conv_id, role, content, images=None, artifact=None):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    images_json = json.dumps(images) if images else None
    artifact_json = json.dumps(artifact) if artifact else None
    cur.execute(
        f"INSERT INTO messages (conversation_id, role, content, images_json, artifact_json) VALUES ({p},{p},{p},{p},{p})",
        (conv_id, role, content, images_json, artifact_json),
    )
    conn.commit()
    cur.close(); conn.close()
    touch_conversation(conv_id)


def get_messages(conv_id):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(f"SELECT role, content, images_json, artifact_json, created_at FROM messages WHERE conversation_id = {p} ORDER BY id ASC", (conv_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r["images"] = json.loads(r.pop("images_json")) if r.get("images_json") else []
        r["artifact"] = json.loads(r.pop("artifact_json")) if r.get("artifact_json") else None
    return rows


def search_messages(query, limit=60):
    """Keyword search across every message. Returns matching messages with the
    parent conversation's id/title and a short snippet, newest first. The
    frontend groups these by conversation so you can jump straight to a chat
    where a topic was mentioned weeks ago.
    """
    q = (query or "").strip()
    if not q:
        return []
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    like = f"%{q}%"
    cur.execute(
        f"""SELECT m.conversation_id AS conversation_id,
                   c.title           AS title,
                   c.pinned          AS pinned,
                   m.role            AS role,
                   m.content         AS content,
                   m.created_at      AS created_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.content LIKE {p}
            ORDER BY m.id DESC
            LIMIT {limit}""",
        (like,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    # attach a compact snippet centred on the match (case-insensitive)
    ql = q.lower()
    for r in rows:
        content = r.get("content") or ""
        idx = content.lower().find(ql)
        if idx == -1:
            snippet = content[:120]
        else:
            start = max(0, idx - 40)
            end = min(len(content), idx + len(q) + 40)
            snippet = ("…" if start > 0 else "") + content[start:end] + ("…" if end < len(content) else "")
        r["snippet"] = snippet.replace("\n", " ").strip()
    return rows


# ------------------------------------------------------------ activity log --
# Phase 9 v1: a shared "what have I been up to" feed between the local and
# cloud instances of Wendy. Deliberately lightweight — short one-line notes
# covering BOTH conversations with the user AND self-run tasks she does on
# her own (daily briefing generation, a reminder/news email firing, sending
# an email on the user's behalf) — not full conversation transcripts. See
# recent_activity_text(), injected into the system prompt in
# wendy_agent.ask_wendy(), so each instance is aware of what "the other you"
# (and this you) has actually been doing.
#
# IMPORTANT: this only actually SHARES anything if both instances point at
# the SAME Postgres database — i.e. your local .env also has DATABASE_URL set
# to the same Railway Postgres connection string the cloud deployment uses.
# Without that, local falls back to its own SQLite file and this table stays
# local-only (still a harmless personal activity log, just not shared yet —
# see the startup print in init_db()).
_ACTIVITY_KEEP = 300  # prune old rows so the table (and prompt text) stay small


def log_activity(kind, summary, source=None):
    """Record one short activity note.

    kind    : free-form label, e.g. "chat" (talked with the user) or
              "task" (something Wendy did on her own — briefing, reminder
              firing, sending an email, etc.)
    summary : a single short line describing what happened.
    """
    summary = (summary or "").strip().replace("\n", " ")[:300]
    if not summary:
        return
    src = source or INSTANCE_SOURCE
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(
        f"INSERT INTO activity_log (source, kind, summary) VALUES ({p},{p},{p})",
        (src, kind, summary),
    )
    # keep the table (and the system-prompt text built from it) small
    cur.execute(
        f"DELETE FROM activity_log WHERE id NOT IN "
        f"(SELECT id FROM activity_log ORDER BY id DESC LIMIT {p})",
        (_ACTIVITY_KEEP,),
    )
    conn.commit()
    cur.close(); conn.close()


def recent_activity(limit=12):
    conn = _connect(); cur = conn.cursor()
    p = _ph()
    cur.execute(
        f"SELECT source, kind, summary, created_at FROM activity_log ORDER BY id DESC LIMIT {p}",
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def recent_activity_text(limit=10):
    """Compact text block for the system prompt, newest first."""
    rows = recent_activity(limit)
    if not rows:
        return ""
    lines = []
    for r in rows:
        ts = str(r.get("created_at", ""))[:16].replace("T", " ")
        lines.append(f"- [{r['source']}] ({r['kind']}) {ts} — {r['summary']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- export ----
def export_all():
    """Full backup of everything Wendy stores for the user: memories, to-dos,
    and every conversation with its messages. Returned as a plain dict so the
    web layer can hand it back as a downloadable JSON file — a backup that's
    independent of Railway/Postgres.
    """
    data = {
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "memories": list_memories(),
        "todos": list_todos(),
        "conversations": [],
    }
    for c in list_conversations():
        msgs = get_messages(c["id"])
        entry = dict(c)
        entry["messages"] = msgs
        data["conversations"].append(entry)
    return data