# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Batches: runs of proofmass-check that the GUI starts in the engines' Pythons (docs/gui.md, 4.3 and 6.2).

A batch is a folder in the workspace:

    2026-11-22_140512_lightwheel/
      batch.json                         what was asked: assets, engines, settings, each run's Python
      physx/events-1.jsonl               the progress of the run's first worker (run --events)
      physx/log-1.txt                    that worker's stdout and stderr
      physx/Dishwasher036/results.json   as the command line writes it
      newton/, newton-2/                 a run for each engine, and for each repeat in Newton

A worker is one process, `<python> -m proofmass_check run <assets> ...`, so the engine starts once
for all the assets of a run. One worker runs at a time, in the order the runs were asked for. When
a worker stops in the middle of an asset, that asset is marked as stopped, and a new worker runs
the rest (docs/gui.md, section 5.4).

The GUI learns what a worker did only from its files, so the state of a batch can be read again
after the GUI restarts. Only whether a worker is running now is kept in memory.
"""

import itertools
import json
import os
import re
import shlex
import subprocess
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from proofmass_check import engines
from proofmass_check.gui.settings import GuiSettings, check_python
from proofmass_check.rules import SETTLE_S

USD_SUFFIXES = {".usd", ".usda", ".usdc", ".usdz"}
MAX_USD_FILES = 2000  # the most USD files listed under one folder
MAX_REPEATS = 20
VARIANT = re.compile(r"^[^=\s]+=[^=\s]+$")
BATCH_ID = re.compile(r"^[\w.-]+$")
LOG_LINES = 200  # the lines of a worker's log the page shows


class BatchError(ValueError):
    """A request the GUI cannot carry out. The page shows the message."""


# --- choosing assets


def usd_files(path: str) -> dict:
    """The USD files of a file or below a folder. The user ticks the root files: the GUI does not guess them."""
    root = Path(path.strip().strip('"')).expanduser()
    if root.is_file():
        base, found, truncated = root.parent, [root], False
    elif root.is_dir():
        base, found, truncated = root, [], False
        for folder, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            found += [Path(folder) / f for f in sorted(files) if Path(f).suffix.lower() in USD_SUFFIXES]
            if len(found) > MAX_USD_FILES:
                found, truncated = found[:MAX_USD_FILES], True
                break
    else:
        raise BatchError(f"no file or folder {root}")
    files = [
        {"path": str(f.resolve()), "name": f.relative_to(base).as_posix(), "size": f.stat().st_size} for f in found
    ]
    return {"root": str(base.resolve()), "files": files, "truncated": truncated}


# --- what a batch is


@dataclass(frozen=True)
class Request:
    name: str
    assets: tuple[str, ...]  # absolute paths of the root files
    engines: tuple[str, ...]
    repeats: int  # runs of each asset in Newton, whose results can differ from run to run
    settle_s: float
    floor: bool
    variants: tuple[str, ...]  # SET=VALUE

    def runs(self) -> list[tuple[str, str]]:
        """(run ID, engine) of each run. PhysX gives the same numbers in every run, so it runs once."""
        found = []
        for engine in self.engines:
            count = self.repeats if engine == "newton" else 1
            found += [(engine if n == 1 else f"{engine}-{n}", engine) for n in range(1, count + 1)]
        return found


def parse_request(body: dict, settings: GuiSettings) -> Request:
    """The batch the page asks for, checked. Raises BatchError with the first problem."""
    repeats, settle_s = _numbers(body)
    return Request(
        name=str(body.get("name") or "batch").strip() or "batch",
        assets=_assets(body.get("assets")),
        engines=_engines(body.get("engines"), settings),
        repeats=repeats,
        settle_s=settle_s,
        floor=bool(body.get("floor", True)),
        variants=_variants(body.get("variants", [])),
    )


def _assets(assets) -> tuple[str, ...]:
    if not isinstance(assets, list) or not assets:
        raise BatchError("tick one asset or more")
    paths = [Path(str(a)) for a in assets]
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in USD_SUFFIXES:
            raise BatchError(f"not a USD file: {path}")
    # Each asset's results go to a folder with the name of its file (command()).
    names = [p.stem for p in paths]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise BatchError(f"several assets have the same file name ({', '.join(twice)}): put them in separate batches")
    return tuple(str(p.resolve()) for p in paths)


def _engines(chosen, settings: GuiSettings) -> tuple[str, ...]:
    if not isinstance(chosen, list) or not chosen or not set(chosen) <= set(engines.ENGINES):
        raise BatchError(f"choose one engine or more of {', '.join(sorted(engines.ENGINES))}")
    for engine in chosen:
        if not settings.python(engine):
            raise BatchError(f"set the Python of {engine} in the settings first")
    return tuple(e for e in engines.ENGINES if e in chosen)


def _variants(variants) -> tuple[str, ...]:
    found = [str(v).strip() for v in variants if str(v).strip()] if isinstance(variants, list) else []
    for variant in found:
        if not VARIANT.match(variant):
            raise BatchError(f"a variant is SET=VALUE, not {variant!r}")
    return tuple(found)


def _numbers(body: dict) -> tuple[int, float]:
    """The repeats and the settle time (s)."""
    try:
        repeats = int(body.get("repeats", 1))
        settle_s = float(body.get("settle_s", SETTLE_S))
    except (TypeError, ValueError):
        raise BatchError("repeats and the settle time must be numbers") from None
    if not 1 <= repeats <= MAX_REPEATS:
        raise BatchError(f"repeats must be from 1 to {MAX_REPEATS}")
    if not 0 < settle_s <= 60:
        raise BatchError("the settle time must be more than 0 s and at most 60 s")
    return repeats, settle_s


def command(
    python: str, engine: str, assets: list[str], run_dir: Path, events: Path, settle_s: float, floor: bool, variants
) -> list[str]:
    """The command of one worker. Each asset's results go to <run_dir>/<file name>/results.json."""
    out = run_dir / Path(assets[0]).stem if len(assets) == 1 else run_dir
    line = [python, "-m", "proofmass_check", "run", *assets, "--engine", engine, "--out", str(out)]
    line += ["--events", str(events)]
    if settle_s != SETTLE_S:
        line += ["--settle", repr(settle_s)]
    if not floor:
        line.append("--no-floor")
    for variant in variants:
        line += ["--variant", variant]
    return line


