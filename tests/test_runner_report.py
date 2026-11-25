# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import dataclasses
import json
from importlib import resources

import jsonschema
from fake_engine import IdealEngine

from proofmass_check import report
from proofmass_check.engines.base import LoadOutcome
from proofmass_check.rules import Settings
from proofmass_check.runner import run_checks

SCHEMA = json.loads(resources.files("proofmass_check").joinpath("results.schema.json").read_text(encoding="utf-8"))


def test_a_full_run_on_the_gripper(gripper, tmp_path):
    run = run_checks(IdealEngine(), gripper, Settings())
    assert run.passed
    assert [(r.id, r.verdict) for r in run.results] == [
        ("LOAD", "PASS"), ("DROP", "N/A"), ("HOLD", "PASS"), ("TRACK", "PASS"), ("LIMIT", "PASS"),
        ("STABLE", "PASS"), ("SPEED", "N/A"), ("PASSIVE", "N/A"), ("GRIP", "PASS"), ("SHAKE", "PASS"),
        ("STAND", "N/A"), ("DRIVE", "N/A"), ("TURN", "N/A"), ("STEER", "N/A"),
    ]  # fmt: skip
    data = report.to_dict(run)
    jsonschema.validate(data, SCHEMA)
    assert data["asset"]["name"] == "unit_gripper" and len(data["asset"]["sha256"]) == 64
    assert data["engine_cannot_run"] == [] and data["wheels_without_mobile"] == []
    assert data["engine"] == {"name": "fake", "versions": {"fake": "1"}}
    path = report.write(data, tmp_path / "out")
    assert json.loads(path.read_text(encoding="utf-8")) == data


def test_other_checks_wait_for_load(arm):
    class DropsAJoint(IdealEngine):
        def load(self):
            return LoadOutcome(missing=("arm_joint",), masses={"/unit_arm/base": 8.0, "/unit_arm/arm": 1.44})

    run = run_checks(DropsAJoint(), arm, Settings())
    assert not run.passed
    assert {r.id: r.verdict for r in run.results}["HOLD"] == "N/A"
    assert run.results[2].detail == "the engine did not build the asset as the USD describes it (LOAD)"


def test_only_an_engine_that_reads_mjc_actuators_drives_a_joint_with_one(actuated_arm):
    class ReadsMjcActuators(IdealEngine):
        reads_mjc_actuators = True

    def verdicts(engine):
        return {r.id: r.verdict for r in run_checks(engine, actuated_arm, Settings()).results}

    physx, newton = verdicts(IdealEngine()), verdicts(ReadsMjcActuators())
    assert (physx["HOLD"], physx["TRACK"], physx["PASSIVE"]) == ("N/A", "N/A", "PASS")
    assert (newton["HOLD"], newton["TRACK"], newton["PASSIVE"]) == ("PASS", "PASS", "N/A")
    assert actuated_arm.joint("arm_joint").drive is None  # the run does not change the asset it was given


def test_settings_that_differ_from_the_spec_are_noted(prop):
    run = run_checks(IdealEngine(), prop, Settings(settle_s=4.0))
    assert run.notes == ("settings differ from the spec: settle_s is 4.0 (spec: 1.5)",)


def test_results_after_an_error(prop, tmp_path):
    asset_file = tmp_path / "prop.usda"
    data = report.error_dict(asset_file, "physx", "Traceback ...")
    jsonschema.validate(data, SCHEMA)
    assert data["passed"] is False


def test_checks_the_engine_cannot_run_are_in_the_results(gripper):
    class NoGrip(IdealEngine):
        supported = IdealEngine.supported - {"GRIP", "SHAKE"}

    run = run_checks(NoGrip(), gripper, Settings())
    assert run.passed and run.engine_cannot_run == ("GRIP", "SHAKE")
    data = report.to_dict(run)
    jsonschema.validate(data, SCHEMA)
    assert data["engine_cannot_run"] == ["GRIP", "SHAKE"]
    note = "the fake engine cannot run GRIP, SHAKE on this asset yet, so this result does not cover them"
    assert note in data["notes"]


def test_wheels_without_their_description_are_in_the_results(rover):
    run = run_checks(IdealEngine(), dataclasses.replace(rover, wheeled=None), Settings())
    data = report.to_dict(run)
    jsonschema.validate(data, SCHEMA)
    assert data["wheels_without_mobile"] == ["left_wheel_joint", "right_wheel_joint"]
