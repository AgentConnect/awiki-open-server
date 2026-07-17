# Public Deployment Notes

These files are examples for publishing this repository as `https://rwiki.cn`.
They are not meant to be copied into the repository with real secrets.

## Required Boundary

`rwiki.cn` must point to `awiki-open-server` itself. It must not proxy to
`awiki.info`, `user-service`, or `message-service`.

The public checks that must pass before testing against online `awiki.info` are:

```bash
PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public \
  --base-url https://rwiki.cn \
  --did-domain rwiki.cn
```

That command verifies:

- `GET /.well-known/did.json` is served by this process.
- The service DID is `did:wba:rwiki.cn`.
- The DID document contains exactly one `ANPMessageService`.
- The `ANPMessageService.serviceEndpoint` is `https://rwiki.cn/anp-im/rpc`.
- `/healthz` responds with `status=ok`.
- `/anp-im/rpc` responds to `anp.get_capabilities`.
- Cross-domain Group is declared as DID-discovery direct-call mode; federation
  relay and peer-route infrastructure remain disabled.
- Contact-verification compatibility remains disabled; no phone/email provider
  or Aliyun integration is configured.

## Files

- `awiki-open-server.env.example`: environment variables for a real deployment.
- `awiki-open-server.service.example`: systemd unit that binds Uvicorn to localhost.
- `nginx-rwiki.cn.conf.example`: nginx TLS proxy that exposes only the public routes needed by clients and DID discovery.
- `install-rwiki-cn-service.sh`: idempotent helper that writes the env file,
  systemd unit, and nginx `rwiki.cn` config, then enables and restarts the
  service. It contains no real private key material; it generates a private key
  only when the target key file is missing.

## Deployment Checklist

1. Install the repository under a release path such as `/opt/awiki-open-server`.
2. Create a Python virtual environment, then install the app so pinned
   dependencies, including `anp==0.8.8`, are installed:

   ```bash
   cd /opt/awiki-open-server
   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   ```

3. Create a private env file from `deploy/awiki-open-server.env.example`.
4. Generate and protect an Ed25519 service private key outside the repository.
5. Keep `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false` for public service.
6. Keep `AWIKI_ALLOW_UNSIGNED_PEER_DEV=false`; local user DID documents should
   be e1 DIDs under `AWIKI_DID_DOMAIN`, and uploaded DID documents should carry
   proof.
7. Create a separate random operations token outside the repository, protect it
   as mode `0600`, and set only `AWIKI_OPERATIONS_TOKEN_FILE` in the env file.
8. Confirm attachment and Group limits in the env file:
   `AWIKI_MAX_ATTACHMENT_BYTES` and `AWIKI_ATTACHMENT_ALLOWED_MIME_TYPES`.
9. Start the app on `127.0.0.1:8766`.
10. Configure nginx with routes from `deploy/nginx-rwiki.cn.conf.example`.
11. Confirm every `proxy_pass` targets `127.0.0.1:8766`; `awiki.info` is only a
   remote interoperability peer, not a backend.
12. Run `nginx -t` and reload nginx.
13. Run `verify-public`.
14. Verify `/operations/status` returns `401` without its bearer token, returns
    aggregate diagnostics with the token, and that `/healthz` stays minimal.
15. Configure isolated Rust CLI workspaces for `https://rwiki.cn` and `https://awiki.info`.
16. Verify Direct plus both Group Host directions, including create/add/join,
    profile/policy changes, bidirectional messages, projection, leave, remove,
    outbox retry, and receipt validation.

If the interoperability gate fails after `verify-public` passes, record the request direction, sender DID,
recipient DID, target URL, RPC error body, and service logs before changing any sibling
service.

## Current rwiki.cn Server Notes

On the current shared server, PyPI access returned SSL EOF while creating an
isolated venv. The installed systemd service therefore sets `PYTHONPATH` so the
process loads the sibling ANP SDK checkout first:

```bash
<workspace>/anp/anp:<workspace>/awiki-open-server/src:<python-user-site-packages>
```

This was verified to load ANP SDK `0.8.8`. A cleaner production deployment can
switch back to `.venv/bin/python` once `pip install -e .` can install
`anp==0.8.8` normally.
