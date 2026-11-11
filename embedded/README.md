# PocketBrain ESP32-S3 firmware

CMake/ESP-IDF bench firmware based on [the project plan](../docs/PocketBrain_Project_Plan.md).
Targets the Waveshare ESP32-S3-DEV-KIT-N16R8 / ESP32-S3-WROOM-1-N16R8:
16 MB flash, octal 8 MB PSRAM. Built and linked with **ESP-IDF 5.4.3**.
This is a prototype implementation; hardware and live service validation are outstanding.

## Build and flash

Install ESP-IDF 5.4.3 using Espressif's [installation instructions](https://docs.espressif.com/projects/esp-idf/en/v5.4.3/esp32s3/get-started/index.html).
Then, from an ESP-IDF terminal:

```sh
cd embedded
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

The backend defaults to **https://peabrain.se**, with the device API at
`https://peabrain.se/api.php`. Under **PocketBrain**, configure a unique BLE
provisioning proof of possession. The backend URL remains configurable (the directory
containing `api.php`, without query parameters).
An empty proof of possession deliberately disables provisioning. Never put an OpenAI
API key in the firmware: PHP issues the short-lived Realtime secret.

The component manager downloads pinned WebSocket and U8g2 dependencies on the first
build. Keep `dependencies.lock` under version control. Local `sdkconfig`, downloaded
components, and build output are ignored. Disable **Enable SSD1363 OLED** if testing
without the display. Serial commands still work. The default console is the board's
USB-to-UART bridge at 115200 baud; select USB Serial/JTAG in ESP-IDF console settings
if using the native USB port instead. Native USB GPIO19/20 are left free.

## Deployment URL for linking

The **live server's private** `config.php` must contain:

```php
'base_url' => 'https://peabrain.se',
```

The local private configuration and the example have been updated. Preserve all
other server settings when applying this line; do not replace the private config
with the example, which has empty secrets. The server must return
`https://peabrain.se/index.php#devices` from `pair-start`. The firmware detects an
approval address outside its configured backend path and displays a configuration
error instead of sending the user to a placeholder domain. Invitations also depend
on the server's `base_url` being correct.

