# PocketBrain PHP backend

This build provides the MariaDB connection, first-admin setup, a browser
dashboard for accounts and invitations, and owner-managed device pairing.
It includes device authentication and an authenticated Realtime client-secret
endpoint, personal OpenAI API keys, shared conversation history, and retry-safe transcript saving.

## Install

1. Use PHP 8.4 with PDO, pdo_mysql, OpenSSL, cURL, and sessions. Use a dedicated MariaDB
   database and application user. The runtime uses SELECT, INSERT, UPDATE
   and DELETE. Use your hosting panel or a separate setup account for DDL.
2. On a new database, import `sql/001_initial.sql`,
   `sql/002_auth_rate_limits.sql`, and `sql/003_user_openai_keys.sql` in order.
   On existing databases, import only migrations that have not run. If you
   originally imported `PocketBrain_MariaDB_Setup.sql`, that covers migration 001.
3. Copy config.example.php to config.php and set the database connection
   and public HTTPS URL. For a subdirectory deployment, include that
   path in base_url. Generate app_key once and keep it private:

       php -r 'echo bin2hex(random_bytes(32)), PHP_EOL;'

4. Set the site's document root to the public_html/ directory, or map just
   that directory to the configured URL. Keep config.php, app/, bin/,
   and sql/ outside the served directory. Restrict config.php to the
   account that runs PHP and turn off PHP display_errors on the site.
5. Set up HTTPS at the web server. PHP must receive HTTPS=on or HTTPS=1
   from the server on secure requests. If TLS terminates on a reverse
   proxy, configure this on the trusted server side. The backend uses
   REMOTE_ADDR for rate limits, so configure the server to resolve the
   real client address through trusted proxies if applicable. Device
   requests must also pass the Authorization header to PHP. Upload the included
   `public_html/.htaccess` as well (file managers may hide dotfiles); it preserves
   bearer headers on Apache CGI/FastCGI hosting with mod_setenvif. PHP also accepts
   `REDIRECT_HTTP_AUTHORIZATION` and the native request-header API when available.
   If the host still strips the header, ask it to enable `CGIPassAuth On` or the
   equivalent forwarding setting. A successful `pair-start` followed by
   `pair-poll` returning HTTP 401 / `invalid_polling_secret` with the returned
   secret indicates a header-forwarding problem, rather than code expiry.
6. Run the bootstrap from the package directory. It prompts for a password
   without echo on a Unix terminal and refuses a second bootstrap admin.

       php bin/create-admin.php you@example.com

7. Open the HTTPS URL and sign in. Create an invitation and copy the link
   while it is shown. Open it in a private browser window to test signup
   as a member.

Invitation URLs carry a short-lived bearer token in the query string.
Configure access logs for this site to omit query strings and authorization
headers. The browser redirects to a clean URL after opening an invite. The
database stores token digests. The admin page displays each raw invite
link only on the first dashboard load after creation.

## Enable Realtime voice

Each user signs in to the dashboard and saves an OpenAI API key under
**My OpenAI API key**. The account's linked devices use that key for Realtime.
The model is controlled by `openai_realtime_model` in the private config.
The backend checks the key's format on save; permissions, model access, and
available credits are checked when the next voice request reaches OpenAI.
Create a dedicated project key at https://platform.openai.com/api-keys and check
credits/billing in the API Platform. This uses API access rather than a ChatGPT
password or session. Eligible ChatGPT Pro/Business subscriptions can currently
claim credits for a linked API organization; see the official documentation:
https://developers.openai.com/api/docs/guides/chatgpt-api-credits.

Keys are encrypted with AES-256-GCM, a random nonce, and a purpose-derived key
from the private `app_key`. Authentication binds each ciphertext to its user ID.
The dashboard displays only whether a key is saved and its update time. It never
returns the secret to the browser after saving, or sends it to a device. The
server can decrypt it to request the short-lived device credential. Keep
`app_key` stable and back it up separately from database backups: changing or
losing it makes saved API keys unreadable. Keep request bodies out of web/APM
logs and keep PHP `display_errors` off on the host.

