# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import json
import math
from pathlib import Path

import jsonschema
import pytest
from results_files import error_results, measured, results, write

from proofmass_check.gui import runs

SCHEMA = json.loads((Path(runs.__file__).parent.parent / "results.schema.json").read_text(encoding="utf-8"))
ONE_DEG = math.radians(1.0)


def test_the_test_files_follow_the_schema():
    jsonschema.validate(results(), SCHEMA)
    jsonschema.validate(error_results(), SCHEMA)


def test_scan_finds_results_by_their_content_not_their_name(tmp_path):
    write(tmp_path, "g2/physx/results.json", results("g2"))
    write(tmp_path, "g2/newton_results.json", results("g2", engine="newton"))
    write(tmp_path, "g2/validator.json", {"passed": True})  # another tool's JSON: not a problem
    write(tmp_path, "g2/notes.txt", "not JSON")
    write(tmp_path, ".venv/results.json", results("hidden"))  # tools live in folders that start with "."
    folder = runs.scan(tmp_path)
    assert [run.id for run in folder.runs] == ["g2/newton_results.json", "g2/physx/results.json"]
    assert folder.problems == [] and not folder.truncated


def test_scan_says_why_a_results_file_was_not_read(tmp_path):
    write(tmp_path, "broken/results.json", '{"tool": {"name": "proofmass-check"}, ')
    write(tmp_path, "other.json", "{ not JSON of proofmass-check")
    write(tmp_path, "newer.json", results() | {"schema_version": 2})
    incomplete = results()
    del incomplete["asset"]["sha256"]
    write(tmp_path, "incomplete.json", incomplete)
    problems = dict(runs.scan(tmp_path).problems)
    assert problems.keys() == {"broken/results.json", "newer.json", "incomplete.json"}
    assert problems["broken/results.json"].startswith("not valid JSON")
    assert problems["newer.json"] == "schema_version 2: this GUI reads version 1"
    assert problems["incomplete.json"] == "not a complete results file: no asset.sha256"


def test_scan_stops_after_its_limit_of_files(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "MAX_FILES", 3)
    for n in range(5):
        write(tmp_path, f"run{n}.json", results(f"asset{n}"))
    folder = runs.scan(tmp_path)
    assert len(folder.runs) == 3 and folder.truncated


def test_scan_needs_a_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        runs.scan(write(tmp_path, "results.json", results()))


def test_asset_label_from_windows_and_linux_paths():
    assert runs.asset_label("C:\\assets\\Dishwasher036\\Dishwasher036.usd") == "Dishwasher036"
    assert runs.asset_label("/data/g2/simready_usd/g2_omnipicker.usda") == "g2_omnipicker"
    assert runs.asset_label("plain") == "plain"


def test_summary():
    note = "settings differ from the spec: settle_s is 3.0 (spec: 1.5)"
    run = runs.Run("x.json", Path("x.json"), results(verdicts={"LOAD": "PASS", "PASSIVE": "FAIL"}, notes=[note]))
    s = runs.summary(run)
    assert s["asset"] == "arm" and s["engine"] == "physx" and s["failed"] == 1 and not s["passed"]
    assert s["verdicts"] == {"LOAD": "PASS", "PASSIVE": "FAIL"}
    assert s["settings_differ"] and not s["measured"] and s["worst_margin"] is None
    assert s["spec_url"] == "https://github.com/proofmass/proofmass-check/blob/v0.2.0/docs/spec.md"


def test_summary_of_a_run_that_stopped():
    s = runs.summary(runs.Run("e.json", Path("e.json"), error_results()))
    assert s["error"].endswith("the engine stopped") and s["verdicts"] == {} and not s["passed"]


def test_details_order_the_checks_and_put_the_worst_measurement_first():
    data = results(
        verdicts={"PASSIVE": "FAIL", "LOAD": "PASS", "HOLD": "PASS"},  # not in the order of a run
        measurements={
            "HOLD": [measured("elbow", 0.2 * ONE_DEG, ONE_DEG, True), measured("wrist", 0.9 * ONE_DEG, ONE_DEG, True)],
            "PASSIVE": [measured("door", 27.67 * ONE_DEG, ONE_DEG, False, case="upper", quantity="distance")],
            "LOAD": [measured("arm", 0.0, None, True, unit="kg")],
        },
    )
    d = runs.details(runs.Run("x.json", Path("x.json"), data))
    assert [c["id"] for c in d["checks"]] == ["LOAD", "HOLD", "PASSIVE"]
    assert [m["subject"] for m in d["measurements"]] == ["door", "wrist", "elbow", "arm"]
    assert d["worst_margin"] == pytest.approx(27.67)


def test_margin():
    assert runs.margin(0.5, 1.0) == 0.5
    assert runs.margin(-0.5, 1.0) == 0.5
    assert runs.margin(1.7, 0.85, "min") == pytest.approx(0.5)  # held twice the load it needs
    assert runs.margin(0.0, 0.85, "min") is None  # held nothing: no ratio, and ok says it failed
    for value, limit in ((1.0, None), (1.0, 0.0), (float("nan"), 1.0), (True, 1.0), ("1", 1.0)):
        assert runs.margin(value, limit) is None


