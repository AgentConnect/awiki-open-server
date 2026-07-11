#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

import jcs
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from awiki_open_server.service_identity import content_digest, generate_ed25519_private_key_pem


def http_get_json(base_url: str, path: str) -> tuple[int, dict]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode()
            return response.status, json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed


def rpc(base_url: str, path: str, method: str, params: dict | None = None, token: str | None = None) -> dict:
    return rpc_payload(base_url, path, {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": "cli"}, token)


def rpc_payload(base_url: str, path: str, payload_obj: dict, token: str | None = None) -> dict:
    payload = json.dumps(payload_obj).encode()
    request = urllib.request.Request(
        urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode())
    if "error" in data:
        raise RuntimeError(f"{payload_obj.get('method')} failed: {data['error']}")
    return data["result"]


def anp_params(method: str, args: argparse.Namespace, body: dict | None = None) -> dict:
    sender_did = args.sender_did or f"did:wba:{args.did_domain}:users:smoke:e1_default"
    content_type = "text/plain" if method == "direct.send" else "application/json"
    meta: dict = {
        "anp_version": "1.0",
        "profile": "anp.direct.base.v1" if method == "direct.send" else "anp.core.binding.v1",
        "security_profile": "transport-protected",
        "sender_did": sender_did,
        "operation_id": f"op-{uuid.uuid4()}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content_type": content_type,
    }
    if method == "direct.send":
        meta["message_id"] = f"msg-{uuid.uuid4()}"
        meta["target"] = {"kind": "agent", "did": args.recipient_did}
    params = {
        "meta": meta,
        "body": body or {},
        "client": {"response_mode": "wait-final"},
    }
    if method == "direct.send":
        origin_proof = json.loads(args.origin_proof_json) if args.origin_proof_json else None
        if origin_proof is None:
            raise RuntimeError("direct.send remote smoke requires --origin-proof-json")
        params["auth"] = {
            "scheme": args.auth_scheme,
            "origin_proof": origin_proof,
        }
    return params


def anp_rpc(base_url: str, method: str, params: dict, token: str | None = None) -> dict:
    return rpc_payload(base_url, "/anp-im/rpc", {"jsonrpc": "2.0", "method": method, "params": params, "id": "cli-anp"}, token)


def put_bytes(base_url: str, path: str, data: bytes, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")) + "?" + query
    request = urllib.request.Request(url, data=data, method="PUT")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def get_bytes(base_url: str, path: str, params: dict) -> bytes:
    query = urllib.parse.urlencode(params)
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")) + "?" + query
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read()


def unique_handle(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def page_messages(page: dict) -> list[dict]:
    messages = page.get("messages", [])
    if not isinstance(messages, list):
        raise RuntimeError("message page response missing messages list")
    return messages


def default_group_did(did_domain: str) -> str:
    return f"did:wba:{did_domain}:groups:open"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def multikey(public_key: ed25519.Ed25519PublicKey) -> str:
    import base58

    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return "z" + base58.b58encode(b"\xed\x01" + raw).decode("ascii")


def user_did_document(did: str, service_endpoint: str, service_did: str, key: ed25519.Ed25519PrivateKey) -> dict:
    key_id = f"{did}#key-1"
    document = {
        "id": did,
        "verificationMethod": [
            {
                "id": key_id,
                "type": "Multikey",
                "controller": did,
                "publicKeyMultibase": multikey(key.public_key()),
            }
        ],
        "authentication": [key_id],
        "assertionMethod": [key_id],
        "service": [
            {
                "id": f"{did}#anp-message",
                "type": "ANPMessageService",
                "serviceEndpoint": service_endpoint,
                "serviceDid": service_did,
                "profiles": ["anp.direct.base.v1"],
                "securityProfiles": ["transport-protected"],
            }
        ],
    }
    return sign_did_document(document, key, key_id)


def sign_did_document(document: dict, key: ed25519.Ed25519PrivateKey, key_id: str) -> dict:
    proof = {
        "type": "DataIntegrityProof",
        "created": "2026-07-10T00:00:00Z",
        "verificationMethod": key_id,
        "proofPurpose": "assertionMethod",
        "cryptosuite": "eddsa-jcs-2022",
    }
    unsigned = {k: v for k, v in document.items() if k != "proof"}
    signing_input = hashlib.sha256(jcs.canonicalize(proof)).digest() + hashlib.sha256(jcs.canonicalize(unsigned)).digest()
    signed = dict(document)
    signed["proof"] = {**proof, "proofValue": b64u(key.sign(signing_input))}
    return signed


def origin_proof(method: str, meta: dict, body: dict, key: ed25519.Ed25519PrivateKey) -> dict:
    target = meta["target"]
    digest = content_digest(jcs.canonicalize({"method": method, "meta": meta, "body": body}))
    created = int(time.time())
    signature_input = (
        'sig1=("@method" "@target-uri" "content-digest");'
        f'created={created};expires={created + 300};keyid="{meta["sender_did"]}#key-1"'
    )
    proof_base = "\n".join(
        [
            f'"@method": {method}',
            f'"@target-uri": anp://{target["kind"]}/{urllib.parse.quote(target["did"], safe="-._~")}',
            f'"content-digest": {digest}',
            f'"@signature-params": {signature_input.split("=", 1)[1].strip()}',
        ]
    ).encode()
    return {
        "contentDigest": digest,
        "signatureInput": signature_input,
        "signature": f"sig1=:{b64(key.sign(proof_base))}:",
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_health(base_url: str, process: subprocess.Popen, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited before healthz: {process.returncode}")
        try:
            status, body = http_get_json(base_url, "/healthz")
            if status == 200 and body.get("status") == "ok":
                return
            last_error = f"status={status} body={body}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise RuntimeError(f"server did not become healthy at {base_url}: {last_error}")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def resolve_executable(path_or_name: str) -> str:
    if os.sep in path_or_name or (os.altsep and os.altsep in path_or_name):
        path = Path(path_or_name)
        if not path.exists():
            raise RuntimeError(f"executable not found: {path_or_name}")
        return str(path)
    resolved = shutil.which(path_or_name)
    if not resolved:
        raise RuntimeError(f"executable not found on PATH: {path_or_name}")
    return resolved


def start_open_server(
    *,
    data_dir: Path,
    port: int,
    domain: str,
    private_key_pem: str,
    resolver_map: dict[str, str],
) -> subprocess.Popen:
    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[1]
    python_path_entries = [str(repo_root / "src")]
    if env.get("PYTHONPATH"):
        python_path_entries.append(env["PYTHONPATH"])
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(python_path_entries),
            "AWIKI_DATA_DIR": str(data_dir),
            "AWIKI_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
            "AWIKI_DID_DOMAIN": domain,
            "AWIKI_SERVICE_DID": f"did:wba:{domain}",
            "AWIKI_SERVICE_PRIVATE_KEY_PEM": private_key_pem.replace("\n", "\\n"),
            "AWIKI_ALLOW_UNSIGNED_PEER_DEV": "0",
            "AWIKI_DID_RESOLVER_BASE_URLS": json.dumps(resolver_map),
        }
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "awiki_open_server.app.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def write_rust_cli_config(workspace: Path, *, base_url: str, did_domain: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "config.yaml").write_text(
        f"""schema_version: 1
identity:
  active: ""
runtime:
  mode: websocket
  socket_path: ""
  listener:
    enabled: false
    auto_install: false
    auto_start: false
  host_notify:
    enabled: false
    sink: log
    file_path: ""
    openclaw:
      hook_url: ""
      agent_id: main
      hook_name: AWiki
      token: ""
    hermes:
      notify_url: http://127.0.0.1:8765/notify/host-event
      secret: ""
output:
  format: json
  no_color: true
services:
  service_base_url: {base_url}
  user_service_endpoint: {base_url}
  message_service_endpoint: {base_url}
  did_domain: {did_domain}
  anp_service_endpoint: {base_url.rstrip('/')}/anp-im/rpc
  anp_service_did: did:wba:{did_domain}
  ca_bundle: ""
  mail_service_url: {base_url}
""",
        encoding="utf-8",
    )


def rust_cli_json(cli_bin: str, workspace: Path, home: Path, *args: str) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "AWIKI_CLI_WORKSPACE_HOME_DIR": str(workspace),
        }
    )
    completed = subprocess.run(
        [cli_bin, *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "rust cli command failed: "
            + json.dumps(
                {
                    "args": list(args),
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-2000:],
                    "stderr": completed.stderr[-2000:],
                },
                ensure_ascii=False,
            )
        )
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "rust cli command returned non-json output: "
            + json.dumps({"args": list(args), "stdout": completed.stdout[-2000:]}, ensure_ascii=False)
        ) from exc
    if parsed.get("ok") is not True:
        raise RuntimeError(
            "rust cli command returned ok=false: "
            + json.dumps({"args": list(args), "response": parsed}, ensure_ascii=False)
        )
    return parsed


def rust_register_did(result: dict[str, Any]) -> str:
    did = (((result.get("data") or {}).get("identity") or {}).get("did"))
    if not isinstance(did, str) or not did:
        raise RuntimeError("rust cli id register response missing data.identity.did")
    return did


def rust_message_id(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    delivery = data.get("delivery") if isinstance(data.get("delivery"), dict) else {}
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    message_id = delivery.get("message_id") or message.get("id")
    if not isinstance(message_id, str) or not message_id:
        raise RuntimeError("rust cli msg send response missing message id")
    return message_id


def rust_messages(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise RuntimeError("rust cli message list response missing data.messages")
    return [message for message in messages if isinstance(message, dict)]


def assert_message_visible(result: dict[str, Any], *, message_id: str, text: str) -> None:
    for message in rust_messages(result):
        if message.get("message_id") == message_id and message.get("content") == text:
            return
    raise RuntimeError(f"message {message_id} with expected text not visible")


def china_dev_phone() -> str:
    return f"138{uuid.uuid4().int % 100000000:08d}"


def smoke_rust_cli_local(args: argparse.Namespace) -> int:
    cli_bin = resolve_executable(args.awiki_cli_bin)
    port = args.port or free_port()
    base_url = f"http://127.0.0.1:{port}"
    did_domain = args.did_domain
    root = Path(args.data_root) if args.data_root else Path(tempfile.mkdtemp(prefix="awiki-open-rust-cli-"))
    if args.clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    home = root / "home"
    alice_workspace = root / "cli-alice"
    bob_workspace = root / "cli-bob"
    server_data = root / "server"
    write_rust_cli_config(alice_workspace, base_url=base_url, did_domain=did_domain)
    write_rust_cli_config(bob_workspace, base_url=base_url, did_domain=did_domain)

    process = start_open_server(
        data_dir=server_data,
        port=port,
        domain=did_domain,
        private_key_pem=generate_ed25519_private_key_pem(),
        resolver_map={did_domain: base_url},
    )
    try:
        wait_health(base_url, process)
        prefix = args.handle_prefix
        alice_handle = unique_handle(f"{prefix}-alice")
        bob_handle = unique_handle(f"{prefix}-bob")
        alice_register = rust_cli_json(
            cli_bin,
            alice_workspace,
            home,
            "id",
            "register",
            "--handle",
            alice_handle,
            "--phone",
            china_dev_phone(),
            "--otp",
            "123456",
        )
        bob_register = rust_cli_json(
            cli_bin,
            bob_workspace,
            home,
            "id",
            "register",
            "--handle",
            bob_handle,
            "--phone",
            china_dev_phone(),
            "--otp",
            "123456",
        )
        alice_did = rust_register_did(alice_register)
        bob_did = rust_register_did(bob_register)

        direct_text = "hello from rust cli local smoke"
        direct_send = rust_cli_json(cli_bin, alice_workspace, home, "msg", "send", "--to", bob_did, "--text", direct_text)
        direct_message_id = rust_message_id(direct_send)
        bob_inbox = rust_cli_json(cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct", "--limit", "10")
        bob_history = rust_cli_json(cli_bin, bob_workspace, home, "msg", "history", "--with", alice_did, "--limit", "10")
        assert_message_visible(bob_inbox, message_id=direct_message_id, text=direct_text)
        assert_message_visible(bob_history, message_id=direct_message_id, text=direct_text)

        group_did = default_group_did(did_domain)
        group_text = "hello group from rust cli local smoke"
        rust_cli_json(cli_bin, alice_workspace, home, "group", "join", "--group", group_did)
        group_send = rust_cli_json(cli_bin, alice_workspace, home, "msg", "send", "--group", group_did, "--text", group_text)
        group_message_id = rust_message_id(group_send)
        group_messages = rust_cli_json(cli_bin, alice_workspace, home, "group", "messages", "--group", group_did, "--limit", "10")
        assert_message_visible(group_messages, message_id=group_message_id, text=group_text)

        rust_cli_json(cli_bin, alice_workspace, home, "people", "follow", bob_did)
        people_status = rust_cli_json(cli_bin, alice_workspace, home, "people", "status", bob_did)
        if ((people_status.get("data") or {}).get("is_following")) is not True:
            raise RuntimeError("people status did not report is_following=true")
        following = rust_cli_json(cli_bin, alice_workspace, home, "people", "following", "--limit", "10")
        followers = rust_cli_json(cli_bin, bob_workspace, home, "people", "followers", "--limit", "10")
        following_items = ((following.get("data") or {}).get("items") or (following.get("data") or {}).get("following") or [])
        followers_items = ((followers.get("data") or {}).get("items") or (followers.get("data") or {}).get("followers") or [])
        if not isinstance(following_items, list) or len(following_items) < 1:
            raise RuntimeError("people following response did not include followed user")
        if not isinstance(followers_items, list) or len(followers_items) < 1:
            raise RuntimeError("people followers response did not include follower")

        rust_cli_json(cli_bin, alice_workspace, home, "site", "root", "get", "--domain", did_domain)
        rust_cli_json(cli_bin, alice_workspace, home, "site", "root", "set", "--domain", did_domain, "--markdown", "# Rust CLI Local Smoke")
        rust_cli_json(cli_bin, alice_workspace, home, "site", "page", "create", "--domain", did_domain, "--slug", "smoke", "--markdown", "# Smoke Page")
        site_page = rust_cli_json(cli_bin, alice_workspace, home, "site", "page", "get", "--domain", did_domain, "--slug", "smoke")
        page_body = ((((site_page.get("data") or {}).get("page") or {}).get("body")))
        if page_body != "# Smoke Page":
            raise RuntimeError("site page get did not return expected body")

        result = {
            "ok": True,
            "mode": "rust-cli-local",
            "base_url": base_url,
            "did_domain": did_domain,
            "cli_bin": cli_bin,
            "data_root": str(root),
            "alice": {"handle": alice_handle, "did": alice_did},
            "bob": {"handle": bob_handle, "did": bob_did},
            "verified": [
                "rust cli id register via /user-service/did-auth/rpc with placeholder phone/otp CLI args; server does not run contact verification",
                "direct msg send, inbox, and history through /im/rpc",
                "group join, group msg send, and group messages",
                "people follow/status/following/followers through /user-service/did/relationships/rpc",
                "site root/page commands through /site/rpc",
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop_process(process)


def send_signed_cross_domain(
    *,
    source_base: str,
    sender: dict,
    recipient_did: str,
    text: str,
) -> dict:
    operation_id = f"op-{uuid.uuid4().hex}"
    message_id = f"msg-{uuid.uuid4().hex}"
    meta = {
        "anp_version": "1.0",
        "profile": "anp.direct.base.v1",
        "security_profile": "transport-protected",
        "sender_did": sender["did"],
        "target": {"kind": "agent", "did": recipient_did},
        "operation_id": operation_id,
        "message_id": message_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content_type": "text/plain",
    }
    body = {"text": text}
    return rpc_payload(
        source_base,
        "/im/rpc",
        {
            "jsonrpc": "2.0",
            "method": "direct.send",
            "params": {
                "meta": meta,
                "auth": {
                    "scheme": "anp-rfc9421-origin-proof-v1",
                    "origin_proof": origin_proof("direct.send", meta, body, sender["key"]),
                },
                "body": body,
                "client": {"response_mode": "wait-final"},
            },
            "id": operation_id,
        },
        sender["token"],
    )


def smoke_cross_domain_local(args: argparse.Namespace) -> int:
    source_domain = args.source_domain
    target_domain = args.target_domain
    source_port = args.source_port or free_port()
    target_port = args.target_port or free_port()
    source_base = f"http://127.0.0.1:{source_port}"
    target_base = f"http://127.0.0.1:{target_port}"
    root = Path(args.data_root) if args.data_root else Path(tempfile.mkdtemp(prefix="awiki-open-cross-domain-"))
    if args.clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    resolver_map = {source_domain: source_base, target_domain: target_base}
    source_key = generate_ed25519_private_key_pem()
    target_key = generate_ed25519_private_key_pem()
    processes: list[subprocess.Popen] = []
    try:
        processes.append(
            start_open_server(
                data_dir=root / "source",
                port=source_port,
                domain=source_domain,
                private_key_pem=source_key,
                resolver_map=resolver_map,
            )
        )
        processes.append(
            start_open_server(
                data_dir=root / "target",
                port=target_port,
                domain=target_domain,
                private_key_pem=target_key,
                resolver_map=resolver_map,
            )
        )
        wait_health(source_base, processes[0])
        wait_health(target_base, processes[1])

        source_user_key = ed25519.Ed25519PrivateKey.generate()
        target_user_key = ed25519.Ed25519PrivateKey.generate()
        source_handle = unique_handle(args.source_handle)
        target_handle = unique_handle(args.target_handle)
        source_did = f"did:wba:{source_domain}:users:{source_handle}:e1_default"
        target_did = f"did:wba:{target_domain}:users:{target_handle}:e1_default"
        source_user = rpc(
            source_base,
            "/did-auth/rpc",
            "register",
            {
                "handle": source_handle,
                "did_document": user_did_document(
                    source_did,
                    f"{source_base}/anp-im/rpc",
                    f"did:wba:{source_domain}",
                    source_user_key,
                ),
            },
        )
        target_user = rpc(
            target_base,
            "/did-auth/rpc",
            "register",
            {
                "handle": target_handle,
                "did_document": user_did_document(
                    target_did,
                    f"{target_base}/anp-im/rpc",
                    f"did:wba:{target_domain}",
                    target_user_key,
                ),
            },
        )
        source_sender = {"did": source_user["did"], "token": source_user["token"], "key": source_user_key}
        target_sender = {"did": target_user["did"], "token": target_user["token"], "key": target_user_key}

        outbound = send_signed_cross_domain(
            source_base=source_base,
            sender=source_sender,
            recipient_did=target_user["did"],
            text="hello target from local cross-domain",
        )
        target_inbox = rpc(target_base, "/im/rpc", "inbox.get", token=target_user["token"])
        if not any(message.get("message_id") == outbound["message_id"] for message in page_messages(target_inbox)):
            raise RuntimeError("target inbox missing outbound cross-domain message")

        inbound = send_signed_cross_domain(
            source_base=target_base,
            sender=target_sender,
            recipient_did=source_user["did"],
            text="hello source from local cross-domain",
        )
        source_inbox = rpc(source_base, "/im/rpc", "inbox.get", token=source_user["token"])
        if not any(message.get("message_id") == inbound["message_id"] for message in page_messages(source_inbox)):
            raise RuntimeError("source inbox missing inbound cross-domain message")

        result = {
            "ok": True,
            "mode": "cross-domain-local",
            "source": {
                "base_url": source_base,
                "domain": source_domain,
                "service_did": f"did:wba:{source_domain}",
                "user_did": source_user["did"],
                "received_message_id": inbound["message_id"],
            },
            "target": {
                "base_url": target_base,
                "domain": target_domain,
                "service_did": f"did:wba:{target_domain}",
                "user_did": target_user["did"],
                "received_message_id": outbound["message_id"],
            },
            "verified": [
                "two independent uvicorn processes",
                "service DID documents with Ed25519 HTTP signatures",
                "DID discovery through AWIKI_DID_RESOLVER_BASE_URLS",
                "origin_proof verification",
                "signed /anp-im/rpc inbound direct",
                "bidirectional inbox delivery",
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        for process in processes:
            stop_process(process)


def smoke_local(args: argparse.Namespace) -> int:
    base = args.base_url
    caps = rpc(base, "/im/rpc", "anp.get_capabilities")
    assert caps["features"]["group_participant"]["enabled"] is True
    assert caps["features"]["group_participant"]["management"] is False

    alice_handle = unique_handle(args.alice)
    bob_handle = unique_handle(args.bob)
    alice = rpc(base, "/did-auth/rpc", "register", {"handle": alice_handle})
    bob = rpc(base, "/did-auth/rpc", "register", {"handle": bob_handle})

    rpc(base, "/did/profile/rpc", "update_me", {"description": "cli smoke"}, alice["token"])
    rpc(base, "/content/rpc", "create", {"slug": "cli-smoke", "title": "CLI Smoke", "body": "# CLI Smoke"}, alice["token"])

    sent = rpc(base, "/im/rpc", "direct.send", {"recipient_did": bob["did"], "text": "hello from cli"}, alice["token"])
    history = rpc(base, "/im/rpc", "direct.get_history", {"peer_did": alice["did"]}, bob["token"])
    assert page_messages(history)[0]["message_id"] == sent["message_id"]

    group_did = default_group_did(args.did_domain)
    rpc(base, "/im/rpc", "group.join", {"group_did": group_did}, alice["token"])
    rpc(base, "/im/rpc", "group.send", {"group_did": group_did, "text": "group hello"}, alice["token"])
    messages = page_messages(rpc(base, "/im/rpc", "group.list_messages", {"group_did": group_did}, alice["token"]))
    assert messages[-1]["body"]["text"] == "group hello"

    slot = rpc(base, "/im/rpc", "attachment.create_slot", {}, alice["token"])
    put_bytes(base, f"/objects/upload/{slot['slot_id']}", b"cli attachment", {"token": slot["upload_token"]})
    committed = rpc(
        base,
        "/im/rpc",
        "attachment.commit_object",
        {"slot_id": slot["slot_id"], "commit_token": slot["commit_token"], "content_type": "text/plain"},
        alice["token"],
    )
    ticket = rpc(base, "/im/rpc", "attachment.get_download_ticket", {"object_id": committed["object_id"]}, alice["token"])
    assert get_bytes(base, f"/objects/{committed['object_id']}", {"ticket": ticket["ticket"]}) == b"cli attachment"

    print(json.dumps({"ok": True, "mode": "local", "alice": alice["did"], "bob": bob["did"], "alice_handle": alice_handle, "bob_handle": bob_handle}, ensure_ascii=False))
    return 0


def smoke_awiki_info(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    caps = anp_rpc(base, "anp.get_capabilities", anp_params("anp.get_capabilities", args), token=args.token)
    result = {
        "ok": True,
        "mode": "awiki-info-capability",
        "service_base_url": base,
        "did_domain": args.did_domain,
        "service_did": caps.get("service_did"),
        "request_shape": "capability=params.meta/body direct=params.meta/auth/body",
    }
    if args.token and args.sender_did and args.recipient_did and args.origin_proof_json:
        sent = anp_rpc(
            base,
            "direct.send",
            anp_params("direct.send", args, {"text": args.text}),
            args.token,
        )
        result["direct_message_id"] = sent.get("message_id")
    else:
        result["direct_skipped"] = (
            "provide --token --sender-did --recipient-did --origin-proof-json; "
            "sender DID should normally be under the configured --did-domain"
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


async def _smoke_asgi_async(args: argparse.Namespace) -> int:
    import httpx

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from awiki_open_server.app.main import create_app
    from awiki_open_server.app.settings import Settings

    app = create_app(
        Settings(
            data_dir=Path(args.data_dir),
            public_base_url="http://testserver",
            service_did="did:wba:testserver",
            did_domain="testserver",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async def arpc(path: str, method: str, params: dict | None = None, token: str | None = None) -> dict:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            response = await client.post(path, json={"jsonrpc": "2.0", "method": method, "params": params or {}, "id": "cli"}, headers=headers)
            data = response.json()
            if "error" in data:
                raise RuntimeError(f"{method} failed: {data['error']}")
            return data["result"]

        caps = await arpc("/im/rpc", "anp.get_capabilities")
        assert caps["features"]["group_participant"]["enabled"] is True
        alice_handle = unique_handle(args.alice)
        bob_handle = unique_handle(args.bob)
        alice = await arpc("/did-auth/rpc", "register", {"handle": alice_handle})
        bob = await arpc("/did-auth/rpc", "register", {"handle": bob_handle})
        await arpc("/content/rpc", "create", {"slug": "cli-smoke-asgi", "title": "CLI Smoke", "body": "# CLI Smoke"}, alice["token"])
        sent = await arpc("/im/rpc", "direct.send", {"recipient_did": bob["did"], "text": "hello from cli"}, alice["token"])
        history = await arpc("/im/rpc", "direct.get_history", {"peer_did": alice["did"]}, bob["token"])
        assert page_messages(history)[0]["message_id"] == sent["message_id"]
        group_did = default_group_did("testserver")
        await arpc("/im/rpc", "group.join", {"group_did": group_did}, alice["token"])
        await arpc("/im/rpc", "group.send", {"group_did": group_did, "text": "group hello"}, alice["token"])
        messages = page_messages(await arpc("/im/rpc", "group.list_messages", {"group_did": group_did}, alice["token"]))
        assert messages[-1]["body"]["text"] == "group hello"
    print(json.dumps({"ok": True, "mode": "asgi", "alice": alice["did"], "bob": bob["did"], "alice_handle": alice_handle, "bob_handle": bob_handle}, ensure_ascii=False))
    return 0


def smoke_asgi(args: argparse.Namespace) -> int:
    return asyncio.run(_smoke_asgi_async(args))


def verify_public(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    expected_service_did = args.service_did or f"did:wba:{args.did_domain}"
    expected_endpoint = f"{base}/anp-im/rpc"
    checks: list[dict] = []

    def add_check(name: str, ok: bool, **details: object) -> None:
        checks.append({"name": name, "ok": ok, **details})

    status, document = http_get_json(base, "/.well-known/did.json")
    add_check("service_did_document_http", status == 200, status=status)
    add_check("service_did_document_id", document.get("id") == expected_service_did, actual=document.get("id"), expected=expected_service_did)
    services = document.get("service")
    anp_services = []
    if isinstance(services, list):
        anp_services = [
            service
            for service in services
            if isinstance(service, dict) and service.get("type") == "ANPMessageService"
        ]
    add_check("single_anp_message_service", len(anp_services) == 1, count=len(anp_services))
    service = anp_services[0] if anp_services else {}
    add_check("anp_service_endpoint", service.get("serviceEndpoint") == expected_endpoint, actual=service.get("serviceEndpoint"), expected=expected_endpoint)
    add_check("anp_service_did", service.get("serviceDid") == expected_service_did, actual=service.get("serviceDid"), expected=expected_service_did)
    add_check("anp_service_auth_schemes", service.get("authSchemes") == ["bearer", "didwba"], actual=service.get("authSchemes"), expected=["bearer", "didwba"])
    add_check("service_did_has_verification_method", bool(document.get("verificationMethod")), count=len(document.get("verificationMethod") or []))
    add_check("service_did_has_authentication", bool(document.get("authentication")), count=len(document.get("authentication") or []))

    try:
        health = urllib.request.urlopen(f"{base}/healthz", timeout=15)
        health_body = json.loads(health.read().decode())
        add_check("healthz", health.status == 200 and health_body.get("status") == "ok", status=health.status, body=health_body)
    except Exception as exc:
        add_check("healthz", False, error=str(exc))

    capability_params = {
        "meta": {
            "anp_version": "1.0",
            "profile": "anp.core.binding.v1",
            "security_profile": "transport-protected",
            "sender_did": expected_service_did,
            "operation_id": f"op-{uuid.uuid4()}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "content_type": "application/json",
        },
        "body": {},
    }
    try:
        caps = anp_rpc(base, "anp.get_capabilities", capability_params)
        add_check("anp_get_capabilities", caps.get("service_did") == expected_service_did, service_did=caps.get("service_did"))
        features = caps.get("features") if isinstance(caps.get("features"), dict) else {}
        add_check("cross_domain_direct_enabled", bool((features.get("cross_domain_direct") or {}).get("enabled")))
        disabled = caps.get("disabled_features") if isinstance(caps.get("disabled_features"), dict) else {}
        add_check("federation_disabled", "federation" in disabled, disabled_features=disabled)
    except Exception as exc:
        add_check("anp_get_capabilities", False, error=str(exc))

    ok = all(check["ok"] for check in checks)
    print(json.dumps({"ok": ok, "mode": "verify-public", "base_url": base, "did_domain": args.did_domain, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Awiki Open Server smoke CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    local = sub.add_parser("smoke-local")
    local.add_argument("--base-url", required=True)
    local.add_argument("--did-domain", default=os.environ.get("AWIKI_DID_DOMAIN", "localhost"))
    local.add_argument("--alice", default="cli-alice")
    local.add_argument("--bob", default="cli-bob")
    local.set_defaults(func=smoke_local)

    asgi = sub.add_parser("smoke-asgi")
    asgi.add_argument("--data-dir", default="/tmp/awiki-open-server-cli-asgi")
    asgi.add_argument("--alice", default="cli-asgi-alice")
    asgi.add_argument("--bob", default="cli-asgi-bob")
    asgi.set_defaults(func=smoke_asgi)

    cross = sub.add_parser("smoke-cross-domain-local")
    cross.add_argument("--data-root", default="/tmp/awiki-open-server-cross-domain-local")
    cross.add_argument("--source-domain", default="source.test")
    cross.add_argument("--target-domain", default="target.test")
    cross.add_argument("--source-port", type=int)
    cross.add_argument("--target-port", type=int)
    cross.add_argument("--source-handle", default="local-source")
    cross.add_argument("--target-handle", default="local-target")
    cross.add_argument("--clean", dest="clean", action="store_true", default=True)
    cross.add_argument("--no-clean", dest="clean", action="store_false")
    cross.set_defaults(func=smoke_cross_domain_local)

    rust_cli = sub.add_parser("smoke-rust-cli-local")
    rust_cli.add_argument("--awiki-cli-bin", default=os.environ.get("AWIKI_CLI_BIN", "awiki-cli"))
    rust_cli.add_argument("--data-root", default="/tmp/awiki-open-server-rust-cli-local")
    rust_cli.add_argument("--did-domain", default="localhost")
    rust_cli.add_argument("--port", type=int)
    rust_cli.add_argument("--handle-prefix", default="rust-smoke")
    rust_cli.add_argument("--clean", dest="clean", action="store_true", default=True)
    rust_cli.add_argument("--no-clean", dest="clean", action="store_false")
    rust_cli.set_defaults(func=smoke_rust_cli_local)

    remote = sub.add_parser("smoke-awiki-info")
    remote.add_argument("--base-url", default=os.environ.get("AWIKI_INFO_BASE_URL", "https://awiki.info"))
    remote.add_argument("--did-domain", default=os.environ.get("RWIKI_DID_DOMAIN", "rwiki.cn"))
    remote.add_argument("--token", default=os.environ.get("AWIKI_INFO_TOKEN"))
    remote.add_argument("--sender-did", default=os.environ.get("AWIKI_INFO_SENDER_DID"))
    remote.add_argument("--recipient-did", default=os.environ.get("AWIKI_INFO_RECIPIENT_DID"))
    remote.add_argument("--auth-scheme", default=os.environ.get("AWIKI_INFO_AUTH_SCHEME", "anp-rfc9421-origin-proof-v1"))
    remote.add_argument("--origin-proof-json", default=os.environ.get("AWIKI_INFO_ORIGIN_PROOF_JSON"))
    remote.add_argument("--text", default="awiki-open-server remote smoke")
    remote.set_defaults(func=smoke_awiki_info)

    public = sub.add_parser("verify-public")
    public.add_argument("--base-url", required=True)
    public.add_argument("--did-domain", required=True)
    public.add_argument("--service-did")
    public.set_defaults(func=verify_public)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