**Upgrade existing installations:** Import `sql/003_user_openai_keys.sql` once,
then upload `app/openai_keys.php`, `app/realtime.php`, and the updated
`public_html/index.php` and `public_html/api.php` together. Keep private config
and existing data. Users can then add keys without editing server configuration.
Removing a key stops its use for new requests through this backend; it does not
revoke the key at OpenAI or invalidate credentials already issued. Users should
revoke old keys in the API Platform when replacing them.

**Shared billing is disabled by default**, including on existing deployments
with only `openai_api_key` configured. To deliberately retain site-funded voice
for users without a personal key, set these entries in the private config:

```php
'allow_shared_openai_key' => true,
'openai_api_key' => 'YOUR_SITE_PROJECT_KEY',
```

A saved personal key always takes precedence. A corrupt, rejected, or
quota-limited personal key never falls back to the shared account. The
dashboard states when shared billing is available for an account with no
personal key. Removing a personal key then returns that account to shared
billing. Leave the setting false when every user should supply their own key.

A paired device calls POST /api.php?action=realtime-secret with its device
credential in the Authorization bearer header. The response contains
value, expires_at (Unix seconds), and model. The backend requests a
60-second client secret. The device uses it to open a direct Realtime
connection. The long-lived OpenAI API key stays in PHP.

## peabrain.se linking configuration

The production base URL is **https://peabrain.se**. Set the following entry in the
**deployed private** `config.php`, keeping its existing database credentials,
application key and OpenAI key:

```php
'base_url' => 'https://peabrain.se',
```

The local private file and example now use this URL; a local edit does not update
the hosted copy. Pair-start should return
`https://peabrain.se/index.php#devices` as `verification_uri`. If it still returns
`pocketbrain.example.com`, update the hosted private file before linking a device.
The same setting controls invitation URLs.

The ESP32 defaults to this host. Provision Wi-Fi, choose **Link account**, then sign
in at the displayed address and enter the code under **My devices**. The firmware
shows a countdown, supports Talk-to-cancel, and stores its credential after approval.

## Pair a test device

Set BASE to your configured HTTPS URL without a trailing slash. Treat the
returned polling secret and device credential as private.

    BASE=https://peabrain.se
    curl -i -X POST "$BASE/api.php?action=pair-start"

The response is 201 with an eight-character code, a polling_secret,
verification_uri, expires_in, and poll_interval in seconds. Enter the
displayed code under **My devices** while signed in to the owner account.
A fresh pairing is valid for five minutes.

    read -r -s -p 'Polling secret: ' POLLING_SECRET; printf '\n'
    curl -i -X POST "$BASE/api.php?action=pair-poll" \
      -H "Authorization: Bearer $POLLING_SECRET"

The response is 202 while approval is pending, 200 with
device_credential after approval, or 404 for an expired or unknown
pairing. The same secret can fetch the same credential again until the
pairing expires, provided the device still has access. In firmware, wait
at least poll_interval between requests and respect Retry-After on 429.
Keep the application key stable during pairing.

    read -r -s -p 'Device credential: ' DEVICE_CREDENTIAL; printf '\n'
    curl -i "$BASE/api.php?action=device" \
      -H "Authorization: Bearer $DEVICE_CREDENTIAL"
    unset POLLING_SECRET DEVICE_CREDENTIAL

This endpoint returns the linked device ID and name and updates its
last-seen time. Unlink the device in the dashboard, then retry the same
request with its old credential to verify a 401. Pairing again creates
a new device record while preserving the old record for history attribution.

## Check after deployment

- Sign in as admin and verify that a member account has no invitation controls.
- Try a redeemed, revoked, and expired invitation in separate browser sessions.
- Poll before approving a code, approve it as a member, then poll twice.
  Confirm that the credential is identical and only one device is listed.
- Sign in as a different member and confirm that the first member's device is absent.
- Unlink the device and confirm that its credential stops authenticating.

Run these cleanup statements daily using the application database account:

    DELETE FROM auth_rate_limits WHERE window_start < UNIX_TIMESTAMP() - 86400;
    DELETE FROM device_pairings WHERE expires_at < CURRENT_TIMESTAMP - INTERVAL 1 DAY;

