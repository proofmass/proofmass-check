# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Batches of the GUI: what a request may ask, the commands, and workers that run, crash or are cancelled."""

import json
import sys
import time
from pathlib import Path

import pytest

from proofmass_check.gui import batches
from proofmass_check.gui.settings import GuiSettings
from proofmass_check.rules import SETTLE_S

FAKE_WORKER = Path(__file__).parent / "fake_worker.py"
REAL_COMMAND = batches.command


def usd(folder: Path, name: str) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#usda 1.0\n", encoding="utf-8")
    return path


@pytest.fixture
def settings(tmp_path):
    return GuiSettings(pythons={"physx": sys.executable, "newton": sys.executable}, workspace=str(tmp_path / "ws"))


@pytest.fixture
def manager(settings, monkeypatch):
    """A manager whose workers are fake_worker.py, and whose Pythons all pass their test."""
    monkeypatch.setattr(batches, "check_python", lambda python: (True, "proofmass-check 0.2.0 (spec 0.3)"))

    def fake_command(python, engine, assets, run_dir, events, settle_s, floor, variants):
        return [sys.executable, str(FAKE_WORKER), str(events), str(run_dir), *assets]

    monkeypatch.setattr(batches, "command", fake_command)
    made = batches.Manager(lambda: settings)
    yield made
    made.stop()


def wait(manager, folder, until, seconds=30.0) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = manager.state(folder)
        if until(found):
            return found
        time.sleep(0.1)
    raise AssertionError(f"the batch did not get there: {manager.state(folder)}")


def ended(found: dict) -> bool:
    return found["state"] != "running"


def asset_states(found: dict, run_id: str) -> dict:
    run = next(r for r in found["runs"] if r["id"] == run_id)
    return {a["name"]: a["state"] for a in run["assets"]}


def test_what_a_request_may_ask(tmp_path, settings):
    arm = str(usd(tmp_path, "arm.usda"))

    def problem(**body) -> str:
        with pytest.raises(batches.BatchError) as e:
            batches.parse_request({"assets": [arm], "engines": ["physx"]} | body, settings)
        return str(e.value)

    assert problem(assets=[]) == "tick one asset or more"
    assert problem(assets=[str(tmp_path / "none.usda")]).startswith("not a USD file")
    assert "same file name (arm)" in problem(assets=[arm, str(usd(tmp_path / "b", "arm.usd"))])
    assert problem(engines=["bullet"]) == "choose one engine or more of newton, physx"
    assert problem(variants=["Physics"]) == "a variant is SET=VALUE, not 'Physics'"
    assert problem(repeats=0) == "repeats must be from 1 to 20"
    assert problem(settle_s="soon") == "repeats and the settle time must be numbers"
    no_newton = GuiSettings(pythons={"physx": sys.executable})
    with pytest.raises(batches.BatchError, match="set the Python of newton"):
        batches.parse_request({"assets": [arm], "engines": ["newton"]}, no_newton)
    request = batches.parse_request({"assets": [arm], "engines": ["newton", "physx"], "repeats": 3}, settings)
    assert request.runs() == [("physx", "physx"), ("newton", "newton"), ("newton-2", "newton"), ("newton-3", "newton")]


def test_the_command_of_a_worker(tmp_path):
    run_dir, events = tmp_path / "physx", tmp_path / "physx" / "events-1.jsonl"
    one = REAL_COMMAND("py", "physx", ["C:/a/arm.usda"], run_dir, events, SETTLE_S, True, ())
    assert one == ["py", "-m", "proofmass_check", "run", "C:/a/arm.usda", "--engine", "physx",
                   "--out", str(run_dir / "arm"), "--events", str(events)]  # fmt: skip
    two = REAL_COMMAND("py", "newton", ["a.usda", "b.usda"], run_dir, events, 3.0, False, ("Physics=MuJoCo",))
    assert two[two.index("--out") + 1] == str(run_dir)  # run writes <out>/<file name>/results.json
    assert two[-5:] == ["--settle", "3.0", "--no-floor", "--variant", "Physics=MuJoCo"]


def test_usd_files_of_a_folder(tmp_path):
    for name in ("x.usda", "sub/y.USD", ".git/z.usd", "texture.png"):
        usd(tmp_path / "set", name)
    found = batches.usd_files(str(tmp_path / "set"))
    assert [f["name"] for f in found["files"]] == ["x.usda", "sub/y.USD"] and not found["truncated"]
    assert [f["name"] for f in batches.usd_files(f'"{tmp_path / "set" / "x.usda"}"')["files"]] == ["x.usda"]
    with pytest.raises(batches.BatchError, match="no file or folder"):
        batches.usd_files(str(tmp_path / "none"))


