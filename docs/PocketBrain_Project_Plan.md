# PocketBrain project plan

**Status** · Working brief, 10 November 2026

PocketBrain is a one-handed, battery-powered voice assistant. Hold Talk to ask a question, then read the answer on the OLED or listen through the speaker. Use the wheel to scroll, change settings, and return to earlier conversations.

## Decisions so far

| Area | Decision |
|---|---|
| Connectivity | Home Wi-Fi and a phone's 2.4 GHz Wi-Fi hotspot are the normal connections. The pocket unit has no cellular modem. |
| Voice connection | PocketBrain streams audio directly to OpenAI Realtime over a secure WebSocket. The PHP/MariaDB service manages accounts, device access, and saved transcripts. |
| Account signup | An administrator creates an invite link. The invited user creates their own account, then pairs a physical PocketBrain separately. |
| Device ownership | PocketBrain is personal. Each physical unit links to one owner account at a time. Changing owners requires unlinking and pairing again. |
| Reply mode | Display every reply and speak it by default. Mute is a persistent setting. Pressing Talk during playback stops the reply and starts recording the next question. |
| Conversation history | Browse saved threads, read their transcripts, and choose an earlier thread to continue. Threads stay until manually deleted. Starting a new conversation preserves the previous one. |
| Offline reading | Keep as much as fits of the most recently used conversation on the device, prioritizing the newest turns. |
| Recording limit | Capture up to 30 seconds per question and show the remaining recording time as a bar on the OLED. |
| Physical controls | Mount Talk on the side opposite the scrollwheel. When a menu is open, Talk acts as Back. |
| Wake to read | Press the scrollwheel from deep sleep to open the last cached conversation with the mic idle. |
| Failed question upload | Keep the recording on the device and offer to retry it once connectivity returns. |
| Conversation language | Set the language from the first question and keep it for that thread's written and spoken replies, including after resuming it from History. |
| Enclosure | Start with a 48 mm-wide, 3D-printable case. The first packaging target is 105 × 48 × 20 mm. |
| Battery | Use the existing LP553580 pouch cell for the first build. Its nominal rating is 1,800 mAh at 3.7 V. Measure runtime on the prototype. |
| Display | Prototype with the TCC SYO256128027ASWCG01, a bare 2.7-inch, 256 × 128 white or yellow OLED. White is the working choice. |

## Device interaction

1. **Ask.** Hold the dedicated Talk button to wake and record. Show **Listening** once the mic is ready. The remaining-time bar starts full and drains from 30 seconds to zero based on elapsed recording time, including while Wi-Fi is connecting. Fetch a Realtime token and open the direct voice session while buffering audio as needed. At zero, stop recording and show **Recording limit reached**. Releasing Talk commits the captured audio and requests the answer, including when the limit was reached. If the connection fails before a complete reply arrives, show **Question saved** and offer **Retry** once connected.
2. **Read or listen.** Display the reply transcript as it arrives and play the incoming audio. Request text output when muted. Turn the wheel to scroll. Press the wheel during playback to stop just that reply. Press Talk during playback to stop the speaker immediately, clear queued audio, and begin recording the next question in the active conversation. Cancel any reply still being generated and ignore late audio from it. Preserve the text already displayed and mark the reply as interrupted if the text is incomplete.
3. **Browse History.** List threads by latest activity and derive a short title from the first question. Opening a thread starts at the latest reply. Turn the wheel to read older turns. Choose **Continue here** to make that thread active. Show the active thread's title before the next question. Offer **Delete conversation** in the thread's menu and confirm before deleting. If the active thread is deleted, the next Talk starts a fresh thread. When offline, show the cached conversation and mark where older turns need a connection.
4. **Start a new thread.** Put **New conversation** at the top of the wheel menu. A spoken shortcut remains a proposal. If used, check a complete utterance such as “Start a new conversation” or “Ny konversation” before requesting a model reply and confirm the new thread on the OLED.
5. **Navigate menus and change settings.** Turn the wheel to move through items and press it to select. Whenever a menu is open, Talk acts as **Back**. It goes up one level in a submenu or closes the top-level menu and restores the previous view. Consume the whole Talk press and release as navigation, including when it closes the last menu. Include Volume, Mute, Wi-Fi, Usage, and Display timeout. A longer reading timeout or a reset of the timeout whenever the wheel moves would help when reading a muted reply.
6. **Wake to read.** Press the scrollwheel from sleep to open the last cached conversation at its latest reply. Keep the mic and Wi-Fi idle while reading cached turns. If there is no cached conversation, show the idle view. Consume the first wheel press and release as wake, then use normal wheel navigation.

