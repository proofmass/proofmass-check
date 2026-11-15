# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
from proofmass_check.checks import TITLES
from proofmass_check.plan import make_plan
from proofmass_check.rules import Settings

ALL = frozenset(TITLES)


def ran(plan):
    return [check_id for check_id in TITLES if plan.runs(check_id)]


def test_a_prop_is_dropped(prop):
    plan = make_plan(prop, "fake", ALL, Settings())
    assert ran(plan) == ["LOAD", "DROP"]
    assert plan.skip["HOLD"] == "no joint has a position drive"
    assert plan.skip["GRIP"] == "the asset has no gripper site (gripper_maxOpening)"


def test_an_arm_fixed_to_the_world(arm):
    plan = make_plan(arm, "fake", ALL, Settings())
    assert ran(plan) == ["LOAD", "HOLD", "TRACK", "LIMIT", "STABLE", "SPEED"]
    assert plan.skip["DROP"] == "the asset is fixed to the world by root_joint"
    assert [j.name for j in plan.speed_limited] == ["arm_joint"]


def test_a_gripper(gripper):
    plan = make_plan(gripper, "fake", ALL, Settings())
    assert ran(plan) == ["LOAD", "HOLD", "TRACK", "LIMIT", "STABLE", "GRIP", "SHAKE"]
    assert plan.skip["SPEED"] == "no joint with a position drive has a speed limit"
    assert plan.site.name == "grasp"


def test_a_cabinet(cabinet):
    plan = make_plan(cabinet, "fake", ALL, Settings())
    assert ran(plan) == ["LOAD", "PASSIVE"]


def test_no_floor_and_checks_an_engine_cannot_run(prop, arm):
    assert make_plan(prop, "fake", ALL, Settings(floor=False)).skip["DROP"] == "the run has no floor (--no-floor)"
    plan = make_plan(arm, "newton", ALL - {"SPEED"}, Settings())
    assert plan.skip["SPEED"] == "the newton engine cannot run this check on this asset yet"
