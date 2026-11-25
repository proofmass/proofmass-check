# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import dataclasses

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
    assert plan.engine_cannot_run == ("SPEED",)
    assert "the newton engine cannot run SPEED on this asset yet, so this result does not cover them" in plan.notes
    assert make_plan(arm, "fake", ALL, Settings()).engine_cannot_run == ()
    # a check the asset does not need is not one the engine could not run
    assert make_plan(prop, "newton", ALL - {"SPEED"}, Settings()).engine_cannot_run == ()


def test_physx_joint_friction_is_noted_in_the_engines_that_do_not_read_it(cabinet):
    door = dataclasses.replace(cabinet.joint("door_joint"), physx_friction=5.0)
    rubbing = dataclasses.replace(cabinet, joints=tuple(door if j.name == door.name else j for j in cabinet.joints))
    note = (
        "only PhysX reads joint friction (physxJoint:jointFriction), so in the newton engine these joints move "
        "without it: door_joint 5"
    )
    assert note in make_plan(rubbing, "newton", ALL, Settings()).notes
    assert not any("jointFriction" in n for n in make_plan(rubbing, "physx", ALL, Settings()).notes)
    assert not any("jointFriction" in n for n in make_plan(cabinet, "newton", ALL, Settings()).notes)


def test_wheels_without_their_description_are_noted(rover, cabinet):
    bare = dataclasses.replace(rover, wheeled=None)  # a robot from another maker: wheels, but no mobile description
    note = (
        "left_wheel_joint, right_wheel_joint look like wheels (no limits, a horizontal axis, a velocity drive), but "
        "the asset has no SimReady_Metadata.mobile, so STAND, DRIVE, TURN and STEER do not run (docs/wheeled-robots.md)"
    )
    plan = make_plan(bare, "physx", ALL, Settings())
    assert note in plan.notes and plan.wheels_without_mobile == ("left_wheel_joint", "right_wheel_joint")
    assert make_plan(rover, "physx", ALL, Settings()).wheels_without_mobile == ()
    assert not any("look like wheels" in n for n in make_plan(rover, "physx", ALL, Settings()).notes)
    assert not any("look like wheels" in n for n in make_plan(cabinet, "physx", ALL, Settings()).notes)
