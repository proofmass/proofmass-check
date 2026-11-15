# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""results.json: what a run found, with every version needed to repeat it.

results.schema.json describes the file. Raise SCHEMA_VERSION when a field changes meaning or goes
away; a new optional field does not need it.
"""

import hashlib
import json
from pathlib import Path

from proofmass_check import __version__
from proofmass_check.rules import SPEC_VERSION
from proofmass_check.runner import Run

SCHEMA_VERSION = 1


def sha256(file: str | Path) -> str:
    """The SHA-256 of the root USD file only. Layers it references are not included."""
    digest = hashlib.sha256()
    with open(file, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def header(file: str | Path, engine: str) -> dict:
    """The fields every results.json has, also one written after an error."""
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "proofmass-check", "version": __version__},
        "spec_version": SPEC_VERSION,
        "asset": {"file": str(file), "sha256": sha256(file)},
        "engine": {"name": engine},
    }


def to_dict(run: Run) -> dict:
    data = header(run.asset.file, run.engine)
    data["asset"] |= {"name": run.asset.name, "variants": dict(run.asset.variants)}
    data["engine"]["versions"] = run.engine_version
    s = run.settings
    data["settings"] = {
        "settle_s": s.settle_s,
        "linear_tol": s.linear_tol,
        "angular_tol": s.angular_tol,
        "random_poses": s.random_poses,
        "floor": run.floor,
    }
    data["notes"] = list(run.notes)
    data["checks"] = [{"id": r.id, "title": r.title, "verdict": r.verdict, "detail": r.detail} for r in run.results]
    data["passed"] = run.passed
    data["seconds"] = run.seconds
    return data


def error_dict(file: str | Path, engine: str, error: str) -> dict:
    """results.json for a run that stopped with an error."""
    return header(file, engine) | {"error": error, "passed": False}


def write(data: dict, folder: str | Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "results.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path
