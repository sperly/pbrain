"""Desktop stand-in for the PocketBrain controls and display."""
import base64
import hashlib
import re
import sys
import tkinter as tk
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from tkinter import messagebox, ttk
from uuid import uuid4

import audio
import history as shared_history
import store
import transport
from display import OLED

MODES = ("Demo", "Loopback", "Live")
HELP = "Hold Talk to ask. Turn the wheel to scroll. Push the wheel for the menu."


class Simulator:
    def __init__(self, root, directory):
        self.root = root
        self.directory = directory
        self.config_path = directory / "settings.json"
        self.config = store.read(self.config_path, {})
        self.base = tk.StringVar(value=self.config.get("backend", ""))
        self.mode = tk.StringVar(value=self.config.get("mode", "Demo"))
        self.input = tk.StringVar(value=self.config.get("input", "System default"))
        self.output = tk.StringVar(value=self.config.get("output", "System default"))
        self.notice = tk.StringVar(value="Space = Talk   |   Up / Down = Turn wheel   |   Enter = Push wheel")
        self.messages = Queue()
        self.capture = self.playback = self.job = self.pending = None
        self.held = self.recording = False
        self.release_timer = self.preview = None
        self.generation = 0
        self.menus = []
        self.reply = ""
        self.scroll = None
        self.recorded = b""
        self.progress = None
        self.speaker_failed = False
        self.pair_code = None
        self.pair_uri = None
        self.pair_deadline = None
        self.volume = int(self.config.get("volume", 70))
        self.mute = bool(self.config.get("mute", False))
        self.credentials = store.read(directory / "credentials.json", {})
        self.root.title("PocketBrain Desktop")
        self.build_ui()
        self.load_profile()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(25, self.tick)

    def build_ui(self):
        pane = ttk.Frame(self.root, padding=10)
        pane.grid(sticky="nsew")
        tools = ttk.Frame(pane)
        tools.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(tools, text="Mode").grid(row=0, column=0, sticky="w")
        mode = ttk.Combobox(tools, values=MODES, textvariable=self.mode, state="readonly", width=12)
        mode.grid(row=0, column=1, sticky="w", padx=4)
        mode.bind("<<ComboboxSelected>>", self.change_mode)
        ttk.Button(tools, text="Audio devices...", command=self.audio_dialog).grid(row=0, column=2, sticky="e")
        ttk.Label(tools, text="Backend").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(tools, textvariable=self.base, width=34).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(tools, text="Link account / cancel", command=self.start_pairing).grid(row=1, column=2, sticky="ew")
        tools.columnconfigure(1, weight=1)

        talk = ttk.Button(pane, text="TALK\nhold", takefocus=False)
        talk.grid(row=1, column=0, sticky="n", pady=60, padx=(0, 8))
        talk.bind("<ButtonPress-1>", lambda e: self.press_talk())
        talk.bind("<ButtonRelease-1>", lambda e: self.release_talk())
        screen = tk.Label(pane, background="black", borderwidth=0)
        screen.grid(row=1, column=1, pady=8)
        self.oled = OLED(screen)
        wheel = ttk.Frame(pane)
        wheel.grid(row=1, column=2, sticky="n", pady=60, padx=(8, 0))
        for caption, action in (("UP", lambda: self.turn(-1)), ("PUSH", self.push), ("DOWN", lambda: self.turn(1))):
            ttk.Button(wheel, text=caption, width=5, command=action, takefocus=False).pack(pady=2)
        for widget in (screen, wheel, *wheel.winfo_children()):
            widget.bind("<MouseWheel>", lambda e: self.turn(-1 if e.delta > 0 else 1))
            widget.bind("<Button-4>", lambda e: self.turn(-1))
            widget.bind("<Button-5>", lambda e: self.turn(1))
        ttk.Label(pane, textvariable=self.notice, wraplength=415).grid(row=2, column=0, columnspan=3, sticky="w")

        for key, action in (("<Up>", lambda: self.turn(-1)), ("<Down>", lambda: self.turn(1)),
                            ("<Return>", self.push), ("<Escape>", self.back),
                            ("<KeyPress-space>", self.key_talk), ("<KeyRelease-space>", self.key_release)):
            self.root.bind(key, lambda event, fn=action: self.key(event, fn))
        self.root.bind("<ButtonPress-1>", self.focus_controls, add="+")
        self.root.bind("<FocusOut>", self.on_focus_out, add="+")
        self.root.focus_set()

    def on_focus_out(self, event):
        if self.held:
            self.root.after_idle(self.release_if_unfocused)

    def release_if_unfocused(self):
        if self.held and self.root.focus_get() is None:
            self.release_talk()

    def focus_controls(self, event):
        if isinstance(event.widget, (ttk.Button, tk.Label)):
            self.root.focus_set()

    def key(self, event, fn):
        # Window switches can leave queued shortcuts behind. Only the focused
        # emulator window may dispatch Talk/Back or other device controls.
        focused = self.root.focus_get()
        if focused is None or focused.winfo_toplevel() != self.root:
            return
        if not isinstance(event.widget, (ttk.Entry, ttk.Combobox, tk.Entry)):
            fn()
            return "break"

    def key_talk(self):
        if self.release_timer is not None:
            self.root.after_cancel(self.release_timer)
            self.release_timer = None
        else:
            self.press_talk()

    def key_release(self):
        if self.release_timer is not None:
            self.root.after_cancel(self.release_timer)
        self.release_timer = self.root.after(45, self.release_talk)

    def save_settings(self):
        self.config.update(mode=self.current_mode, backend=self.current_base, mute=self.mute,
                           volume=self.volume, input=self.input.get(), output=self.output.get())
        store.write(self.config_path, self.config)

    def load_profile(self, sync=True):
        self.clear_pairing()
        self.current_mode = self.mode.get()
        self.current_base = self.base.get().strip().rstrip("/")
        if self.current_mode not in MODES:
            self.mode.set("Demo")
            self.current_mode = "Demo"
        token = self.credentials.get(self.current_base, "")
        self.token = token
        key = self.current_mode.lower()
        if self.current_mode == "Live":
            key += "-" + hashlib.sha256((self.current_base + "\n" + token).encode()).hexdigest()[:20]
        self.history_path = self.directory / (key + "-history.json")
        self.pending_path = self.directory / (key + "-pending.json")
        self.history = store.read(self.history_path, {"active": None, "threads": {}})
        self.pending = store.read(self.pending_path, None)
        if self.pending:
            thread = self.history["threads"].get(self.pending["thread"], {})
            if any(turn["id"] == self.pending["id"] for turn in thread.get("turns", [])):
                self.clear_pending()
        self.preview = None
        self.reply = ""
        self.scroll = None
        self.menus.clear()
        self.draw()
        if sync and self.current_mode == "Live" and self.token:
            self.sync_history()

    def change_mode(self, event=None):
        if self.held or self.job or self.playback:
            self.mode.set(self.current_mode)
            self.notice.set("Finish the current action before changing modes.")
            return
        self.load_profile()
        self.save_settings()
        self.root.focus_set()

    def audio_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("PocketBrain audio")
        dialog.transient(self.root)
        dialog.grab_set()
        for row, (direction, setting) in enumerate((("input", self.input), ("output", self.output))):
            ttk.Label(dialog, text=direction.capitalize(), padding=6).grid(row=row, column=0)
            choices = ["System default"]
            try:
                choices += [f"{index}: {name}" for index, name in audio.devices(direction)]
            except Exception as exc:
                ttk.Label(dialog, text=str(exc), wraplength=270).grid(row=3 + row, columnspan=2)
            ttk.Combobox(dialog, textvariable=setting, values=choices, state="readonly", width=42).grid(
                row=row, column=1, padx=6, pady=6)
        def finish():
            self.save_settings()
            dialog.destroy()
            self.root.focus_set()
        ttk.Button(dialog, text="Done", command=finish).grid(row=2, columnspan=2, pady=6)
        dialog.protocol("WM_DELETE_WINDOW", finish)

    def device_index(self, setting, direction):
        selected = setting.get()
        if selected == "System default":
            return None
        for index, name in audio.devices(direction):
            if selected == f"{index}: {name}":
                return index
        return None

    def start_job(self, kind, work):
        self.generation += 1
        generation = self.generation
        stop = Event()
        self.job = (kind, stop)
        def emit(event, value):
            self.messages.put((generation, event, value))
        def worker():
            try:
                work(stop, emit)
            except Exception as error:
                emit("error", str(error))
        Thread(target=worker, daemon=True).start()

    def start_pairing(self):
        if self.job and self.job[0] == "pair":
            self.back()
            return
        if self.held or self.job or self.playback:
            self.notice.set("Finish the current action before linking an account.")
            return
        base = self.base.get().strip().rstrip("/")
        if self.credentials.get(base):
            self.notice.set("Already linked; unlink locally before pairing again.")
            return
        self.mode.set("Live")
        self.load_profile(sync=False)
        self.save_settings()
        base = self.current_base
        self.clear_pairing()
        self.scroll = 0
        self.root.focus_set()
        self.start_job("pair", lambda stop, emit: transport.pair(base, stop, emit))
        self.draw()

    def clear_pairing(self):
        self.pair_code = self.pair_uri = self.pair_deadline = None
        self.pair_error = None

    def confirm_unlink(self):
        if not self.token:
            self.notice.set("No account linked to this backend.")
            return
        self.add_menu("Unlink locally?", [("Keep", self.back), ("Unlink and clear data", self.unlink_local)])
        self.notice.set("Unlink clears this device's cached history and saved question. "
                        "Also revoke the device in the web dashboard when transferring it.")

    def unlink_local(self):
        if self.held or self.job or self.playback:
            self.notice.set("Finish the current action before unlinking.")
            return
        key = "live-" + hashlib.sha256((self.current_base + "\n" + self.token).encode()).hexdigest()[:20]
        # Clear the old account's files before removing its credential, as on ESP32.
        credentials = self.credentials.copy()
        credentials.pop(self.current_base, None)
        try:
            for suffix in ("pending", "history"):
                (self.directory / f"{key}-{suffix}.json").unlink(missing_ok=True)
            store.write(self.directory / "credentials.json", credentials)
        except OSError as error:
            self.notice.set(f"Could not finish local unlink: {error}. Retry Unlink locally.")
            return
        self.credentials = credentials
        self.cancel_job()
        self.clear_pairing()
        self.base.set(self.current_base)
        self.load_profile(sync=False)
        self.notice.set("Unlinked locally. Revoke the device in the web dashboard as well when transferring it.")

    def press_talk(self):
        if self.held:
            return "break"
        self.held = True
        if self.menus or self.preview or self.pair_error or (self.job and self.job[0] == "pair"):
            self.back()
            return "break"
        if self.job and self.job[0] != "voice":
            self.notice.set("Wait for conversation sync to finish.")
            return "break"
        if self.job or self.playback:
            self.interrupt()
        if self.pending:
            self.pending_menu()
            return "break"
        if self.current_mode == "Live" and not self.token:
            self.notice.set("Enter your backend URL and pair this simulator first.")
            self.draw()
            return "break"
        try:
            if self.current_mode != "Demo":
                self.capture = audio.Capture(self.device_index(self.input, "input"))
            self.notice.set(HELP)
            self.recording = True
            self.recorded = b""
            self.record_start = monotonic()
            self.progress = 1.0
        except Exception as error:
            self.notice.set(f"Microphone: {error}")
        self.draw()
        return "break"

    def stop_capture(self):
        if self.capture:
            capture, self.capture = self.capture, None
            self.recorded = capture.finish()[:transport.MAX_BYTES]
        self.progress = 0.0

    def release_talk(self):
        timer, self.release_timer = self.release_timer, None
        if timer is not None:
            self.root.after_cancel(timer)
        if not self.held:
            return "break"
        self.held = False
        if not self.recording:
            return "break"
        self.recording = False
        try:
            if self.progress != 0:
                self.stop_capture()
            if self.current_mode != "Demo" and len(self.recorded) < transport.MIN_BYTES:
                self.notice.set("Hold Talk for at least 0.1 seconds to record a question.")
                return "break"
            thread = self.history["active"]
            if self.current_mode != "Live":
                thread = thread or uuid4().hex
            pending = {"id": str(uuid4()), "thread": thread,
                       "audio": base64.b64encode(self.recorded).decode("ascii")}
            store.write(self.pending_path, pending)
            self.pending = pending
            self.send_pending()
        except Exception as error:
            self.notice.set(f"Could not record the question: {error}")
        finally:
            self.progress = None
            self.draw()
        return "break"

    def send_pending(self):
        pending = store.read(self.pending_path, self.pending)
        self.pending = pending
        if pending is None:
            return
        if self.current_mode == "Live" and "transcript" in pending:
            self.retry_save()
            return
        self.menus.clear()
        self.reply = ""
        self.scroll = None
        self.speaker_failed = False
        pcm = base64.b64decode(pending["audio"], validate=True)
        mode = self.current_mode
        base, token, muted = self.current_base, self.token, self.mute
        thread = self.history["threads"].get(pending["thread"], {})
        # Retain the first turn as the language anchor even in a long thread.
        turns = thread.get("turns", [])
        context = turns[:1] + turns[-5:] if len(turns) > 6 else turns
        def work(stop, emit):
            if mode == "Live":
                live_context = []
                if pending["thread"] is not None:
                    remote = shared_history.transcript(base, token, pending["thread"])
                    turns = remote["turns"]
                    live_context = turns[:1] + turns[-5:] if len(turns) > 6 else turns
                if not stop.is_set():
                    transport.voice(base, token, pcm, muted, live_context, stop, emit)
            else:
                transport.demo(pcm, muted, stop, emit, mode == "Loopback")
        self.start_job("voice", work)
        self.draw()

    def clear_pending(self):
        self.pending_path.unlink(missing_ok=True)
        self.pending = None

    def save_reply(self, question, interrupted=False):
        if not self.pending:
            return
        if self.current_mode == "Live":
            self.pending["transcript"] = {
                "question_text": question, "reply_text": self.reply.strip(),
                "reply_status": "interrupted" if interrupted else "complete",
            }
            # Persist before HTTP: a save retry must not generate another answer.
            store.write(self.pending_path, self.pending)
            self.retry_save()
            return
        thread_id = self.pending["thread"]
        label = (question.strip() or ("Audio check" if self.current_mode == "Loopback" else "Conversation"))[:42]
        threads = self.history["threads"].copy()
        thread = threads.pop(thread_id, {"title": label, "turns": []})
        turn = {
            "id": self.pending["id"], "question": question, "reply": self.reply.strip(),
            "interrupted": interrupted,
        }
        threads[thread_id] = {"title": thread["title"], "turns": [*thread["turns"], turn]}
        updated = {"active": thread_id, "threads": threads}
        store.write(self.history_path, updated)
        self.history = updated
        self.clear_pending()

    def cancel_job(self):
        if self.job:
            self.job[1].set()
            self.job = None
        self.generation += 1

    def stop_playback(self):
        if self.playback:
            playback, self.playback = self.playback, None
            try:
                playback.stop()
            except Exception as error:
                self.notice.set(f"Speaker: {error}")

    def interrupt(self):
        self.stop_playback()
        if self.job and self.job[0] == "voice":
            self.cancel_job()
            if self.pending:
                if self.current_mode == "Live":
                    self.notice.set("Reply stopped. The recording is saved for retry or discard.")
                elif self.reply.strip():
                    self.save_reply("", interrupted=True)
                else:
                    self.clear_pending()

    def clear_reply_view(self):
        self.reply = ""
        self.scroll = None

    def add_menu(self, title, entries):
        self.menus.append([title, entries, 0])
        self.draw()

    def pending_menu(self):
        self.add_menu("Question saved", [
            ("Retry save" if self.pending and "transcript" in self.pending else "Retry recording", self.send_pending),
            ("Discard recording", self.confirm_discard),
            ("Menu", self.main_menu),
        ])

    def confirm_discard(self):
        self.add_menu("Discard recording?", [("Keep", self.back), ("Discard", self.discard)])

    def discard(self):
        self.clear_pending()
        self.menus.clear()
        self.clear_reply_view()

    def main_menu(self):
        self.add_menu("Menu", [
            ("New conversation", self.new_thread), ("History", self.history_menu),
            ("Mute: " + ("on" if self.mute else "off"), self.toggle_mute), ("Volume", self.volume_menu),
            ("Link account", self.start_pairing), ("Usage", self.show_usage),
            ("Unlink locally", self.confirm_unlink),
        ])

    def show_usage(self):
        self.notice.set("Usage is available in the backend dashboard.")

    def new_thread(self):
        if self.current_mode == "Live":
            self.remote_selection(None)
            return
        self.history["active"] = None
        store.write(self.history_path, self.history)
        self.menus.clear()
        self.clear_reply_view()

    def history_menu(self):
        if self.current_mode == "Live":
            self.sync_history(show_menu=True)
            return
        self.show_history_menu()

    def show_history_menu(self):
        entries = [(thread["title"], lambda key=key: self.open_thread(key))
                   for key, thread in reversed(self.history["threads"].items())]
        self.add_menu("History", entries or [("No conversations", self.back)])

    def open_thread(self, key):
        if self.current_mode == "Live":
            base, token = self.current_base, self.token
            self.menus.clear()
            self.start_job("history", lambda stop, emit: emit(
                "thread_loaded", (key, shared_history.transcript(base, token, key))))
            return
        self.menus.clear()
        self.preview = key
        self.clear_reply_view()

    def preview_menu(self):
        self.add_menu("Conversation", [
            ("Continue here", self.continue_thread), ("Delete conversation", self.confirm_delete),
        ])

    def continue_thread(self):
        if self.current_mode == "Live":
            self.remote_selection(self.preview)
            return
        self.history["active"] = self.preview
        store.write(self.history_path, self.history)
        self.preview = None
        self.menus.clear()

    def confirm_delete(self):
        self.add_menu("Delete thread?", [("Keep", self.back), ("Delete", self.delete_thread)])

    def delete_thread(self):
        key = self.preview
        if self.current_mode == "Live":
            base, token = self.current_base, self.token
            self.menus.clear()
            def work(stop, emit):
                transport.api(base, "conversation-delete", token, payload={"conversation_id": key})
                emit("history_synced", (shared_history.sync(base, token, {}), False))
            self.start_job("history", work)
            return
        self.history["threads"].pop(key, None)
        if self.history["active"] == key:
            self.history["active"] = None
        store.write(self.history_path, self.history)
        self.preview = None
        self.menus.clear()
        self.clear_reply_view()

    def toggle_mute(self):
        self.mute = not self.mute
        self.save_settings()
        self.menus.pop()
        self.main_menu()

    def volume_menu(self):
        self.add_menu("Volume", [(f"{value}%" + (" *" if value == self.volume else ""),
                                  lambda v=value: self.set_volume(v)) for value in range(0, 101, 10)])

    def set_volume(self, value):
        self.volume = value
        self.save_settings()
        self.back()

    def back(self):
        if self.pair_error or (self.job and self.job[0] == "pair"):
            self.cancel_job()
            self.clear_pairing()
            self.scroll = None
            self.notice.set("Account linking cancelled.")
        elif self.menus:
            self.menus.pop()
        elif self.preview:
            self.preview = None
            self.clear_reply_view()
        self.draw()

    def turn(self, step):
        if self.menus:
            menu = self.menus[-1]
            menu[2] = max(0, min(len(menu[1]) - 1, menu[2] + step))
        else:
            start = self.oled.max_scroll if self.scroll is None else self.scroll
            end = max(0, min(self.oled.max_scroll, start + step))
            self.scroll = None if end == self.oled.max_scroll else end
        self.draw()
        return "break"

    def push(self):
        if self.pair_error:
            self.start_pairing()
            return "break"
        if self.recording or (self.job and self.job[0] == "pair"):
            return "break"
        if self.job and self.job[0] != "voice":
            return "break"
        if self.job or self.playback:
            self.interrupt()
        elif self.menus:
            _, entries, selected = self.menus[-1]
            entries[selected][1]()
        elif self.preview:
            self.preview_menu()
        elif self.pending:
            self.pending_menu()
        else:
            self.main_menu()
        self.draw()
        return "break"

    def draw(self):
        title = "PocketBrain"
        footer = "Talk / Wheel"
        text = HELP
        if self.menus:
            title, entries, selected = self.menus[-1]
            self.oled.show(title, "", "Talk: Back", menu=[label for label, _ in entries], selected=selected)
            return
        if self.pair_error or (self.job and self.job[0] == "pair"):
            title = "Link account"
            text = (f"Code: {self.pair_code}\n\n{self.pair_uri}\n\n"
                    "Open this address on another device. Sign in and approve the code under My devices."
                    if self.pair_code else "Requesting a pairing code...")
            seconds = max(0, int(self.pair_deadline - monotonic())) if self.pair_deadline else None
            footer = f"{seconds}s / Talk: Cancel" if seconds is not None else "Talk: Cancel"
            if self.pair_error:
                title = "Link interrupted"
                text = (f"Code: {self.pair_code}\n{self.pair_uri}\n\n" if self.pair_code else "") + self.pair_error
                footer = "Push retry/Talk back"
        elif self.job and self.job[0] in ("history", "save"):
            title, text = "Conversations", "Saving reply..." if self.job[0] == "save" else "Syncing history..."
        elif self.recording:
            title = "Listening" if self.progress else "Limit reached"
            text = "Release Talk to send."
            footer = f"{max(0, 30 - int(monotonic() - self.record_start))} seconds left"
        elif self.pending and not self.job:
            title, text = "Question saved", "Push the wheel to retry or discard the saved recording."
        elif self.current_mode == "Live" and not self.token:
            title, text = "Link account", "Push the wheel and select Link account. Open the verification address on another device to approve the code."
        else:
            key = self.preview or self.history["active"]
            thread = self.history["threads"].get(key, {})
            if thread:
                title = thread["title"]
                blocks = []
                for turn in thread["turns"]:
                    if turn["question"]:
                        blocks.append("> " + turn["question"])
                    blocks.append(turn["reply"] + ("\n[Interrupted]" if turn["interrupted"] else ""))
                text = "\n\n".join(blocks)
            if self.job and self.job[0] == "voice":
                title = "Reply" if self.reply else "Connecting"
                text = self.reply or "Waiting for a reply..."
            if self.preview:
                footer = "Push: Options"
            elif self.playback:
                footer = "Push: Stop"
            elif self.mute:
                footer = "Muted / Wheel"
        self.oled.show(title, text, footer, scroll=self.scroll, progress=self.progress)

    def retry_save(self):
        base, token, pending = self.current_base, self.token, self.pending.copy()
        self.menus.clear()
        self.start_job("save", lambda stop, emit: emit("turn_saved", shared_history.save(base, token, pending)))

    def sync_history(self, show_menu=False):
        base, token = self.current_base, self.token
        cached = self.history["threads"].copy()
        self.menus.clear()
        self.start_job("history", lambda stop, emit: emit(
            "history_synced", (shared_history.sync(base, token, cached), show_menu)))

    def remote_selection(self, key):
        base, token = self.current_base, self.token
        cached = self.history["threads"].copy()
        self.menus.clear()
        def work(stop, emit):
            transport.api(base, "conversation-active", token, payload={"conversation_id": key})
            emit("history_synced", (shared_history.sync(base, token, cached), False))
        self.start_job("history", work)

    def on_message(self, event, value):
        if event == "history_synced":
            self.job = None
            self.history, show_menu = value
            store.write(self.history_path, self.history)
            self.preview = None
            self.clear_reply_view()
            self.notice.set(HELP)
            if show_menu:
                self.show_history_menu()
        elif event == "thread_loaded":
            self.job = None
            key, thread = value
            self.history["threads"][key] = thread
            store.write(self.history_path, self.history)
            self.preview = key
            self.clear_reply_view()
        elif event == "turn_saved":
            self.job = None
            key = value["conversation_id"]
            pending = self.pending
            text = pending["transcript"]
            thread = self.history["threads"].pop(key, {
                "title": text["question_text"].strip()[:160] or "Conversation", "turns": [],
            })
            if not any(turn["id"] == pending["id"] for turn in thread["turns"]):
                thread["turns"].append({
                    "id": pending["id"], "question": text["question_text"],
                    "reply": text["reply_text"], "interrupted": text["reply_status"] == "interrupted",
                })
            self.history["threads"][key] = thread
            self.history["active"] = key
            store.write(self.history_path, self.history)
            self.clear_pending()
            self.sync_history()
        elif event == "text":
            self.reply += value
        elif event == "audio" and not self.speaker_failed:
            if not self.playback:
                self.playback = audio.Playback(self.device_index(self.output, "output"), self.volume)
            self.playback.append(value)
        elif event == "done":
            self.job = None
            self.save_reply(value)
        elif event == "pair_code":
            self.pair_code, self.pair_uri, self.pair_deadline = value
            self.notice.set(f"Open {self.pair_uri} and approve code {self.pair_code} under My devices.")
        elif event == "pair_wait":
            self.notice.set(value)
        elif event == "paired":
            if not isinstance(value, str) or re.fullmatch(r"[a-fA-F0-9]{64}", value) is None:
                raise ValueError("Backend returned an invalid device credential.")
            credentials = {**self.credentials, self.current_base: value}
            store.write(self.directory / "credentials.json", credentials)
            self.credentials = credentials
            self.job = None
            self.clear_pairing()
            self.base.set(self.current_base)
            self.load_profile()
            self.notice.set("Account linked. Hold Talk to record.")
        elif event == "error":
            pairing = self.job and self.job[0] == "pair"
            self.job = None
            if pairing:
                self.pair_error = value
            else:
                self.clear_pairing()
            self.stop_playback()
            self.notice.set(value)

    def tick(self):
        redraw = bool(self.job and self.job[0] == "pair" and self.pair_deadline)
        try:
            if self.recording and self.progress:
                self.progress = max(0.0, 1.0 - (monotonic() - self.record_start) / 30)
                if self.progress == 0:
                    try:
                        self.stop_capture()
                    except Exception as error:
                        self.recording = False
                        self.notice.set(f"Microphone: {error}")
                redraw = True

            for _ in range(64):
                try:
                    generation, event, value = self.messages.get_nowait()
                except Empty:
                    break
                if generation != self.generation:
                    continue
                try:
                    self.on_message(event, value)
                except Exception as error:
                    if event == "audio":
                        self.speaker_failed = True
                        self.stop_playback()
                        self.notice.set(f"Speaker: {error}")
                    else:
                        self.on_message("error", str(error))
                        self.cancel_job()
                redraw = True
            if self.playback and not self.job and not self.playback.busy():
                self.stop_playback()
                redraw = True
            if redraw:
                self.draw()
        finally:
            self.root.after(40, self.tick)

    def close(self):
        self.cancel_job()
        self.stop_playback()
        if self.capture:
            try:
                self.capture.finish()
            except Exception:
                pass
        self.root.destroy()


def main():
    if "--check" in sys.argv:
        print("PocketBrain dependencies imported successfully.")
        for direction in ("input", "output"):
            try:
                print(f"{direction}: {audio.devices(direction)}")
            except Exception as error:
                print(f"{direction}: {error}")
        return
    root = tk.Tk()
    try:
        Simulator(root, store.state_directory())
    except (ValueError, OSError) as error:
        messagebox.showerror("PocketBrain", str(error))
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