def shown(line: list[str]) -> str:
    """A command as a person types it in the terminal of this computer."""
    return subprocess.list2cmdline(line) if os.name == "nt" else shlex.join(line)


def preview(request: Request, settings: GuiSettings) -> list[dict]:
    """The command of each run, as it will run, with the batch's folder not made yet."""
    folder = Path(settings.workspace).expanduser() / "<new batch>"
    return [
        {
            "run": run_id,
            "command": shown(
                command(
                    settings.python(engine), engine, list(request.assets), folder / run_id,
                    folder / run_id / "events-1.jsonl", request.settle_s, request.floor, request.variants,
                )
            ),
        }
        for run_id, engine in request.runs()
    ]  # fmt: skip


# --- reading a batch from its files


def read_events(path: Path) -> list[dict]:
    """The events in a file. A line the worker has not finished writing is left out."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def attempts(run_dir: Path) -> list[tuple[int, Path]]:
    """(number, events file) of each worker of a run, in order."""
    found = []
    for path in run_dir.glob("events-*.jsonl"):
        number = path.stem.removeprefix("events-")
        if number.isdigit():
            found.append((int(number), path))
    return sorted(found)


def finished(run_dir: Path) -> set[str]:
    """The assets a run is done with: they ended, or a worker stopped while it ran them."""
    done = set()
    for _, path in attempts(run_dir):
        done |= {e["asset"] for e in read_events(path) if e.get("event") in ("asset", "end") and "asset" in e}
    return done


def read_batch(folder: Path) -> dict:
    return json.loads((folder / "batch.json").read_text(encoding="utf-8"))


def run_state(folder: Path, run: dict, assets: list[str], live: str | None, started: float | None) -> dict:
    """The state of one run and of each of its assets, from its events files.

    live: "running" or "queued" when the GUI runs or will run it now, "cancelled", or None.
    started: when the running worker started (time.time()), for the time an asset has run.
    """
    found = attempts(folder / run["id"])
    reader = _RunReader(assets)
    for index, (number, path) in enumerate(found):
        is_live = live == "running" and index == len(found) - 1
        reader.read(number, read_events(path), is_live, started)
    state = _run_state(reader, live, workers=len(found))
    for s in reader.states.values():
        if s["state"] == "waiting" and state not in ("running", "queued"):
            s["state"] = "not run"
        elif s["state"] == "stopped" and state == "cancelled":
            s["error"] = "cancelled while it ran"
    return {
        "id": run["id"],
        "engine": run["engine"],
        "python": run.get("python", ""),
        "version": run.get("version", ""),
        "state": state,
        "phase": reader.phase if live == "running" else None,
        "error": reader.engine_error,
        "workers": len(found),
        "assets": [{"file": a, "name": Path(a).stem} | reader.states[a] for a in assets],
    }


def _run_state(reader: "_RunReader", live: str | None, workers: int) -> str:
    """One word for a run: running, queued, cancelled, done, error (the engine did not start), stopped, not started."""
    if live in ("running", "queued", "cancelled"):
        return live
    if all(s["state"] not in ("waiting", "running") for s in reader.states.values()):
        return "done"
    if reader.engine_error:
        return "error"
    return "stopped" if workers else "not started"


class _RunReader:
    """Follows the events of a run's workers, in order, to the state of each asset."""

    def __init__(self, assets: list[str]):
        self.states = {a: {"state": "waiting"} for a in assets}
        self.engine_error: str | None = None
        self.phase: str | None = None  # "starting the engine" between the "start" and "engine" events
        self._current: str | None = None

    def read(self, number: int, events: list[dict], is_live: bool, started: float | None) -> None:
        """One worker's events. is_live: it runs now, so its current asset is running, not stopped."""
        self._current = None
        for event in events:
            handler = getattr(self, f"_on_{event.get('event')}", None)
            if handler is not None:
                handler(number, event)
        current = self._current
        if current and not is_live:
            log = f"log-{number}.txt"
            self.states[current] = {"state": "stopped", "error": f"the worker stopped during this asset: see {log}"}
        elif current and started is not None:
            self.states[current]["elapsed"] = round(time.time() - started - self.states[current]["since"], 1)

    def _on_start(self, number: int, event: dict) -> None:
        self.phase = "starting the engine"

    def _on_engine(self, number: int, event: dict) -> None:
        self.phase = None

    def _on_error(self, number: int, event: dict) -> None:
        self.engine_error = event.get("error")

    def _on_asset(self, number: int, event: dict) -> None:
        if event.get("asset") in self.states:
            self._current = event["asset"]
            self.states[self._current] = {
                "state": "running",
                "attempt": number,
                "check": None,
                "done": 0,
                "total": None,
                "results": 0,
                "since": event.get("t", 0.0),  # s after the worker started
            }

    def _on_check(self, number: int, event: dict) -> None:
        if self._current:
            self.states[self._current] |= {"check": event.get("id"), "done": 0, "total": event.get("total")}

    def _on_step(self, number: int, event: dict) -> None:
        if self._current:
            self.states[self._current] |= {"done": event.get("done", 0), "total": event.get("total")}

    def _on_result(self, number: int, event: dict) -> None:
        if self._current:
            self.states[self._current]["results"] += 1

    def _on_end(self, number: int, event: dict) -> None:
        if event.get("asset") in self.states:
            verdict = "error" if event.get("error") else "passed" if event.get("passed") else "failed"
            self.states[event["asset"]] = {
                "state": verdict,
                "error": event.get("error"),
                "seconds": event.get("seconds"),
            }
            self._current = None


