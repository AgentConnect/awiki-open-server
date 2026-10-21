"""Exact fixture ownership, rejection-before-delete, and replay contracts."""
import importlib.util
import json
from pathlib import Path

import pytest

from awiki_open_server.storage.db import Store

spec = importlib.util.spec_from_file_location("scope_cleanup", Path(__file__).parents[1] / "scripts/cleanup_system_test_scope.py")
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)


def insert(db, table, **values):
    db.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))


@pytest.fixture
def state(tmp_path):
    store = Store(tmp_path / "awiki-open-server.sqlite3")
    (tmp_path / "group-keys").mkdir()
    with store.connect() as db:
        for did, account, handle in (("fixture", "account1", "adaptcross0123456789@openserver-adapt.anpclaw.com"),
                                     ("unrelated", "account2", "manual@openserver-adapt.anpclaw.com")):
            insert(db, "users", did=did, handle=handle, token="token-"+did, created_at="now")
            insert(db, "single_device_accounts", owner_did=did, account_id=account, device_id="device",
                   signing_key_id="sign", root_key_id="root", key_fingerprint="fp", auth_generation=1)
            insert(db, "direct_messages", message_id=did, sender_did=did, recipient_did="peer", body_json="{}", created_at="now", server_seq=1)
            insert(db, "direct_message_views", owner_did=did, message_id=did, peer_did="peer")
            insert(db, "sync_events", event_id=did, owner_did=did, event_seq=1, event_type="message", payload_json="{}", created_at="now")
            insert(db, "hosted_groups", group_did="group-"+did, host_service_did="host", creator_did=did,
                   profile_json="{}", policy_json="{}", group_state_version=1, group_event_seq=0, created_at="now", updated_at="now")
            key = tmp_path / "group-keys" / (did+".pem")
            key.write_text("test-key")
            insert(db, "group_did_documents", group_did="group-"+did, document_json="{}", key_reference=str(key), created_at="now")
    return store, tmp_path


def test_exact_plaintext_cleanup_retains_identity_and_unrelated_data_and_replays(state):
    store, directory = state
    receipt = operator.cleanup(directory, ("account1",))
    assert receipt["service"] == "open-server"
    assert receipt["authorizedAccountCount"] == 1 and receipt["residualCount"] == 0
    assert receipt["deletedCounts"]["direct"] == 2
    with store.connect() as db:
        assert [r[0] for r in db.execute("SELECT message_id FROM direct_messages")] == ["unrelated"]
        assert [r[0] for r in db.execute("SELECT group_did FROM hosted_groups")] == ["group-unrelated"]
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM single_device_accounts").fetchone()[0] == 2
    assert not (directory / "group-keys/fixture.pem").exists()
    assert (directory / "group-keys/unrelated.pem").read_text() == "test-key"
    replay = operator.cleanup(directory, ("account1",))
    assert replay["scopeFingerprint"] == receipt["scopeFingerprint"]
    assert sum(replay["deletedCounts"].values()) == 0


@pytest.mark.parametrize("accounts", [("account1", "account2"), ("account1", "missing")])
def test_all_accounts_validated_before_any_delete(state, accounts):
    store, directory = state
    with pytest.raises(ValueError):
        operator.cleanup(directory, accounts)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM direct_messages").fetchone()[0] == 2
    assert (directory / "group-keys/fixture.pem").exists()


def test_attachment_scope_is_rejected_without_partial_plaintext_cleanup(state):
    store, directory = state
    with store.connect() as db:
        insert(db, "attachment_objects", object_id="attachment", owner_did="fixture", path="outside", size=1, sha256="digest", content_type="text/plain", created_at="now")
    with pytest.raises(ValueError, match="outside plaintext"):
        operator.cleanup(directory, ("account1",))
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM direct_messages").fetchone()[0] == 2


def test_group_key_path_escape_is_rejected_before_delete(state):
    store, directory = state
    outside = directory / "outside.pem"
    outside.write_text("keep")
    with store.connect() as db:
        db.execute("UPDATE group_did_documents SET key_reference=? WHERE group_did='group-fixture'", (str(outside),))
    with pytest.raises(ValueError, match="scoped group key"):
        operator.cleanup(directory, ("account1",))
    assert outside.read_text() == "keep"
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM direct_messages").fetchone()[0] == 2


@pytest.mark.parametrize("raw_request", [b'{}', b'{"action":"cleanup_test_scope","account_ids":[]}',
    b'{"action":"cleanup_test_scope","account_ids":["a","a"]}',
    b'{"action":"cleanup_test_scope","account_ids":["a"],"sql":"delete"}',
    b'{"action":"cleanup_test_scope_preflight","action":"cleanup_test_scope_preflight"}'])
def test_closed_request_rejects_unbounded_or_ambiguous_input(raw_request):
    with pytest.raises(ValueError):
        operator.parse_request(raw_request)


def test_private_config_requires_explicit_task_gate(state):
    _, directory = state
    path = directory / "operator.json"
    value = {"enabled": True, "data_dir": str(directory), "service_url": "https://openserver-adapt.anpclaw.com", "handle_prefix": "adaptcross"}
    path.write_text(json.dumps(value)); path.chmod(0o600)
    assert operator.load_config(path) == directory
    path.chmod(0o644)
    with pytest.raises(ValueError):
        operator.load_config(path)
    path.chmod(0o600)
    value["enabled"] = False; path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        operator.load_config(path)
