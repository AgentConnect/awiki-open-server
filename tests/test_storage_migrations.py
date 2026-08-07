from __future__ import annotations

from awiki_open_server.storage.db import Store


def test_protocol_alignment_migrations_are_additive_and_reentrant(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    first = Store(db_path, "migration.test")
    with first.connect() as conn:
        conn.execute(
            "INSERT INTO groups(group_did, display_name, description, join_mode, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            ("did:wba:migration.test:groups:legacy", "Legacy", None, "closed_legacy"),
        )

    second = Store(db_path, "migration.test")
    with second.connect() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        migrations = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [(row["version"], row["name"]) for row in migrations] == [
            (1, "protocol-api-alignment-foundation"),
            (2, "direct-canonical-proof-and-idempotency"),
            (3, "attachment-canonical-digest-contract"),
            (4, "single-device-sync-v2-wire-compatibility"),
        ]
        direct_columns = {row["name"] for row in conn.execute("PRAGMA table_info(direct_messages)")}
        assert {
            "meta_json",
            "origin_auth_json",
            "origin_proof_verified",
            "authoritative_sender_did",
            "security_profile",
        } <= direct_columns
        assert conn.execute(
            "SELECT 1 FROM groups WHERE group_did = ?",
            ("did:wba:migration.test:groups:legacy",),
        ).fetchone() is not None
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
        ).fetchone()[0] == 1
