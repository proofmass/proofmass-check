# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Results files in a folder: find them, summarize them, and compare them.

A results file is a JSON file that proofmass-check wrote: its `tool.name` is "proofmass-check".
Its file name does not matter, because people rename them (physx_results.json, for example).

The GUI never reads numbers from the detail text of a check. That text is for people, and its
wording changes between versions. Numbers come only from `measurements` (docs/gui.md, section 5.1),
and a run without them shows its detail text only.
"""

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from proofmass_check.checks import TITLES

SCHEMA_VERSION = 1  # the version of results.json this GUI reads
MAX_BYTES = 2_000_000  # a results file has a few kB to about 100 kB, so a larger JSON file is something else
MAX_FILES = 5000  # the most JSON files read in one folder, so that opening a large folder by mistake ends
SETTINGS_NOTE = "settings differ from the spec"  # runner.py starts each note about a changed setting so
SPEC_URL = "https://github.com/proofmass/proofmass-check/blob/v{version}/docs/spec.md"


@dataclass(frozen=True)
class Run:
    id: str  # the file's path below its folder, with "/"
    path: Path
    data: dict


@dataclass
class Folder:
    path: Path
    runs: list[Run] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)  # (file, why it was not read)
    truncated: bool = False  # the folder has more than MAX_FILES JSON files, and the rest were not read

    def run(self, run_id: str) -> Run:
        for run in self.runs:
            if run.id == run_id:
                return run
        raise KeyError(run_id)


# --- reading


def scan(folder: str | Path) -> Folder:
    """Every results file in a folder and the folders below it, in path order.

    Folders whose names start with "." are not read: they hold tools (.git, .venv), not results.
    """
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise NotADirectoryError(f"no folder {folder}")
    result = Folder(folder)
    count = 0
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "node_modules")
        for name in sorted(files):
            if not name.lower().endswith(".json"):
                continue
            count += 1
            if count > MAX_FILES:
                result.truncated = True
                return result
            path = Path(root) / name
            file_id = path.relative_to(folder).as_posix()
            data, why = read(path)
            if data is not None:
                result.runs.append(Run(file_id, path, data))
            elif why:
                result.problems.append((file_id, why))
    return result


def read(path: Path) -> tuple[dict | None, str | None]:
    """The results in a file, or None and why not.

    A JSON file that proofmass-check did not write gives (None, None): a folder of results also
    holds other JSON files, such as a validator's report, and they are not a problem.
    """
    try:
        if path.stat().st_size > MAX_BYTES:
            return None, (f"larger than {MAX_BYTES // 1_000_000} MB" if path.name == "results.json" else None)
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"cannot read it: {e.strerror}"
    except UnicodeDecodeError:
        return None, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, (f"not valid JSON: {e.msg}, line {e.lineno}" if '"proofmass-check"' in text else None)
    tool = data.get("tool") if isinstance(data, dict) else None
    if not isinstance(tool, dict) or tool.get("name") != "proofmass-check":
        return None, None
    if data.get("schema_version") != SCHEMA_VERSION:
        return None, f"schema_version {data.get('schema_version')}: this GUI reads version {SCHEMA_VERSION}"
    missing = _missing_fields(data)
    if missing:
        return None, f"not a complete results file: no {missing}"
    return data, None


def _missing_fields(data: dict) -> str | None:
    """The first required field of results.schema.json that the data does not have, or None."""
    for name in ("spec_version", "passed"):
        if name not in data:
            return name
    for parent, names in (("tool", ("version",)), ("asset", ("file", "sha256")), ("engine", ("name",))):
        if not isinstance(data.get(parent), dict):
            return parent
        for name in names:
            if name not in data[parent]:
                return f"{parent}.{name}"
    for check in data.get("checks", []):
        if not isinstance(check, dict) or not {"id", "verdict", "detail"} <= check.keys():
            return "id, verdict or detail in a check"
    return None


# --- what the page shows


def asset_label(file: str) -> str:
    """The asset's root file name without its extension. results.json can come from Windows or Linux."""
    name = re.split(r"[\\/]", file)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def check_order(ids) -> list[str]:
    """Check IDs in the order a run reports them. An ID this version does not know comes last."""
    ids = list(dict.fromkeys(ids))
    return [i for i in TITLES if i in ids] + [i for i in ids if i not in TITLES]