def test_shown_values_use_degrees_and_millimetres():
    assert runs.shown(ONE_DEG / 2, "rad") == ("0.500", "deg")
    assert runs.shown(0.00123, "m") == ("1.23", "mm")
    assert runs.shown(math.radians(120.0), "rad/s") == ("120", "deg/s")
    assert runs.shown(3, "1") == ("3", "")
    assert runs.shown(35.02, "kg") == ("35.02", "kg")
    assert runs.shown(None, "m") == ("", "mm")


def test_a_failing_value_never_looks_equal_to_its_limit():
    value, limit = math.radians(1.0000004), ONE_DEG
    shown_value, shown_limit, unit = runs.shown_pair(value, limit, "rad", ok=False)
    assert shown_value != shown_limit and unit == "deg"
    assert runs.shown_pair(limit, limit, "rad", ok=True) == ("1.000", "1.000", "deg")


def _run(name, **kwargs) -> runs.Run:
    return runs.Run(name, Path(name), results(**kwargs))


def test_compare_marks_the_checks_whose_verdicts_differ():
    c = runs.compare(
        [
            _run("physx.json", verdicts={"LOAD": "PASS", "TRACK": "FAIL"}),
            _run("newton.json", engine="newton", verdicts={"LOAD": "PASS", "TRACK": "PASS"}),
        ]
    )
    assert c["same_asset"] and c["same_spec"]
    rows = {row["id"]: row for row in c["checks"]}
    assert not rows["LOAD"]["differs"] and rows["TRACK"]["differs"]
    assert rows["TRACK"]["counts"] == {"FAIL": 1, "PASS": 1}


def test_compare_marks_nothing_between_spec_versions():
    c = runs.compare(
        [
            _run("old.json", spec="0.2", sha="c" * 64, verdicts={"TRACK": "PASS"}),
            _run("new.json", spec="0.3", verdicts={"TRACK": "FAIL"}),
        ]
    )
    assert not c["same_spec"] and not c["same_asset"]
    assert not any(row["differs"] for row in c["checks"])


def test_compare_a_run_that_stopped_with_one_that_finished():
    stopped = runs.Run("e.json", Path("e.json"), error_results(sha="a" * 64))
    c = runs.compare([_run("ok.json"), stopped])
    assert all(row["differs"] and row["cells"][1] is None for row in c["checks"])


def test_compare_measurements():
    first = _run("1.json", measurements={"HOLD": [measured("elbow", 0.2 * ONE_DEG, ONE_DEG, True)]})
    second = _run("2.json", measurements={"HOLD": [measured("elbow", 1.5 * ONE_DEG, ONE_DEG, False)]})
    third = _run("3.json")
    [row] = runs.compare([first, second, third])["measurements"]
    assert (row["check"], row["subject"], row["shown_unit"]) == ("HOLD", "elbow", "deg")
    assert (row["lowest"], row["highest"]) == ("0.200", "1.500")
    assert row["cells"][2] is None and row["differs"]


def test_pair_folders_by_asset_and_engine(tmp_path):
    for name, sha, engine in (
        ("a/arm.json", "1", "physx"),
        ("a/arm_newton.json", "1", "newton"),
        ("a/door.json", "2", "physx"),
    ):
        write(tmp_path, name, results(sha=sha * 64, engine=engine))
    for name, sha, engine in (
        ("b/arm.json", "1", "newton"),
        ("b/arm_physx.json", "1", "physx"),
        ("b/lamp.json", "3", "physx"),
    ):
        write(tmp_path, name, results(sha=sha * 64, engine=engine))
    p = runs.pair_folders(runs.scan(tmp_path / "a"), runs.scan(tmp_path / "b"))
    assert {(pair["a"], pair["b"]) for pair in p["pairs"]} == {
        ("arm.json", "arm_physx.json"),
        ("arm_newton.json", "arm.json"),
    }
    assert p["only_a"] == ["door.json"] and p["only_b"] == ["lamp.json"]


def test_pair_folders_of_two_engines(tmp_path):
    write(tmp_path, "physx/arm.json", results(engine="physx"))
    write(tmp_path, "newton/arm.json", results(engine="newton"))
    p = runs.pair_folders(runs.scan(tmp_path / "physx"), runs.scan(tmp_path / "newton"))
    assert [(pair["a"], pair["b"]) for pair in p["pairs"]] == [("arm.json", "arm.json")]


def test_finite_json():
    value = {"a": [float("nan"), 1.5, {"b": float("inf")}], "c": "text"}
    assert runs.finite_json(value) == {"a": ["nan", 1.5, {"b": "inf"}], "c": "text"}
    json.dumps(runs.finite_json(value), allow_nan=False)
