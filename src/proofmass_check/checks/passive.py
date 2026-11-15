# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""PASSIVE: a joint without a drive, such as a door or a drawer, opens to its limits and stops there.

The base push is what the joint needs against gravity, plus a little to get it moving. A joint held
by friction (a door that stays where you leave it) needs more. So a push that does not reach the
limit is tried again, PUSH_STEP times stronger each time, up to what a hand adds at the handle.
"""

import math
from collections.abc import Sequence

import numpy as np

from proofmass_check.checks import CheckResult, judge, text
from proofmass_check.engines.base import Engine
from proofmass_check.geometry import apply
from proofmass_check.model import Asset, Joint
from proofmass_check.rules import (
    GRAVITY,
    HAND_FORCE,
    LIMIT_TOL,
    PUSH_ACCEL_ANGULAR,
    PUSH_ACCEL_LINEAR,
    PUSH_GRAVITY_FACTOR,
    PUSH_MIN_LEVER,
    PUSH_SETTLE,
    PUSH_STEP,
    Settings,
)


def passive_joints(asset: Asset) -> list[Joint]:
    """The joints PASSIVE pushes: limited, not following another joint, and with no position drive.

    A damping-only drive (a door closer) counts as no drive, except on a wheeled robot: there it
    turns a wheel.
    """
    skip = {"position", "velocity"} if asset.wheeled else {"position"}
    return [j for j in asset.joints if j.moves and j.limited and not j.mimic and j.drive_kind not in skip]


def lever(asset: Asset, joint: Joint) -> tuple[float, float]:
    """The mass a joint carries (kg), and for a revolute joint the distance of its centre of mass from the axis (m)."""
    carried = [asset.bodies[path] for path in asset.carried(joint.body1)] if joint.body1 else []
    unknown = [b.path for b in carried if b.mass is None]
    if unknown:  # the engine reports these masses (checks/load.py: with_engine_masses)
        raise ValueError(f"the mass of {unknown} is not known")
    mass = sum(b.mass for b in carried)
    if mass <= 0:
        return 0.0, 0.0
    com = sum(b.mass * apply(b.pose, b.com) for b in carried) / mass
    return mass, float(np.linalg.norm(np.cross(com - joint.pivot, joint.direction)))


def base_push(asset: Asset, joint: Joint, seconds: float) -> float:
    """The force (N) or torque (N m) that moves a joint to a limit against gravity.

    PUSH_GRAVITY_FACTOR times the largest gravity load on the joint, plus enough to accelerate what
    it carries (PUSH_ACCEL_LINEAR or PUSH_ACCEL_ANGULAR), plus what a damper needs to cross the range
    in half the push.
    """
    mass, distance = lever(asset, joint)
    axis = joint.direction
    if joint.revolute:
        arm = max(distance, PUSH_MIN_LEVER)
        tilt_of_axis = float(np.linalg.norm(np.cross(axis, [0.0, 0.0, 1.0])))  # 0 for a vertical axis
        gravity = mass * (PUSH_GRAVITY_FACTOR * GRAVITY * tilt_of_axis * distance + PUSH_ACCEL_ANGULAR * arm**2)
    else:
        gravity = mass * (PUSH_GRAVITY_FACTOR * GRAVITY * abs(axis[2]) + PUSH_ACCEL_LINEAR)
    damping = joint.drive.damping if joint.drive else 0.0
    return gravity + damping * (joint.upper - joint.lower) / (seconds / 2)


def hand_budget(asset: Asset, joint: Joint, seconds: float) -> float:
    """The most PASSIVE pushes a joint with: base_push plus HAND_FORCE at the handle.

    On a revolute joint the handle is twice as far from the axis as the centre of mass, and at
    least PUSH_MIN_LEVER away.
    """
    arm = 1.0 if not joint.revolute else max(2 * lever(asset, joint)[1], PUSH_MIN_LEVER)
    return base_push(asset, joint, seconds) + HAND_FORCE * arm


def passive(engine: Engine, asset: Asset, joints: Sequence[Joint], settings: Settings) -> CheckResult:
    seconds = PUSH_SETTLE * settings.settle_s
    rows, ok_all = [], True
    for joint in joints:
        for row, ok in _push_both_ways(engine, asset, joint, seconds, settings):
            ok_all &= ok
            rows.append(row + ("" if ok else " FAIL"))
    return judge("PASSIVE", ok_all, "; ".join(rows))


def _push_both_ways(engine: Engine, asset: Asset, joint: Joint, seconds: float, settings: Settings):
    effort, budget = base_push(asset, joint, seconds), hand_budget(asset, joint, seconds)
    margin = LIMIT_TOL * settings.tolerance(joint.revolute)
    unit = text.effort_unit(joint)
    for sign, limit, side in ((1, joint.upper, "upper"), (-1, joint.lower, "lower")):
        tried = effort
        error = abs(engine.push(joint.name, sign * tried, seconds) - limit)
        ok = math.isfinite(error) and error <= margin
        if ok:
            yield f"{joint.name}@{side} {text.error(joint, error)} from the limit", True
            continue
        while not ok and tried < budget:
            tried = min(tried * PUSH_STEP, budget)
            error = abs(engine.push(joint.name, sign * tried, seconds) - limit)
            ok = math.isfinite(error) and error <= margin
        if ok:
            yield f"{joint.name}@{side} needs {tried:.3g} {unit} (base push {effort:.3g}, hand {budget:.3g})", True
        else:
            yield (
                f"{joint.name}@{side} {text.error(joint, error)} from the limit at the hand push {budget:.3g} {unit}",
                False,
            )
