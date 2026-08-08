#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
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
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509.oid import NameOID

from awiki_open_server.service_identity import content_digest, generate_ed25519_private_key_pem


def open_server_provenance() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {
        "repository": str(repository),
        "commit": commit,
        "dirty": bool(status),
        "changed_path_count": len(status),
    }


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
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
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
    public_base_url: str | None = None,
    bind_host: str = "127.0.0.1",
    ssl_certfile: Path | None = None,
    ssl_keyfile: Path | None = None,
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
            "AWIKI_PUBLIC_BASE_URL": public_base_url or f"http://127.0.0.1:{port}",
            "AWIKI_DID_DOMAIN": domain,
            "AWIKI_SERVICE_DID": f"did:wba:{domain}",
            "AWIKI_SERVICE_PRIVATE_KEY_PEM": private_key_pem.replace("\n", "\\n"),
            "AWIKI_ALLOW_UNSIGNED_PEER_DEV": "0",
            "AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT": "0",
            "AWIKI_DID_RESOLVER_BASE_URLS": json.dumps(resolver_map),
        }
    )
    command = [
            sys.executable,
            "-m",
            "uvicorn",
            "awiki_open_server.app.main:create_app",
            "--factory",
            "--host",
            bind_host,
            "--port",
            str(port),
            "--log-level",
            "warning",
        ]
    if ssl_certfile is not None and ssl_keyfile is not None:
        command.extend(["--ssl-certfile", str(ssl_certfile), "--ssl-keyfile", str(ssl_keyfile)])
    return subprocess.Popen(
        command,
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def rust_cli_env(workspace: Path, home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({"HOME": str(home), "AWIKI_CLI_WORKSPACE_HOME_DIR": str(workspace)})
    return env


def start_rust_cli_listener(cli_bin: str, workspace: Path, home: Path) -> subprocess.Popen:
    env = rust_cli_env(workspace, home)
    env["AWIKI_CLI_INTERNAL_ENTRY"] = "1"
    return subprocess.Popen(
        [cli_bin, "runtime", "listener", "run"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def rust_cli_json(cli_bin: str, workspace: Path, home: Path, *args: str) -> dict[str, Any]:
    env = rust_cli_env(workspace, home)
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


def initialize_rust_cli_workspace(
    cli_bin: str,
    workspace: Path,
    home: Path,
    *,
    base_url: str,
    did_domain: str,
    ca_bundle: Path | None = None,
) -> None:
    rust_cli_json(
        cli_bin,
        workspace,
        home,
        "tenant",
        "create",
        "local",
        "--backend-base-url",
        base_url,
        "--did-host",
        did_domain,
    )
    rust_cli_json(cli_bin, workspace, home, "tenant", "use", "local")
    if ca_bundle is not None:
        config_path = workspace / "tenants" / "local" / "config.yaml"
        raw = config_path.read_text(encoding="utf-8")
        marker = "  ca_bundle: \n"
        if marker not in raw:
            raise RuntimeError(f"rust cli config missing services.ca_bundle marker: {config_path}")
        config_path.write_text(raw.replace(marker, f"  ca_bundle: {json.dumps(str(ca_bundle))}\n", 1), encoding="utf-8")
    resolved = rust_cli_json(cli_bin, workspace, home, "config", "show").get("data") or {}
    expected = {
        "service_base_url": base_url,
        "did_domain": did_domain,
        "anp_service_endpoint": f"{base_url.rstrip('/')}/anp-im/rpc",
        "anp_service_did": f"did:wba:{did_domain}",
    }
    actual = {key: resolved.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError(
            "rust cli workspace resolved unexpected service configuration: "
            + json.dumps({"expected": expected, "actual": actual}, ensure_ascii=False)
        )


def generate_test_tls_material(root: Path, domains: list[str]) -> tuple[Path, Path, Path]:
    tls_dir = root / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AWiki Open Server Test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domains[0])])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain) for domain in domains]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = tls_dir / "ca.pem"
    cert_path = tls_dir / "server.pem"
    key_path = tls_dir / "server-key.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return ca_path, cert_path, key_path


def rust_register_did(result: dict[str, Any]) -> str:
    did = (((result.get("data") or {}).get("identity") or {}).get("did"))
    if not isinstance(did, str) or not did:
        raise RuntimeError("rust cli id register response missing data.identity.did")
    return did


def rust_group_did(result: dict[str, Any]) -> str:
    group = ((result.get("data") or {}).get("group") or {})
    group_did = group.get("group_did") if isinstance(group, dict) else None
    if not isinstance(group_did, str) or not group_did:
        raise RuntimeError("rust cli group response missing data.group.group_did")
    return group_did


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


def find_visible_message(result: dict[str, Any], *, message_id: str, text: str | None = None) -> dict[str, Any]:
    for message in rust_messages(result):
        serialized = json.dumps(message, ensure_ascii=False, sort_keys=True)
        id_matches = message.get("message_id") == message_id or message.get("id") == message_id or message_id in serialized
        text_matches = text is None or message.get("content") == text or text in serialized
        if id_matches and text_matches:
            return message
    raise RuntimeError(f"message {message_id} not visible with expected content")


def assert_message_visible(result: dict[str, Any], *, message_id: str, text: str) -> None:
    find_visible_message(result, message_id=message_id, text=text)


def assert_message_not_visible(result: dict[str, Any], *, message_id: str) -> None:
    for message in rust_messages(result):
        if message.get("message_id") == message_id or message.get("id") == message_id or message_id in json.dumps(
            message, ensure_ascii=False, sort_keys=True
        ):
            raise RuntimeError(f"message {message_id} unexpectedly visible")


def assert_group_visible(result: dict[str, Any], *, group_did: str) -> None:
    groups = ((result.get("data") or {}).get("groups") or [])
    if any(isinstance(group, dict) and group.get("group_did") == group_did for group in groups):
        return
    raise RuntimeError(f"group {group_did} not visible in rust cli group list")


def assert_active_member(result: dict[str, Any], *, member_did: str) -> None:
    members = ((result.get("data") or {}).get("members") or [])
    for member in members:
        if not isinstance(member, dict):
            continue
        did = member.get("member_did") or member.get("agent_did") or member.get("did")
        if did == member_did and member.get("status", "active") == "active":
            return
    raise RuntimeError(f"active member {member_did} not visible in rust cli group members")


def assert_active_member_absent(result: dict[str, Any], *, member_did: str) -> None:
    members = ((result.get("data") or {}).get("members") or [])
    for member in members:
        if not isinstance(member, dict):
            continue
        did = member.get("member_did") or member.get("agent_did") or member.get("did")
        if did == member_did and member.get("status", "active") == "active":
            raise RuntimeError(f"inactive member {member_did} remained in active group inventory")


