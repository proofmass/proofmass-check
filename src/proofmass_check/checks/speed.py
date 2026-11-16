# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""SPEED: at Isaac Sim's default physics step, each drive stays under its speed limit.

An asset can be stable at a small step and break at the step most users run. This follows NVIDIA's
velocity_limit benchmark.
"""

import math
from collections.abc import Sequence

import numpy as np

from proofmass_check.checks import CheckResult, judge, text
from proofmass_check.checks.joints import rest_pose
from proofmass_check.engines.base import Engine
from proofmass_check.model import Joint
from proofmass_check.rules import (
    LIMIT_TOL,
    SPEED_DT,
    SPEED_MARGIN,
    SPEED_SECONDS,
    SPEED_SKIP_STEPS,
    SPEED_TOL,
    Settings,
)


def far_target(joint: Joint) -> float:
    """The end of the range farther from rest, SPEED_MARGIN of the range short of it."""
    margin = SPEED_MARGIN * (joint.upper - joint.lower)
    return joint.upper - margin if joint.rest <= (joint.lower + joint.upper) / 2 else joint.lower + margin


def speed(engine: Engine, driven: Sequence[Joint], tested: Sequence[Joint], settings: Settings) -> CheckResult:
    """tested: the driven joints with limits and a speed limit.

    Each one moves to far_target for SPEED_SECONDS. After the first SPEED_SKIP_STEPS steps its speed
    must stay within its limit plus SPEED_TOL. At the end, every driven joint must be inside its
    limits: a coupling that blows up at a large step pushes joints out of them.

    A short joint can end its move inside the steps that are not measured, and the measured speed is
    then that of a joint that already stands. So when the joint was faster in those steps, the
    result gives that speed too. It does not change the verdict.
    """
    rows, ok_all = [], True
    for joint in tested:
        motion = engine.move({**rest_pose(driven), joint.name: far_target(joint)}, SPEED_SECONDS, SPEED_DT)
        speeds = np.abs(motion.speeds[joint.name])
        early = float(np.max(speeds[:SPEED_SKIP_STEPS], initial=0.0))
        peak = float(np.max(speeds[SPEED_SKIP_STEPS:], initial=0.0))
        inside = motion.finite and all(_inside(j, motion.positions[j.name], settings) for j in driven)
        ok = inside and peak <= joint.max_speed * (1 + SPEED_TOL)
        ok_all &= ok
        rows.append(
            f"{joint.name} {text.speed(joint, peak)} of {text.speed(joint, joint.max_speed, 'g')} "
            f"{text.speed_unit(joint)}"
            + (
                f" ({text.speed(joint, early)} in the first {SPEED_SKIP_STEPS} steps, which are not measured)"
                if early > peak
                else ""
            )
            + ("" if inside else ", a joint left its limits")
            + ("" if ok else " FAIL")
        )
    return judge("SPEED", ok_all, "; ".join(rows))


def _inside(joint: Joint, position: float, settings: Settings) -> bool:
    if not math.isfinite(position):
        return False
    if not joint.limited:
        return True
    margin = LIMIT_TOL * settings.tolerance(joint.revolute)
    return joint.lower - margin <= position <= joint.upper + margin
