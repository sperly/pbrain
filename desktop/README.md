# PocketBrain Desktop

A Python desktop simulator for the physical PocketBrain. Its simulated OLED is
a one-bit 256 × 128 panel mounted in portrait, yielding a 128 × 256 framebuffer
shown at 2× scale. It uses the same device pairing endpoints as the PHP backend.

## Install and run

Use Python 3.11–3.14 with Tk. On Linux Mint, Ubuntu, or Debian, install Tk
and the PortAudio runtime if needed:

    sudo apt install python3-tk python3-venv libportaudio2

From this directory:

    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -r requirements.txt
    python pocketbrain.py

On Windows, install Python with Tcl/Tk support, use
`.venv\Scripts\activate` in Command Prompt after creating the environment,
and run the same pip and Python commands. On macOS, use a Python
distribution with Tk. If the OS asks, grant microphone access to the
terminal or Python process. `python pocketbrain.py --check` lists audio
devices without opening the UI.

| Mode | What it tests |
|---|---|
| Demo | Controls, text scrolling, mute, menus, and history without a microphone or server. |
| Loopback | Records the selected microphone and plays it through the selected output without a server. |
| Live | Records locally, then sends 24 kHz mono PCM directly to OpenAI Realtime over WebSocket. The PHP backend pairs the simulator and issues its short-lived credential. |

Choose **Audio devices** to select separate input and output devices or keep
the system defaults. Start with **Loopback** to check the audio path.

## Controls

| Control | Mouse | Keyboard |
|---|---|---|
| Talk | Hold the left Talk button, then release | Hold Space, then release |
| Turn wheel | Scroll over the display or click Up / Down | Up / Down |
| Push wheel | Click Push | Enter |
| Back | Press Talk inside a menu | Space or Escape |

Talk records for up to 30 seconds and displays a countdown bar. Release
to submit, including after reaching the limit. Talk during a reply stops
playback and starts recording the next question. Push during playback
stops that reply. Inside menus the entire Talk press is consumed as Back.

The wheel menu offers New conversation, History, Mute, Volume, Link account,
Usage and Unlink locally. Like the ESP32, linking shows a verification address
and code on the OLED. Turn the wheel to scroll the instructions; Talk or Escape
cancels linking and consumes the Talk press without recording. The desktop uses
the computer's network connection instead of the ESP32's BLE Wi-Fi setup.
Switching to the browser keeps pairing active. Temporary polling connection or
server failures retry with the same code until expiry. If linking fails, the OLED
keeps the code and error visible; push the wheel to start again or Talk to go Back.
Open an
old thread to scroll through it. Push again to continue or delete it.
A failed Live turn stays on disk until you retry or discard it. Start in
the same Live profile to recover a saved question after a restart.

## Enable Live mode

1. Deploy the current `backend/` source from this repository using its README.
   Import all four SQL migrations on a fresh database. Existing installations
   need migrations 003 and 004 if they have not run. Enable PHP cURL and OpenSSL.
   Use `backend/public_html/` as the site's document root.
2. Sign in to the web dashboard and add your key under **My OpenAI API key**.
   The encrypted long-lived key stays on the server; your device uses only a
   short-lived credential. Manage API credits and permissions in your OpenAI
   API project. The host can explicitly enable shared billing for users without
   personal keys; this is disabled by default.
3. Deploy the current backend source, including `app/conversations.php`,
   `app/openai_keys.php`, `app/realtime.php`, and both `public_html/` PHP files. The historical `desktop/backend-addon/`
   copies are obsolete; do not copy them over the current backend.
4. Enter your PocketBrain HTTPS base URL in the desktop app. Push the wheel
   and select **Link account**, or use the **Link account / cancel** toolbar
   button. This selects Live mode. Open the verification address shown on the
   OLED in a browser, sign in to your PocketBrain account, enter the code under
   **My devices**, and approve it. The simulator polls automatically at the
   backend interval (bounded to 5–60 seconds), displays the remaining time,
   and stores the device credential after approval. Expired codes require
   starting Link account again. An already linked backend requires local unlink
   before linking another account.
5. Hold Talk, ask a question, and release. Try mute and then a second
   question in the same conversation. The desktop app requests a fresh
   Realtime secret on each turn using `POST /api.php?action=realtime-secret`
   with the existing PocketBrain device credential as a bearer token. The
   long-lived OpenAI key stays on the PHP server.

The desktop simulator buffers the full recording before upload. In Live mode,
conversation titles, transcripts, and the active selection sync with MariaDB.
History refreshes on profile load and when opening History; selected threads
are loaded before each voice exchange. Previewing a thread does not select it;
**Continue here** does. Deleting removes the server copy and clears selections
on other devices; their cached copies disappear on their next successful sync.
A bounded selection of previous turns, including the first question as a
language cue, is sent to Realtime when continuing a conversation.

Completed replies are written to the pending file before the transcript is
uploaded. If saving fails, choose **Retry save**: it uploads the same transcript
and turn UUID without generating another answer. A failed or stopped voice
exchange retains its recording for **Retry recording** or **Discard**; retrying
an incomplete exchange can generate a new answer. A pending question remains
attached to its original thread. If that thread was deleted, discard the
pending question and start a new conversation. The app never silently moves it.

Demo and Loopback retain local history. Live caches and pending recordings are
separate by backend and device credential. Older local-only Live conversations
are not uploaded automatically; their old cache file is replaced by server
history after a successful sync. Back up that file before upgrading if you
want to retain it. The app stores credentials, cached text, and recordings in
your user state directory under `pocketbrain-desktop`. **Unlink locally** in the
wheel menu requires confirmation, then removes the selected backend's local
credential, cached Live history, and saved recording. Other backend profiles and
Demo/Loopback history are retained. Also unlink the simulator in the web dashboard
to revoke backend access when transferring it; local unlink does not revoke the
server credential.

Run the conversation client tests with the desktop's dependencies installed:

    python -m unittest discover -s tests -p 'test_*.py'

Run that command from the repository root. These tests do not open a Tk window
or use audio hardware. Real audio and a deployed HTTPS host still require a Live
smoke test.

## Weather and web questions

Live mode can now look up weather and search the web through the backend.
Ask with a location, for example “What is the weather in Stockholm tomorrow?”,
or say “Search the web for …”. The reply includes provider/source links in its
saved transcript. Lookups run only when the model requests them, with a maximum
of three per question. If a provider is unavailable the assistant is instructed
to explain the failure, not invent a current answer.

Deploy the current backend's `app/tools.php`, `app/realtime.php`, and
`public_html/api.php` before using these features. Web searches use your saved
OpenAI API key and incur additional search/model usage. The host can disable
either lookup in private config. Demo and Loopback make no lookup requests.
