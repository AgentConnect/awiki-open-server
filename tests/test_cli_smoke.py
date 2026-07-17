from __future__ import annotations

import argparse
import json
import subprocess
import sys

from scripts import awiki_open_cli
from scripts.awiki_open_cli import anp_params, smoke_awiki_info, verify_public


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "scripts/awiki_open_cli.py", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "smoke-local" in result.stdout
    assert "smoke-cross-domain-local" in result.stdout
    assert "smoke-awiki-info" in result.stdout
    assert "verify-public" in result.stdout


def test_remote_cli_uses_anp_envelope():
    args = argparse.Namespace(
        did_domain="rwiki.cn",
        sender_did="did:wba:rwiki.cn:users:alice",
        recipient_did="did:wba:awiki.info:users:bob",
        auth_scheme="anp-rfc9421-origin-proof-v1",
        origin_proof_json='{"contentDigest":"sha-256=:x:","signatureInput":"sig1=();created=1","signature":"sig1=:x:"}',
    )
    params = anp_params("direct.send", args, {"text": "hello"})
    assert set(["meta", "auth", "body"]).issubset(params)
    assert params["meta"]["sender_did"].startswith("did:wba:rwiki.cn")
    assert params["meta"]["target"]["did"].startswith("did:wba:awiki.info")
    assert params["body"]["text"] == "hello"

    caps = anp_params("anp.get_capabilities", args)
    assert set(["meta", "body"]).issubset(caps)
    assert "auth" not in caps


def test_verify_public_accepts_open_server_surface(monkeypatch, capsys):
    def fake_http_get_json(base_url: str, path: str):
        assert base_url == "https://rwiki.cn"
        assert path == "/.well-known/did.json"
        return 200, {
            "id": "did:wba:rwiki.cn",
            "verificationMethod": [{"id": "did:wba:rwiki.cn#key-1"}],
            "authentication": ["did:wba:rwiki.cn#key-1"],
            "service": [
                {
                    "type": "ANPMessageService",
                    "serviceEndpoint": "https://rwiki.cn/anp-im/rpc",
                    "serviceDid": "did:wba:rwiki.cn",
                    "authSchemes": ["bearer", "didwba"],
                }
            ],
        }

    class FakeHealth:
        status = 200

        def read(self):
            return b'{"status":"ok"}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(url: str, timeout: int):
        assert url == "https://rwiki.cn/healthz"
        return FakeHealth()

    def fake_anp_rpc(base_url: str, method: str, params: dict, token=None):
        assert base_url == "https://rwiki.cn"
        assert method == "anp.get_capabilities"
        return {
            "service_did": "did:wba:rwiki.cn",
            "features": {
                "cross_domain_direct": {"enabled": True},
                "cross_domain_group": {"enabled": True, "mode": "did_discovery_direct_call"},
                "group_participant": {
                    "enabled": True,
                    "management": True,
                    "join_modes": ["open-join", "admin-add"],
                },
            },
            "disabled_features": {"federation_relay": "commercial"},
        }

    monkeypatch.setattr(awiki_open_cli, "http_get_json", fake_http_get_json)
    monkeypatch.setattr(awiki_open_cli.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(awiki_open_cli, "anp_rpc", fake_anp_rpc)

    args = argparse.Namespace(base_url="https://rwiki.cn", did_domain="rwiki.cn", service_did=None)
    assert verify_public(args) == 0
    output = capsys.readouterr().out
    assert '"ok": true' in output


def test_verify_public_rejects_domain_not_serving_open_server(monkeypatch, capsys):
    def fake_http_get_json(base_url: str, path: str):
        return 404, {"detail": "Server DID document not found"}

    def fake_urlopen(url: str, timeout: int):
        raise RuntimeError("HTTP Error 404")

    def fake_anp_rpc(base_url: str, method: str, params: dict, token=None):
        raise RuntimeError("anp rpc 404")

    monkeypatch.setattr(awiki_open_cli, "http_get_json", fake_http_get_json)
    monkeypatch.setattr(awiki_open_cli.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(awiki_open_cli, "anp_rpc", fake_anp_rpc)

    args = argparse.Namespace(base_url="https://rwiki.cn", did_domain="rwiki.cn", service_did=None)
    assert verify_public(args) == 1
    output = capsys.readouterr().out
    assert '"ok": false' in output
    assert "service_did_document_http" in output


def test_smoke_awiki_info_reports_missing_direct_credentials(monkeypatch, capsys):
    def fake_anp_rpc(base_url: str, method: str, params: dict, token=None):
        assert base_url == "https://awiki.info"
        assert method == "anp.get_capabilities"
        assert "meta" in params
        return {"service_did": "did:wba:awiki.info"}

    monkeypatch.setattr(awiki_open_cli, "anp_rpc", fake_anp_rpc)
    args = argparse.Namespace(
        base_url="https://awiki.info",
        did_domain="rwiki.cn",
        token=None,
        sender_did=None,
        recipient_did=None,
        auth_scheme="anp-rfc9421-origin-proof-v1",
        origin_proof_json=None,
        text="hello",
    )

    assert smoke_awiki_info(args) == 0
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["ok"] is True
    assert data["direct_ready"] is False
    assert data["live_direct_gate"] == "skipped_missing_credentials"
    assert data["credential_status"]["token"] == "unset"
    assert {item["env"] for item in data["missing_credentials"]} == {
        "AWIKI_INFO_TOKEN",
        "AWIKI_INFO_SENDER_DID",
        "AWIKI_INFO_RECIPIENT_DID",
        "AWIKI_INFO_ORIGIN_PROOF_JSON",
    }
    assert "secret-token" not in output


def test_smoke_awiki_info_sends_direct_when_credentials_are_complete(monkeypatch, capsys):
    calls: list[tuple[str, str | None]] = []

    def fake_anp_rpc(base_url: str, method: str, params: dict, token=None):
        assert base_url == "https://awiki.info"
        calls.append((method, token))
        if method == "anp.get_capabilities":
            return {"service_did": "did:wba:awiki.info"}
        assert method == "direct.send"
        assert params["auth"]["origin_proof"]["contentDigest"] == "sha-256=:x:"
        return {"message_id": "msg-live"}

    monkeypatch.setattr(awiki_open_cli, "anp_rpc", fake_anp_rpc)
    args = argparse.Namespace(
        base_url="https://awiki.info",
        did_domain="rwiki.cn",
        token="secret-token",
        sender_did="did:wba:rwiki.cn:users:alice:e1_default",
        recipient_did="did:wba:awiki.info:users:bob:e1_default",
        auth_scheme="anp-rfc9421-origin-proof-v1",
        origin_proof_json='{"contentDigest":"sha-256=:x:","signatureInput":"sig1=();created=1","signature":"sig1=:x:"}',
        text="hello",
    )

    assert smoke_awiki_info(args) == 0
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["direct_ready"] is True
    assert data["live_direct_gate"] == "passed"
    assert data["direct_message_id"] == "msg-live"
    assert calls == [("anp.get_capabilities", "secret-token"), ("direct.send", "secret-token")]
    assert "secret-token" not in output


def test_smoke_cross_domain_local_subprocess(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/awiki_open_cli.py",
            "smoke-cross-domain-local",
            "--data-root",
            str(tmp_path / "cross-domain"),
            "--clean",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["mode"] == "cross-domain-local"
    assert data["source"]["service_did"] == "did:wba:source.test"
    assert data["target"]["service_did"] == "did:wba:target.test"
    assert "signed /anp-im/rpc inbound direct" in data["verified"]
    assert "bidirectional inbox delivery" in data["verified"]
