# AWiki Open Server Client Compatibility

[English](client-compatibility.md) | [简体中文](client-compatibility.zh-CN.md)

Last reviewed: 2026-07-16. Record a specific client version/commit, server commit, and verification date.

## 1. Overview

| Client/peer | Position | Known capabilities | Key limitations |
| --- | --- | --- | --- |
| `awiki-cli` | Primary compatibility client | Local registration, Direct, complete Community Group v1 lifecycle, People, Site, Attachment | No E2EE or large-group/complex governance; registration contact arguments preserve compatibility shape only. |
| AWiki Me | Basic product compatibility target | Identity/messages/attachments on a custom tenant require continuous validation | Agent realm allowlist, no E2EE, and no claim of every app feature. |
| Other ANP peer | Selected public methods | Capability, Direct, selected Group/Attachment | Not complete federation; origin proof and service signature required. |
| Legacy AWiki client | Compatibility routes | User/Message Service-shaped routes | Shims are not production identity providers or a complete hosted platform. |

## 2. awiki-cli

Repository and public gates cover DID registration; Direct send, Inbox, and History; Group create/get/list/add/join/members/update/send/messages/leave/remove in both host directions; People follow/status/following/followers; Site root/pages; and attachments as implemented.

```bash
awiki-cli tenant setup community \
  --backend-base-url https://community.example.com \
  --did-host community.example.com
awiki-cli init
```

Do not use `--secure required` or treat the Contact Verification development shim as real SMS/email. Group admission is immediate-active `group.add` or `group.join`; clients must not expect invitation tokens, join codes, pending membership, or an accept-invite command.

## 3. AWiki Me

A basic tenant needs a reachable backend base URL, matching DID host, compatibility routes for the app version, reachable attachment URLs/tickets, and matching WebSocket route/ticket flow.

Verify registration/login; Direct send/receive/history; unread/read; Group create/add/join/update/send/messages/leave/remove; attachment send/download/open; People/Contact/Profile; and app restart/local sync recovery.

### Agent/Daemon limitation

AWiki Me enables Agent/Daemon APIs only for `awiki.ai`, `awiki.info`, and `anpclaw.com`. A normal self-hosted domain may support login and messages while the Agent page remains unsupported. Open Server compatibility routes do not bypass the app realm policy.

### E2EE

Open Server implements neither Direct nor Group E2EE. AWiki Me must treat it as a non-E2EE tenant and must not show a misleading end-to-end-encrypted state.

## 4. Public ANP methods

Public `/anp-im/rpc` exposes `anp.get_capabilities`, `direct.send`, the Community Group Host methods (`group.create/get_info/join/add/remove/rebind_member/leave/update_profile/update_policy/send`), the `group.incoming` and `group.state_changed` Notifications, and `attachment.get_download_ticket`. Local `/im/rpc` additionally contains Inbox, History, Sync, Read State, local Group views, and attachment-control methods. Do not expose all local compatibility RPC as a cross-domain contract.

## 5. Meaning of compatibility routes

User Service/Message Service-shaped routes are implemented locally and do not proxy `awiki.info`. They let current clients reuse existing shapes, provide local profile/token/DID/relationship/message entry points, return `contact_verification_not_enabled` when appropriate, and provide local verification headers for integrations such as Nginx `auth_request`.

Compatibility does not mean a complete hosted platform, production identity provider, complete Agent orchestration, large-group/complex governance, or permanent compatibility with every future client.

## 6. Verification record

```text
Date: YYYY-MM-DD
Open Server commit/version:
Client name/version/commit:
Domain/base URL:
ANP SDK version:

Passed:
- identity
- direct
- inbox/history
- read/sync
- Community Group v1 lifecycle and both cross-domain host directions
- attachment
- people/profile/site
- websocket/restart

Limitations/failures:
- agent
- secure
- large-group/complex governance
- ...
```
