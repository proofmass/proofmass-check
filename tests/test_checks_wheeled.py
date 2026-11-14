# SPDX-FileCopyrightText: 2026 The proofmass-check authors
# SPDX-License-Identifier: Apache-2.0
import dataclasses
import math

import numpy as np
import pytest
from fake_engine import IdealEngine

from proofmass_check.checks import TITLES
from proofmass_check.checks.wheeled import Commands, commands, drive_speed, evaluate
from proofmass_check.model import SteeringJoint, Wheel, WheeledBase
from proofmass_check.plan import make_plan
from proofmass_check.rules import BASE_LIFT, Settings
from proofmass_check.runner import run_checks


def test_the_rover_is_planned_as_a_wheeled_robot(rover):
    plan = make_plan(rover, "fake", frozenset(TITLES), Settings())
    assert [c for c in TITLES if plan.runs(c)] == ["LOAD", "STAND", "DRIVE", "TURN"]
    assert plan.skip["DROP"] == "a wheeled robot: STAND drops it instead"
    assert plan.skip["STEER"] == "a differential robot does not steer: see TURN"
    assert make_plan(rover, "fake", frozenset(TITLES), Settings(floor=False)).skip["STAND"] == (
        "the run has no floor (--no-floor)"
    )


def test_wheel_commands(rover):
    base = rover.wheeled
    drive = commands(base, "DRIVE")
    assert drive.wheels == {"left_wheel_joint": pytest.approx(5.0), "right_wheel_joint": pytest.approx(5.0)}  # 0.5 m/s
    turn = commands(base, "TURN")
    assert turn.wheels["left_wheel_joint"] == pytest.approx(-5.0) and turn.yaw_rate == pytest.approx(2.5)
    assert commands(base, "STAND").wheels == {"left_wheel_joint": 0.0, "right_wheel_joint": 0.0}
    # a wheel limited to 2 rad/s (0.2 m/s) halves to 0.1 m/s
    slow = dataclasses.replace(base, wheels=(dataclasses.replace(base.wheels[0], max_speed=2.0), base.wheels[1]))
    assert drive_speed(slow) == pytest.approx(0.1)


def test_ackermann_commands():
    """Front steering 1 m ahead of the driven axle, 0.6 m apart, +-30 deg: the inner wheel turns 15 deg."""
    wheels = tuple(
        Wheel(f"{side}_rear", side, True, 0.1, 1, np.array([0.0, y, 0.1]))
        for side, y in (("left", 0.3), ("right", -0.3))
    )
    steering = tuple(
        SteeringJoint(f"{side}_steer", side, 1.0, y, 1, math.radians(-30), math.radians(30))
        for side, y in (("left", 0.3), ("right", -0.3))
    )
    base = WheeledBase("ackermann", 0.1, 0.6, np.zeros(2), wheels, steering, wheelbase=1.0, front_track=0.6)
    steer = commands(base, "STEER")
    radius = 1.0 / math.tan(math.radians(15)) + 0.3
    assert steer.radius == pytest.approx(radius)
    assert steer.steer["left_steer"] == pytest.approx(math.radians(15))  # the inner wheel
    assert steer.steer["right_steer"] == pytest.approx(math.atan(1.0 / (radius + 0.3)))
    assert steer.wheels["left_rear"] == pytest.approx(0.5 * (radius - 0.3) / radius / 0.1)


def path(rows):
    return np.array(rows, float)


def straight(speed=0.5, drift=0.0, seconds=4.0):
    t = np.arange(0, seconds + 1e-9, 0.02)
    return path(np.c_[t, speed * t, drift * t, np.zeros_like(t), np.zeros_like(t)])


def test_evaluate_drive(rover):
    sent = Commands({}, seconds=4.0, speed=0.5)
    ok, detail = evaluate(rover.wheeled, "DRIVE", sent, straight())
    assert ok and detail == "speed 0.500 m/s (commanded 0.500), sideways drift 0 mm over 1.25 m, heading change 0.0 deg"
    assert not evaluate(rover.wheeled, "DRIVE", sent, straight(drift=0.1))[0]  # 20 % sideways
    backwards = evaluate(rover.wheeled, "DRIVE", sent, straight(speed=-0.5))
    assert not backwards[0] and backwards[1].endswith("the robot drove toward -X: turn the model so its front faces +X")
    unstable = straight()
    unstable[10, 1] = np.nan
    assert evaluate(rover.wheeled, "DRIVE", sent, unstable) == (False, "the simulation became unstable (NaN)")


def test_evaluate_turn_and_stand(rover):
    t = np.arange(0, 4.0 + 1e-9, 0.02)
    turning = path(np.c_[t, np.zeros_like(t), np.zeros_like(t), 2.5 * t, np.zeros_like(t)])
    ok, detail = evaluate(rover.wheeled, "TURN", Commands({}, speed=0.5, yaw_rate=2.5), turning)
    assert ok and detail == "yaw rate 143.2 deg/s (expected 143.2), centre moved 0 mm"
    leaning = path(np.c_[t, np.zeros_like(t), np.zeros_like(t), np.zeros_like(t), np.full_like(t, math.radians(5))])
    assert evaluate(rover.wheeled, "STAND", Commands({}), leaning) == (
        False,
        "tilt 5.00 deg, speed 0.0 mm/s after the drop",
    )


def test_a_full_run_on_the_rover(rover):
    engine = IdealEngine()
    run = run_checks(engine, rover, Settings())
    assert engine.hold_base == BASE_LIFT
    verdicts = {r.id: r.verdict for r in run.results}
    assert {c: verdicts[c] for c in ("LOAD", "STAND", "DRIVE", "TURN", "STEER")} == {
        "LOAD": "PASS",
        "STAND": "PASS",
        "DRIVE": "PASS",
        "TURN": "PASS",
        "STEER": "N/A",
    }
