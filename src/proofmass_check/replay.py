# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The replay: the motion of every body during a run, in replay.bin next to results.json.

docs/gui.md, section 5.5, describes it. Each engine operation (a settle, a move, a push, a drop, a
drive, or one trial of the grip scene) gives a clip. A clip has frames: its time from the start of
the clip, then the position and rotation of each body, in the world.

- The runner starts and ends a clip around each operation, with the check it belongs to.
- The check labels the clip with the measurement it gives: `with replay.label(subject, case) as
  clip:` around the engine call, then `clip.ok = ...` when it has decided. Without a recorder, the
  label does nothing.
- The engine calls Recorder.frame() while it steps: at the start, about FPS times per simulated
  second, and at the end.

Recording only reads the engine's state, so a run gives the same results with and without it.
"""

import json
import math
import secrets
import struct
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FILE_NAME = "replay.bin"
MAGIC = b"PMREPLAY"
FORMAT_VERSION = 1
FPS = 30  # frames per simulated second, to the nearest step of the engine
POSE = 7  # x y z qw qx qy qz


@dataclass
class Label:
    """What a clip shows, as the check gives it. ok is set by the check once it has decided."""

    subject: str = ""  # as the measurement's: a joint, a gripper site, or "" for the whole asset
    case: str = ""  # as the measurement's: "25%", "upper", "out of the fingers", or ""
    attempt: str = ""  # which clip of several for one measurement: "pose 17", "push 74 N m", "1.7 kg"
    check: str | None = None  # a check ID other than the runner's: SHAKE for the shaken trial of GRIP
    ok: bool | None = None


_current: ContextVar[Label | None] = ContextVar("proofmass_check_replay_label", default=None)


@contextmanager
def label(subject: str = "", case: str = "", attempt: str = "", check: str | None = None) -> Iterator[Label]:
    """The label of the engine operations called inside the block."""
    current = Label(subject, case, attempt, check)
    token = _current.set(current)
    try:
        yield current
    finally:
        _current.reset(token)


@dataclass(eq=False)
class Clip:
    check: str
    label: Label
    operation: str
    arguments: dict
    box: tuple[float, float, float] | None  # the size of the grip box, m, or None
    frames: list[np.ndarray] = field(default_factory=list)  # each: time, then POSE values for each body


class Recorder:
    """The clips of one asset's run. bodies: the body paths of the file, in the order of the frames."""

    def __init__(self, bodies: Sequence[str]):
        self.bodies = tuple(bodies)
        self.id = secrets.token_hex(16)  # results.json carries it too, so a replay is never shown for another run
        self.clips: list[Clip] = []
        self._open: Clip | None = None

    def start(self, check: str, operation: str, arguments: dict, box: Sequence[float] | None = None) -> None:
        """A new clip, for an engine operation that starts now. Its label is the check's current one."""
        current = _current.get() or Label()
        size = tuple(float(s) for s in box) if box is not None else None
        self._open = Clip(current.check or check, current, operation, _plain(arguments), size)
        self.clips.append(self._open)

    def end(self) -> None:
        self._open = None

    def frame(self, time: float, poses) -> None:
        """One frame of the clip that is open: poses is (bodies, 7), with the grip box last in a grip clip.

        A frame at time 0 starts the clip's frames again. Newton runs a measurement again when a buffer
        of its solver ran out, and only the last run counts. Without an open clip, the frame is dropped.
        """
        clip = self._open
        if clip is None:
            return
        poses = np.asarray(poses, dtype=np.float64)
        rows = len(self.bodies) + (clip.box is not None)
        if poses.shape != (rows, POSE):
            raise ValueError(f"a frame of this clip has {rows} poses of {POSE} values, not shape {poses.shape}")
        if time == 0:
            clip.frames.clear()
        clip.frames.append(np.concatenate(([time], poses.ravel())).astype("<f4"))


def write(recorder: Recorder, folder: str | Path, engine: str, sha256: str) -> Path:
    """replay.bin in folder (docs/gui.md, section 5.5)."""
    clips, blocks, offset = [], [], 0
    for clip in recorder.clips:
        width = 1 + POSE * (len(recorder.bodies) + (clip.box is not None))
        frames = np.stack(clip.frames) if clip.frames else np.zeros((0, width), "<f4")
        clips.append(
            {
                "check": clip.check,
                "subject": clip.label.subject,
                "case": clip.label.case,
                "attempt": clip.label.attempt,
                "ok": clip.label.ok,
                "operation": clip.operation,
                "arguments": clip.arguments,
                "box": list(clip.box) if clip.box is not None else None,
                "offset": offset,
                "frames": len(frames),
            }
        )
        blocks.append(frames)
        offset += frames.size
    header = {"id": recorder.id, "engine": engine, "sha256": sha256, "bodies": list(recorder.bodies), "clips": clips}
    text = json.dumps(header, allow_nan=False, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)  # the frames start on a multiple of 4 bytes
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / FILE_NAME
    with open(path, "wb") as f:
        f.write(MAGIC + struct.pack("<II", FORMAT_VERSION, len(text)) + text)
        for frames in blocks:
            f.write(frames.astype("<f4", copy=False).tobytes())
    return path


def header(data: bytes) -> dict:
    """The header of a replay file, from its bytes. ValueError when they are not a replay this version reads."""
    if len(data) < 16 or data[:8] != MAGIC:
        raise ValueError("not a replay file")
    version, n = struct.unpack("<II", data[8:16])
    if version != FORMAT_VERSION:
        raise ValueError(f"replay format {version}: this version of proofmass-check reads format {FORMAT_VERSION}")
    return json.loads(data[16 : 16 + n])


def read(path: str | Path) -> tuple[dict, list[np.ndarray]]:
    """The header of a replay file, and the frames of each clip as a (frames, values) array."""
    data = Path(path).read_bytes()
    found = header(data)
    n = struct.unpack("<I", data[12:16])[0]
    values = np.frombuffer(data, "<f4", offset=16 + n)
    frames = []
    for clip in found["clips"]:
        width = 1 + POSE * (len(found["bodies"]) + (clip["box"] is not None))
        end = clip["offset"] + clip["frames"] * width
        frames.append(values[clip["offset"] : end].reshape(clip["frames"], width))
    return found, frames


def every(step: float) -> int:
    """The steps between two frames, for an engine that steps by `step` seconds: 8 at 1/240 s, 2 at 1/60 s."""
    return max(1, round(1 / (FPS * step)))


def _plain(value):
    """value with only what JSON holds: numpy values as numbers and lists, a value that is not finite as None."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_plain(v) for v in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    return str(value)
