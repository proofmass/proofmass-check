# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Progress of a run as JSON Lines (--events FILE): one object per line, written as the run goes.

A program that starts proofmass-check, such as the GUI, reads this file to show the progress. It
does not read stdout: stdout is for people, and an engine can print to it. docs/gui.md, section 5.2,
lists the events.

Every event has "event", its name, and "t", the seconds since the command started. Events of one
asset also have "asset", the asset's file as the command line gave it.
"""

import json
import time
from pathlib import Path
from typing import TextIO


class Events:
    """Writes events to a file, or nothing when the run has no --events."""

    def __init__(self, path: Path | None = None):
        self._file: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, "w", encoding="utf-8")  # noqa: SIM115  open for the whole run
        self._start = time.monotonic()

    def __call__(self, event: str, **fields) -> None:
        if self._file is None:
            return
        line = {"event": event, "t": round(time.monotonic() - self._start, 2)} | fields
        # Flushed at once: the reader follows the file while the run goes, and an engine that
        # crashes must not take the last events with it.
        self._file.write(json.dumps(line, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def asset_events(events: Events, asset: str):
    """The same events, with "asset" added to each."""

    def emit(event: str, **fields) -> None:
        events(event, asset=asset, **fields)

    return emit
