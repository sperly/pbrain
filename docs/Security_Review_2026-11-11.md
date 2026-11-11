# PocketBrain security review — 11 November 2026

Scope: the current PHP/MariaDB backend, dashboard, Python desktop client, ESP32
source and generated build configuration. Public deployment checks were limited
to unauthenticated HTTP/HTTPS requests to peabrain.se. No production credentials,
private transcripts, paid API calls, load testing, or production writes were used.
This is a source review with targeted reproductions, not a penetration-test
certification. No application security fixes were made during this review.

## Priorities

| ID | Priority | Finding | Evidence level |
|---|---|---|---|
| S1 | High | Issued Realtime secrets bypass application usage limits | Code + official provider behavior; no paid exploit attempted |
| S2 | High for physical deployment | Device credentials, Wi-Fi secrets and cached conversations lack storage protection | Source and generated build configuration; no physical extraction attempted |
| S3 | Medium | Clear/unlink leaves recoverable audio/history in flash | Reproduced with actual journal code and synthetic data |
| S4 | Medium | A delayed first-turn save can resurrect a deleted thread | Reproduced through PHP/MariaDB API in isolated containers |
| S5 | Medium | No account storage quota; anonymous rate-limit keys can grow database state | Code + isolated reproductions |
| S6 | Medium, depending on access path | Live HTTPS responses lack HSTS | Confirmed on a normal unauthenticated HTTPS GET |

High here means a priority for wider deployment under the stated prerequisites;
it does not mean an unauthenticated attacker can currently steal every account.

## S1 — Realtime credentials do not enforce a spending/session budget

Evidence: `backend/app/realtime.php:24` issues a client secret with a 60-second
expiry. `backend/public_html/api.php:78` rate-limits issuance, but audio sessions
then go directly from the client to OpenAI. There is no backend-enforced session
count, session duration, token consumption budget, or account spending cutoff.

Attack prerequisite: a valid paired device credential (for example, stolen from
a device) or access to a legitimately issued Realtime secret. A modified client
can skip the simulator/firmware's recording and response limits. One issued
secret can create multiple sessions before expiry, and established sessions can
continue after the secret expires. Existing sessions are not terminated by the
backend's device revocation. Actual usage is still subject to upstream account
and provider limits; no cost amount was measured.

The billing victim is the owner of the selected API key. When shared billing is
explicitly enabled, that can be the site owner. A short secret TTL and rate limits
on token issuance alone do not provide a spending ceiling.

Recommended fix: make billing/session control a server responsibility. Evaluate
a server-controlled session/proxy architecture, or a controlled session setup
that allows the server to observe and terminate sessions. Add concurrent-session
limits, account budgets, usage reconciliation, and operational alerts. Keep
shared billing disabled until this boundary is addressed. Reducing the TTL can
reduce credential replay opportunity but does not solve the underlying problem.
Do not treat client instructions or max-output settings mutable by clients as
an authorization boundary.

Official behavior:
- [Realtime client secrets](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets/methods/create): expiration governs creating sessions; secrets can create multiple sessions and existing sessions continue afterward.
- [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations): session parameters are generally client-updatable, and sessions can last up to 60 minutes.

## S2 — Physical device access can become account access

Evidence: `embedded/main/storage.c:149` writes the bearer credential into NVS;
`embedded/main/network.c:52` persists saved Wi-Fi profiles as an NVS blob.
Recordings and cached text use raw journal partitions through
`embedded/main/storage.c:17`. `embedded/partitions.csv` has no encrypted flags
on the pending/history partitions. The reviewed `embedded/sdkconfig` has secure
boot, flash encryption, and NVS encryption disabled (lines 464–465 and 2296).
The defaults do not establish a protected release configuration.

Attack prerequisite: physical access sufficient to read/reflash an unprotected
unit. Such access can expose Wi-Fi credentials, the device bearer credential,
cached text, and pending audio. The bearer credential is long-lived until revoked
and intentionally has account-wide history access: it can read/delete the owner's
threads and request paid voice/search operations. It cannot directly retrieve
the owner's raw OpenAI key through the existing API.

