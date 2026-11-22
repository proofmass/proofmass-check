# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""proofmass-check run with several assets, and its progress events (--events)."""

import json

import usd_assets
from fake_engine import IdealEngine

from proofmass_check import cli, engines


def events_of(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def started_engines(monkeypatch) -> list:
    """Every engine the command starts, so a test can count them."""
    made = []

    def create(name):
        made.append(IdealEngine())
        return made[-1]

    monkeypatch.setattr(engines, "create", create)
    return made


def test_several_assets_in_one_start_of_the_engine(tmp_path, monkeypatch, capsys):
    made = started_engines(monkeypatch)
    prop, arm = usd_assets.prop(tmp_path / "prop.usda"), usd_assets.arm(tmp_path / "arm.usda")
    out, progress = tmp_path / "out", tmp_path / "progress.jsonl"
    assert cli.main(["run", str(prop), str(arm), "--out", str(out), "--events", str(progress)]) == cli.PASSED
    assert len(made) == 1 and made[0].closed_with == cli.PASSED
    for name in ("prop", "arm"):
        assert json.loads((out / name / "results.json").read_text(encoding="utf-8"))["passed"]
    assert f"== {prop}" in capsys.readouterr().out

    events = events_of(progress)
    kinds = [e["event"] for e in events]
    assert kinds[:2] == ["start", "engine"] and kinds[-1] == "exit" and events[-1]["status"] == cli.PASSED
    assert [e["asset"] for e in events if e["event"] in ("asset", "end")] == [str(prop), str(prop), str(arm), str(arm)]
    assert all(e["t"] >= 0 for e in events)
    plan = next(e for e in events if e["event"] == "plan" and e["asset"] == str(arm))
    assert "TRACK" in plan["runs"] and plan["skip"]["DROP"].startswith("the asset is fixed to the world")
    end = next(e for e in events if e["event"] == "end" and e["asset"] == str(arm))
    assert end["passed"] and end["results"] == str(out / "arm" / "results.json")


def test_steps_count_the_engine_operations(tmp_path, monkeypatch):
    started_engines(monkeypatch)
    arm, progress = usd_assets.arm(tmp_path / "arm.usda"), tmp_path / "progress.jsonl"
    cli.main(["run", str(arm), "--out", str(tmp_path / "out"), "--events", str(progress)])
    events = events_of(progress)
    for check_id, total in (("HOLD", 1), ("TRACK", 2), ("LIMIT", 1), ("STABLE", 50)):
        start = next(e for e in events if e["event"] == "check" and e["id"] == check_id)
        steps = [e for e in events if e["event"] == "step" and e["id"] == check_id]
        assert start["total"] == total and [s["done"] for s in steps] == list(range(1, total + 1)), check_id
    results = [e["id"] for e in events if e["event"] == "result"]
    assert results == ["LOAD", "HOLD", "TRACK", "LIMIT", "STABLE", "SPEED"]  # the checks that ran on the arm


def test_one_asset_that_stops_does_not_stop_the_others(tmp_path, monkeypatch):
    started_engines(monkeypatch)
    broken = tmp_path / "broken.usda"
    broken.write_text("#usda 1.0\nthis is not USD\n", encoding="utf-8")
    prop, out, progress = usd_assets.prop(tmp_path / "prop.usda"), tmp_path / "out", tmp_path / "progress.jsonl"
    assert cli.main(["run", str(broken), str(prop), "--out", str(out), "--events", str(progress)]) == cli.ERROR
    assert "error" in json.loads((out / "broken" / "results.json").read_text(encoding="utf-8"))
    assert json.loads((out / "prop" / "results.json").read_text(encoding="utf-8"))["passed"]
    ends = {e["asset"]: e for e in events_of(progress) if e["event"] == "end"}
    assert ends[str(broken)]["error"] and not ends[str(broken)]["passed"] and ends[str(prop)]["passed"]


def test_two_assets_of_one_name_are_refused(tmp_path, monkeypatch, capsys):
    made = started_engines(monkeypatch)
    first = usd_assets.prop(tmp_path / "a" / "prop.usda")
    second = usd_assets.prop(tmp_path / "b" / "prop.usda")
    assert cli.main(["run", str(first), str(second), "--out", str(tmp_path / "out")]) == cli.ERROR
    assert "same file name (prop)" in capsys.readouterr().err and made == []


def test_an_engine_that_does_not_start(tmp_path, monkeypatch):
    def unavailable(name):
        raise engines.EngineUnavailableError(f"the {name} engine needs Isaac Sim")

    monkeypatch.setattr(engines, "create", unavailable)
    prop, progress = usd_assets.prop(tmp_path / "prop.usda"), tmp_path / "progress.jsonl"
    assert cli.main(["run", str(prop), "--events", str(progress)]) == cli.ERROR
    assert [(e["event"], e.get("error") or e.get("status")) for e in events_of(progress)][1:] == [
        ("error", "the physx engine needs Isaac Sim"),
        ("exit", cli.ERROR),
    ]
