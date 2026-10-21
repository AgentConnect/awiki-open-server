#!/usr/bin/env python3
"""Offline, default-off cleanup for exact plaintext cross-backend test accounts.

Retains account/identity records. Never accepts SQL, paths, handles or DIDs from
the request. A private operator config binds the database and test handle prefix.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

DOMAINS = ("account", "attachment", "direct", "group", "outbox", "sync")
PREFIX = b"awiki.system-test.cleanup.account-scope.v1\0"
ACTION = "cleanup_test_scope"
PREFLIGHT = "cleanup_test_scope_preflight"


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate member")
        value[key] = item
    return value


def parse_request(raw: bytes):
    if not raw or len(raw) > 4096:
        raise ValueError("invalid request size")
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if value == {"action": PREFLIGHT}:
        return None
    if not isinstance(value, dict) or set(value) != {"action", "account_ids"} or value["action"] != ACTION:
        raise ValueError("invalid request")
    accounts = value["account_ids"]
    if (not isinstance(accounts, list) or not 1 <= len(accounts) <= 16
            or any(not isinstance(a, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", a) for a in accounts)
            or len(set(accounts)) != len(accounts)):
        raise ValueError("invalid account scope")
    return tuple(sorted(accounts))


def load_config(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("private operator config required")
        config = json.load(stream, object_pairs_hook=_unique_object)
    if (not isinstance(config, dict) or set(config) != {"enabled", "data_dir", "service_url", "handle_prefix"}
            or config["enabled"] is not True
            or config["service_url"] != "https://openserver-adapt.anpclaw.com"
            or config["handle_prefix"] != "adaptcross"):
        raise ValueError("task-only cleanup is disabled")
    directory = Path(config["data_dir"])
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("invalid data directory")
    return directory


def connect(directory: Path):
    database = directory / "awiki-open-server.sqlite3"
    if database.is_symlink() or not database.is_file():
        raise ValueError("existing database required")
    connection = sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    # Readiness does not initialize, migrate or create a database.
    connection.execute("SELECT account_id, owner_did FROM single_device_accounts LIMIT 0")
    connection.execute("SELECT creator_did FROM hosted_groups LIMIT 0")
    return connection


def cleanup(directory: Path, accounts: tuple[str, ...]):
    with closing(connect(directory)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TEMP TABLE scope_accounts (value TEXT PRIMARY KEY)")
        db.executemany("INSERT INTO scope_accounts VALUES (?)", [(a,) for a in accounts])
        owners = db.execute("""SELECT a.account_id, a.owner_did, u.handle FROM single_device_accounts a
            JOIN users u ON u.did=a.owner_did WHERE a.account_id IN (SELECT value FROM scope_accounts)""").fetchall()
        if len(owners) != len(accounts) or any(not re.fullmatch(r"adaptcross[0-9a-f]{10}@openserver-adapt\.anpclaw\.com", row["handle"]) for row in owners):
            raise ValueError("scope is not an exact cross-backend fixture")
        db.execute("CREATE TEMP TABLE scope_dids (value TEXT PRIMARY KEY)")
        db.executemany("INSERT INTO scope_dids VALUES (?)", [(r["owner_did"],) for r in owners])
        dids = "(SELECT value FROM scope_dids)"
        groups = "(SELECT value FROM scope_groups)"
        db.execute(f"CREATE TEMP TABLE scope_groups AS SELECT group_did AS value FROM hosted_groups WHERE creator_did IN {dids}")
        # This operator is deliberately limited to the plaintext pair fixture.
        # Broader resources require their owning cleanup, never a partial purge.
        for table, column in (("attachment_slots", "owner_did"), ("attachment_objects", "owner_did"),
                              ("message_agent_bindings", "human_did"), ("agent_registration_tokens", "owner_did")):
            if db.execute(f"SELECT 1 FROM {table} WHERE {column} IN {dids} LIMIT 1").fetchone():
                raise ValueError("fixture has resources outside plaintext cleanup")
        if db.execute(f"SELECT 1 FROM hosted_group_members WHERE agent_did IN {dids} AND group_did NOT IN {groups} LIMIT 1").fetchone():
            raise ValueError("fixture belongs to an unrelated local hosted group")
        keys = []
        key_directory = directory / "group-keys"
        if key_directory.is_symlink():
            raise ValueError("invalid group key directory")
        key_root = key_directory.resolve()
        for row in db.execute(f"SELECT key_reference FROM group_did_documents WHERE group_did IN {groups}"):
            key = Path(row[0])
            if key.is_symlink() or key.parent.resolve() != key_root or not key.is_absolute():
                raise ValueError("invalid scoped group key")
            keys.append(key)
        rules = [
            ("direct", "direct_message_views", f"owner_did IN {dids} OR peer_did IN {dids}"),
            ("direct", "direct_messages", f"sender_did IN {dids} OR recipient_did IN {dids}"),
            ("direct", "direct_conversation_refs", f"owner_did IN {dids} OR peer_did IN {dids}"),
            ("outbox", "protocol_operations", f"sender_did IN {dids}"),
            ("outbox", "group_delivery_outbox", f"group_did IN {groups}"),
            ("outbox", "inbound_peer_events", f"target_did IN {dids} OR group_did IN {groups}"),
            ("group", "group_operations", f"sender_did IN {dids} OR group_scope IN {groups}"),
            *[("group", table, f"owner_did IN {dids} OR group_did IN {groups}") for table in
              ("group_message_views", "group_member_views", "group_views")],
            *[("group", table, f"group_did IN {groups}") for table in
              ("hosted_group_events", "hosted_group_messages", "hosted_group_members", "group_protocol_migrations",
               "group_did_documents", "hosted_groups", "group_messages")],
            ("group", "group_members", f"member_did IN {dids} OR group_did IN {groups}"),
            ("group", "groups", f"group_did IN {groups}"),
            *[("sync", table, f"owner_did IN {dids}") for table in
              ("sync_events", "thread_read_states", "sync_snapshot_sessions", "sync_v2_bindings")],
            ("sync", "sync_capability_negotiations", "account_id IN (SELECT value FROM scope_accounts)"),
        ]
        counts = dict.fromkeys(DOMAINS, 0)
        for domain, table, predicate in rules:
            counts[domain] += db.execute(f"DELETE FROM {table} WHERE {predicate}").rowcount
        if any(db.execute(f"SELECT 1 FROM {table} WHERE {predicate} LIMIT 1").fetchone() for _, table, predicate in rules):
            raise ValueError("cleanup residual")
        # Only validated fixture keys are removed. Missing keys permit replay if
        # an earlier attempt failed before the database transaction committed.
        for key in keys:
            key.unlink(missing_ok=True)
    fingerprint = hashlib.sha256(PREFIX + json.dumps(sorted(accounts), separators=(",", ":")).encode("ascii")).hexdigest()
    return {"schemaVersion": 1, "service": "open-server", "action": "system_test_scope_cleanup",
            "scopeFingerprint": fingerprint, "authorizedAccountCount": len(accounts),
            "deletedCounts": counts, "residualCount": 0, "cleaned": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    try:
        directory = load_config(args.config)
        accounts = parse_request(sys.stdin.buffer.read(4097))
        if accounts is None:
            with closing(connect(directory)):
                pass
            receipt = {"schemaVersion": 1, "service": "open-server",
                       "action": "system_test_scope_cleanup_preflight", "ready": True, "code": "ready"}
        else:
            receipt = cleanup(directory, accounts)
        print(json.dumps(receipt))
        return 0
    except (ValueError, OSError, sqlite3.Error):
        print(json.dumps({"code": "cleanup_rejected"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