Recommended fix: create and validate a production ESP32 security profile covering
secure boot, flash/NVS encryption, encrypted custom data partitions, and download/
debug interfaces. Provision unique secrets and protect signing/encryption keys.
These settings require a deliberate hardware provisioning process; do not
indiscriminately burn production eFuses on development boards. Verify actual
hardware eFuse state separately; repository configuration does not establish it.
Consider credential rotation and more granular device permissions where useful.

Related desktop exposure: `desktop/store.py:35` serializes device credentials,
transcripts, and pending recordings as plaintext JSON. POSIX file creation is
private (mkstemp files and a 0700 state directory), which is good, but same-user
malware or copied backups can still expose them. An OS credential store and
optional cache encryption reduce that exposure. This is not evidence of a
remote file-read vulnerability.

## S3 — Clear/unlink is a tombstone, not a secure erasure

Evidence: `embedded/main/app_main.c:214` clears pending/history with
`pb_blob_save(..., NULL, 0)`. `embedded/components/pb_core/pb_journal.c:65` writes
a new empty journal generation in the other slot, erasing only its header
sector. The previous slot and old payload bytes remain. CRCs provide corruption
detection, not confidentiality.

Reproduction: compile the real journal/core sources with in-memory flash
callbacks. Save a synthetic private-recording marker, then write an empty
record. The public read reports EMPTY, but scanning the partition still finds
the marker. Corrupting the newest empty header makes the previous valid record
readable through the normal journal API again. Both observations were confirmed.

Impact: discarded recordings and unlinked-account history can remain recoverable
by someone with raw flash access, including after transferring the unit. Header
corruption can also resurrect an old journal generation.

Recommended fix: separate crash-safe transactional deletion from privacy erasure.
Design a full-partition erase flow for unlink/reset that accounts for both slots
and stale tails, with explicit power-loss behavior. For routine discarded audio,
consider encrypting records with erasable per-record/per-owner keys, while
accounting for key remnants in NVS. Encryption and retention/deletion need to be
designed together. Add tests that inspect raw storage after privacy deletion.

## S4 — A retry can restore a deleted conversation

Evidence: `backend/app/conversations.php:163` checks idempotency only in live
`conversation_turns`. Deleting a thread cascades away those rows. At line 180,
a retry of the original first-turn body (`conversation_id: null`) consequently
looks like a brand-new request and creates another thread.

Reproduced API sequence in an isolated database:

1. Save a first turn with a new `client_turn_id` and null conversation ID: 201.
2. Delete its returned conversation ID: 200.
3. Retry the unchanged original save: 201 with a different conversation ID.

Impact: deletion does not reliably keep the transcript deleted when another
client has a pending upload, a lost acknowledgement, or a delayed retry. It is a
privacy/data-integrity issue within one account, not a cross-account access bug.

Recommended fix: retain minimal idempotency/deletion receipts separately from
the transcript, bound to owner/device/turn UUID. A replay referencing a deleted
record should fail with a defined deleted response (for example 410), rather
than create another thread. Establish a retry retention period, and ensure the
client asks the user before resubmitting in a new thread.

## S5 — Request rate limits do not bound storage growth

Authenticated case: `backend/public_html/api.php:109` permits 120 history
operations per minute per device. A saved turn can carry 32 KiB of question plus
32 KiB of reply; `saveConversationTurn()` has no total-turn, thread-count, or
account-byte quota. One paired device can therefore submit roughly 450 MiB of
transcript per hour at its steady-state limit, before indexes/overhead, subject
to runtime/hosting throughput. A single 65,536-byte save was accepted in the
isolated reproduction; no sustained flood was attempted.

Anonymous case: `backend/public_html/api.php:53` creates a limiter bucket for
any syntactically valid polling secret before checking whether it exists.
`backend/app/bootstrap.php:130` inserts those keys. Five distinct unknown poll
secrets created six limiter rows (five secret buckets plus the IP bucket) in the
isolated reproduction. IP limits restrict a single source, but distributed
sources can continuously add buckets/pairing rows. Cleanup is only a documented
manual/scheduled action, not something configured by the application.