def summary(run: Run) -> dict:
    """What the list of runs and the matrix need from a run."""
    data = run.data
    checks = data.get("checks", [])
    found = [measurement(m, c["id"]) for c in checks for m in c.get("measurements", [])]
    margins = [m["margin"] for m in found if m["margin"] is not None]
    return {
        "id": run.id,
        "asset": asset_label(data["asset"]["file"]),
        "asset_name": data["asset"].get("name"),
        "file": data["asset"]["file"],
        "sha256": data["asset"]["sha256"],
        "variants": data["asset"].get("variants", {}),
        "engine": data["engine"]["name"],
        "engine_versions": data["engine"].get("versions", {}),
        "tool_version": data["tool"]["version"],
        "spec_version": data["spec_version"],
        "spec_url": SPEC_URL.format(version=data["tool"]["version"]),
        "passed": bool(data["passed"]),
        "error": data.get("error"),
        "seconds": data.get("seconds"),
        "verdicts": {c["id"]: c["verdict"] for c in checks},
        "details": {c["id"]: c["detail"] for c in checks},
        "failed": sum(c["verdict"] == "FAIL" for c in checks),
        "settings_differ": any(str(n).startswith(SETTINGS_NOTE) for n in data.get("notes", [])),
        "engine_cannot_run": list(data.get("engine_cannot_run", [])),  # tool 0.3.0 and older do not write it
        "measured": bool(found),
        "worst_margin": max(margins) if margins else None,
    }


def details(run: Run) -> dict:
    """Everything the page of one run shows: the summary, settings, notes, checks and measurements."""
    data = run.data
    by_id = {c["id"]: c for c in data.get("checks", [])}
    checks = []
    for check_id in check_order(by_id):
        check = by_id[check_id]
        checks.append(
            {
                "id": check_id,
                "title": check.get("title") or TITLES.get(check_id, ""),
                "verdict": check["verdict"],
                "detail": check["detail"],
                "measurements": [measurement(m, check_id) for m in check.get("measurements", [])],
            }
        )
    measured = [m for c in checks for m in c["measurements"]]
    return summary(run) | {
        "settings": data.get("settings", {}),
        "notes": list(data.get("notes", [])),
        "checks": checks,
        "measurements": sorted(measured, key=_worst_first),
    }


def _worst_first(m: dict):
    return (m["ok"], -(m["margin"] if m["margin"] is not None else -1.0))


def measurement(m: dict, check_id: str) -> dict:
    """One measurement with its margin, and its value and limit as the page shows them."""
    value, limit, bound = m.get("value"), m.get("limit"), m.get("bound", "max")
    unit, ok = str(m.get("unit", "1")), bool(m.get("ok", False))
    shown_value, shown_limit, shown_unit = shown_pair(value, limit, unit, ok)
    return {
        "check": check_id,
        "subject": str(m.get("subject", "")),
        "case": str(m.get("case", "")),
        "quantity": str(m.get("quantity", "")),
        "value": value,
        "limit": limit,
        "bound": bound,
        "unit": unit,
        "ok": ok,
        "margin": margin(value, limit, bound),
        "shown_value": shown_value,
        "shown_limit": shown_limit,
        "shown_unit": shown_unit,
    }


def margin(value, limit, bound: str = "max") -> float | None:
    """How much of its limit a measurement uses: above 1, it is past the limit.

    For a lower bound ("min"), it is limit / value. None when the ratio has no meaning: no limit, a
    limit of 0, a value that is not a finite number, or nothing at all against a lower bound.
    """
    if not (_finite(value) and _finite(limit)) or limit == 0:
        return None
    if bound == "min":
        return limit / value if value > 0 else None
    return abs(value) / abs(limit)


def shown(value, unit: str, extra_digits: int = 0) -> tuple[str, str]:
    """A value and its unit as the page shows them: degrees and millimetres, as spec.md section 1 says.

    The digits are those of the detail text (checks/text.py): 0.001 deg and 0.01 mm.
    """
    if not _finite(value):
        return ("" if value is None else str(value)), _SHOWN_UNITS.get(unit, unit)
    if unit == "rad":
        return f"{math.degrees(value):.{3 + extra_digits}f}", "deg"
    if unit == "m":
        return f"{value * 1000:.{2 + extra_digits}f}", "mm"
    if unit == "rad/s":
        return format(math.degrees(value), f".{3 + extra_digits}g"), "deg/s"
    return format(value, f".{4 + extra_digits}g"), _SHOWN_UNITS.get(unit, unit)


