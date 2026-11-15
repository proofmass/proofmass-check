# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""HOLD, TRACK, LIMIT and STABLE: what the position drives do.

Every move starts from the rest pose. The joint under test gets a target, and every other
position-driven joint holds its rest position.
"""

from collections.abc import Sequence

import numpy as np

from proofmass_check.checks import CheckResult, judge, text
from proofmass_check.engines.base import Engine
from proofmass_check.model import Joint
from proofmass_check.rules import LIMIT_TOL, OVERSHOOT, SEED, TRACK_AT, UNSTABLE_SPEED, Settings


def rest_pose(driven: Sequence[Joint]) -> dict[str, float]:
    return {j.name: j.rest for j in driven}


def move_time(settings: Settings, distance: float, max_speed: float) -> float:
    """The time a drive gets for a move: settle_s, plus the time its speed limit needs for the distance.

    A long joint with a speed limit, such as an arm that turns 180 deg at 120 deg/s, cannot get
    there in settle_s alone. A speed limit of 0 or less is read as no limit.
    """
    return settings.settle_s + (abs(distance) / max_speed if max_speed > 0 else 0.0)


def hold(engine: Engine, driven: Sequence[Joint], settings: Settings) -> CheckResult:
    state = engine.settle(rest_pose(driven), settings.settle_s)
    errors = {j.name: abs(state.positions[j.name] - j.rest) for j in driven}
    ok = state.finite and all(errors[j.name] <= settings.tolerance(j.revolute) for j in driven)
    return judge("HOLD", ok, "; ".join(f"{j.name} {text.error(j, errors[j.name])}" for j in driven))


def track(engine: Engine, driven: Sequence[Joint], limited: Sequence[Joint], settings: Settings) -> CheckResult:
    rows, ok_all = [], True
    for joint in limited:
        for fraction in TRACK_AT:
            target = joint.lower + fraction * (joint.upper - joint.lower)
            state = engine.settle(
                {**rest_pose(driven), joint.name: target}, move_time(settings, target - joint.rest, joint.max_speed)
            )
            error = abs(state.positions[joint.name] - target)
            ok = state.finite and error <= settings.tolerance(joint.revolute)
            ok_all &= ok
            rows.append(f"{joint.name}@{fraction:.0%} {text.error(joint, error)}{'' if ok else ' FAIL'}")
    return judge("TRACK", ok_all, "; ".join(rows))


def limit(engine: Engine, driven: Sequence[Joint], limited: Sequence[Joint], settings: Settings) -> CheckResult:
    """Each drive is sent OVERSHOOT of its range past its upper limit. It may stop LIMIT_TOL tolerances past it."""
    rows, ok_all = [], True
    for joint in limited:
        target = joint.upper + OVERSHOOT * (joint.upper - joint.lower)
        state = engine.settle(
            {**rest_pose(driven), joint.name: target}, move_time(settings, joint.upper - joint.rest, joint.max_speed)
        )
        past = state.positions[joint.name] - joint.upper
        ok = state.finite and past <= LIMIT_TOL * settings.tolerance(joint.revolute)
        ok_all &= ok
        rows.append(f"{joint.name} {text.error(joint, max(past, 0.0))} past limit{'' if ok else ' FAIL'}")
    return judge("LIMIT", ok_all, "; ".join(rows))


def stable(engine: Engine, driven: Sequence[Joint], limited: Sequence[Joint], settings: Settings) -> CheckResult:
    """Random poses inside the limits. A pose is unstable when a value is not finite or a joint is too fast."""
    rng = np.random.default_rng(SEED)
    unstable = 0
    for _ in range(settings.random_poses):
        draws = rng.random(len(limited))
        pose = rest_pose(driven) | {
            j.name: j.lower + d * (j.upper - j.lower) for j, d in zip(limited, draws, strict=True)
        }
        state = engine.settle(pose, settings.settle_s)
        unstable += (not state.finite) or state.max_speed > UNSTABLE_SPEED
    return judge("STABLE", unstable == 0, f"{unstable} unstable")
