# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The inspector's data: `proofmass-check inspect` run in a Python that has pxr (docs/gui.md, 5.3 and 6.5).

The GUI's server never imports pxr itself. Reading a stage can take seconds and much memory, and a
crash of USD must not stop the server. So inspect runs as a process of its own: in the GUI's own
Python when it has pxr (the `usd` extra), else in Newton's Python. Never in Isaac Sim's Python:
there, pxr exists only after Isaac Sim starts.
"""

import importlib.util
import json
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

from proofmass_check import engines
from proofmass_check.gui.batches import USD_SUFFIXES, VARIANT, BatchError
from proofmass_check.gui.settings import GuiSettings

INSPECT_SECONDS = 180  # the most one inspect may take: a large stage can take long to open
KEPT = 8  # inspections kept, so that the page can show an asset again at once


def python_with_pxr(settings: GuiSettings) -> str:
    """The Python to run inspect in. Raises BatchError when there is none."""
    if importlib.util.find_spec("pxr") is not None:
        return sys.executable
    if settings.python("newton"):
        return settings.python("newton")
    raise BatchError(
        "inspect needs a Python with pxr and without Isaac Sim: install proofmass-check[usd] in the "
        "Python that runs the GUI, or set Newton's Python in the settings"
    )


class Inspector:
    def __init__(self):
        self._kept: OrderedDict[tuple, dict] = OrderedDict()

    def inspect(self, body: dict, settings: GuiSettings) -> dict:
        """The inspection of an asset, from the page's request {file, engine, variants, floor}."""
        file = Path(str(body.get("file", "")).strip().strip('"'))
        if not file.is_file() or file.suffix.lower() not in USD_SUFFIXES:
            raise BatchError(f"no USD file {file}")
        engine = body.get("engine") or "physx"
        if engine not in engines.ENGINES:
            raise BatchError(f"no engine {engine}")
        variants = [str(v) for v in body.get("variants", []) if str(v).strip()]
        for variant in variants:
            if not VARIANT.match(variant):
                raise BatchError(f"a variant is SET=VALUE, not {variant!r}")
        floor = bool(body.get("floor", True))
        stat = file.stat()
        key = (str(file.resolve()), stat.st_mtime_ns, stat.st_size, engine, tuple(variants), floor)
        if key not in self._kept:
            self._kept[key] = run_inspect(python_with_pxr(settings), file, engine, variants, floor)
            while len(self._kept) > KEPT:
                self._kept.popitem(last=False)
        self._kept.move_to_end(key)
        return self._kept[key]


def run_inspect(python: str, file: Path, engine: str, variants: list[str], floor: bool) -> dict:
    """Run `<python> -m proofmass_check inspect ... --geometry` and give its JSON."""
    line = [python, "-m", "proofmass_check", "inspect", str(file), "--engine", engine, "--geometry"]
    for variant in variants:
        line += ["--variant", variant]
    if not floor:
        line.append("--no-floor")
    try:
        done = subprocess.run(
            line, capture_output=True, text=True, encoding="utf-8", timeout=INSPECT_SECONDS,
            stdin=subprocess.DEVNULL, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise BatchError(f"inspect did not end in {INSPECT_SECONDS} s") from None
    except OSError as e:
        raise BatchError(f"inspect did not start: {e}") from None
    if done.returncode != 0:
        lines = done.stderr.strip().splitlines()
        raise BatchError(lines[-1] if lines else f"inspect stopped with status {done.returncode}")
    return json.loads(done.stdout)
