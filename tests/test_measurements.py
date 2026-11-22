# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Measurements: each check that ran lists the numbers it compared with its rule (docs/spec.md, section 6)."""

import json
import math
from importlib import resources

import jsonschema
import pytest
from fake_engine import IdealEngine

from proofmass_check import report
from proofmass_check.checks.grip import grip_and_shake
from proofmass_check.checks.passive import hand_budget, passive, passive_joints
from proofmass_check.engines.base import JointState
from proofmass_check.rules import ANGULAR_TOL_DEG, GRIP_LOAD, LIMIT_TOL, PUSH_SETTLE, Settings
from proofmass_check.runner import run_checks

SCHEMA = json.loads(resources.files("proofmass_check").joinpath("results.schema.json").read_text(encoding="utf-8"))
UNITS = {"m", "rad", "m/s", "rad/s", "kg", "N", "N m", "1"}
ASSETS = ("arm", "tooled_arm", "gripper", "mimic_gripper", "cabinet", "prop", "rover")


def assert_measured(results):
    """Every check that ran lists measurements, and passes exactly when all of them are ok."""
    for result in results:
        if result.verdict == "N/A":
            assert result.measurements == (), result.id
            continue
        assert result.measurements, f"{result.id} ran but lists no measurement"
        assert result.verdict == ("PASS" if all(m.ok for m in result.measurements) else "FAIL"), result.id
        for m in result.measurements:
            assert m.unit in UNITS and m.bound in ("max", "min"), (result.id, m)


def written(run) -> dict:
    """results.json of a run, checked against the schema and written as strict JSON."""
    data = report.to_dict(run)
    jsonschema.validate(data, SCHEMA)
    json.dumps(data, allow_nan=False)
    return data


@pytest.mark.parametrize("name", ASSETS)
def test_every_check_of_a_full_run_lists_its_measurements(name, request):
    run = run_checks(IdealEngine(), request.getfixturevalue(name), Settings())
    assert_measured(run.results)
    data = written(run)
    for check in data["checks"]:
        assert ("measurements" in check) == (check["verdict"] != "N/A"), check["id"]


class NoLimits(IdealEngine):
    """Drives reach every target, also past the joint limits."""

    def settle(self, targets, seconds):
        return JointState(dict(targets), finite=True, max_speed=0.0)


class BlowsUp(IdealEngine):
    """Every joint ends as NaN."""

    def settle(self, targets, seconds):
        return JointState(dict.fromkeys(targets, math.nan), finite=False, max_speed=math.nan)


def test_a_failing_check_names_the_number_that_failed(arm):
    run = run_checks(NoLimits(), arm, Settings())
    assert_measured(run.results)
    limit = next(r for r in run.results if r.id == "LIMIT")
    (past,) = limit.measurements
    assert (past.subject, past.case, past.quantity, past.unit, past.ok) == (
        "arm_joint",
        "upper",
        "past the limit",
        "rad",
        False,
    )
    assert past.value == pytest.approx(math.radians(12.0))  # 20 % of the 60 deg range
    assert past.limit == pytest.approx(LIMIT_TOL * math.radians(ANGULAR_TOL_DEG))


def test_a_value_that_is_not_finite_is_written_as_null(arm):
    run = run_checks(BlowsUp(), arm, Settings())
    assert_measured(run.results)
    hold = next(c for c in written(run)["checks"] if c["id"] == "HOLD")
    assert hold["verdict"] == "FAIL"
    assert [(m["value"], m["ok"]) for m in hold["measurements"]] == [(None, False)]


def test_passive_measures_the_distance_and_the_push(cabinet):
    class Stuck(IdealEngine):
        """Nothing moves the joints: each stays at its rest position."""

        def push(self, joint, effort, seconds):
            return self.asset.joint(joint).rest

    engine = Stuck()
    engine.open(cabinet, floor=0.0)
    settings = Settings(settle_s=1.0)
    result = passive(engine, cabinet, passive_joints(cabinet), settings)
    assert_measured([result])
    door = cabinet.joint("door_joint")
    upper = {m.quantity: m for m in result.measurements if m.subject == "door_joint" and m.case == "upper"}
    assert upper["distance from the limit"].value == pytest.approx(door.upper - door.rest)
    assert upper["push"].unit == "N m" and not upper["push"].ok
    assert upper["push"].value == pytest.approx(hand_budget(cabinet, door, PUSH_SETTLE * settings.settle_s))
    assert upper["push"].limit == upper["push"].value  # it pushed with all a hand adds, and the door stayed


def test_grip_measures_the_load_held_against_a_lower_bound(gripper):
    engine = IdealEngine()
    engine.open(gripper, floor=0.0)
    (site,) = gripper.sites
    grip, shake = grip_and_shake(engine, gripper, site, Settings())
    assert_measured([grip, shake])
    assert [(m.case, m.bound, m.unit) for m in grip.measurements] == [
        ("out of the fingers", "min", "kg"),
        ("along the grip line", "min", "kg"),
    ]
    assert all(m.value >= m.limit == pytest.approx(GRIP_LOAD * site.payload) for m in grip.measurements)
    assert [m.quantity for m in shake.measurements] == ["slip along the pads"]