Impact: a malicious invited account, stolen device credential, or distributed
anonymous traffic can put pressure on a shared database/hosting account. The
anonymous vector is slower per source and is not an authentication bypass.

Recommended fix: enforce account byte/turn quotas, maximum device counts, and
appropriate per-account write limits. Add bounded limiter storage and automatic
cleanup/monitoring. Consider applying a coarse IP limiter before looking up a
polling secret, then allocate per-secret state only for an actual pending
pairing. Add upstream request/concurrency/body limits at the host as well.

## S6 — HSTS is missing from the live response

The live site passed TLS certificate validation and redirects HTTP to HTTPS.
A normal HTTPS GET returned 200 with CSP, `Referrer-Policy: no-referrer`,
`X-Content-Type-Options: nosniff`, and a Secure/HttpOnly/SameSite=Lax cookie.
It did not include `Strict-Transport-Security`.

A redirect alone does not protect an initial HTTP visit against an attacker
able to modify that connection. That attacker can substitute a counterfeit
sign-in page. This depends on the browser's existing HTTPS-upgrade/preload state;
no such interception was performed.

Recommended fix: add HSTS at the hosting layer, beginning with an appropriate
rollout max-age and increasing it after checking HTTPS reliability. Include
subdomains only after verifying all affected subdomains support HTTPS. HSTS
protects future visits after policy receipt; preload is a separate decision.

## Additional hardening and deployment questions

- Dashboard sessions can last 12 hours (`index.php:116`). API-key changes and
  pairing approval require CSRF but no fresh password/MFA. There is no user-facing
  global session revocation. A stolen authenticated browser session therefore
  enables reading transcripts and linking an attacker-controlled device for
  persistence. Require fresh authentication for sensitive changes and add session
  management; this assumes an already-compromised session, not a demonstrated
  authentication bypass.
- The local unlink action deliberately does not revoke the server credential.
  The desktop warns about this, but transferring hardware should guide the owner
  through server revocation as well as local data erasure. Recoverable old bearer
  tokens remain usable until revoked.
- Search output and old transcripts are untrusted model input. Instructions to
  ignore page instructions reduce risk but do not prove prompt-injection
  resistance. Answer manipulation, phishing links, or private context included in
  later search queries remain design risks; no successful model-based exploit
  was tested. Avoid passing unnecessary sensitive history and keep tool access
  tightly scoped. Fixed HTTP destinations are a useful existing control.
- API-key encryption protects against a database-only leak, not a compromised
  PHP account plus private `config.php`. Verify private configuration/backups are
  outside the document root, file permissions are restricted, PHP display_errors
  is off, and request bodies/Authorization headers are not logged. Those hosting
  details were not independently established in this review.
- Dependency advisories, PHP/MariaDB host patching, backup access/retention, and
  real device debug/eFuse settings need a separate deployment/dependency audit.
  No claim is made that dependencies are free of known vulnerabilities.

## Controls that held in this review

The existing isolation, CSRF, encrypted-key tamper/owner-binding, stored-HTML
escaping, and revoked-device checks passed in the integration suite. SQL values
are parameterized; the dynamic pagination offset is validated as digits. Source
links escape HTML and use noopener/noreferrer, and CSP blocks scripts/frames.
Server-side HTTP lookup targets are fixed and redirects are disabled. API keys
are encrypted with authenticated encryption and never returned to devices.
No cross-account transcript access, SQL injection, stored XSS, or arbitrary-URL
server fetch was demonstrated in the reviewed paths. This is a scoped finding,
not a guarantee of their absence elsewhere.

Validation: 33 existing PHP/MariaDB integration checks plus three synthetic audit
reproductions completed. The journal raw-data/deletion test was compiled against
the real C implementation. The audit reproductions intentionally confirmed
unwanted behavior: their successful assertions are not a security pass. Public
headers were checked with unauthenticated requests only. Application source was
left unchanged; this report is the only project artifact added by the review.