The backend keeps the device's active thread across deep sleep and network changes. Previewing a saved thread leaves the current thread active until **Continue here** is selected. Store the full text transcript for reading and restore a bounded amount of the selected thread's context when opening a new Realtime session.

## Electronics and packaging

| Item | Working design |
|---|---|
| Controller | Waveshare ESP32-S3-DEV-KIT-N16R8 for the bench, then ESP32-S3-WROOM-1-N16R8 on the custom PCB. The module has 16 MB flash and 8 MB PSRAM. Use ESP-IDF. |
| Audio input | One digital I²S MEMS microphone. Pack audio for Realtime as 24 kHz, 16-bit mono PCM, up to 30 seconds per question. A full recording in this format takes 1.44 MB before transport encoding. Encode and send in chunks. |
| Audio output | MAX98357A I²S class-D amplifier and an 8 Ω miniature speaker. Stream 24 kHz, 16-bit mono PCM through a 32–64 KiB playback ring buffer. Keep I²S DMA buffers in internal RAM and use amplifier shutdown outside playback. |
| OLED | TCC panel outline is 73.0 × 41.86 × 2.0 mm. Active area is 61.42 × 30.70 mm. Mount in portrait for a 128 × 256 reading view. Prefer 4-wire SPI with the SSD1363. The panel uses a 30-pin, 0.5 mm-pitch flex. |
| Power | Prototype the custom board around USB-C charging, a BQ24074 power-path charger, and a TPS63802 3.3 V buck-boost. Confirm the actual battery's connector, polarity, and thermistor before finalising the charger. |
| Controls | Recessed Talk button on the side opposite the detented scrollwheel with push switch. Give each switch a separate RTC-capable wake GPIO so the firmware can distinguish Talk from wake to read. |

At 48 mm outside width with 2 mm walls, the cavity is 44 mm wide. The TCC glass leaves roughly 1.1 mm per side. Its flex exits the long edge and must turn behind the display. Verify the flex length, bend radius, contact orientation, connector height, pinout, and panel supply requirements before PCB layout. The LaskaKit breakout's drawing gives a 50 mm carrier width, so the first fit design uses the bare TCC panel.

Use a two-piece PETG shell with a screw-on back. Stack the battery behind the PCB, allow room for its leads, keep the antenna clear of the battery and speaker, and give the speaker and microphone separate acoustic openings. Fit-check the Talk button and scrollwheel on opposite sides with the physical parts. The 105 × 48 × 20 mm envelope is a fit target until the stack has been measured.

### Bench audio wiring

The ordered bench hardware is the **Waveshare ESP32-S3-DEV-KIT-N16R8** and **SparkFun DEV-14809 MAX98357A** breakout. This pin map assumes the previously proposed **Adafruit 3421 SPH0645LM4H** microphone breakout and an **8 Ω speaker**. GPIO assignments are for the bench prototype.

| Signal | Waveshare S3 | Adafruit microphone | SparkFun amplifier |
|---|---|---|---|
| I²S bit clock | `GPIO4` | `BCLK` | `BCLK` |
| I²S word select | `GPIO5` | `LRCL` | `LRCLK` |
| Microphone data to ESP32 | `GPIO6` | `DOUT` | |
| ESP32 audio data to amplifier | `GPIO7` | | `DIN` |
| 3.3 V power | `3V3` | `3V` | `VDD` |
| Common ground | `GND` | `GND` and `SEL` | `GND` |

Power the dev board over USB and begin at low playback volume. Connect the speaker across the amplifier's `+` and `−` pads. Leave `GAIN`, `SD`, and the board jumpers at their defaults for this test. Grounding the mic's `SEL` selects the left slot.

Reserve `GPIO15` for the Talk button and `GPIO16` for scrollwheel push. Wire each switch active-low to ground with a pull-up. Both GPIOs are RTC-capable and give the two wake actions separate inputs.

#### First audio test

1. Configure standard Philips I²S at **48 kHz** with **two 32-bit slots**. The ESP32 drives the shared clock and word select. The expected bit clock is **3.072 MHz**.
2. Capture five seconds into RAM using the microphone's left slot. Play the recording back locally, putting the same mono sample in both output slots. Check that speech is intelligible and playback is stable before adding networking.
3. For the first Realtime exchange, send **24 kHz, 16-bit mono PCM**. Try running the microphone directly at 24 kHz once the 48 kHz bench test passes. If direct 24 kHz capture is unreliable, keep the I²S bus at 48 kHz and resample at the Realtime boundary. Knowles' Rev C datasheet lists 16–64 kHz, while the older datasheet linked by Adafruit lists 32–64 kHz. The 48 kHz starting point is within both ranges.

