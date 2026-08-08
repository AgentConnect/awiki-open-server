from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


RUN_RUST_CLI_SYSTEM_TESTS = os.environ.get("AWIKI_RUN_RUST_CLI_SYSTEM_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}
CLI_BIN = os.environ.get("AWIKI_CLI_BIN", "awiki-cli")

pytestmark = pytest.mark.skipif(
    not RUN_RUST_CLI_SYSTEM_TESTS,
    reason="set AWIKI_RUN_RUST_CLI_SYSTEM_TESTS=1 and AWIKI_CLI_BIN to run real Rust CLI gates",
)


def _resolved_cli() -> str:
    if os.sep in CLI_BIN:
        path = Path(CLI_BIN).resolve()
        if path.is_file():
            return str(path)
    else:
        resolved = shutil.which(CLI_BIN)
        if resolved:
            return resolved
    pytest.skip(f"real Rust CLI artifact not found: {CLI_BIN}")


def _run_gate(tmp_path: Path, command: str, *extra: str) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/awiki_open_cli.py",
            command,
            "--awiki-cli-bin",
            _resolved_cli(),
            "--data-root",
            str(tmp_path / command),
            "--clean",
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
        env=os.environ.copy(),
    )
    assert completed.returncode == 0, (
        f"{command} failed\nstdout:\n{completed.stdout[-8000:]}\n"
        f"stderr:\n{completed.stderr[-8000:]}"
    )
    report = json.loads(completed.stdout)
    assert report["ok"] is True
    assert report["cli_artifact_sha256"]
    assert report["cli_version"]["version"]
    assert report["cli_version"]["commit"]
    assert report["open_server"]["commit"]
    assert isinstance(report["open_server"]["dirty"], bool)
    return report


def test_real_cli_attachment_members_mark_read_and_restart(tmp_path):
    report = _run_gate(tmp_path, "smoke-rust-cli-local", "--standard-https")
    evidence = "\n".join(report["verified"])
    assert "attachment" in evidence.lower()
    assert "members cursor" in evidence.lower()
    assert "mark-read" in evidence.lower()
    assert "server restart persistence" in evidence.lower()
    assert report["attachment_fixture"]["verified"] is True
    assert report["attachment_fixture"]["size"] > 0
    assert len(report["attachment_fixture"]["sha256"]) == 64


def test_real_cli_realtime_restart(tmp_path):
    report = _run_gate(tmp_path, "smoke-rust-cli-realtime-restart")
    assert len(report["server_boots"]) == 2
    assert len(report["listener_boots"]) == 3
    for snapshot in report["readiness_snapshots"]:
        reliable = snapshot["listener"]["reliable_sync"]
        assert reliable == {
            "last_reconcile_protocol": "sync_v2",
            "legacy_sync_used": False,
            "v2_bootstrap_completed": True,
            "v2_subprotocol_negotiated": True,
        }


def test_real_cli_cross_domain_plaintext_direct_and_group(tmp_path):
    report = _run_gate(tmp_path, "smoke-rust-cli-cross-domain")
    assert len(report["direct_message_ids"]) == 2
    assert set(report["groups"]) == {"source_hosted", "target_hosted"}
    assert len(report["group_message_ids"]) == 2
