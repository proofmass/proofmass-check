# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""HOLD, TRACK, LIMIT and STABLE: what the position drives do.

Every move starts from the rest pose. The joint under test gets a target, and every other
position-driven joint holds its rest position.
"""

from collections.abc import Sequence

import numpy as np

from proofmass_check import replay
from proofmass_check.checks import CheckResult, Measurement, judge, text
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
    with replay.label() as clip:
        state = engine.settle(rest_pose(driven), settings.settle_s)
    measurements = []
    for joint in driven:
        error, tolerance = abs(state.positions[joint.name] - joint.rest), settings.tolerance(joint.revolute)
        ok = state.finite and error <= tolerance
        measurements.append(Measurement(joint.name, "", "error", error, tolerance, text.si_unit(joint), ok))
    rows = [f"{m.subject} {text.error(j, m.value)}" for j, m in zip(driven, measurements, strict=True)]
    detail = "; ".join(row + ("" if m.ok else " FAIL") for row, m in zip(rows, measurements, strict=True))
    clip.ok = all(m.ok for m in measurements)
    return judge("HOLD", clip.ok, detail, measurements)


def track(engine: Engine, driven: Sequence[Joint], limited: Sequence[Joint], settings: Settings) -> CheckResult:
    rows, measurements = [], []
    for joint in limited:
        tolerance = settings.tolerance(joint.revolute)
        for fraction in TRACK_AT:
            target = joint.lower + fraction * (joint.upper - joint.lower)
            with replay.label(joint.name, f"{fraction:.0%}") as clip:
                state = engine.settle(
                    {**rest_pose(driven), joint.name: target}, move_time(settings, target - joint.rest, joint.max_speed)
                )
            error = abs(state.positions[joint.name] - target)
            ok = clip.ok = state.finite and error <= tolerance
            measurements.append(
                Measurement(joint.name, f"{fraction:.0%}", "error", error, tolerance, text.si_unit(joint), ok)
            )
            rows.append(f"{joint.name}@{fraction:.0%} {text.error(joint, error)}{'' if ok else ' FAIL'}")
    return judge("TRACK", all(m.ok for m in measurements), "; ".join(rows), measurements)


def limit(engine: Engine, driven: Sequence[Joint], limited: Sequence[Joint], settings: Settings) -> CheckResult:
    """Each drive is sent OVERSHOOT of its range past its upper limit. It may stop LIMIT_TOL tolerances past it."""
    rows, measurements = [], []
    for joint in limited:
        target = joint.upper + OVERSHOOT * (joint.upper - joint.lower)
        seconds = move_time(settings, joint.upper - joint.rest, joint.max_speed)
        with replay.label(joint.name, "upper") as clip:
            state = engine.settle({**rest_pose(driven), joint.name: target}, seconds)
        past = state.positions[joint.name] - joint.upper
        allowed = LIMIT_TOL * settings.tolerance(joint.revolute)
        ok = clip.ok = state.finite and past <= allowed
        # A joint that stops short of its limit is 0 past it. max() keeps a NaN, which then fails.
        past = max(past, 0.0)
        measurements.append(Measurement(joint.name, "upper", "past the limit", past, allowed, text.si_unit(joint), ok))
        rows.append(f"{joint.name} {text.error(joint, past)} past limit{'' if ok else ' FAIL'}")
    return judge("LIMIT", all(m.ok for m in measurements), "; ".join(rows), measurements)


def stable(engine: Engine, driven: Sequence[Joint], limited: Sequence[Joint], settings: Settings) -> CheckResult:
    """Random poses inside the limits. A pose is unstable when a value is not finite or a joint is too fast."""
    rng = np.random.default_rng(SEED)
    unstable = 0
    for number in range(1, settings.random_poses + 1):
        draws = rng.random(len(limited))
        pose = rest_pose(driven) | {
            j.name: j.lower + d * (j.upper - j.lower) for j, d in zip(limited, draws, strict=True)
        }
        with replay.label(attempt=f"pose {number}") as clip:
            state = engine.settle(pose, settings.settle_s)
        bad = (not state.finite) or state.max_speed > UNSTABLE_SPEED
        clip.ok = not bad
        unstable += bad
    measurement = Measurement("", "", "unstable poses", int(unstable), 0, "1", unstable == 0)
    return judge("STABLE", unstable == 0, f"{unstable} unstable", [measurement])