## Backend and connectivity

- **Voice connection.** The ESP32 sends PCM to OpenAI Realtime and receives reply audio and its transcript, or text only in mute mode. Enable input transcription for History. PHP issues short-lived Realtime client secrets over HTTPS and keeps the long-lived OpenAI key in its server configuration.
- **History.** The device posts question and reply text, or the spoken reply transcript, to PHP. Save the turn under a device-generated turn ID so a retry cannot create a duplicate. Wait for acknowledgement before sleep when practical. Return titles first and load transcript pages on demand. Keep threads until the user deletes them. On deletion, remove the thread and messages from the live store and invalidate cached copies on connected devices or when they next sync.
- **Offline history.** Keep the most recently used conversation with messages in a bounded flash cache so it survives deep sleep and reboot. Cache the text, title, and conversation ID. Keep the whole thread when it fits and retain the newest complete turns when space runs short. If a single turn exceeds the available space, mark its saved excerpt as partial. Update the cache as turns complete or when the user resumes a different saved thread. Clear it on local unlink or reset. MariaDB retains the full transcript. Choose the cache size after allocating space for firmware, settings, and updates.
- **Pending question.** Reserve flash separately from the offline history cache for one failed recording and its metadata. Budget 1.44 MB for the 30-second PCM limit plus metadata and storage overhead. Keep the original conversation ID, or the intent to create a new thread, and the original turn ID. The recording survives deep sleep and reboot. When connected, let the user choose **Retry** or **Discard** and confirm before replacing an unsent recording. A retry uses the original thread. If that thread has been deleted, ask the user whether to discard the recording or submit it in a new conversation.
- **Retry and cleanup.** If the reply already arrived and saving it failed, retry the transcript save with the same turn ID. If no complete reply arrived and the backend has no saved turn, retrying the question may generate another Realtime response. Clear the pending audio after the completed turn is saved, or on discard, local unlink, or reset.
- **Language.** Set the thread language from its first substantive question. In a new thread, instruct Realtime to reply in the language of that question. Save the detected language and restore it in session instructions when the thread is resumed. Later questions can be transcribed as spoken while the reply remains in the original thread language.
- **Access.** Use PHP for the account and device UI and the authenticated device API. Use MariaDB for users, invitations, paired devices, conversation metadata and transcripts, and usage. PHP identifies the account from the device credential and checks ownership on every history operation. Store password hashes and hashes of invite tokens and device credentials. Make the HTTPS endpoint reachable from home Wi-Fi and the phone hotspot.
- **Bluetooth.** Use Bluetooth LE for Wi-Fi setup in the first version. A companion app could later relay PocketBrain traffic over BLE using the phone's connection. Standard phone Bluetooth tethering uses Classic Bluetooth PAN, which the ESP32-S3 does not support.

### Proposed account and device setup

1. **Create an account by invitation.** Set up the first administrator at deployment. In the web UI, the administrator generates an invite link they can copy and share. The recipient opens it on a phone or computer and completes signup. Use single-use, expiring invitations that the administrator can revoke before redemption. Redeem the invite when account creation succeeds. The new account can then pair its own PocketBrain.
2. **Start pairing.** Connect the physical PocketBrain to Wi-Fi, then choose **Link account**. The device asks PHP for a short pairing code and a separate, high-entropy polling secret. It shows the pairing code and web address on the OLED.
3. **Approve the link.** Sign in to the web UI, open **Devices → Add device**, enter the displayed code, and confirm the link. Make the code single-use, expire it after a few minutes, and rate-limit guesses and polling.
4. **Store a device credential.** PocketBrain polls over HTTPS with its private secret and obtains its own revocable credential once the link is approved. It uses that credential for history, turn saves, and Realtime token requests. Browser sign-in stays on the phone or computer.
5. **Manage devices.** Show linked devices with a name and last-seen time, and let users unlink them. A unit has one owner account at a time. The proposed v1 allows an owner to link several units, share their account history across them, and keep a separate active thread on each. Unlinking revokes backend access and future token issuance. Already-issued Realtime tokens and open sessions follow OpenAI's lifetime rules. When transferring a unit, clear its device credential and any locally cached account data before pairing it again. Saved history stays with the original account.

