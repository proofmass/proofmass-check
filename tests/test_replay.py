# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The replay (docs/gui.md, section 5.5): the file, the labels the checks give, and that it changes no result."""

import json
import math
import struct
from importlib import resources

import jsonschema
import numpy as np
import pytest
import usd_assets
from fake_engine import IdealEngine

from proofmass_check import cli, engines, replay, report
from proofmass_check.gui import runs
from proofmass_check.rules import Settings
from proofmass_check.runner import STATIC, run_checks

SCHEMA = json.loads(resources.files("proofmass_check").joinpath("results.schema.json").read_text(encoding="utf-8"))
# Together, every check that runs an operation but STEER. loose_arm is held (spec 0.5).
ASSETS = ["arm", "prop", "cabinet", "gripper", "rover", "loose_arm"]
NO_CLIP = {"LOAD", *STATIC}  # they run no step
POSE = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]


def recorded(asset, engine=None):
    recorder = replay.Recorder(asset.bodies)
    run = run_checks(engine or IdealEngine(), asset, Settings(), recorder=recorder)
    return run, recorder


def test_a_replay_file_reads_back(tmp_path):
    recorder = replay.Recorder(["/a/base", "/a/arm"])
    recorder.start("TRACK", "settle", {"targets": {"j": np.float64(0.5), "k": math.nan}, "seconds": 1.5})
    recorder.frame(0.0, [POSE, POSE])
    recorder.frame(0.5, [[1.0, 2.0, 3.0, 1.0, 0.0, 0.0, 0.0], [math.nan] * 7])
    recorder.end()
    with replay.label("site", "out of the fingers", "1.7 kg") as clip:
        recorder.start("GRIP", "trial", {"mass": 1.7, "direction": np.array([0.0, 0.0, 1.0])}, box=(0.05, 0.02, 0.02))
    clip.ok = False
    recorder.frame(0.0, [POSE, POSE, POSE])
    recorder.end()
    path = replay.write(recorder, tmp_path, "physx", "ab" * 32)
    assert path == tmp_path / "replay.bin"

    data = path.read_bytes()
    assert data[:8] == b"PMREPLAY" and struct.unpack("<II", data[8:16])[0] == 1
    assert (16 + struct.unpack("<II", data[8:16])[1]) % 4 == 0  # the frames start on a multiple of 4 bytes

    header, frames = replay.read(path)
    assert header["id"] == recorder.id and len(recorder.id) == 32
    assert header["engine"] == "physx" and header["sha256"] == "ab" * 32
    assert header["bodies"] == ["/a/base", "/a/arm"]
    first, grip = header["clips"]
    assert first == {
        "check": "TRACK", "subject": "", "case": "", "attempt": "", "ok": None, "operation": "settle",
        "arguments": {"targets": {"j": 0.5, "k": None}, "seconds": 1.5}, "box": None, "offset": 0, "frames": 2,
    }  # fmt: skip
    assert frames[0].shape == (2, 15)
    assert frames[0][1, :4].tolist() == [0.5, 1.0, 2.0, 3.0] and np.isnan(frames[0][1, 8:]).all()
    assert grip["check"] == "GRIP" and grip["subject"] == "site" and grip["case"] == "out of the fingers"
    assert grip["attempt"] == "1.7 kg" and grip["ok"] is False and grip["arguments"]["direction"] == [0.0, 0.0, 1.0]
    assert grip["box"] == pytest.approx([0.05, 0.02, 0.02]) and grip["offset"] == 2 * 15
    assert frames[1].shape == (1, 22)  # the grip box is a third pose


def test_a_frame_at_time_0_starts_the_clip_again():
    """Newton runs a measurement again when a buffer of its solver ran out: only the last run counts."""
    recorder = replay.Recorder(["/a/base"])
    recorder.start("HOLD", "settle", {})
    for t in (0.0, 0.5, 0.0, 0.25):
        recorder.frame(t, [POSE])
    assert [f[0] for f in recorder.clips[0].frames] == [0.0, 0.25]


def test_a_frame_of_the_wrong_size_is_refused():
    recorder = replay.Recorder(["/a/base", "/a/arm"])
    recorder.start("HOLD", "settle", {})
    with pytest.raises(ValueError, match="2 poses of 7 values"):
        recorder.frame(0.0, [POSE])


def test_a_frame_without_an_open_clip_is_dropped():
    recorder = replay.Recorder(["/a/base"])
    recorder.frame(0.0, [POSE])
    assert recorder.clips == []


def test_steps_between_frames():
    assert replay.every(1 / 240) == 8 and replay.every(1 / 60) == 2 and replay.every(0.1) == 1


