# AWiki Community Group v1 Release Gate Report

Date: 2026-07-16 (Asia/Shanghai)

This report records redacted, reproducible release evidence for Community Group v1. It intentionally excludes access/refresh/operations tokens, private keys, complete origin proofs, HTTP Signatures, Group Receipt proofs, and message bodies.

## 1. Components

| Component | Evidence version |
| --- | --- |
| Open Server | worktree based on `77874af854e092a9fcfc09bb9d8d874faac77043` |
| Message Service | worktree based on `0c24af337574d87cb951da883122d58c37670d7b` |
| Rust CLI / SDK | `dev`, source HEAD `9d7edf2313b76613dae8857992f949638b950c53` |
| ANP Python SDK | pinned `0.8.8`, verified through `PYTHONPATH=../anp/anp:src` |
| Public services | `https://rwiki.cn` and `https://awiki.info` |

The worktrees contain the implementation under test, so the baseline commit alone is not a release artifact identifier. A release commit/tag should be recorded when these changes are committed.

## 2. Public Discovery Gate

`verify-public` passed against `https://rwiki.cn` with all checks true:

- service DID `did:wba:rwiki.cn`;
- one `ANPMessageService` at `https://rwiki.cn/anp-im/rpc`;
- `bearer` and `didwba` auth schemes;
- Direct and Group DID-discovery direct-call modes enabled;
- Community Group management enabled with `open-join` and `admin-add`;
- federation relay, Direct/Group E2EE, Group HA, and large-group fanout disabled.

The public system suite passed `2/2` tests over public HTTPS.

## 3. Direction A: rwiki.cn Group Host

Run ID: `community-group-public-gate-20260716-direction-a`

Group DID:

```text
did:wba:rwiki.cn:groups:grp_UBcWVjvyAlg4YKd_:e1_51XgrwYXaGGLgOY4kxJY45gB-Bv55YDiZNn4KwVdvtI
```

Participants:

| Role/path | Agent DID | Final status |
| --- | --- | --- |
| owner | `did:wba:rwiki.cn:gate-rwiki-owner-214516:e1_w0ouaU2f8ODenvDGzX1g-RT2Utu1q9lSu_qtgp5hw7M` | active |
| remote `group.add` member | `did:wba:awiki.info:gate-awiki-add-214703:e1_qDS4mcWQfsaGd_xGzEehK3rjE937Tw94chKZNryju5s` | removed |
| remote `group.join` member | `did:wba:awiki.info:gate-awiki-join-214703:e1_2fJHrgszqPKxvxQ6Sx67zEEoC4fjuGEu3MfRpRU0E4M` | left |

Authoritative event sequence:

| Seq | Method | Resulting state version |
| --- | --- | --- |
| 1 | `group.create` | 1 |
| 2 | `group.add` (immediately active) | 2 |
| 3 | `group.update_profile` | 3 |
| 4 | `group.update_policy` to open-join | 4 |
| 5 | `group.join` (immediately active) | 5 |
| 6 | owner-domain `group.send` | 5 |
| 7 | remote-domain `group.send` | 5 |
| 8 | `group.leave` | 6 |
| 9 | `group.remove` | 7 |

Message evidence:

| Seq | Message ID | Operation ID |
| --- | --- | --- |
| 6 | `msg-gate-a-owner-1784209737219560237` | `op-18df38c18879b9d5` |
| 7 | `msg-gate-a-awiki-20260716-2212` | `op-gate-a-awiki-20260716-2212` |

All 9 authoritative Group Receipts passed public Group DID Document signature verification, Group DID/event binding, and `sha-256=:...:` digest verification. All 10 remote outbox deliveries are `delivered`; pending, retry, and dead are zero.

## 4. Direction B: awiki.info Group Host

Run ID: `community-group-public-gate-20260716-direction-b-final`

Group DID:

```text
did:wba:awiki.info:groups:1a25669ca9404dcfb37e3c587a655280:e1_UC0Ltm-QP_Qk0AbZf964XzUZzh4EdGjRNrVEMjGnioE
```