def assert_rust_cli_fails(
    cli_bin: str,
    workspace: Path,
    home: Path,
    *args: str,
    expected: str | None,
) -> None:
    env = os.environ.copy()
    env.update({"HOME": str(home), "AWIKI_CLI_WORKSPACE_HOME_DIR": str(workspace)})
    completed = subprocess.run(
        [cli_bin, *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode == 0:
        raise RuntimeError(f"rust cli command unexpectedly succeeded: {list(args)}")
    output = f"{completed.stdout}\n{completed.stderr}"
    if expected is not None and expected not in output:
        raise RuntimeError(
            "rust cli command failed for an unexpected reason: "
            + json.dumps(
                {
                    "args": list(args),
                    "expected": expected,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-2000:],
                    "stderr": completed.stderr[-2000:],
                },
                ensure_ascii=False,
            )
        )


def china_dev_phone() -> str:
    return f"138{uuid.uuid4().int % 100000000:08d}"


def smoke_rust_cli_local(args: argparse.Namespace) -> int:
    if args.standard_https and not args.inside_netns:
        unshare = shutil.which("unshare")
        ip = shutil.which("ip")
        mount = shutil.which("mount")
        if not unshare or not ip or not mount:
            raise RuntimeError("standard HTTPS real-CLI smoke requires unshare, ip, and mount")
        with tempfile.TemporaryDirectory(prefix="awiki-open-local-netns-") as temporary:
            hosts_path = Path(temporary) / "hosts"
            shutil.copyfile("/etc/hosts", hosts_path)
            with hosts_path.open("a", encoding="utf-8") as hosts_file:
                hosts_file.write(f"\n{args.bind_host} {args.did_domain}\n")
            child_command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "smoke-rust-cli-local",
                "--inside-netns",
                "--standard-https",
                "--awiki-cli-bin",
                str(Path(resolve_executable(args.awiki_cli_bin)).resolve()),
                "--data-root",
                str(Path(args.data_root).resolve()),
                "--did-domain",
                args.did_domain,
                "--bind-host",
                args.bind_host,
                "--handle-prefix",
                args.handle_prefix,
                "--clean" if args.clean else "--no-clean",
            ]
            if args.skip_attachments:
                child_command.append("--skip-attachments")
            shell_program = 'mount --bind "$1" /etc/hosts && "$2" link set lo up && shift 2 && exec "$@"'
            completed = subprocess.run(
                [unshare, "-Urnm", "sh", "-c", shell_program, "sh", str(hosts_path), ip, *child_command],
                cwd=Path(__file__).resolve().parents[1],
                env=os.environ.copy(),
                check=False,
                capture_output=True,
                text=True,
            )
            sys.stdout.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            return completed.returncode
    cli_bin = resolve_executable(args.awiki_cli_bin)
    port = args.port or (443 if args.standard_https else free_port())
    did_domain = args.did_domain
    scheme = "https" if args.standard_https else "http"
    base_url = f"{scheme}://{did_domain}" if args.standard_https and port == 443 else f"{scheme}://{did_domain}:{port}"
    root = Path(args.data_root) if args.data_root else Path(tempfile.mkdtemp(prefix="awiki-open-rust-cli-"))
    if args.clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    ca_bundle: Path | None = None
    ssl_certfile: Path | None = None
    ssl_keyfile: Path | None = None
    if args.standard_https:
        ca_bundle, ssl_certfile, ssl_keyfile = generate_test_tls_material(root, [did_domain])
        os.environ["SSL_CERT_FILE"] = str(ca_bundle)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        for proxy_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(proxy_name, None)
    home = root / "home"
    alice_workspace = root / "cli-alice"
    bob_workspace = root / "cli-bob"
    charlie_workspace = root / "cli-charlie"
    server_data = root / "server"
    cli_version = rust_cli_json(cli_bin, alice_workspace, home, "version")
    artifact_sha256 = hashlib.sha256(Path(cli_bin).read_bytes()).hexdigest()
    service_private_key = generate_ed25519_private_key_pem()
    process = start_open_server(
        data_dir=server_data,
        port=port,
        domain=did_domain,
        private_key_pem=service_private_key,
        resolver_map={did_domain: base_url},
        public_base_url=base_url,
        bind_host=args.bind_host,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )
    try:
        wait_health(base_url, process)
        initialize_rust_cli_workspace(
            cli_bin,
            alice_workspace,
            home,
            base_url=base_url,
            did_domain=did_domain,
            ca_bundle=ca_bundle,
        )
        initialize_rust_cli_workspace(
            cli_bin,
            bob_workspace,
            home,
            base_url=base_url,
            did_domain=did_domain,
            ca_bundle=ca_bundle,
        )
        initialize_rust_cli_workspace(
            cli_bin,
            charlie_workspace,
            home,
            base_url=base_url,
            did_domain=did_domain,
            ca_bundle=ca_bundle,
        )
        prefix = args.handle_prefix
        alice_handle = unique_handle(f"{prefix}-alice")
        bob_handle = unique_handle(f"{prefix}-bob")
        charlie_handle = unique_handle(f"{prefix}-charlie")
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
        charlie_register = rust_cli_json(
            cli_bin,
            charlie_workspace,
            home,
            "id",
            "register",
            "--handle",
            charlie_handle,
            "--phone",
            china_dev_phone(),
            "--otp",
            "123456",
        )
        alice_did = rust_register_did(alice_register)
        bob_did = rust_register_did(bob_register)
        charlie_did = rust_register_did(charlie_register)

        direct_text = "hello from rust cli local smoke"
        direct_send = rust_cli_json(cli_bin, alice_workspace, home, "msg", "send", "--to", bob_did, "--text", direct_text)
        direct_message_id = rust_message_id(direct_send)
        direct_text_two = "second unread message for batch mark-read"
        direct_message_two = rust_message_id(
            rust_cli_json(cli_bin, alice_workspace, home, "msg", "send", "--to", bob_did, "--text", direct_text_two)
        )
        direct_text_three = "third unread message for batch mark-read"
        direct_message_three = rust_message_id(
            rust_cli_json(cli_bin, alice_workspace, home, "msg", "send", "--to", bob_did, "--text", direct_text_three)
        )
        bob_inbox = rust_cli_json(cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct", "--limit", "10")
        bob_history = retry_rust_cli_json(cli_bin, bob_workspace, home, "msg", "history", "--with", alice_did, "--limit", "10")
        assert_message_visible(bob_inbox, message_id=direct_message_id, text=direct_text)
        assert_message_visible(bob_history, message_id=direct_message_id, text=direct_text)
        bob_unread = rust_cli_json(cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct", "--unread", "--limit", "10")
        visible_direct = find_visible_message(bob_unread, message_id=direct_message_id, text=direct_text)
        find_visible_message(bob_unread, message_id=direct_message_two, text=direct_text_two)
        find_visible_message(bob_unread, message_id=direct_message_three, text=direct_text_three)
        visible_direct_id = visible_direct.get("id") or visible_direct.get("message_id")
        if not isinstance(visible_direct_id, str) or not visible_direct_id:
            raise RuntimeError("rust cli unread message missing a mark-read id")
        rust_cli_json(cli_bin, bob_workspace, home, "msg", "mark-read", visible_direct_id)
        rust_cli_json(cli_bin, bob_workspace, home, "msg", "mark-read", visible_direct_id)
        bob_unread_after = rust_cli_json(
            cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct", "--unread", "--limit", "10"
        )
        assert_message_not_visible(bob_unread_after, message_id=direct_message_id)
        find_visible_message(bob_unread_after, message_id=direct_message_two, text=direct_text_two)
        find_visible_message(bob_unread_after, message_id=direct_message_three, text=direct_text_three)
        rust_cli_json(cli_bin, bob_workspace, home, "msg", "mark-read", direct_message_two, direct_message_three)
        batch_unread_after = rust_cli_json(
            cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct", "--unread", "--limit", "20"
        )
        for marked_id in (direct_message_id, direct_message_two, direct_message_three):
            assert_message_not_visible(batch_unread_after, message_id=marked_id)
        marked_history = retry_rust_cli_json(
            cli_bin, bob_workspace, home, "msg", "history", "--with", alice_did, "--limit", "20"
        )
        for marked_id in (direct_message_id, direct_message_two, direct_message_three):
            marked = find_visible_message(marked_history, message_id=marked_id)
            if marked.get("is_read") is not True:
                raise RuntimeError(f"rust cli history did not project is_read=true for {marked_id}")
        page_mark_text = "message read through inbox --mark-read"
        page_mark_id = rust_message_id(
            rust_cli_json(cli_bin, alice_workspace, home, "msg", "send", "--to", bob_did, "--text", page_mark_text)
        )
        page_unread_before = rust_cli_json(
            cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct", "--unread", "--limit", "20"
        )
        page_visible = find_visible_message(page_unread_before, message_id=page_mark_id, text=page_mark_text)
        page_visible_id = page_visible.get("id") or page_visible.get("message_id")
        if not isinstance(page_visible_id, str) or not page_visible_id:
            raise RuntimeError("rust cli page mark-read message missing local id")
        assert_rust_cli_fails(
            cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct",
            "--unread", "--mark-read", "--limit", "20", expected="inbox-mark-read-side-effect",
        )
        rust_cli_json(cli_bin, bob_workspace, home, "msg", "mark-read", page_visible_id)
        page_unread_after = rust_cli_json(
            cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct",
            "--unread", "--limit", "20",
        )
        assert_message_not_visible(page_unread_after, message_id=page_mark_id)
        assert_rust_cli_fails(
            cli_bin, charlie_workspace, home, "msg", "mark-read", direct_message_id, expected=None
        )

        attachment_source = root / "attachment-source.bin"
        attachment_bytes = b"awiki-open-server-cli-attachment\x00\xff\x10"
        attachment_source.write_bytes(attachment_bytes)
        if not args.skip_attachments:
            direct_attachment = rust_cli_json(
                cli_bin,
                alice_workspace,
                home,
                "msg",
                "send",
                "--to",
                bob_did,
                "--text",
                "direct attachment caption",
                "--file",
                str(attachment_source),
                "--mime-type",
                "application/octet-stream",
                "--secure",
                "off",
            )
            direct_attachment_id = rust_message_id(direct_attachment)
            direct_attachment_inbox = rust_cli_json(
                cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct", "--limit", "20"
            )
            find_visible_message(direct_attachment_inbox, message_id=direct_attachment_id, text="direct attachment caption")
            direct_download = root / "direct-attachment-download.bin"
            rust_cli_json(
                cli_bin,
                bob_workspace,
                home,
                "msg",
                "attachment",
                "download",
                "--with",
                alice_handle,
                "--message-id",
                direct_attachment_id,
                "--output",
                str(direct_download),
            )
            if direct_download.read_bytes() != attachment_bytes:
                raise RuntimeError("rust cli Direct attachment download differs from source bytes")

        group_name = f"Rust CLI Group {uuid.uuid4().hex[:8]}"
        created_group = rust_cli_json(
            cli_bin,
            alice_workspace,
            home,
            "group",
            "create",
            "--name",
            group_name,
            "--discoverability",
            "private",
            "--admission-mode",
            "admin-add",
            "--max-members",
            "100",
        )
        group_did = rust_group_did(created_group)
        group_get = rust_cli_json(cli_bin, alice_workspace, home, "group", "get", "--group", group_did)
        if rust_group_did(group_get) != group_did:
            raise RuntimeError("rust cli group get returned the wrong group")
        group_list = rust_cli_json(cli_bin, alice_workspace, home, "group", "list", "--limit", "20")
        assert_group_visible(group_list, group_did=group_did)

        rust_cli_json(
            cli_bin,
            alice_workspace,
            home,
            "group",
            "add",
            "--group",
            group_did,
            "--member",
            bob_did,
            "--role",
            "member",
        )

        updated_name = f"{group_name} Updated"
        rust_cli_json(
            cli_bin,
            alice_workspace,
            home,
            "group",
            "update",
            "--group",
            group_did,
            "--name",
            updated_name,
            "--admission-mode",
            "open-join",
        )
        updated_group = rust_cli_json(cli_bin, alice_workspace, home, "group", "get", "--group", group_did)
        updated_snapshot = ((updated_group.get("data") or {}).get("group") or {})
        if updated_snapshot.get("name") != updated_name:
            raise RuntimeError("rust cli group update did not persist the new name")

        rust_cli_json(cli_bin, charlie_workspace, home, "group", "join", "--group", group_did)

        members = rust_cli_json(cli_bin, alice_workspace, home, "group", "members", "--group", group_did, "--limit", "100")
        for member_did in (alice_did, bob_did, charlie_did):
            assert_active_member(members, member_did=member_did)
        members_page_one = rust_cli_json(
            cli_bin, alice_workspace, home, "group", "members", "--group", group_did, "--limit", "1"
        )
        page_one_data = members_page_one.get("data") if isinstance(members_page_one.get("data"), dict) else {}
        page_one_members = page_one_data.get("members")
        members_cursor = page_one_data.get("next_cursor") or page_one_data.get("cursor")
        if not isinstance(page_one_members, list) or len(page_one_members) != 1 or not isinstance(members_cursor, str) or not members_cursor:
            raise RuntimeError("rust cli group members first page did not expose one member and a next cursor")
        members_page_two = rust_cli_json(
            cli_bin,
            alice_workspace,
            home,
            "group",
            "members",
            "--group",
            group_did,
            "--limit",
            "1",
            "--cursor",
            members_cursor,
        )
        page_two_members = (((members_page_two.get("data") or {}).get("members")) or [])
        if len(page_two_members) != 1 or page_two_members[0] == page_one_members[0]:
            raise RuntimeError("rust cli group members cursor did not advance to a distinct member")

        alice_group_text = "hello group from rust cli owner"
        alice_client_message_id = f"msg-{uuid.uuid4().hex}"
        alice_group_send = rust_cli_json(
            cli_bin,
            alice_workspace,
            home,
            "msg",
            "send",
            "--group",
            group_did,
            "--text",
            alice_group_text,
            "--client-message-id",
            alice_client_message_id,
        )
        alice_group_message_id = rust_message_id(alice_group_send)
        if alice_group_message_id != alice_client_message_id:
            raise RuntimeError("rust cli group send did not preserve client-message-id")

        bob_group_text = "hello group from rust cli added member"
        bob_group_send = rust_cli_json(
            cli_bin,
            bob_workspace,
            home,
            "msg",
            "send",
            "--group",
            group_did,
            "--text",
            bob_group_text,
            "--client-message-id",
            f"msg-{uuid.uuid4().hex}",
        )
        bob_group_message_id = rust_message_id(bob_group_send)
        for workspace in (alice_workspace, bob_workspace, charlie_workspace):
            group_messages = rust_cli_json(
                cli_bin, workspace, home, "group", "messages", "--group", group_did, "--limit", "20"
            )
            assert_message_visible(
                group_messages,
                message_id=alice_group_message_id,
                text=alice_group_text,
            )
            assert_message_visible(
                group_messages,
                message_id=bob_group_message_id,
                text=bob_group_text,
            )

        if not args.skip_attachments:
            group_attachment = rust_cli_json(
                cli_bin,
                alice_workspace,
                home,
                "msg",
                "send",
                "--group",
                group_did,
                "--text",
                "group attachment caption",
                "--file",
                str(attachment_source),
                "--mime-type",
                "application/octet-stream",
                "--secure",
                "off",
            )
            group_attachment_id = rust_message_id(group_attachment)
            bob_group_attachments = rust_cli_json(
                cli_bin, bob_workspace, home, "group", "messages", "--group", group_did, "--limit", "50"
            )
            find_visible_message(bob_group_attachments, message_id=group_attachment_id, text="group attachment caption")
            group_download = root / "group-attachment-download.bin"
            rust_cli_json(
                cli_bin,
                bob_workspace,
                home,
                "msg",
                "attachment",
                "download",
                "--group",
                group_did,
                "--message-id",
                group_attachment_id,
                "--output",
                str(group_download),
            )
            if group_download.read_bytes() != attachment_bytes:
                raise RuntimeError("rust cli Group attachment download differs from source bytes")

        stop_process(process)
        process = start_open_server(
            data_dir=server_data,
            port=port,
            domain=did_domain,
            private_key_pem=service_private_key,
            resolver_map={did_domain: base_url},
            public_base_url=base_url,
            bind_host=args.bind_host,
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
        )
        wait_health(base_url, process)
        restarted_history = retry_rust_cli_json(
            cli_bin, bob_workspace, home, "msg", "history", "--with", alice_did, "--limit", "20"
        )
        assert_message_visible(restarted_history, message_id=direct_message_id, text=direct_text)
        restarted_unread = rust_cli_json(
            cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct", "--unread", "--limit", "20"
        )
        assert_message_not_visible(restarted_unread, message_id=direct_message_id)
        restarted_group = rust_cli_json(cli_bin, alice_workspace, home, "group", "get", "--group", group_did)
        if rust_group_did(restarted_group) != group_did:
            raise RuntimeError("rust cli group did not survive OpenServer restart")
        restarted_members = rust_cli_json(
            cli_bin, alice_workspace, home, "group", "members", "--group", group_did, "--limit", "100"
        )
        for member_did in (alice_did, bob_did, charlie_did):
            assert_active_member(restarted_members, member_did=member_did)
        restarted_messages = rust_cli_json(
            cli_bin, bob_workspace, home, "group", "messages", "--group", group_did, "--limit", "50"
        )
        assert_message_visible(restarted_messages, message_id=alice_group_message_id, text=alice_group_text)
        assert_message_visible(restarted_messages, message_id=bob_group_message_id, text=bob_group_text)
        if not args.skip_attachments:
            restarted_group_download = root / "group-attachment-download-after-restart.bin"
            rust_cli_json(
                cli_bin,
                bob_workspace,
                home,
                "msg",
                "attachment",
                "download",
                "--group",
                group_did,
                "--message-id",
                group_attachment_id,
                "--output",
                str(restarted_group_download),
            )
            if restarted_group_download.read_bytes() != attachment_bytes:
                raise RuntimeError("rust cli Group attachment download after restart differs from source bytes")

        rust_cli_json(cli_bin, charlie_workspace, home, "group", "leave", "--group", group_did)
        after_leave_members = rust_cli_json(
            cli_bin, alice_workspace, home, "group", "members", "--group", group_did, "--limit", "100"
        )
        assert_active_member_absent(after_leave_members, member_did=charlie_did)
        assert_rust_cli_fails(
            cli_bin, charlie_workspace, home, "group", "members", "--group", group_did, "--limit", "10", expected=None
        )
        if not args.skip_attachments:
            assert_rust_cli_fails(
                cli_bin, charlie_workspace, home, "msg", "attachment", "download", "--group", group_did,
                "--message-id", group_attachment_id, "--output", str(root / "charlie-after-leave.bin"), expected=None,
            )
        assert_rust_cli_fails(
            cli_bin,
            charlie_workspace,
            home,
            "msg",
            "send",
            "--group",
            group_did,
            "--text",
            "must fail after leave",
            expected=None,
        )
        rust_cli_json(
            cli_bin,
            alice_workspace,
            home,
            "group",
            "remove",
            "--group",
            group_did,
            "--member",
            bob_did,
        )
        after_remove_members = rust_cli_json(
            cli_bin, alice_workspace, home, "group", "members", "--group", group_did, "--limit", "100"
        )
        assert_active_member_absent(after_remove_members, member_did=bob_did)
        assert_rust_cli_fails(
            cli_bin, bob_workspace, home, "group", "members", "--group", group_did, "--limit", "10", expected=None
        )
        if not args.skip_attachments:
            assert_rust_cli_fails(
                cli_bin, bob_workspace, home, "msg", "attachment", "download", "--group", group_did,
                "--message-id", group_attachment_id, "--output", str(root / "bob-after-remove.bin"), expected=None,
            )
        assert_rust_cli_fails(
            cli_bin,
            bob_workspace,
            home,
            "msg",
            "send",
            "--group",
            group_did,
            "--text",
            "must fail after removal",
            expected=None,
        )

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
            "cli_artifact_sha256": artifact_sha256,
            "cli_version": cli_version.get("data"),
            "open_server": open_server_provenance(),
            "data_root": str(root),
            "alice": {"handle": alice_handle, "did": alice_did},
            "bob": {"handle": bob_handle, "did": bob_did},
            "charlie": {"handle": charlie_handle, "did": charlie_did},
            "group_did": group_did,
            "attachment_fixture": {
                "size": len(attachment_bytes),
                "sha256": hashlib.sha256(attachment_bytes).hexdigest(),
                "verified": not args.skip_attachments,
            },
            "verified": [
                "rust cli id register via /user-service/v1/did-auth/rpc with placeholder phone/otp CLI args; server does not run contact verification",
                "direct msg send, inbox, and history through /im/rpc",
                "direct single, batch, idempotent, unauthorized, and restart-persistent mark-read; page side-effect is CLI-declared unsupported",
                *([] if args.skip_attachments else ["direct and group attachment send/download with byte-for-byte verification"]),
                "hosted group create/get/list/add/update/join/send/messages/leave/remove lifecycle",
                "group members inventory, leave/remove convergence, and non-member denial through the real CLI",
                "group members cursor pagination through the real CLI",
                "server restart persistence for messages, read state, groups, members, and attachment objects",
                "group client-message-id preservation and post-leave/post-remove authorization denial",
                "people follow/status/following/followers through /user-service/v1/did/relationships/rpc",
                "site root/page commands through /user-service/v1/site/rpc",
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        stop_process(process)
        stderr_tail = process.stderr.read()[-8000:] if process.stderr is not None else ""
        raise RuntimeError(f"{exc}; open_server_stderr={stderr_tail}") from exc
    finally:
        stop_process(process)


def _json_values_for_key(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            if item_key == key:
                found.append(item_value)
            found.extend(_json_values_for_key(item_value, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_json_values_for_key(item, key))
    return found


def wait_rust_listener_ready(
    cli_bin: str,
    workspace: Path,
    home: Path,
    process: subprocess.Popen,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_status: dict[str, Any] | None = None
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            stdout = process.stdout.read()[-4000:] if process.stdout is not None else ""
            stderr = process.stderr.read()[-4000:] if process.stderr is not None else ""
            raise RuntimeError(
                "rust cli listener exited before ready: "
                + json.dumps({"returncode": process.returncode, "stdout": stdout, "stderr": stderr}, ensure_ascii=False)
            )
        try:
            last_status = rust_cli_json(cli_bin, workspace, home, "runtime", "listener", "status")
            connected = True in _json_values_for_key(last_status, "connected")
            v2_negotiated = True in _json_values_for_key(last_status, "v2_subprotocol_negotiated")
            v2_bootstrap = True in _json_values_for_key(last_status, "v2_bootstrap_completed")
            protocols = _json_values_for_key(last_status, "last_reconcile_protocol")
            legacy_values = _json_values_for_key(last_status, "legacy_sync_used")
            if connected and v2_negotiated and v2_bootstrap and "sync_v2" in protocols and False in legacy_values:
                return last_status
            last_error = "listener status not ready"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(
        "rust cli listener did not reach reliable sync v2 readiness: "
        + json.dumps({"error": last_error, "last_status": last_status}, ensure_ascii=False)
    )


def wait_file_contains(path: Path, needles: list[str], *, timeout_seconds: float = 30.0) -> str:
    deadline = time.time() + timeout_seconds
    text = ""
    while time.time() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if all(needle in text for needle in needles):
                return text
        time.sleep(0.2)
    raise RuntimeError(
        "host-notify file did not contain expected durable identifiers: "
        + json.dumps({"path": str(path), "needles": needles, "tail": text[-4000:]}, ensure_ascii=False)
    )


def retry_rust_cli_json(
    cli_bin: str,
    workspace: Path,
    home: Path,
    *args: str,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            return rust_cli_json(cli_bin, workspace, home, *args)
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise RuntimeError(f"rust cli command did not become ready: {last_error}")


def wait_rust_message_visible(
    cli_bin: str,
    workspace: Path,
    home: Path,
    *args: str,
    message_id: str,
    text_value: str,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            result = rust_cli_json(cli_bin, workspace, home, *args)
            try:
                find_visible_message(result, message_id=message_id, text=text_value)
            except Exception as exc:
                raise RuntimeError(
                    f"{exc}; response={json.dumps(result, ensure_ascii=False)}"
                ) from exc
            return result
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise RuntimeError(f"message {message_id} did not become visible through real CLI: {last_error}")


def smoke_rust_cli_realtime_restart(args: argparse.Namespace) -> int:
    cli_bin = resolve_executable(args.awiki_cli_bin)
    port = args.port or free_port()
    did_domain = args.did_domain
    base_url = f"http://{did_domain}:{port}"
    root = Path(args.data_root)
    if args.clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    home = root / "home"
    alice_workspace = root / "cli-alice"
    bob_workspace = root / "cli-bob"
    server_data = root / "server"
    service_private_key = generate_ed25519_private_key_pem()
    cli_version = rust_cli_json(cli_bin, alice_workspace, home, "version")
    artifact_sha256 = hashlib.sha256(Path(cli_bin).read_bytes()).hexdigest()
    server_boots: list[dict[str, Any]] = []
    listener_boots: list[dict[str, Any]] = []
    process = start_open_server(
        data_dir=server_data,
        port=port,
        domain=did_domain,
        private_key_pem=service_private_key,
        resolver_map={did_domain: base_url},
        public_base_url=base_url,
    )
    server_boots.append({"boot_id": uuid.uuid4().hex, "pid": process.pid})
    listener: subprocess.Popen | None = None
    try:
        wait_health(base_url, process)
        for workspace in (alice_workspace, bob_workspace):
            initialize_rust_cli_workspace(
                cli_bin, workspace, home, base_url=base_url, did_domain=did_domain
            )
        alice_handle = unique_handle("realtime-alice")
        bob_handle = unique_handle("realtime-bob")
        alice_did = rust_register_did(
            rust_cli_json(
                cli_bin, alice_workspace, home, "id", "register", "--handle", alice_handle,
                "--phone", china_dev_phone(), "--otp", "123456",
            )
        )
        bob_did = rust_register_did(
            rust_cli_json(
                cli_bin, bob_workspace, home, "id", "register", "--handle", bob_handle,
                "--phone", china_dev_phone(), "--otp", "123456",
            )
        )
        created_group = rust_cli_json(
            cli_bin, alice_workspace, home, "group", "create", "--name", "Realtime Restart Gate",
            "--discoverability", "private", "--admission-mode", "admin-add", "--max-members", "10",
        )
        group_did = rust_group_did(created_group)
        rust_cli_json(
            cli_bin, alice_workspace, home, "group", "add", "--group", group_did,
            "--member", bob_did, "--role", "member",
        )

        rust_cli_json(
            cli_bin, bob_workspace, home, "runtime", "listener", "config", "set",
            "--enabled=false", "--auto-install=false", "--auto-start=false",
        )
        rust_cli_json(cli_bin, bob_workspace, home, "runtime", "mode", "set", "websocket")
        rust_cli_json(cli_bin, bob_workspace, home, "runtime", "host-notify", "config", "set", "--sink", "file")
        rust_cli_json(cli_bin, bob_workspace, home, "runtime", "host-notify", "enable")
        rust_cli_json(
            cli_bin, bob_workspace, home, "runtime", "listener", "config", "set",
            "--enabled=true", "--auto-install=false", "--auto-start=false",
        )
        notify_file = bob_workspace / "tenants" / "local" / "logs" / "host-notify.events.jsonl"

        listener = start_rust_cli_listener(cli_bin, bob_workspace, home)
        listener_boots.append({"boot_id": uuid.uuid4().hex, "pid": listener.pid})
        first_status = wait_rust_listener_ready(cli_bin, bob_workspace, home, listener)
        direct_one = rust_message_id(
            rust_cli_json(
                cli_bin, alice_workspace, home, "msg", "send", "--to", bob_did,
                "--text", "realtime direct while connected", "--secure", "off",
            )
        )
        group_one = rust_message_id(
            rust_cli_json(
                cli_bin, alice_workspace, home, "msg", "send", "--group", group_did,
                "--text", "realtime group while connected", "--secure", "off",
            )
        )
        wait_file_contains(notify_file, [direct_one, group_one])

        stop_process(listener)
        listener = None
        direct_offline = rust_message_id(
            rust_cli_json(
                cli_bin, alice_workspace, home, "msg", "send", "--to", bob_did,
                "--text", "direct while listener stopped", "--secure", "off",
            )
        )
        group_offline = rust_message_id(
            rust_cli_json(
                cli_bin, alice_workspace, home, "msg", "send", "--group", group_did,
                "--text", "group while listener stopped", "--secure", "off",
            )
        )
        listener = start_rust_cli_listener(cli_bin, bob_workspace, home)
        listener_boots.append({"boot_id": uuid.uuid4().hex, "pid": listener.pid})
        second_status = wait_rust_listener_ready(cli_bin, bob_workspace, home, listener)
        wait_file_contains(notify_file, [direct_offline, group_offline])

        stop_process(process)
        process = start_open_server(
            data_dir=server_data,
            port=port,
            domain=did_domain,
            private_key_pem=service_private_key,
            resolver_map={did_domain: base_url},
            public_base_url=base_url,
        )
        server_boots.append({"boot_id": uuid.uuid4().hex, "pid": process.pid})
        wait_health(base_url, process)
        # The foreground entry is deliberately supervised by this test instead
        # of installing a system service. Restart it after the server outage so
        # the recovery path matches the production service-manager contract.
        stop_process(listener)
        listener = start_rust_cli_listener(cli_bin, bob_workspace, home)
        listener_boots.append({"boot_id": uuid.uuid4().hex, "pid": listener.pid})
        third_status = wait_rust_listener_ready(cli_bin, bob_workspace, home, listener, timeout_seconds=45.0)
        direct_after_restart = rust_message_id(
            rust_cli_json(
                cli_bin, alice_workspace, home, "msg", "send", "--to", bob_did,
                "--text", "direct after OpenServer restart", "--secure", "off",
            )
        )
        wait_file_contains(notify_file, [direct_after_restart])

        history = rust_cli_json(cli_bin, bob_workspace, home, "msg", "history", "--with", alice_did, "--limit", "50")
        for message_id, text_value in (
            (direct_one, "realtime direct while connected"),
            (direct_offline, "direct while listener stopped"),
            (direct_after_restart, "direct after OpenServer restart"),
        ):
            assert_message_visible(history, message_id=message_id, text=text_value)
        group_messages = rust_cli_json(
            cli_bin, bob_workspace, home, "group", "messages", "--group", group_did, "--limit", "50"
        )
        assert_message_visible(group_messages, message_id=group_one, text="realtime group while connected")
        assert_message_visible(group_messages, message_id=group_offline, text="group while listener stopped")

        final_status = rust_cli_json(cli_bin, bob_workspace, home, "runtime", "listener", "status")
        if True in _json_values_for_key(final_status, "legacy_sync_used"):
            raise RuntimeError("rust cli realtime gate used legacy sync")
        print(json.dumps({
            "ok": True,
            "mode": "rust-cli-realtime-restart",
            "base_url": base_url,
            "cli_bin": cli_bin,
            "cli_artifact_sha256": artifact_sha256,
            "cli_version": cli_version.get("data"),
            "open_server": open_server_provenance(),
            "server_boots": server_boots,
            "listener_boots": listener_boots,
            "group_did": group_did,
            "message_ids": [direct_one, group_one, direct_offline, group_offline, direct_after_restart],
            "readiness_snapshots": [first_status.get("data"), second_status.get("data"), third_status.get("data")],
            "verified": [
                "foreground listener negotiated awiki.sync.changed.v2 and completed sync v2 bootstrap",
                "Direct and Group realtime dirty hints reconciled to durable local views",
                "listener downtime was recovered by sync v2 after foreground restart",
                "OpenServer outage plus supervised foreground restart recovered without legacy sync fallback",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        if listener is not None:
            stop_process(listener)
        stop_process(process)


def smoke_rust_cli_cross_domain(args: argparse.Namespace) -> int:
    if not args.inside_netns:
        unshare = shutil.which("unshare")
        ip = shutil.which("ip")
        mount = shutil.which("mount")
        if not unshare or not ip or not mount:
            raise RuntimeError("smoke-rust-cli-cross-domain requires unshare, ip, and mount")
        with tempfile.TemporaryDirectory(prefix="awiki-open-cross-netns-") as temporary:
            hosts_path = Path(temporary) / "hosts"
            shutil.copyfile("/etc/hosts", hosts_path)
            with hosts_path.open("a", encoding="utf-8") as hosts_file:
                hosts_file.write(f"\n{args.source_bind_host} {args.source_domain}\n")
                hosts_file.write(f"{args.target_bind_host} {args.target_domain}\n")
            child_command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "smoke-rust-cli-cross-domain",
                "--inside-netns",
                "--awiki-cli-bin",
                str(Path(resolve_executable(args.awiki_cli_bin)).resolve()),
                "--data-root",
                str(Path(args.data_root).resolve()),
                "--source-domain",
                args.source_domain,
                "--target-domain",
                args.target_domain,
                "--source-bind-host",
                args.source_bind_host,
                "--target-bind-host",
                args.target_bind_host,
                "--clean" if args.clean else "--no-clean",
            ]
            shell_program = 'mount --bind "$1" /etc/hosts && "$2" link set lo up && shift 2 && exec "$@"'
            completed = subprocess.run(
                [unshare, "-Urnm", "sh", "-c", shell_program, "sh", str(hosts_path), ip, *child_command],
                cwd=Path(__file__).resolve().parents[1],
                env=os.environ.copy(),
                check=False,
                capture_output=True,
                text=True,
            )
            sys.stdout.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            return completed.returncode
    cli_bin = resolve_executable(args.awiki_cli_bin)
    root = Path(args.data_root)
    if args.clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    source_domain = args.source_domain
    target_domain = args.target_domain
    source_base = f"https://{source_domain}"
    target_base = f"https://{target_domain}"
    ca_bundle, ssl_certfile, ssl_keyfile = generate_test_tls_material(root, [source_domain, target_domain])
    os.environ["SSL_CERT_FILE"] = str(ca_bundle)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    for proxy_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(proxy_name, None)
    resolver_map = {source_domain: source_base, target_domain: target_base}
    source_key = generate_ed25519_private_key_pem()
    target_key = generate_ed25519_private_key_pem()
    home = root / "home"
    alice_workspace = root / "cli-source-alice"
    bob_workspace = root / "cli-target-bob"
    cli_version = rust_cli_json(cli_bin, alice_workspace, home, "version")
    artifact_sha256 = hashlib.sha256(Path(cli_bin).read_bytes()).hexdigest()
    processes: list[subprocess.Popen] = []
    try:
        processes.append(start_open_server(
            data_dir=root / "source-server", port=443, domain=source_domain,
            private_key_pem=source_key, resolver_map=resolver_map, public_base_url=source_base,
            bind_host=args.source_bind_host, ssl_certfile=ssl_certfile, ssl_keyfile=ssl_keyfile,
        ))
        processes.append(start_open_server(
            data_dir=root / "target-server", port=443, domain=target_domain,
            private_key_pem=target_key, resolver_map=resolver_map, public_base_url=target_base,
            bind_host=args.target_bind_host, ssl_certfile=ssl_certfile, ssl_keyfile=ssl_keyfile,
        ))
        wait_health(source_base, processes[0])
        wait_health(target_base, processes[1])
        initialize_rust_cli_workspace(
            cli_bin, alice_workspace, home, base_url=source_base, did_domain=source_domain, ca_bundle=ca_bundle
        )
        initialize_rust_cli_workspace(
            cli_bin, bob_workspace, home, base_url=target_base, did_domain=target_domain, ca_bundle=ca_bundle
        )
        alice_handle = unique_handle("cross-alice")
        bob_handle = unique_handle("cross-bob")
        alice_did = rust_register_did(rust_cli_json(
            cli_bin, alice_workspace, home, "id", "register", "--handle", alice_handle,
            "--phone", china_dev_phone(), "--otp", "123456",
        ))
        bob_did = rust_register_did(rust_cli_json(
            cli_bin, bob_workspace, home, "id", "register", "--handle", bob_handle,
            "--phone", china_dev_phone(), "--otp", "123456",
        ))
        # Establish each single-device Sync v2 binding before creating remote
        # events so the test exercises delta delivery rather than a late first
        # bootstrap at the account tail.
        rust_cli_json(cli_bin, alice_workspace, home, "msg", "inbox", "--scope", "direct", "--limit", "1")
        rust_cli_json(cli_bin, bob_workspace, home, "msg", "inbox", "--scope", "direct", "--limit", "1")
        source_direct_text = "plaintext Direct source to target"
        source_direct = rust_message_id(rust_cli_json(
            cli_bin, alice_workspace, home, "msg", "send", "--to", bob_did,
            "--text", source_direct_text, "--secure", "off",
        ))
        target_inbox = wait_rust_message_visible(
            cli_bin, bob_workspace, home, "msg", "history", "--with", alice_did, "--limit", "20",
            message_id=source_direct, text_value=source_direct_text,
        )

        target_direct_text = "plaintext Direct target to source"
        target_direct = rust_message_id(rust_cli_json(
            cli_bin, bob_workspace, home, "msg", "send", "--to", alice_did,
            "--text", target_direct_text, "--secure", "off",
        ))
        source_inbox = wait_rust_message_visible(
            cli_bin, alice_workspace, home, "msg", "history", "--with", bob_did, "--limit", "20",
            message_id=target_direct, text_value=target_direct_text,
        )

        source_group = rust_group_did(rust_cli_json(
            cli_bin, alice_workspace, home, "group", "create", "--name", "Source Hosted Community",
            "--discoverability", "private", "--admission-mode", "admin-add", "--max-members", "20",
        ))
        rust_cli_json(
            cli_bin, alice_workspace, home, "group", "add", "--group", source_group,
            "--member", bob_did, "--role", "member",
        )
        source_group_members = retry_rust_cli_json(
            cli_bin, bob_workspace, home, "group", "members", "--group", source_group, "--limit", "20"
        )
        assert_active_member(source_group_members, member_did=alice_did)
        assert_active_member(source_group_members, member_did=bob_did)
        source_group_text = "source-hosted group from remote Bob"
        source_group_message = rust_message_id(rust_cli_json(
            cli_bin, bob_workspace, home, "msg", "send", "--group", source_group,
            "--text", source_group_text, "--secure", "off",
        ))
        source_group_history = wait_rust_message_visible(
            cli_bin, alice_workspace, home, "group", "messages", "--group", source_group, "--limit", "20",
            message_id=source_group_message, text_value=source_group_text,
        )

        target_group = rust_group_did(rust_cli_json(
            cli_bin, bob_workspace, home, "group", "create", "--name", "Target Hosted Community",
            "--discoverability", "private", "--admission-mode", "admin-add", "--max-members", "20",
        ))
        rust_cli_json(
            cli_bin, bob_workspace, home, "group", "add", "--group", target_group,
            "--member", alice_did, "--role", "member",
        )
        target_group_members = retry_rust_cli_json(
            cli_bin, alice_workspace, home, "group", "members", "--group", target_group, "--limit", "20"
        )
        assert_active_member(target_group_members, member_did=alice_did)
        assert_active_member(target_group_members, member_did=bob_did)
        target_group_text = "target-hosted group from remote Alice"
        target_group_message = rust_message_id(rust_cli_json(
            cli_bin, alice_workspace, home, "msg", "send", "--group", target_group,
            "--text", target_group_text, "--secure", "off",
        ))
        target_group_history = wait_rust_message_visible(
            cli_bin, bob_workspace, home, "group", "messages", "--group", target_group, "--limit", "20",
            message_id=target_group_message, text_value=target_group_text,
        )

        rust_cli_json(cli_bin, bob_workspace, home, "group", "leave", "--group", source_group)
        assert_rust_cli_fails(
            cli_bin, bob_workspace, home, "msg", "send", "--group", source_group,
            "--text", "must fail after remote leave", "--secure", "off", expected=None,
        )
        rust_cli_json(
            cli_bin, bob_workspace, home, "group", "remove", "--group", target_group,
            "--member", alice_did,
        )
        assert_rust_cli_fails(
            cli_bin, alice_workspace, home, "msg", "send", "--group", target_group,
            "--text", "must fail after cross-domain removal", "--secure", "off", expected=None,
        )

        print(json.dumps({
            "ok": True,
            "mode": "rust-cli-cross-domain",
            "cli_bin": cli_bin,
            "cli_artifact_sha256": artifact_sha256,
            "cli_version": cli_version.get("data"),
            "open_server": open_server_provenance(),
            "source": {"base_url": source_base, "domain": source_domain, "did": alice_did, "pid": processes[0].pid},
            "target": {"base_url": target_base, "domain": target_domain, "did": bob_did, "pid": processes[1].pid},
            "direct_message_ids": [source_direct, target_direct],
            "groups": {"source_hosted": source_group, "target_hosted": target_group},
            "group_message_ids": [source_group_message, target_group_message],
            "verified": [
                "two independent TLS OpenServer processes and real CLI workspaces",
                "bidirectional plaintext Direct through DID discovery and signed peer requests",
                "Community Group hosted in each domain with remote members and messages",
                "cross-domain leave/remove authorization convergence",
                "no E2EE or cross-domain attachment relay was exercised",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        for child in processes:
            stop_process(child)


def smoke_rust_cli_connect(args: argparse.Namespace) -> int:
    """Prove that a clean current CLI can configure, register, and write to Open Server.

    This deliberately remains a narrow connection-and-write check.  Inbox/history use
    Open Server's restricted single-device anp.sync.local.v2 contract and are exercised
    by smoke-rust-cli-local instead.
    """
    cli_bin = resolve_executable(args.awiki_cli_bin)
    port = args.port or free_port()
    did_domain = args.did_domain
    base_url = f"http://{did_domain}:{port}"
    root = Path(args.data_root) if args.data_root else Path(tempfile.mkdtemp(prefix="awiki-open-rust-cli-connect-"))
    if args.clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    home = root / "home"
    alice_workspace = root / "cli-alice"
    bob_workspace = root / "cli-bob"
    cli_version = rust_cli_json(cli_bin, alice_workspace, home, "version")
    artifact_sha256 = hashlib.sha256(Path(cli_bin).read_bytes()).hexdigest()
    process = start_open_server(
        data_dir=root / "server",
        port=port,
        domain=did_domain,
        private_key_pem=generate_ed25519_private_key_pem(),
        resolver_map={did_domain: base_url},
        public_base_url=base_url,
    )
    try:
        wait_health(base_url, process)
        for workspace in (alice_workspace, bob_workspace):
            initialize_rust_cli_workspace(
                cli_bin,
                workspace,
                home,
                base_url=base_url,
                did_domain=did_domain,
            )
        prefix = args.handle_prefix
        alice_register = rust_cli_json(
            cli_bin,
            alice_workspace,
            home,
            "id",
            "register",
            "--handle",
            unique_handle(f"{prefix}-alice"),
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
            unique_handle(f"{prefix}-bob"),
            "--phone",
            china_dev_phone(),
            "--otp",
            "123456",
        )
        alice_did = rust_register_did(alice_register)
        bob_did = rust_register_did(bob_register)
        sent = rust_cli_json(
            cli_bin,
            alice_workspace,
            home,
            "msg",
            "send",
            "--to",
            bob_did,
            "--text",
            "open server latest cli connection probe",
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "rust-cli-connect",
                    "scope": "connection-and-write",
                    "base_url": base_url,
                    "did_domain": did_domain,
                    "cli_bin": cli_bin,
                    "cli_artifact_sha256": artifact_sha256,
                    "cli_version": cli_version.get("data"),
                    "alice_did": alice_did,
                    "bob_did": bob_did,
                    "message_id": rust_message_id(sent),
                    "verified": [
                        "clean CLI workspaces configured the Open Server tenant",
                        "two identities registered through /user-service/v1/did-auth/rpc",
                        "plaintext Direct write completed through /im/rpc",
                    ],
                    "not_verified": [
                        "inbox/history and restricted single-device sync v2: exercised by smoke-rust-cli-local, not this narrow check",
                        "group journeys are exercised separately by smoke-rust-cli-local; attachment and realtime/restart remain separate gates",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
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
    assert caps["features"]["group_participant"]["management"] is True
    assert caps["features"]["group_participant"]["join_modes"] == ["open-join", "admin-add"]
    assert caps["features"]["cross_domain_group"] == {
        "enabled": True,
        "mode": "did_discovery_direct_call",
    }

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
    required_direct_credentials = [
        ("token", "--token", "AWIKI_INFO_TOKEN", args.token),
        ("sender_did", "--sender-did", "AWIKI_INFO_SENDER_DID", args.sender_did),
        ("recipient_did", "--recipient-did", "AWIKI_INFO_RECIPIENT_DID", args.recipient_did),
        ("origin_proof_json", "--origin-proof-json", "AWIKI_INFO_ORIGIN_PROOF_JSON", args.origin_proof_json),
    ]
    missing_credentials = [
        {"name": name, "flag": flag, "env": env}
        for name, flag, env, value in required_direct_credentials
        if not value
    ]
    credential_status = {
        name: "set" if value else "unset"
        for name, _, _, value in required_direct_credentials
    }
    credential_status["auth_scheme"] = "set" if args.auth_scheme else "unset"
    result = {
        "ok": True,
        "mode": "awiki-info-capability",
        "service_base_url": base,
        "did_domain": args.did_domain,
        "service_did": caps.get("service_did"),
        "request_shape": "capability=params.meta/body direct=params.meta/auth/body",
        "credential_status": credential_status,
        "missing_credentials": missing_credentials,
        "direct_ready": not missing_credentials,
    }
    if not missing_credentials:
        sent = anp_rpc(
            base,
            "direct.send",
            anp_params("direct.send", args, {"text": args.text}),
            args.token,
        )
        result["direct_message_id"] = sent.get("message_id")
        result["live_direct_gate"] = "passed"
    else:
        result["live_direct_gate"] = "skipped_missing_credentials"
        result["direct_skipped"] = "missing awiki.info live direct credentials; set the listed env vars or pass the listed flags"
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
        assert caps["features"]["group_participant"]["management"] is True
        assert caps["features"]["group_participant"]["join_modes"] == ["open-join", "admin-add"]
        assert caps["features"]["cross_domain_group"] == {
            "enabled": True,
            "mode": "did_discovery_direct_call",
        }
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
        group_feature = features.get("group_participant") or {}
        add_check(
            "community_group_management_enabled",
            group_feature.get("enabled") is True
            and group_feature.get("management") is True
            and group_feature.get("join_modes") == ["open-join", "admin-add"],
            group_participant=group_feature,
        )
        cross_domain_group = features.get("cross_domain_group") or {}
        add_check(
            "cross_domain_group_direct_call_enabled",
            cross_domain_group.get("enabled") is True
            and cross_domain_group.get("mode") == "did_discovery_direct_call",
            cross_domain_group=cross_domain_group,
        )
        disabled = caps.get("disabled_features") if isinstance(caps.get("disabled_features"), dict) else {}
        add_check("federation_relay_disabled", "federation_relay" in disabled, disabled_features=disabled)
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
    rust_cli.add_argument("--did-domain", default="127.0.0.1.nip.io")
    rust_cli.add_argument("--port", type=int)
    rust_cli.add_argument("--bind-host", default="127.0.0.1")
    rust_cli.add_argument("--standard-https", action="store_true")
    rust_cli.add_argument("--inside-netns", action="store_true", help=argparse.SUPPRESS)
    rust_cli.add_argument("--handle-prefix", default="rust-smoke")
    rust_cli.add_argument("--skip-attachments", action="store_true")
    rust_cli.add_argument("--clean", dest="clean", action="store_true", default=True)
    rust_cli.add_argument("--no-clean", dest="clean", action="store_false")
    rust_cli.set_defaults(func=smoke_rust_cli_local)

    rust_cli_realtime = sub.add_parser("smoke-rust-cli-realtime-restart")
    rust_cli_realtime.add_argument("--awiki-cli-bin", default=os.environ.get("AWIKI_CLI_BIN", "awiki-cli"))
    rust_cli_realtime.add_argument("--data-root", default="/tmp/awiki-open-server-rust-cli-realtime")
    rust_cli_realtime.add_argument("--did-domain", default="127.0.0.1.nip.io")
    rust_cli_realtime.add_argument("--port", type=int)
    rust_cli_realtime.add_argument("--clean", dest="clean", action="store_true", default=True)
    rust_cli_realtime.add_argument("--no-clean", dest="clean", action="store_false")
    rust_cli_realtime.set_defaults(func=smoke_rust_cli_realtime_restart)

    rust_cli_cross = sub.add_parser("smoke-rust-cli-cross-domain")
    rust_cli_cross.add_argument("--awiki-cli-bin", default=os.environ.get("AWIKI_CLI_BIN", "awiki-cli"))
    rust_cli_cross.add_argument("--data-root", default="/tmp/awiki-open-server-rust-cli-cross-domain")
    rust_cli_cross.add_argument("--source-domain", default="source.open.test")
    rust_cli_cross.add_argument("--target-domain", default="target.open.test")
    rust_cli_cross.add_argument("--source-bind-host", default="127.0.0.2")
    rust_cli_cross.add_argument("--target-bind-host", default="127.0.0.3")
    rust_cli_cross.add_argument("--inside-netns", action="store_true", help=argparse.SUPPRESS)
    rust_cli_cross.add_argument("--clean", dest="clean", action="store_true", default=True)
    rust_cli_cross.add_argument("--no-clean", dest="clean", action="store_false")
    rust_cli_cross.set_defaults(func=smoke_rust_cli_cross_domain)

    rust_cli_connect = sub.add_parser("smoke-rust-cli-connect")
    rust_cli_connect.add_argument("--awiki-cli-bin", default=os.environ.get("AWIKI_CLI_BIN", "awiki-cli"))
    rust_cli_connect.add_argument("--data-root", default="/tmp/awiki-open-server-rust-cli-connect")
    rust_cli_connect.add_argument("--did-domain", default="127.0.0.1.nip.io")
    rust_cli_connect.add_argument("--port", type=int)
    rust_cli_connect.add_argument("--handle-prefix", default="rust-connect")
    rust_cli_connect.add_argument("--clean", dest="clean", action="store_true", default=True)
    rust_cli_connect.add_argument("--no-clean", dest="clean", action="store_false")
    rust_cli_connect.set_defaults(func=smoke_rust_cli_connect)

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