Deleting an expired pairing does not delete its linked device.

## Shared conversations

The initial schema already includes the conversation tables. Deploy the updated
`public_html/api.php` together with `app/conversations.php`; no additional SQL migration
is required. Keep the server's private `config.php` when uploading.

All endpoints below require the paired device's bearer credential and HTTPS.
Ownership is derived from that credential; the client never supplies a user ID.
IDs are JSON strings. GET requests use query parameters; POST requests use JSON
objects with `Content-Type: application/json`.

| Method / action | Parameters / body | Result |
|---|---|---|
| GET `conversations` | Optional `offset` (default `0`) | Up to 50 titles, metadata, `next_offset`, and this device's `active_conversation_id` |
| GET `conversation` | `id`, optional `after_id` (default `0`) | Metadata, up to 20 turns, and `next_after_id` |
| POST `turn-save` | `client_turn_id`, `conversation_id`, `question_text`, `reply_text`, optional `reply_status`, optional `language_tag` | `conversation_id`, `turn_id`, and `created`; 201 for a new turn, 200 for a retry |
| POST `conversation-active` | `conversation_id` (string or null) | Select a thread, or clear the selection for a new conversation |
| POST `conversation-delete` | `conversation_id` | Delete the owned thread and its turns; clear selections on all devices |

Example turn body:

```json
{
  "client_turn_id": "b87840a5-165c-4358-9a99-7b73c57dcddf",
  "conversation_id": null,
  "question_text": "What did we decide?",
  "reply_text": "We decided to build shared history next.",
  "reply_status": "complete"
}
```

Generate one lowercase UUID per recording and retain it, its original thread
selection, and the completed transcript through retries. Null creates a thread
and its first turn atomically. Subsequent turns use its returned conversation ID.
Concurrent retries from the same device return one saved turn. Reusing the UUID
with different text, reply status, or an incompatible thread returns 409. A
missing or inaccessible thread returns 404; clients must not silently move an
unsent question into another conversation. Deletion is idempotent and does not
reveal another account's threads.

Previewing a transcript does not change the device's selection. Saving a new
turn selects its thread; retrying an existing save leaves the selection alone.
History is shared across an account, while each device has its own selection.
Index pages are ordered by last activity and are not a snapshot: refresh from
the first page if another device changes history while paging. Transcript pages
use increasing turn IDs.

Requests are limited to 128 KiB and each text field to 32 KiB of UTF-8. Empty
question text is permitted when input transcription is unavailable. At least
one text field must contain content. `reply_status` is `complete` (default) or
`interrupted`. An optional validated language tag is stored when the thread has
none and retained thereafter; the backend does not infer language from text.
The desktop currently keeps its first-question context as the language cue.

## Automated conversation checks

With Docker available, run from the repository root:

    python3 tests/run_history_integration.py

This builds PHP 8.4 with PDO MySQL, starts a temporary MariaDB 11.4 database,
imports all three schema migrations, and tests the API through a localhost-only HTTP listener
with a test-only HTTPS server variable. It checks account isolation, revoked
credentials, disabled accounts, concurrent retries, conflicting turn IDs,
pagination, selection, language metadata, and cascading deletion. Temporary
containers, database volumes, and the Docker network are removed afterward.
The test router and mock OpenAI transport are never part of the production
deployment. The suite never loads your private backend config or makes real
OpenAI requests. Personal-key checks cover encrypted storage, owner-bound
ciphertext, independent billing, replacement/removal, CSRF, and safe errors.

## Weather and live web lookup

The current desktop simulator and ESP32 firmware advertise two function tools in
voice sessions. `get_weather` resolves a city/postal code and requests current
modelled conditions and seven daily forecasts from Open-Meteo. `search_web` uses
OpenAI Responses with the `web_search` tool, using the same owner-specific key
selection as voice. The default search model is `gpt-5.4-mini`; it is separate
from `openai_realtime_model`. Users need Responses/web-search access and API
credits for searches as well as Realtime access. Search requests incur model
and web-search charges on the selected API project.

