"""Capture and play the firmware's 24 kHz signed little-endian PCM format."""
from collections import deque
from math import gcd
from threading import Lock

import numpy as np
from scipy.signal import resample_poly

from transport import RATE


def driver():
    try:
        import sounddevice
    except (ImportError, OSError):
        raise RuntimeError("Install sounddevice and the PortAudio runtime to use computer audio.") from None
    return sounddevice


def devices(direction):
    sd = driver()
    return [(index, info["name"]) for index, info in enumerate(sd.query_devices())
            if info[f"max_{direction}_channels"] > 0]


def format_for(device, direction):
    sd = driver()
    info = sd.query_devices(device, direction)
    check = sd.check_input_settings if direction == "input" else sd.check_output_settings
    for rate in dict.fromkeys((RATE, round(info["default_samplerate"]))):
        for channels in range(1, min(2, info[f"max_{direction}_channels"]) + 1):
            try:
                check(device=device, channels=channels, dtype="int16", samplerate=rate)
                return rate, channels
            except sd.PortAudioError:
                continue
    raise RuntimeError(f"The selected {direction} device does not accept 16-bit audio.")


class Capture:
    def __init__(self, device):
        self.rate, self.channels = format_for(device, "input")
        self.remaining = self.rate * self.channels * 2 * 30
        self.chunks = []
        self.stream = driver().RawInputStream(
            device=device, samplerate=self.rate, channels=self.channels,
            dtype="int16", callback=self.callback,
        )
        try:
            self.stream.start()
        except Exception:
            self.stream.close()
            raise

    def callback(self, data, frames, time_info, status):
        chunk = bytes(data)[:self.remaining]
        if chunk:
            self.chunks.append(chunk)
            self.remaining -= len(chunk)

    def finish(self):
        try:
            self.stream.abort()
        finally:
            self.stream.close()
        samples = np.frombuffer(b"".join(self.chunks), dtype=np.int16)
        if self.channels > 1:
            samples = samples.reshape(-1, self.channels).mean(axis=1)
        if self.rate != RATE and len(samples):
            divisor = gcd(self.rate, RATE)
            samples = resample_poly(samples.astype(float), RATE // divisor, self.rate // divisor)
        return np.clip(samples, -32768, 32767).astype("<i2").tobytes()


class Playback:
    def __init__(self, device, volume):
        self.rate, self.channels = format_for(device, "output")
        self.volume = volume
        self.queue = deque()
        self.lock = Lock()
        self.stream = driver().RawOutputStream(
            device=device, samplerate=self.rate, channels=self.channels,
            dtype="int16", callback=self.callback,
        )
        self.source_count = 0
        self.output_count = 0
        self.previous = None
        self.played_until = 0
        self.started = False

    def append(self, pcm):
        data = np.frombuffer(pcm, dtype="<i2")
        if not len(data):
            return
        if self.rate != RATE:
            # Preserve the fractional position across independently received chunks.
            origin = self.source_count
            limit = (origin + len(data) - 1) * self.rate // RATE + 1
            positions = np.arange(self.output_count, limit) * RATE / self.rate - origin
            if self.previous is not None:
                data = np.concatenate(([self.previous], data))
                positions += 1
            self.previous = data[-1]
            self.source_count += len(pcm) // 2
            self.output_count = limit
            data = np.rint(np.interp(positions, np.arange(len(data)), data))
        data = data.astype(np.int16)
        if self.channels > 1:
            data = np.repeat(data, self.channels)
        with self.lock:
            self.queue.append(data)
        if not self.started:
            self.stream.start()
            self.started = True

    def callback(self, output, frames, time_info, status):
        samples = np.frombuffer(output, dtype=np.int16)
        samples.fill(0)
        cursor = 0
        with self.lock:
            while cursor < len(samples) and self.queue:
                chunk = self.queue.popleft()
                count = min(len(samples) - cursor, len(chunk))
                samples[cursor:cursor + count] = chunk[:count] * (self.volume / 100.0)
                cursor += count
                if count < len(chunk):
                    self.queue.appendleft(chunk[count:])
            if cursor:
                start = time_info.outputBufferDacTime
                if start <= time_info.currentTime:
                    start = time_info.currentTime + self.stream.latency
                self.played_until = start + cursor / (self.rate * self.channels)

    def busy(self):
        if not self.started:
            return False
        now = self.stream.time
        with self.lock:
            return bool(self.queue) or now < self.played_until

    def stop(self):
        try:
            self.stream.abort()
        finally:
            self.stream.close()
