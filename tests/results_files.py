# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Results files for the GUI's tests, written by hand in the form report.py gives them."""

import json
from pathlib import Path


def results(
    asset="arm",
    engine="physx",
    sha="a" * 64,
    verdicts=None,
    details=None,
    measurements=None,
    tool="0.2.0",
    spec="0.3",
    notes=(),
    file=None,
) -> dict:
    """A results file. verdicts: {check ID: verdict}. measurements: {check ID: [measurement, ...]}."""
    verdicts = verdicts or {"LOAD": "PASS", "HOLD": "PASS"}
    checks = []
    for check_id, verdict in verdicts.items():
        check = {
            "id": check_id,
            "title": f"the title of {check_id}",
            "verdict": verdict,
            "detail": (details or {}).get(check_id, f"the detail of {check_id}"),
        }
        if measurements and check_id in measurements:
            check["measurements"] = measurements[check_id]
        checks.append(check)
    return {
        "schema_version": 1,
        "tool": {"name": "proofmass-check", "version": tool},
        "spec_version": spec,
        "asset": {"file": file or f"C:\\Users\\someone\\assets\\{asset}.usda", "sha256": sha, "name": "root"},
        "engine": {"name": engine, "versions": {"isaacsim": "6.1.0.0"} if engine == "physx" else {}},
        "settings": {"settle_s": 1.5, "linear_tol": 0.002, "angular_tol": 0.0087, "random_poses": 50, "floor": 0.0},
        "notes": list(notes),
        "checks": checks,
        "passed": all(v != "FAIL" for v in verdicts.values()),
        "seconds": 12.5,
    }


def error_results(asset="arm", engine="physx", sha="b" * 64) -> dict:
    """A results file of a run that stopped with an error, as report.error_dict() gives it."""
    return {
        "schema_version": 1,
        "tool": {"name": "proofmass-check", "version": "0.2.0"},
        "spec_version": "0.3",
        "asset": {"file": f"/home/someone/{asset}.usda", "sha256": sha},
        "engine": {"name": engine},
        "error": "Traceback (most recent call last):\nRuntimeError: the engine stopped",
        "passed": False,
    }


def measured(subject, value, limit, ok, case="", quantity="error", unit="rad", bound="max") -> dict:
    return {
        "subject": subject,
        "case": case,
        "quantity": quantity,
        "value": value,
        "limit": limit,
        "bound": bound,
        "unit": unit,
        "ok": ok,
    }


def write(folder: Path, name: str, data) -> Path:
    """Write data (a dict, or text as it is) to folder/name, and give the path."""
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path