_SHOWN_UNITS = {"rad": "deg", "m": "mm", "rad/s": "deg/s", "1": ""}


def shown_pair(value, limit, unit: str, ok: bool) -> tuple[str, str, str]:
    """A value and its limit as text, in one unit.

    A failing value gets more digits until it differs from its limit, so that rounding never shows a
    value that fails as equal to its limit.
    """
    for extra in range(7):
        shown_value, shown_unit = shown(value, unit, extra)
        shown_limit = shown(limit, unit, extra)[0] if limit is not None else ""
        if ok or shown_value != shown_limit:
            break
    return shown_value, shown_limit, shown_unit


def _finite(x) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


# --- comparing


def compare(runs: list[Run]) -> dict:
    """Two or more runs side by side: their verdicts and their measurements.

    Differences are marked only between runs of one spec version: spec.md says that results of
    different spec versions are not compared.
    """
    same_spec = len({r.data["spec_version"] for r in runs}) == 1
    by_run = [{c["id"]: c for c in r.data.get("checks", [])} for r in runs]
    rows = []
    for check_id in check_order(i for checks in by_run for i in checks):
        cells = [checks.get(check_id) for checks in by_run]
        verdicts = [c["verdict"] if c else None for c in cells]
        rows.append(
            {
                "id": check_id,
                "title": TITLES.get(check_id, ""),
                "cells": [{"verdict": c["verdict"], "detail": c["detail"]} if c else None for c in cells],
                "counts": dict(Counter(v for v in verdicts if v)),
                "differs": same_spec and len(set(verdicts)) > 1,
            }
        )
    return {
        "runs": [summary(r) for r in runs],
        "same_asset": len({r.data["asset"]["sha256"] for r in runs}) == 1,
        "same_spec": same_spec,
        "checks": rows,
        "measurements": _compare_measurements(by_run, same_spec),
    }


def _compare_measurements(by_run: list[dict], same_spec: bool) -> list[dict]:
    """Measurements of the same check, subject, case and quantity, one row for each."""
    rows: dict[tuple, list] = {}
    for i, checks in enumerate(by_run):
        for check_id, check in checks.items():
            for m in check.get("measurements", []):
                found = measurement(m, check_id)
                key = (check_id, found["subject"], found["case"], found["quantity"])
                rows.setdefault(key, [None] * len(by_run))[i] = found
    result = []
    for (check_id, subject, case, quantity), cells in rows.items():
        present = [c for c in cells if c is not None]
        values = [c["value"] for c in present if _finite(c["value"])]
        unit = present[0]["unit"]
        result.append(
            {
                "check": check_id,
                "subject": subject,
                "case": case,
                "quantity": quantity,
                "cells": cells,
                "lowest": shown(min(values), unit)[0] if values else "",
                "highest": shown(max(values), unit)[0] if values else "",
                "shown_unit": shown(0.0, unit)[1],
                "differs": same_spec and (len(present) < len(cells) or len({c["ok"] for c in present}) > 1),
            }
        )
    return result


def pair_folders(a: Folder, b: Folder) -> dict:
    """The runs of two folders, paired by asset: the same SHA-256 of the root file.

    A run pairs with a run of the same engine first. When the other folder has one run of that asset
    only, it pairs with that one, whatever its engine, so that a PhysX folder pairs with a Newton one.
    """
    left = list(b.runs)
    pairs, alone_a = [], []
    for run in a.runs:
        same = [r for r in left if r.data["asset"]["sha256"] == run.data["asset"]["sha256"]]
        engine = [r for r in same if r.data["engine"]["name"] == run.data["engine"]["name"]]
        match = engine[0] if engine else same[0] if len(same) == 1 else None
        if match is None:
            alone_a.append(run.id)
            continue
        left.remove(match)
        pairs.append({"a": run.id, "b": match.id, "comparison": compare([run, match])})
    return {"pairs": pairs, "only_a": alone_a, "only_b": [r.id for r in left]}


def finite_json(value):
    """The value with every float that is not finite as text, because JSON has no NaN or infinity.

    Python's json module reads and writes NaN, but a browser does not.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [finite_json(v) for v in value]
    return value