@pytest.mark.parametrize("name", ASSETS)
def test_every_clip_has_a_label_and_each_measurement_finds_its_clips(name, request):
    asset = request.getfixturevalue(name)
    run, recorder = recorded(asset)
    ran = {r.id for r in run.results if r.verdict != "N/A"} - NO_CLIP
    assert {c.check for c in recorder.clips} == ran
    for clip in recorder.clips:
        assert clip.label.ok is not None, (clip.check, clip.operation)
        times = [f[0] for f in clip.frames]
        assert times[0] == 0 and times == sorted(times)
        assert times[-1] == pytest.approx(clip.arguments.get("seconds", times[-1]))
    labels = {(c.check, c.label.subject, c.label.case) for c in recorder.clips}
    for result in run.results:
        for m in result.measurements if result.id not in NO_CLIP else ():
            whole = (result.id, "", "") in labels  # a clip of the whole asset, such as HOLD's
            assert (result.id, m.subject, m.case) in labels or whole, (result.id, m.subject, m.case)


def test_the_labels_of_each_check(gripper, cabinet):
    _, recorder = recorded(gripper)
    by_check = {}
    for clip in recorder.clips:
        by_check.setdefault(clip.check, []).append(clip)
    finger = by_check["TRACK"][0].label.subject
    assert [(c.label.subject, c.label.case) for c in by_check["TRACK"][:2]] == [(finger, "25%"), (finger, "75%")]
    assert {c.label.case for c in by_check["LIMIT"]} == {"upper"}
    assert [c.label.attempt for c in by_check["STABLE"]] == [f"pose {n}" for n in range(1, 51)]
    assert [c.label.subject for c in by_check["HOLD"]] == [""]
    grip = by_check["GRIP"][0]
    assert grip.operation == "trial" and grip.box is not None and grip.label.attempt.endswith(" kg")
    # A player needs the grip scene's times: the pull starts when the fingers have closed.
    assert {"close_seconds": 1.5, "pull_seconds": 2.0, "shake_hz": 2.0}.items() <= grip.arguments.items()
    assert {c.label.case for c in by_check["GRIP"]} == {"out of the fingers", "along the grip line"}
    (shake,) = by_check["SHAKE"]
    assert shake.label.case == "" and shake.arguments["shake"] is True and shake.label.ok is True
    _, recorder = recorded(cabinet)
    assert all(c.label.attempt.startswith("push ") and c.label.case in ("upper", "lower") for c in recorder.clips)


def test_an_operation_that_fails_keeps_its_ok(arm):
    """The clip's ok is what the check decided from that operation."""

    class Stuck(IdealEngine):
        def settle(self, targets, seconds):
            state = super().settle(targets, seconds)
            return type(state)({n: 0.0 for n in targets}, state.finite, state.max_speed)

    _, recorder = recorded(arm, Stuck())
    track = [c for c in recorder.clips if c.check == "TRACK"]
    assert track and not any(c.label.ok for c in track)


@pytest.mark.parametrize("name", ASSETS)
def test_a_replay_changes_no_result(name, request):
    asset = request.getfixturevalue(name)
    without = report.to_dict(run_checks(IdealEngine(), asset, Settings()))
    with_replay = report.to_dict(recorded(asset)[0])
    without.pop("seconds"), with_replay.pop("seconds")
    assert with_replay == without


def test_run_with_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(engines, "create", lambda name: IdealEngine())
    asset = usd_assets.gripper(tmp_path / "gripper.usda")
    assert cli.main(["run", str(asset), "--out", str(tmp_path / "out"), "--replay"]) == cli.PASSED
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    header, frames = replay.read(tmp_path / "out" / data["replay"]["file"])
    assert data["replay"]["id"] == header["id"] and header["sha256"] == data["asset"]["sha256"]
    assert header["engine"] == "fake" and len(frames) == len(header["clips"]) > 0

    assert cli.main(["run", str(asset), "--out", str(tmp_path / "plain")]) == cli.PASSED
    plain = json.loads((tmp_path / "plain" / "results.json").read_text(encoding="utf-8"))
    assert "replay" not in plain and not (tmp_path / "plain" / "replay.bin").exists()


def test_a_run_that_stops_keeps_the_clips_before_the_error(tmp_path, monkeypatch):
    class BreaksInLimit(IdealEngine):
        def settle(self, targets, seconds):
            if any(v > self.asset.joint(n).upper for n, v in targets.items()):
                raise RuntimeError("the engine broke")
            return super().settle(targets, seconds)

    monkeypatch.setattr(engines, "create", lambda name: BreaksInLimit())
    asset = usd_assets.arm(tmp_path / "arm.usda")
    assert cli.main(["run", str(asset), "--out", str(tmp_path / "out"), "--replay"]) == cli.ERROR
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    assert "the engine broke" in data["error"]
    header, _ = replay.read(tmp_path / "out" / "replay.bin")
    assert header["id"] == data["replay"]["id"]
    assert [c["check"] for c in header["clips"]][-1] == "LIMIT"  # the clip of the error, after HOLD and TRACK
    assert {c["check"] for c in header["clips"]} == {"HOLD", "TRACK", "LIMIT"}


def test_the_gui_does_not_take_a_replay_for_results(tmp_path, monkeypatch):
    monkeypatch.setattr(engines, "create", lambda name: IdealEngine())
    asset = usd_assets.prop(tmp_path / "prop.usda")
    cli.main(["run", str(asset), "--out", str(tmp_path / "out"), "--replay"])
    folder = runs.scan(tmp_path / "out")
    assert [r.id for r in folder.runs] == ["results.json"] and folder.problems == []
