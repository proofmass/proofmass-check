# SPDX-FileCopyrightText: 2026 The proofmass-check authors
# SPDX-License-Identifier: Apache-2.0
import dataclasses
import math

import pytest
from fake_engine import IdealEngine

from proofmass_check.checks.joints import hold, limit, stable, track
from proofmass_check.checks.speed import far_target, speed
from proofmass_check.engines.base import JointState, Motion
from proofmass_check.rules import UNSTABLE_SPEED, Settings

SETTINGS = Settings(settle_s=1.0)


def engine_for(asset, cls=IdealEngine):
    engine = cls()
    engine.open(asset, floor=0.0)
    return engine


def driven(asset):
    return [j for j in asset.joints if j.drive_kind == "position"]


def test_an_ideal_engine_passes(gripper):
    engine, joints = engine_for(gripper), driven(gripper)
    assert hold(engine, joints, SETTINGS).verdict == "PASS"
    result = track(engine, joints, joints, SETTINGS)
    assert result.verdict == "PASS"
    assert result.detail == (
        "finger_l_joint@25% 0.00 mm; finger_l_joint@75% 0.00 mm; finger_r_joint@25% 0.00 mm; finger_r_joint@75% 0.00 mm"
    )
    assert limit(engine, joints, joints, SETTINGS).verdict == "PASS"
    assert stable(engine, joints, joints, SETTINGS).detail == "0 unstable"


def test_an_engine_that_ignores_limits_fails_limit(arm):
    class NoLimits(IdealEngine):
        def settle(self, targets, seconds):
            return JointState(dict(targets), finite=True, max_speed=0.0)

    hinge = arm.joint("arm_joint")
    result = limit(engine_for(arm, NoLimits), [hinge], [hinge], SETTINGS)
    assert result.verdict == "FAIL"
    assert result.detail == "arm_joint 12.000 deg past limit FAIL"  # 20 % of the 60 deg range


def test_an_engine_that_blows_up_fails_stable(arm):
    class BlowsUp(IdealEngine):
        def settle(self, targets, seconds):
            return dataclasses.replace(super().settle(targets, seconds), max_speed=2 * UNSTABLE_SPEED)

    hinge = arm.joint("arm_joint")
    assert stable(engine_for(arm, BlowsUp), [hinge], [hinge], SETTINGS).detail == "50 unstable"


def test_moves_start_from_the_rest_pose(gripper):
    """HOLD holds the rest pose. TRACK and LIMIT move one joint while the others hold their rest."""
    engine, joints = engine_for(gripper), driven(gripper)
    hold(engine, joints, SETTINGS)
    track(engine, joints, joints, SETTINGS)
    targets = [call[1] for call in engine.calls]
    assert targets[0] == {"finger_l_joint": 0.0, "finger_r_joint": 0.0}
    assert targets[1] == {"finger_l_joint": pytest.approx(0.00625), "finger_r_joint": 0.0}  # 25 % of 0..0.025
    assert targets[3] == {"finger_l_joint": 0.0, "finger_r_joint": pytest.approx(-0.01875)}  # 25 % of -0.025..0


def test_a_drift_back_to_zero_fails_hold(arm):
    hinge = dataclasses.replace(arm.joint("arm_joint"), rest=math.radians(10))
    assert hold(engine_for(arm), [hinge], SETTINGS).verdict == "PASS"  # the ideal engine holds 10 deg

    class DriftsToZero(IdealEngine):
        def settle(self, targets, seconds):
            return JointState({n: 0.0 for n in targets}, finite=True, max_speed=0.0)

    assert hold(engine_for(arm, DriftsToZero), [hinge], SETTINGS).detail == "arm_joint 10.000 deg"


def test_moves_get_the_time_their_speed_limit_needs(arm):
    """arm_joint has a 90 deg/s limit: from 0 to -15 deg takes 1/6 s more than settle_s."""
    engine, hinge = engine_for(arm), arm.joint("arm_joint")
    track(engine, [hinge], [hinge], SETTINGS)
    limit(engine, [hinge], [hinge], SETTINGS)
    seconds = [call[2] for call in engine.calls]
    assert seconds == pytest.approx([1.0 + 15 / 90, 1.0 + 15 / 90, 1.0 + 30 / 90])


def test_speed_sends_each_drive_to_the_far_end(arm):
    engine, hinge = engine_for(arm), arm.joint("arm_joint")
    result = speed(engine, [hinge], [hinge], SETTINGS)
    assert result.verdict == "PASS" and result.detail == "arm_joint 90 of 90 deg/s"
    # from rest at 0, the upper end less 5 % of the 60 deg range
    assert far_target(hinge) == pytest.approx(math.radians(27))
    assert engine.calls[0][1] == {"arm_joint": pytest.approx(math.radians(27))}


def test_speed_fails_a_joint_over_its_limit_or_out_of_its_limits(arm):
    hinge = arm.joint("arm_joint")

    def engine_with(over=1.0, end=None):
        class Capped(IdealEngine):
            def move(self, targets, seconds, step):
                steps = round(seconds / step)
                speeds = {n: [over * hinge.max_speed] * steps for n in targets}
                return Motion(speeds=speeds, positions={n: end if end is not None else t for n, t in targets.items()},
                              finite=True)  # fmt: skip

        return engine_for(arm, Capped)

    assert speed(engine_with(over=1.04), [hinge], [hinge], SETTINGS).verdict == "PASS"  # within SPEED_TOL
    assert speed(engine_with(over=1.2), [hinge], [hinge], SETTINGS).detail == "arm_joint 108 of 90 deg/s FAIL"
    blown = speed(engine_with(end=-30.0), [hinge], [hinge], SETTINGS)
    assert blown.detail == "arm_joint 90 of 90 deg/s, a joint left its limits FAIL"