def test_a_batch_runs_every_asset_in_every_run(tmp_path, manager):
    assets = [str(usd(tmp_path, "arm.usda")), str(usd(tmp_path, "door.usda"))]
    folder = manager.create({"name": "lab set", "assets": assets, "engines": ["physx", "newton"], "repeats": 2})
    assert folder.parent == tmp_path / "ws" and folder.name.endswith("_lab-set")
    found = wait(manager, folder, ended)
    assert found["state"] == "done" and [r["id"] for r in found["runs"]] == ["physx", "newton", "newton-2"]
    for run in found["runs"]:
        assert run["state"] == "done" and run["workers"] == 1
        assert asset_states(found, run["id"]) == {"arm": "passed", "door": "passed"}
        assert (folder / run["id"] / "arm" / "results.json").is_file()
    data = json.loads((folder / "batch.json").read_text(encoding="utf-8"))
    assert data["assets"] == assets and data["runs"][0]["version"] == "proofmass-check 0.2.0 (spec 0.3)"
    assert manager.log(folder, "physx").startswith("$ ")


def test_a_crash_stops_one_asset_and_a_new_worker_runs_the_rest(tmp_path, manager):
    assets = [str(usd(tmp_path, name)) for name in ("arm.usda", "crash.usda", "door.usda")]
    folder = manager.create({"assets": assets, "engines": ["physx"]})
    found = wait(manager, folder, ended)
    assert asset_states(found, "physx") == {"arm": "passed", "crash": "stopped", "door": "passed"}
    (run,) = found["runs"]
    assert run["state"] == "done" and run["workers"] == 2
    crash = next(a for a in run["assets"] if a["name"] == "crash")
    assert crash["error"] == "the worker stopped during this asset: see log-1.txt"


def test_cancel_a_running_worker(tmp_path, manager):
    folder = manager.create({"assets": [str(usd(tmp_path, "slow.usda"))], "engines": ["physx"]})
    wait(manager, folder, lambda f: asset_states(f, "physx")["slow"] == "running")
    manager.cancel(folder)
    found = wait(manager, folder, ended)
    assert found["runs"][0]["state"] == "cancelled"
    assert (
        found["runs"][0]["assets"][0] | {"state": "stopped", "error": "cancelled while it ran"}
        == found["runs"][0]["assets"][0]
    )


def test_the_state_of_a_batch_is_read_from_its_files(tmp_path, manager, settings):
    folder = manager.create({"assets": [str(usd(tmp_path, "arm.usda"))], "engines": ["physx"]})
    wait(manager, folder, ended)
    restarted = batches.Manager(lambda: settings)  # a new GUI knows nothing of the old one's workers
    assert asset_states(restarted.state(folder), "physx") == {"arm": "passed"}
    assert [b["id"] for b in restarted.batches()] == [folder.name]


def test_only_batches_of_the_workspace(manager):
    for name in ("../ws", "a/b", "none", None):
        with pytest.raises(batches.BatchError):
            manager.folder(name)


def test_the_state_of_a_run_from_its_events(tmp_path):
    run_dir = tmp_path / "physx"
    run_dir.mkdir()
    lines = [
        {"event": "start", "t": 0.0},
        {"event": "engine", "t": 40.0},
        {"event": "asset", "asset": "a.usda", "t": 40.1},
        {"event": "end", "asset": "a.usda", "passed": False, "t": 50.0},
        {"event": "asset", "asset": "b.usda", "t": 50.1},
        {"event": "check", "asset": "b.usda", "id": "TRACK", "total": 92, "t": 51.0},
        {"event": "step", "asset": "b.usda", "id": "TRACK", "done": 12, "total": 92, "t": 60.0},
    ]
    (run_dir / "events-1.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines) + '{"event": "st', "utf-8")
    run = {"id": "physx", "engine": "physx"}
    live = batches.run_state(tmp_path, run, ["a.usda", "b.usda", "c.usda"], "running", time.time() - 70.0)
    a, b, c = live["assets"]
    assert live["state"] == "running" and a["state"] == "failed" and c["state"] == "waiting"
    assert (b["state"], b["check"], b["done"], b["total"]) == ("running", "TRACK", 12, 92)
    assert b["elapsed"] == pytest.approx(19.9, abs=1.0)  # since its "asset" event, 50.1 s after the start
    after = batches.run_state(tmp_path, run, ["a.usda", "b.usda", "c.usda"], None, None)
    assert after["state"] == "stopped" and [x["state"] for x in after["assets"]] == ["failed", "stopped", "not run"]
