"""Private local desktop profiles and the single pending recording per profile."""
import json
import os
import tempfile
from pathlib import Path


def state_directory():
    root = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_STATE_HOME")
    path = Path(root or (Path.home() / ".local" / "state")) / "pocketbrain-desktop"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_bytes(path, contents):
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def write(path, value):
    write_bytes(path, json.dumps(value, ensure_ascii=False).encode("utf-8"))