# --- running batches


class Manager:
    """Makes batches and runs their workers, one at a time, on a thread of its own."""

    def __init__(self, settings: Callable[[], GuiSettings]):
        self._settings = settings
        self._ready = threading.Condition()
        self._queue: list[tuple[Path, str]] = []
        self._running: tuple[Path, str] | None = None
        self._process: subprocess.Popen | None = None
        self._started: float | None = None
        self._cancelled: set[tuple[Path, str]] = set()
        self._thread: threading.Thread | None = None

    def workspace(self) -> Path:
        return Path(self._settings().workspace).expanduser()

    def folder(self, batch_id) -> Path:
        """The folder of a batch in the workspace. Raises BatchError for any other name."""
        if not isinstance(batch_id, str) or not BATCH_ID.match(batch_id):
            raise BatchError(f"no batch {batch_id}")
        folder = self.workspace() / batch_id
        if not (folder / "batch.json").is_file():
            raise BatchError(f"no batch {batch_id} in {self.workspace()}")
        return folder

    def create(self, body: dict) -> Path:
        """Check the request and each engine's Python, write batch.json, and queue the runs."""
        settings = self._settings()
        request = parse_request(body, settings)
        versions = {}
        for engine in request.engines:
            ok, text = check_python(settings.python(engine))
            if not ok:
                raise BatchError(f"the Python of {engine} cannot run proofmass-check: {text}")
            versions[engine] = text
        slug = re.sub(r"[^\w.-]+", "-", request.name).strip("-")[:40] or "batch"
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        folder = next(
            path
            for n in itertools.count(1)
            if not (path := self.workspace() / (f"{stamp}_{slug}" if n == 1 else f"{stamp}_{slug}-{n}")).exists()
        )
        folder.mkdir(parents=True)
        data = {
            "name": request.name,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "assets": list(request.assets),
            "engines": list(request.engines),
            "repeats": request.repeats,
            "settle_s": request.settle_s,
            "floor": request.floor,
            "variants": list(request.variants),
            "runs": [
                {"id": run_id, "engine": engine, "python": settings.python(engine), "version": versions[engine]}
                for run_id, engine in request.runs()
            ],
        }
        (folder / "batch.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        with self._ready:
            self._queue += [(folder, run["id"]) for run in data["runs"]]
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="proofmass-check batches", daemon=True)
                self._thread.start()
            self._ready.notify()
        return folder

    def cancel(self, folder: Path, run_id: str | None = None) -> None:
        """Cancel one run of a batch, or all of them. A running worker is stopped."""
        ids = [r["id"] for r in read_batch(folder)["runs"] if run_id in (None, r["id"])]
        with self._ready:
            for rid in ids:
                if (folder, rid) in self._queue:
                    self._queue.remove((folder, rid))
                    self._cancelled.add((folder, rid))
                if self._running == (folder, rid):
                    self._cancelled.add((folder, rid))
                    if self._process is not None:
                        self._process.terminate()

    def stop(self) -> None:
        """Cancel every queued run and stop the running worker: the GUI is closing."""
        with self._ready:
            self._cancelled |= set(self._queue)
            self._queue.clear()
            if self._running is not None:
                self._cancelled.add(self._running)
                if self._process is not None:
                    self._process.terminate()

    def live(self, folder: Path, run_id: str) -> str | None:
        with self._ready:
            if self._running == (folder, run_id):
                return "running"
            if (folder, run_id) in self._queue:
                return "queued"
            return "cancelled" if (folder, run_id) in self._cancelled else None

    def state(self, folder: Path) -> dict:
        """What the page shows of a batch: what was asked, and the state of each run and asset."""
        data = read_batch(folder)
        runs = []
        for run in data["runs"]:
            live = self.live(folder, run["id"])
            started = self._started if live == "running" else None
            line = command(
                run["python"], run["engine"], data["assets"], folder / run["id"],
                folder / run["id"] / "events-1.jsonl", data["settle_s"], data["floor"], data["variants"],
            )  # fmt: skip
            runs.append(run_state(folder, run, data["assets"], live, started) | {"command": shown(line)})
        busy = any(r["state"] in ("running", "queued") for r in runs)
        return {
            "id": folder.name,
            "path": str(folder),
            "name": data["name"],
            "created": data["created"],
            "engines": data["engines"],
            "settle_s": data["settle_s"],
            "floor": data["floor"],
            "variants": data["variants"],
            "assets": [{"file": a, "name": Path(a).stem} for a in data["assets"]],
            "runs": runs,
            "state": "running" if busy else "done" if all(r["state"] == "done" for r in runs) else "stopped",
        }

    def batches(self) -> list[dict]:
        """Every batch in the workspace, the newest first."""
        workspace = self.workspace()
        if not workspace.is_dir():
            return []
        found = []
        for folder in sorted(workspace.iterdir(), reverse=True):
            if (folder / "batch.json").is_file():
                try:
                    found.append(self.state(folder))
                except (OSError, ValueError, KeyError):
                    continue  # a batch.json that cannot be read is not shown
        return found

    def log(self, folder: Path, run_id: str) -> str:
        """The last lines of the log of a run's newest worker."""
        if run_id not in {r["id"] for r in read_batch(folder)["runs"]}:
            raise BatchError(f"no run {run_id} in this batch")
        found = attempts(folder / run_id)
        if not found:
            return ""
        path = folder / run_id / f"log-{found[-1][0]}.txt"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-LOG_LINES:])

    # --- the thread that runs the workers

    def _loop(self) -> None:
        while True:
            with self._ready:
                while not self._queue:
                    self._ready.wait()
                folder, run_id = self._queue.pop(0)
                self._running = (folder, run_id)
            try:
                self._execute(folder, run_id)
            except Exception:  # noqa: BLE001  one batch that fails must not stop the ones queued after it
                traceback.print_exc()
            finally:
                with self._ready:
                    self._running, self._process, self._started = None, None, None

    def _execute(self, folder: Path, run_id: str) -> None:
        """Run the workers of one run until every asset is done, or a worker cannot start an asset."""
        data = read_batch(folder)
        run = next(r for r in data["runs"] if r["id"] == run_id)
        run_dir = folder / run_id
        run_dir.mkdir(exist_ok=True)
        first = len(attempts(run_dir)) + 1
        for number in range(first, first + len(data["assets"]) + 1):
            done = finished(run_dir)
            remaining = [a for a in data["assets"] if a not in done]
            if not remaining or (folder, run_id) in self._cancelled:
                return
            events = run_dir / f"events-{number}.jsonl"
            line = command(
                run["python"],
                run["engine"],
                remaining,
                run_dir,
                events,
                data["settle_s"],
                data["floor"],
                data["variants"],
            )
            self._work(line, run_dir / f"log-{number}.txt", run_dir, folder, run_id)
            if not any(e.get("event") == "asset" for e in read_events(events)):
                return  # it stopped before its first asset, so the engine did not start: a new worker would too

    def _work(self, line: list[str], log_path: Path, run_dir: Path, folder: Path, run_id: str) -> None:
        """Start one worker and wait for it. Its output goes to the log."""
        with open(log_path, "w", encoding="utf-8") as log:
            log.write(f"$ {shown(line)}\n\n")
            log.flush()
            with self._ready:
                if (folder, run_id) in self._cancelled:
                    return
                try:
                    self._process = subprocess.Popen(
                        line,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,  # no prompt can wait for an answer
                        cwd=run_dir,
                        env=_environment(),
                    )
                except OSError as e:
                    log.write(f"The worker did not start: {e}\n")
                    return
                self._started = time.time()
                process = self._process
            process.wait()


def _environment() -> dict[str, str]:
    """The GUI's own environment, with Python's output unbuffered so the log shows each line at once.

    It never accepts the NVIDIA licence for the user: it does not set OMNI_KIT_ACCEPT_EULA.
    """
    return dict(os.environ) | {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
