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
- `federation` is declared disabled.

## Files

- `awiki-open-server.env.example`: environment variables for a real deployment.
- `awiki-open-server.service.example`: systemd unit that binds Uvicorn to localhost.
- `nginx-rwiki.cn.conf.example`: nginx TLS proxy that exposes only the public routes needed by clients and DID discovery.

## Deployment Checklist

1. Install the repository under a release path such as `/opt/awiki-open-server`.
2. Create a private env file from `deploy/awiki-open-server.env.example`.
3. Generate and protect an Ed25519 service private key outside the repository.
4. Start the app on `127.0.0.1:8766`.
5. Configure nginx with routes from `deploy/nginx-rwiki.cn.conf.example`.
6. Run `nginx -t` and reload nginx.
7. Run `verify-public`.
8. Configure one Rust CLI workspace for `https://rwiki.cn` and another for `https://awiki.info`.
9. Register a test user on each side and verify direct send, inbox, and history in both directions.

If step 9 fails after `verify-public` passes, record the request direction, sender DID,
recipient DID, target URL, RPC error body, and service logs before changing any sibling
service.