For an existing build, set **PocketBrain → Backend HTTPS base URL** to
`https://peabrain.se` in `idf.py menuconfig`; a changed default does not replace an
existing customized `sdkconfig`. The working build in this workspace is updated.
Then build/flash, provision Wi-Fi, select **Link account**, and approve the code at
[peabrain.se](https://peabrain.se/index.php#devices) while signed in. Cancellation
stops the local flow; any device already approved on the server can be revoked in
the dashboard.

## Bench wiring

All GPIOs are configurable in `menuconfig`. The defaults are:

| Signal | GPIO | Connection |
|---|---:|---|
| I²S BCLK | 4 | Mic BCLK and amplifier BCLK |
| I²S WS | 5 | Mic LRCL and amplifier LRCLK |
| Microphone input | 6 | SPH0645 DOUT |
| Speaker output | 7 | MAX98357A DIN |
| OLED chip select | 10 | SSD1363 CS |
| OLED SPI MOSI | 11 | SSD1363 serial data input |
| OLED SPI clock | 12 | SSD1363 serial clock |
| OLED data/command | 13 | SSD1363 D/C |
| OLED reset | 14 | SSD1363 reset |
| Talk | 15 | Active-low switch to ground |
| Wheel push | 16 | Active-low switch to ground |
| Encoder A/B | 17 / 18 | Quadrature contacts, common to ground |
| Amplifier shutdown | Disabled (`-1`) | Optional; choose GPIO21 and wire SD for power gating |

Mic SEL connects to ground (left slot). Follow the project plan for breakout power,
ground, and differential speaker wiring. Buttons and encoder use pull-ups. External
pull-ups are recommended for the final low-power board. Set either encoder pin to
`-1` to use serial navigation without an encoder. Startup rejects duplicated pins,
flash/PSRAM pins GPIO26–37, and non-RTC wake pins.

**The bare OLED requires its specified power supply, interface straps, flex connector,
and panel pinout. The GPIO table is a logical signal assignment, not a 30-pin flex
pin-number table.** Confirm those electrical details before connecting or powering it.
The driver uses U8g2's SSD1363 initialization, 4 MHz four-wire SPI and R1 portrait
rotation (128 × 256). Verify reset polarity, orientation, and panel initialization on
this exact TCC part. The built-in font supports Latin-1, including Swedish; full
Unicode font coverage remains future work.

## First use

1. Start with low volume and select **5s audio loopback**, or send serial `l`.
   Speak for five seconds and listen to the playback. Both directions use Philips
   I²S at 48 kHz with two 32-bit slots (3.072 MHz BCLK). The left microphone slot is
   averaged in pairs to 24 kHz PCM16; playback repeats each sample into both slots
   at 48 kHz. This tests the Realtime conversion path; the plan's separate native
   48 kHz recording/playback measurement still needs bench verification.
2. Select **Wi-Fi setup**, or send `f`. Use Espressif's BLE provisioning application,
   connect to service `PocketBrain`, and supply the configured proof of possession.
   Two successfully provisioned SSIDs/passwords are retained; reconnect alternates
   between them when a network is unavailable. Provision the home network and phone
   hotspot in turn. Provisioning waits up to three minutes.
3. Select **Link account**, or send `p`. Open the displayed verification address on
   another device, sign in, approve the pairing code, and wait for **Account linked**.
   The linking screen shows the complete address, code, and remaining time.
   Talk cancels linking; serial `b` or `p` also cancels. An in-flight HTTPS request
   may take up to its network timeout to return before cancellation finishes.
   The Talk release is consumed and never starts recording.
   The revocable device credential is installed only after successful NVS storage;
   failed writes are retried while the code is valid. Polling respects the backend
   interval, expiry, and numeric `Retry-After` on rate limits, and retries temporary
   network/server failures with backoff. Local unlink clears device credentials and cached
   account data; revoke the device in the web dashboard as well when transferring it.
4. Hold Talk to capture, then release it to send. Recording continues while Wi-Fi,
   clock synchronization, token issuance and TLS are being prepared. The 30-second
   bar follows elapsed capture time; reaching zero stops capture and waits for the
   Talk release before committing.
5. Read or listen. Wheel rotation scrolls. Wheel push stops the current reply during
   playback; otherwise it opens the menu. Talk stops playback and begins the next
   capture. In a menu, Talk goes Back and its entire press/release is consumed.
6. **History** lists thread titles with pagination. Open a thread to preview it, then
   select **Continue here** to make it active. **New conversation** preserves the old
   server transcript. Deletion, discarding a recording, local unlink and explicitly
   retrying in a new thread require a second wheel press to confirm.

Volume advances in 10% steps; mute persists. Display timeout switches between two and
ten minutes. Wheel movement and completed operations reset the timeout. **Usage**
points to the backend dashboard because there is no device usage API yet.

Serial keys (single characters; a newline is unnecessary):

| Key | Action |
|---|---|
| `t` / `r` | Talk press / release |
| `w` | Wheel push |
| `j` / `k` | Scroll/menu down / up |
| `b` | Back |
| `l` | Five-second loopback |
| `f` / `p` | Wi-Fi provisioning / start or cancel account pairing |
| `s` | Sleep when work is safely stored |

## Persistence, conversation context and cancellation

Audio is 24 kHz little-endian PCM16 mono, capped at 720,000 samples / 1,440,000 bytes.
Capture resides in PSRAM; I²S DMA remains in internal RAM. Playback uses a 64 KiB
PSRAM ring and fixed-size internal DMA blocks. Network processing runs separately
from capture and controls. A second PSRAM recording buffer permits Talk to begin
capturing immediately while the interrupted turn finishes saving. Cancellation
blocks subsequent audio from the old socket and resets queued playback.

The input recording is committed to flash **before upload**. Ordinary retries keep
its original conversation ID and UUID. A completed or interrupted transcript is
journaled before `turn-save`; retries of an acknowledged-or-uncertain save resend
that transcript and UUID without generating another answer. Pending audio is cleared
only after backend acknowledgement and local cache persistence, or an explicit
discard/unlink. If the original thread was deleted, ordinary retry refuses to generate
an answer in it. **Retry in new thread** is a separately confirmed user choice for
an unsent recording. Completed transcripts retain their original thread identity.

A newly captured interruption can coexist with an older failed turn in RAM. If the
older save fails, resolve that pending turn before submitting the new one; the device
stays awake to protect the extra RAM recording. Only **one** failed question has a
persistent flash reservation. A flash-write failure also prevents sleep and displays
that the recording remains only in RAM. Power loss during capture, or before the first
successful journal commit, cannot preserve that recording.

The first question uses a required Realtime function call to identify the thread's
BCP-47 language before requesting its answer. The tag is validated, saved through
PHP, cached, and restored in later session instructions. Sessions restore the latest
six turns, capped at 2,000 UTF-8 bytes per message. The full server transcript is
retained by PHP. TLS uses the ESP-IDF CA bundle, hostname verification, and SNTP;
HTTP redirects are disabled. Read wake does not start Wi-Fi or initialize I²S.

| Partition | Budget | Purpose |
|---|---:|---|
| `ota_0`, `ota_1` | 4 MiB each | Application slots; no OTA updater implemented yet |
| `pending` | 4 MiB | Two alternating slots, each holding maximum PCM plus metadata |
| `history` | 1 MiB | Two alternating slots; 448 KiB bounded JSON reading cache |

Each journal slot has sequence numbers and payload/header CRCs. The new slot is
erased and written first, with the commit header written last; an interrupted write
leaves the previous slot readable. Clearing writes a newer empty record. NVS stores
settings and credentials. This bench configuration does not enable flash encryption
or secure boot; logical clearing does not securely erase old physical flash contents.

History preview does not change the active thread. On History synchronization, active
thread state is fetched from PHP and deleted cached threads are invalidated. Cached
history retains the newest complete turns that fit and marks the older boundary.
**Current limitation:** opening a long online thread traverses forward pages to build
that bounded latest window; scrolling farther back online needs a separate paging UI.
There is no spoken New conversation shortcut. Runtime, battery measurement, robust
encoder behavior at fast wheel speeds, and final power optimization remain bench work.

## Source layout

- `main/app_main.c`: controls, portrait UI, menus, worker ownership, wake/sleep.
- `main/audio.c`: shared full-duplex I²S, capture, conversion and bounded playback.
- `main/display.c`: SSD1363 SPI adapter and text rendering.
- `main/network.c`: Wi-Fi/BLE, clock synchronization, verified HTTPS and pairing.
- `main/realtime.c`: session preparation, chunked upload, streamed reply, cancellation,
  language detection and retry-safe transcript saving.
- `main/storage.c`: ESP flash journal adapter and NVS settings.
- `components/pb_core`: portable control, PCM, text layout, journal logic and tested
  linking state machine.

The implementation follows the existing actions in `backend/public/api.php`:
`pair-start`, `pair-poll`, `realtime-secret`, `conversations`, `conversation`,
`conversation-active`, `conversation-delete`, and `turn-save`. No backend edits are
required for this firmware.

## Validation

Host tests require only a C compiler and CMake:

```sh
cmake -S embedded/tests -B /tmp/pbrain-host-tests
cmake --build /tmp/pbrain-host-tests
ctest --test-dir /tmp/pbrain-host-tests --output-on-failure
```

The linking suite checks approval, malformed replies/credentials, cancellation
before/during requests, expiry, rate limits and backoff, retrying credential storage,
and verification URL boundaries. The core suite checks debounce, consumed menu/wake
releases, recording limits, chunk-boundary
PCM conversion, saturation, UTF-8 wrapping, language-tag validation, CRCs, journal
capacity and corruption recovery. They simulate 25,503 power interruptions across
erase, payload and header writes. These tests do not validate the RTOS, network,
physical flash endurance or peripheral timing.

Before using the prototype, run the bench checklist in the project plan: loopback,
one spoken and one muted live exchange, both wake buttons, menu Back, interrupt with
Talk, slow reconnect at the recording limit, backend unlink, save acknowledgement
loss, history preview/resume/delete, offline cache after reboot, and pending retry
after reboot. Check amplifier shutdown with GPIO21 wired before measuring sleep
current. GPIO assignments and firmware compilation do not validate panel or audio
hardware compatibility.

Protocol references: [ESP-IDF I²S](https://docs.espressif.com/projects/esp-idf/en/v5.4.3/esp32s3/api-reference/peripherals/i2s.html),
[WebSocket client](https://docs.espressif.com/projects/esp-protocols/esp_websocket_client/docs/latest/index.html),
[OpenAI Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations),
[U8g2 SSD1363 setup](https://github.com/olikraus/u8g2/wiki/u8g2setupc).

## Weather and web lookup

Realtime sessions now accept the backend's `get_weather` and `search_web`
function definitions. The firmware shows “Checking weather” or “Searching the
web”, posts the function arguments to the authenticated `tool-call` endpoint,
and returns the result to Realtime for a spoken/text answer. Source names and
URLs are appended to the saved reply. The existing language-detection tool
still runs first for a new thread, then live lookups use automatic tool choice.
At most three external lookups are allowed per question. HTTP tool requests
have a 35-second timeout; cancellation drops late results, although an in-flight
HTTP request can take until its timeout to return to the voice worker.

Deploy the current backend tool files and rebuild/flash the firmware. Ask for
weather with a city/country; the device does not infer its location. Web search
uses the account's saved OpenAI key, including its API permissions and credits.
See the backend README for provider settings, limits, and deployment steps.
