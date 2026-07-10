from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS users (
  did TEXT PRIMARY KEY,
  handle TEXT UNIQUE NOT NULL,
  token TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL,
  revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS profiles (
  did TEXT PRIMARY KEY REFERENCES users(did) ON DELETE CASCADE,
  handle TEXT NOT NULL,
  display_name TEXT,
  avatar_uri TEXT,
  profile_uri TEXT,
  description TEXT,
  subject_type TEXT NOT NULL DEFAULT 'human',
  profile_md TEXT
);

CREATE TABLE IF NOT EXISTS did_documents (
  did TEXT PRIMARY KEY,
  document_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS content_pages (
  id TEXT PRIMARY KEY,
  handle TEXT NOT NULL,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  visibility TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(handle, slug)
);

CREATE TABLE IF NOT EXISTS did_relationships (
  from_did TEXT NOT NULL,
  to_did TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(from_did, to_did)
);

CREATE TABLE IF NOT EXISTS site_pages (
  domain TEXT NOT NULL,
  page_kind TEXT NOT NULL,
  slug TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(domain, page_kind, slug)
);

CREATE TABLE IF NOT EXISTS direct_messages (
  message_id TEXT PRIMARY KEY,
  sender_did TEXT NOT NULL,
  recipient_did TEXT NOT NULL,
  operation_id TEXT,
  body_json TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'text/plain',
  created_at TEXT NOT NULL,
  server_seq INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS direct_message_views (
  owner_did TEXT NOT NULL,
  message_id TEXT NOT NULL REFERENCES direct_messages(message_id) ON DELETE CASCADE,
  peer_did TEXT NOT NULL,
  read_at TEXT,
  PRIMARY KEY(owner_did, message_id)
);

CREATE TABLE IF NOT EXISTS groups (
  group_did TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  description TEXT,
  join_mode TEXT NOT NULL,
  invite_token TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_members (
  group_did TEXT NOT NULL REFERENCES groups(group_did) ON DELETE CASCADE,
  member_did TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',
  joined_at TEXT NOT NULL,
  PRIMARY KEY(group_did, member_did)
);

CREATE TABLE IF NOT EXISTS group_messages (
  message_id TEXT PRIMARY KEY,
  group_did TEXT NOT NULL REFERENCES groups(group_did) ON DELETE CASCADE,
  sender_did TEXT NOT NULL,
  operation_id TEXT,
  body_json TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'text/plain',
  created_at TEXT NOT NULL,
  server_seq INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_read_states (
  owner_did TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  read_up_to_seq INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(owner_did, thread_id)
);

CREATE TABLE IF NOT EXISTS sync_events (
  event_id TEXT PRIMARY KEY,
  owner_did TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(owner_did, event_seq)
);

CREATE TABLE IF NOT EXISTS attachment_slots (
  slot_id TEXT PRIMARY KEY,
  object_id TEXT UNIQUE NOT NULL,
  attachment_id TEXT,
  object_uri TEXT,
  owner_did TEXT NOT NULL,
  upload_token TEXT NOT NULL,
  commit_token TEXT NOT NULL,
  path TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachment_objects (
  object_id TEXT PRIMARY KEY,
  source_attachment_id TEXT,
  object_uri TEXT,
  owner_did TEXT NOT NULL,
  path TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  content_type TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS download_tickets (
  ticket TEXT PRIMARY KEY,
  object_id TEXT NOT NULL REFERENCES attachment_objects(object_id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_registration_tokens (
  token_hash TEXT PRIMARY KEY,
  owner_did TEXT NOT NULL,
  agent_kind TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  used_at TEXT,
  agent_did TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_agent_bindings (
  binding_id TEXT PRIMARY KEY,
  human_did TEXT NOT NULL,
  daemon_did TEXT NOT NULL,
  runtime_agent_did TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_inventory_statuses (
  agent_did TEXT PRIMARY KEY,
  daemon_agent_did TEXT NOT NULL,
  controller_did TEXT NOT NULL,
  agent_kind TEXT NOT NULL,
  status TEXT NOT NULL,
  display_name TEXT,
  latest_status_json TEXT NOT NULL,
  invocation_policy_json TEXT NOT NULL,
  archived_at TEXT,
  updated_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path, did_domain: str = "localhost"):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init(did_domain)

    def init(self, did_domain: str = "localhost") -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self.ensure_column(conn, "direct_messages", "content_type", "TEXT NOT NULL DEFAULT 'text/plain'")
            self.ensure_column(conn, "direct_messages", "operation_id", "TEXT")
            self.ensure_column(conn, "group_messages", "content_type", "TEXT NOT NULL DEFAULT 'text/plain'")
            self.ensure_column(conn, "group_messages", "operation_id", "TEXT")
            self.ensure_column(conn, "attachment_slots", "attachment_id", "TEXT")
            self.ensure_column(conn, "attachment_slots", "object_uri", "TEXT")
            self.ensure_column(conn, "attachment_objects", "source_attachment_id", "TEXT")
            self.ensure_column(conn, "attachment_objects", "object_uri", "TEXT")
            self.ensure_column(conn, "users", "revoked_at", "TEXT")
            self.ensure_column(conn, "did_documents", "status", "TEXT NOT NULL DEFAULT 'active'")
            self.ensure_column(conn, "did_documents", "revoked_at", "TEXT")
            self.seed_groups(conn, did_domain)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def next_seq(self, conn: sqlite3.Connection, table: str, owner: str | None = None) -> int:
        if table == "direct_messages":
            row = conn.execute("SELECT COALESCE(MAX(server_seq), 0) + 1 AS seq FROM direct_messages").fetchone()
        elif table == "group_messages":
            row = conn.execute("SELECT COALESCE(MAX(server_seq), 0) + 1 AS seq FROM group_messages").fetchone()
        elif table == "sync_events" and owner is not None:
            row = conn.execute(
                "SELECT COALESCE(MAX(event_seq), 0) + 1 AS seq FROM sync_events WHERE owner_did = ?",
                (owner,),
            ).fetchone()
        else:
            row = {"seq": 1}
        return int(row["seq"])

    def ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(row["name"] == column for row in rows):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def seed_groups(self, conn: sqlite3.Connection, did_domain: str = "localhost") -> None:
        group_did = f"did:wba:{did_domain}:groups:open"
        existing = conn.execute("SELECT group_did FROM groups WHERE group_did = ?", (group_did,)).fetchone()
        if existing:
            return
        conn.execute(
            "INSERT INTO groups(group_did, display_name, description, join_mode, invite_token, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (group_did, "Awiki Open Group", "Seeded open-join group", "open_join", None),
        )