The pairing pattern is based on the [OAuth device authorization flow](https://www.rfc-editor.org/rfc/rfc8628.html). The prototype can start on the home network. Test access from the phone hotspot before treating the deployment as ready for mobile use.

## Implementation handoff

The VS Code workspace bundle has the PHP 8.4 backend, MariaDB migrations, and Python desktop simulator. Start with its root README for deployment and validation.

| Area | Current state |
|---|---|
| PHP and MariaDB | Initial schema and auth-rate-limit migration, first-admin bootstrap, invite signup and revocation, pairing approval and polling, device authentication, and unlinking. The Realtime credential endpoint is integrated into the backend in the workspace bundle. |
| Desktop simulator | Portrait 128 × 256 OLED, Talk and wheel controls, selectable computer audio, Demo/Loopback/Live modes, mute, local thread history, and one pending recording per profile. Live pairs through PHP and opens a direct OpenAI WebSocket after Talk is released. |
| Shared history | Conversation tables exist. PHP history endpoints, atomic turn saving with duplicate protection, active-thread sync, and deletion are implemented and connected to the Live simulator. The API accepts and preserves optional language metadata; automatic language detection is still pending. The simulator uses the first saved question as a language cue. |
| Firmware and case | The earlier sections describe the hardware and controls. The workspace bundle starts before ESP-IDF firmware, PCB, and enclosure CAD. |

Desktop controls were exercised in Tk. Realtime events and PCM processing were checked with mocks, and the key relational constraints were exercised using a SQLite translation. The first validation milestone is to deploy on PHP 8.4/MariaDB, pair the simulator, and complete one spoken and one muted exchange with real audio. Then implement the shared history API before wiring it into the simulator and firmware.

## Build and test order

1. **Desktop proof.** Verify PHP-issued Realtime credentials, direct audio, mute, and transcript saving. Measure time to first text and first audio. Verify that two threads started in different languages retain their own context and reply language after switching between them and restarting the backend.
2. **Bench device.** Test invite-only signup, including expired, revoked, and redeemed invites. Then test device pairing, pairing code expiry, unlinking, and access isolation between accounts. Verify both wake actions, press-to-talk, playback, mute, history preview, resume, and deletion. Verify that wheel wake shows the cached reply with the mic and Wi-Fi idle. Verify that Talk goes Back in menus and that releasing it after closing the last menu leaves the mic idle. Check the recording bar during slow Wi-Fi reconnect and at the 30-second limit. Press Talk during playback to verify that old audio stops and the next question starts recording. Check that a transcript save retry creates only one turn, and verify access from both saved Wi-Fi networks. Disable Wi-Fi, reboot, and verify that the last used conversation is still readable. Fill the cache to check that the newest turns remain and the OLED marks the offline boundary. Drop the connection after recording, reboot, reconnect, and retry the saved question in its original conversation.
3. **Fit print and custom PCB.** Confirm the TCC drawing and pinout, then fit-check the glass, flex, connector, cell, wheel, and speaker before fixing the PCB outline.
4. **Power validation.** Measure whole-device sleep current and charge used by a full spoken turn. Test for brownouts with low battery, Wi-Fi transmission, and speaker playback. The earlier estimate was about four weeks at 30 spoken questions per day with 100 µA asleep and roughly 1.76 mAh per turn. Treat it as a model until measured.

## Hardware references

- [TCC SYO256128027ASWCG01 listing](https://tcclcd.en.made-in-china.com/product/qAyYXrixYVWR/China-Monochrome-256-128-LCD-Module-SSD1363-Driver-Spi-I2c-Interface-256X128-OLED-Display.html)
- [LaskaKit module mechanical drawing](https://www.laskakit.cz/user/related_files/laskakit-2-7--256x128-oled-displej-i--c--bily-dimm.jpg)
- [LiPol Battery LP553580 specifications](https://www.lipolbattery.com/Experience-Next-Level-Performance-High-Power-LiPo-Battery.html)
- [Espressif ESP32-S3-WROOM-1 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf)
- [Waveshare development board pinout](https://docs.waveshare.com/ESP32-S3-DEV-KIT-N8R8#pinout-definition)
- [SparkFun DEV-14809 hookup guide](https://media.digikey.com/pdf/Data%20Sheets/Sparkfun%20PDFs/I2S_Audio_Breakout_Hookup_Guide_Web.pdf)
- [Adafruit microphone breakout pinout](https://learn.adafruit.com/adafruit-i2s-mems-microphone-breakout/pinouts)
- [SPH0645LM4H-B Rev C datasheet](https://www.knowles.com/docs/default-source/model-downloads/sph0645lm4h-b-datasheet-rev-c.pdf)
- [Earlier SPH0645 datasheet linked by Adafruit](https://cdn-shop.adafruit.com/product-files/3421/i2S%20Datasheet.PDF)