The server returns tool definitions and the current UTC time with each Realtime
secret. Clients execute complete function calls through the backend, return the
results to Realtime, and request the spoken/text answer. They allow at most
three external lookups per question. Provider failures and missing citations
are returned as errors; instructions explicitly prohibit inventing current
facts when lookup fails. Source names and URLs are appended to the displayed
reply and saved in the conversation transcript. Weather dates use the resolved
location's timezone and include the provider's units. Weather is not a direct
sensor observation. There is no automatic GPS/IP location: ask with a city and,
when needed, country. Questions beyond the next seven forecast days should be
answered with that limitation rather than an invented forecast.

The authenticated device endpoint is:

    POST /api.php?action=tool-call
    Authorization: Bearer DEVICE_CREDENTIAL
    Content-Type: application/json

```json
{"name":"get_weather","arguments":{"location":"Stockholm","country_code":"SE"}}
```

```json
{"name":"search_web","arguments":{"query":"What is the latest announcement from Stockholm city?"}}
```

Results contain provider data or `answer`, `sources` (title/URL pairs), and
`fetched_at`. Source URLs are displayed, never fetched by PHP. PHP contacts
only fixed OpenAI/Open-Meteo endpoints with redirects disabled, bounded response
sizes, and timeouts. Model-supplied arbitrary URLs cannot become HTTP targets.
Per-minute limits are 10 lookups/device and 20/account, plus an IP limit of 60.

These private config entries are optional; missing entries use the defaults:

```php
'enable_weather' => true,
'enable_web_search' => true,
'openai_search_model' => 'gpt-5.4-mini',
'open_meteo_api_key' => '',
```

Open-Meteo's public service is for non-commercial use. For commercial hosting,
obtain an appropriate Open-Meteo subscription and put its key in
`open_meteo_api_key`; PHP then uses its fixed `customer-` provider endpoints.
Weather data is attributed to Open-Meteo (CC BY 4.0) and geocoding to GeoNames.
See [weather documentation](https://open-meteo.com/en/docs),
[geocoding documentation](https://open-meteo.com/en/docs/geocoding-api), and
[OpenAI web-search documentation](https://developers.openai.com/api/docs/guides/tools-web-search).

Deploy `app/tools.php`, the updated `app/realtime.php`, and
`public_html/api.php` together, preserving private config. Restart the updated
desktop app or rebuild/flash the ESP32 firmware. No new database migration is
needed beyond the personal-key migration 003. Ensure the host permits outbound
HTTPS to `api.openai.com`, `geocoding-api.open-meteo.com`, and `api.open-meteo.com`
(or the corresponding `customer-` hosts). Allow at least 30 seconds for tool
requests in the hosting/proxy settings. Older clients that do not handle
function calls must be upgraded before testing live information.

The integration tests simulate both weather providers and OpenAI search; they
make no paid API calls. A live Open-Meteo geocoding/forecast format check passed.
Real Realtime-to-tool-to-answer calls still need a deployed smoke test, such as
“What is the weather in Stockholm tomorrow?” and “Search the web for today's
Stockholm city announcements.”

## Dashboard conversation browser

The browser dashboard now shows your saved conversations first, with a device
filter, recent-activity list, and a full question/reply reader. Each linked
device also has a conversation-count link under **My devices**. Both the thread
list (25 per page) and transcript (20 turns per page) support pagination. Source
URLs are safely linked, and interrupted replies are marked. The page adapts to
phone screens and light/dark system preferences without client-side JavaScript.

A device filter means “threads containing at least one question from this
device.” Opening a shared thread shows its complete transcript, with the device
label on each question. The filter includes unlinked devices so their old
history remains readable. All history is scoped to the signed-in owner;
administrators cannot browse another user's transcripts. Reading a thread here
does not change any device's active conversation.

Deploy these three files together for this dashboard update:

- `app/dashboard_history.php` (new)
- `public_html/index.php`
- `public_html/style.css`

No new SQL migration or private configuration change is needed. Continue to
keep `config.php` and `app/` outside the public document root. If the browser
still shows old styling, refresh its cached `style.css`.
