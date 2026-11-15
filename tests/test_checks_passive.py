# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import dataclasses
import math

import pytest
from fake_engine import IdealEngine

from proofmass_check.checks.passive import base_push, hand_budget, passive, passive_joints
from proofmass_check.model import Drive
from proofmass_check.rules import HAND_FORCE, Settings

SETTINGS = Settings(settle_s=1.0)


def without_drive(asset, name, damping=0.0):
    """The asset with one joint's drive replaced by a damping-only drive (or none)."""
    joint = dataclasses.replace(asset.joint(name), drive=Drive(0.0, damping, None) if damping else None)
    return dataclasses.replace(asset, joints=tuple(joint if j.name == name else j for j in asset.joints)), joint


def test_base_push_of_the_arm(arm):
    """1.5 x gravity on the 1.44 kg bar with its centre 0.2 m out, plus 4 rad/s2."""
    asset, free = without_drive(arm, "arm_joint")
    effort = 1.44 * (1.5 * 9.81 * 0.2 + 4.0 * 0.2**2)
    assert base_push(asset, free, 3.0) == pytest.approx(effort)
    # a damper (a door closer) adds what covers the 60 deg range in half the push
    damped_asset, damped = without_drive(arm, "arm_joint", damping=2.0)
    assert base_push(damped_asset, damped, 3.0) == pytest.approx(effort + 2.0 * math.radians(60) / 1.5)
    # the handle is twice as far out as the centre of mass: 0.4 m
    assert hand_budget(asset, free, 3.0) == pytest.approx(effort + HAND_FORCE * 0.4)


def test_passive_joints(cabinet, arm, gripper):
    assert [j.name for j in passive_joints(cabinet)] == ["drawer_joint", "door_joint"]
    assert passive_joints(arm) == [] and passive_joints(gripper) == []


def test_a_drawer_and_a_door_that_open(cabinet):
    engine = IdealEngine()
    engine.open(cabinet, floor=0.0)
    result = passive(engine, cabinet, passive_joints(cabinet), SETTINGS)
    assert result.verdict == "PASS"
    assert result.detail == (
        "drawer_joint@upper 0.00 mm from the limit; drawer_joint@lower 0.00 mm from the limit; "
        "door_joint@upper 0.000 deg from the limit; door_joint@lower 0.000 deg from the limit"
    )


def test_the_push_rises_up_to_the_hand_budget(cabinet):
    """Joint friction: the drawer moves only with 100 N or more."""

    class Sticky(IdealEngine):
        def push(self, joint, effort, seconds):
            self.calls.append(("push", joint, effort))
            j = self.asset.joint(joint)
            return (j.upper if effort > 0 else j.lower) if abs(effort) >= 100 else 0.2

    drawer = cabinet.joint("drawer_joint")
    engine = Sticky()
    engine.open(cabinet, floor=0.0)
    result = passive(engine, cabinet, [drawer], SETTINGS)
    # 2 kg on a level slide: 2 x 2.0 m/s2 = 4 N, plus 20 N s/m of damping over 0.4 m in 1 s = 8 N
    effort = base_push(cabinet, drawer, 2.0)
    assert effort == pytest.approx(12.0)
    assert [call[2] for call in engine.calls] == pytest.approx([12, 48, 62, -12, -48, -62])  # budget 12 + 50 N
    assert result.verdict == "FAIL"
    assert result.detail == (
        "drawer_joint@upper 200.00 mm from the limit at the hand push 62 N FAIL; "
        "drawer_joint@lower 200.00 mm from the limit at the hand push 62 N FAIL"
    )

    class Stiff(Sticky):
        def push(self, joint, effort, seconds):
            return super().push(joint, effort * 2, seconds)  # needs 50 N instead of 100 N

    engine = Stiff()
    engine.open(cabinet, floor=0.0)
    assert passive(engine, cabinet, [drawer], SETTINGS).detail == (
        "drawer_joint@upper needs 62 N (base push 12, hand 62); drawer_joint@lower needs 62 N (base push 12, hand 62)"
    )
