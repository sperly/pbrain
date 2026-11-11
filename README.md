# PocketBrain VS Code handoff

Open this folder in VS Code. The [project plan](docs/PocketBrain_Project_Plan.md)
covers the hardware, controls, account model, and firmware behavior.

| Path | What it contains |
|---|---|
| [backend](backend/README.md) | PHP 8.4 dashboard, device API, Realtime client-secret endpoint, and MariaDB migrations |
| [desktop](desktop/README.md) | Python/Tk simulator, microphone and speaker routing, and the direct Realtime client |
| [embedded](embedded/README.md) | CMake/ESP-IDF firmware, bench wiring, and host tests for ESP32-S3 |

This workspace folds the desktop ZIP's PHP add-on into the backend. There
is one PHP API entry point. Existing deployments can deploy this source
while retaining their private configuration and database.

## First development session

1. Run the desktop app in **Demo**, then **Loopback**, using its README.
2. Set up the PHP backend on the HTTPS host. On a fresh database, import
   all four SQL migrations in order. On existing databases, import only
   migrations that have not run, including `003_user_openai_keys.sql` and `004_legal_acceptances.sql`.
   Set DB credentials and a stable application key in the private config.
   Each user adds their OpenAI API key through the dashboard; shared site
   billing requires an explicit opt-in setting.
3. Sign in, pair the desktop simulator, and try one spoken and one muted
   question in **Live**. Check that unlinking the device blocks subsequent
   credential requests.
4. Verify shared conversation history in Live mode. Save a turn, restart the
   simulator, and continue it from History. Pair a second device under the same
   account and check shared history with separate active selections. Disconnect
   after receiving a reply and confirm **Retry save** does not generate another
   answer. Delete a thread and confirm it disappears after the other device syncs.

## Device interface

All paths below are relative to the configured HTTPS base URL. The request
credential is sent in the Authorization bearer header where specified.

| Method and action on api.php | Credential | Current response |
|---|---|---|
| POST pair-start | None | 201 with code, polling_secret, expires_in, poll_interval, and verification_uri |
| POST pair-poll | Polling secret | 202 while awaiting approval, 200 with device_credential when linked, 404 when expired or unknown |
| GET device | Device credential | 200 with id and name, 401 for an invalid or revoked credential |
| POST realtime-secret | Device credential | 200 with value, expires_at, and model, 401 for an invalid or revoked credential |

The simulator records into a 24 kHz, 16-bit mono PCM buffer and opens a new
Realtime WebSocket per turn after Talk is released. Live conversation history
and device selections sync through PHP; each profile keeps a local cache and
one pending recording or completed transcript. Demo and Loopback stay local.
See the backend README for the conversation API and integration tests.

## Verification carried forward

The desktop UI was exercised in Tk. Realtime events and PCM processing
were exercised with mocks. Invite, ownership, and pairing SQL behavior
was checked using a SQLite translation. The PHP 8.4/MariaDB integration,
physical audio devices, and a live OpenAI exchange still need to be
verified on the deployment host and desktop.

ESP-IDF firmware is now in [embedded](embedded/README.md), with build
instructions, configurable bench wiring, and host tests. Physical firmware
validation, custom PCB and enclosure CAD remain subsequent milestones.