Participants:

| Role/path | Agent DID |
| --- | --- |
| owner | `did:wba:awiki.info:gate-awiki-owner-214703:e1_PcibLGfZBy8wpzxrsHw7meiFSQoasXOph-sVSFaF4s8` |
| `group.add` member | `did:wba:rwiki.cn:gate-rwiki-add-v3-143936:e1_YVEq3LiEU7m89rWhHCDZmLJ8jrNBWRdP1jgai_7CFGY` |
| `group.join` member | `did:wba:rwiki.cn:gate-rwiki-join-v3-143936:e1_tgGRt8SsIC5qezwwi-_8xg6M8uJVDJPl4bMMaiF7t7A` |

The final event lifecycle is create, immediately-active add, profile update, policy update to open-join, immediately-active join, two cross-domain messages, leave, and remove at event sequences 1 through 9.

Message evidence:

| Seq | Direction | Message ID | Operation ID |
| --- | --- | --- | --- |
| 6 | `rwiki.cn -> awiki.info` | `msg-18dca7333adf56e5` | `op-18dca7333adf3624` |
| 7 | `awiki.info -> rwiki.cn` | `msg-18dca72c50501569` | `op-18dca72c504fed6e` |

Member-home evidence:

- two local member projections contain four message rows representing two unique canonical message IDs;
- event sequences 6 and 7 are preserved in both member projections;
- all four projected Message Home Receipts pass public Group DID signature, message/event binding, and digest-format verification;
- the added member sync contains state events 2-5, messages 6-7, and the member-visible leave event 8;
- both terminal send attempts return `group.not_member` after leave/remove;
- final group-related warning/error count is zero.

Earlier `v3` and `v4` artifacts remain under the isolated gate root as failure/regression evidence for the receipt digest and Notification Signed Request Object fixes. They are not treated as the final passing Gate.

## 5. Automated Verification

| Scope | Result |
| --- | --- |
| Open Server focused protocol/route/User/Group/sync tests | passed |
| Open Server complete pytest suite | `87 passed, 2 skipped` |
| Public rwiki.cn system suite | `2 passed` |
| Two-server projection/open-join plus three-domain recovery tests | `3 passed` |
| Message Service `im-app` | `27 passed` |
| Message Service `im-crypto` | `9 passed` |
| Message Service `im-group` | `67 passed` |
| Message Service workspace check | passed |
| Rust `awiki-im-core` | `522` unit tests plus all integration/doc tests passed |
| Rust CLI build | passed |
| AWiki Me full real E2E | run `20260716160440-hkgadmzr4g`, `16/16 passed` |

The two skipped default-suite tests are the opt-in public system tests; they were run separately with `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1` and passed.

## 6. Operations and Security

- `/operations/status` is configured through `AWIKI_OPERATIONS_TOKEN_FILE` outside the repository.
- The operations secret file is owned by the service user and has mode `0600`.
- Missing and invalid authorization return `401`; valid authorization returns aggregate-only diagnostics.
- `/healthz` remains `{"status":"ok","edition":"community"}` and exposes no operator diagnostics.
- Current aggregate outbox state is 0 pending, 0 retry, 10 delivered, and 0 dead; worker heartbeat is current.
- Production SQLite `PRAGMA integrity_check` is `ok`; foreign-key violations are zero.
- No tracked SQLite, database, PEM/key, operations token, group-key, or object artifact was found.
- No private-key PEM marker was found in the repository worktree.
- Service logs after deployment contain no warning/error/traceback and no searched token/proof/signature markers.
- `awiki-plan` remains present but disabled (`enabled = false`); it was not deleted or enabled.

## 7. Remaining Product Limits

Community v1 remains a small-scale, single-process SQLite service. It has no Direct/Group E2EE or MLS, federation relay/peer-route mesh, HA, multi-region replication, large-group/high-concurrency fanout, external realtime bus, production SMS/email verification, complex governance, or cross-domain object relay.
