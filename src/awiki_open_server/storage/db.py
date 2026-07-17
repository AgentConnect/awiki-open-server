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
  refresh_token TEXT UNIQUE,
  access_expires_at TEXT,
  refresh_expires_at TEXT,
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

CREATE TABLE IF NOT EXISTS hosted_groups (
  group_did TEXT PRIMARY KEY,
  host_service_did TEXT NOT NULL,
  creator_did TEXT NOT NULL,
  profile_json TEXT NOT NULL,
  policy_json TEXT NOT NULL,
  group_state_version INTEGER NOT NULL,
  group_event_seq INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hosted_group_members (
  group_did TEXT NOT NULL REFERENCES hosted_groups(group_did) ON DELETE CASCADE,
  agent_did TEXT NOT NULL,
  member_handle TEXT,
  handle_binding_generation TEXT,
  home_service_did TEXT,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  joined_at TEXT NOT NULL,
  ended_at TEXT,
  added_by TEXT,
  PRIMARY KEY(group_did, agent_did),
  UNIQUE(group_did, member_handle)
);

CREATE TABLE IF NOT EXISTS hosted_group_events (
  group_did TEXT NOT NULL REFERENCES hosted_groups(group_did) ON DELETE CASCADE,
  group_event_seq INTEGER NOT NULL,
  event_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  group_state_version INTEGER NOT NULL,
  subject_method TEXT NOT NULL,
  actor_did TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  receipt_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(group_did, group_event_seq)
);

CREATE TABLE IF NOT EXISTS hosted_group_messages (
  message_id TEXT PRIMARY KEY,
  group_did TEXT NOT NULL REFERENCES hosted_groups(group_did) ON DELETE CASCADE,
  group_event_seq INTEGER NOT NULL,
  sender_did TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  body_json TEXT NOT NULL,
  content_type TEXT NOT NULL,
  origin_auth_json TEXT NOT NULL,
  receipt_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(group_did, group_event_seq)
);

CREATE TABLE IF NOT EXISTS group_operations (
  sender_did TEXT NOT NULL,
  group_scope TEXT NOT NULL,
  method TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(sender_did, group_scope, method, operation_id)
);

CREATE TABLE IF NOT EXISTS group_did_documents (
  group_did TEXT PRIMARY KEY REFERENCES hosted_groups(group_did) ON DELETE CASCADE,
  document_json TEXT NOT NULL,
  key_reference TEXT NOT NULL,
  document_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_views (
  owner_did TEXT NOT NULL,
  group_did TEXT NOT NULL,
  host_service_did TEXT NOT NULL,
  profile_json TEXT NOT NULL,
  policy_json TEXT NOT NULL,
  group_state_version INTEGER NOT NULL,
  group_event_seq INTEGER NOT NULL,
  member_role TEXT NOT NULL,
  membership_status TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(owner_did, group_did)
);

CREATE TABLE IF NOT EXISTS group_member_views (
  owner_did TEXT NOT NULL,
  group_did TEXT NOT NULL,
  agent_did TEXT NOT NULL,
  member_handle TEXT,
  handle_binding_generation TEXT,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  joined_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(owner_did, group_did, agent_did)
);

CREATE TABLE IF NOT EXISTS group_message_views (
  owner_did TEXT NOT NULL,
  group_did TEXT NOT NULL,
  message_id TEXT NOT NULL,
  group_event_seq INTEGER NOT NULL,
  group_state_version INTEGER NOT NULL,
  sender_did TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  content_type TEXT NOT NULL,
  body_json TEXT NOT NULL,
  receipt_json TEXT NOT NULL,
  accepted_at TEXT NOT NULL,
  PRIMARY KEY(owner_did, group_did, message_id),
  UNIQUE(owner_did, group_did, group_event_seq)
);

CREATE TABLE IF NOT EXISTS inbound_peer_events (
  source_service_did TEXT NOT NULL,
  group_did TEXT NOT NULL,
  group_event_seq INTEGER NOT NULL,
  target_did TEXT NOT NULL,
  method TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  received_at TEXT NOT NULL,
  PRIMARY KEY(source_service_did, group_did, group_event_seq, target_did, method)
);

CREATE TABLE IF NOT EXISTS group_delivery_outbox (
  delivery_id TEXT PRIMARY KEY,
  group_did TEXT NOT NULL REFERENCES hosted_groups(group_did) ON DELETE CASCADE,
  group_event_seq INTEGER NOT NULL,
  target_did TEXT NOT NULL,
  target_service_did TEXT NOT NULL,
  method TEXT NOT NULL,
  envelope_json TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(group_did, group_event_seq, target_did, method)
);

CREATE INDEX IF NOT EXISTS group_delivery_outbox_due
  ON group_delivery_outbox(status, next_attempt_at);

CREATE INDEX IF NOT EXISTS hosted_group_members_active_did
  ON hosted_group_members(agent_did, status);
CREATE INDEX IF NOT EXISTS hosted_group_messages_group_seq
  ON hosted_group_messages(group_did, group_event_seq);

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
  expected_size INTEGER,
  expected_sha256 TEXT,
  expected_content_type TEXT,
  expires_at TEXT,
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
            self.ensure_column(conn, "users", "refresh_token", "TEXT")
            self.ensure_column(conn, "users", "access_expires_at", "TEXT")
            self.ensure_column(conn, "users", "refresh_expires_at", "TEXT")
            self.ensure_column(conn, "attachment_slots", "attachment_id", "TEXT")
            self.ensure_column(conn, "attachment_slots", "object_uri", "TEXT")
            self.ensure_column(conn, "attachment_slots", "expected_size", "INTEGER")
            self.ensure_column(conn, "attachment_slots", "expected_sha256", "TEXT")
            self.ensure_column(conn, "attachment_slots", "expected_content_type", "TEXT")
            self.ensure_column(conn, "attachment_slots", "expires_at", "TEXT")
            self.ensure_column(conn, "attachment_objects", "source_attachment_id", "TEXT")
            self.ensure_column(conn, "attachment_objects", "object_uri", "TEXT")
            self.ensure_column(conn, "users", "revoked_at", "TEXT")
            self.ensure_column(conn, "did_documents", "status", "TEXT NOT NULL DEFAULT 'active'")
            self.ensure_column(conn, "did_documents", "revoked_at", "TEXT")
            self.ensure_column(conn, "users", "handle_binding_generation", "TEXT NOT NULL DEFAULT '1'")
            legacy_group_columns = {row["name"] for row in conn.execute("PRAGMA table_info(groups)").fetchall()}
            if "invite_token" in legacy_group_columns:
                conn.execute("UPDATE groups SET invite_token = NULL WHERE invite_token IS NOT NULL")
                conn.execute("UPDATE groups SET join_mode = 'closed_legacy' WHERE join_mode = 'invite_token'")
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
            "INSERT INTO groups(group_did, display_name, description, join_mode, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (group_did, "Awiki Open Group", "Seeded open-join group", "open_join"),
        )
