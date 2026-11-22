# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""STAND, DRIVE, TURN and STEER: a wheeled robot stands, drives straight and turns.

The robot is described by SimReady_Metadata.mobile (docs/wheeled-robots.md). Every engine gets the
same wheel speeds and steering angles, and the result is judged on the path of one point: the
centre of the driven axle, which the robot turns about.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from proofmass_check import rules
from proofmass_check.checks import CheckResult, Measurement, judge
from proofmass_check.engines.base import BaseTrace, Engine
from proofmass_check.model import Asset, WheeledBase


@dataclass(frozen=True)
class Commands:
    """What one check sends to the wheels, and what it expects."""

    wheels: dict[str, float]  # rad/s, by wheel joint
    steer: dict[str, float] = field(default_factory=dict)  # rad, by steering joint
    seconds: float = rules.STAND_SECONDS
    speed: float = 0.0  # m/s, commanded
    yaw_rate: float | None = None  # rad/s, TURN
    radius: float | None = None  # m, STEER


def drive_speed(base: WheeledBase) -> float:
    """WHEEL_SPEED, or WHEEL_LIMIT_FRACTION of the slowest driven wheel's speed limit when that is lower."""
    limits = [w.max_speed * w.radius for w in base.wheels if w.driven and w.max_speed is not None]
    return min([rules.WHEEL_SPEED] + [rules.WHEEL_LIMIT_FRACTION * s for s in limits])


def commands(base: WheeledBase, check_id: str) -> Commands:
    driven = [w for w in base.wheels if w.driven]
    v = drive_speed(base)
    if check_id == "STAND":  # wheels braked
        return Commands(wheels={w.name: 0.0 for w in driven}, speed=v)
    if check_id == "DRIVE":
        return Commands({w.name: v / w.radius * w.spin for w in driven}, seconds=rules.DRIVE_SECONDS, speed=v)
    if check_id == "TURN":  # left wheels back, right wheels forward: the robot turns left
        return Commands(
            {w.name: (-v if w.side == "left" else v) / w.radius * w.spin for w in driven},
            seconds=rules.TURN_SECONDS,
            speed=v,
            yaw_rate=2 * v / base.track,
        )
    if check_id == "STEER":
        return _steer_commands(base, driven, v)
    raise ValueError(check_id)


def _steer_commands(base: WheeledBase, driven, v: float) -> Commands:
    """A left turn with the inner front wheel at STEER_FRACTION of its range, in Ackermann geometry.

    Each front wheel gets the angle that points it at the turn's centre. Each driven wheel gets the
    speed of its own circle around that centre.
    """
    reach = min(s.upper if s.sign > 0 else -s.lower for s in base.steering)
    inner = rules.STEER_FRACTION * reach
    wheelbase, front_track = base.wheelbase, base.front_track
    radius = wheelbase / math.tan(inner) + front_track / 2
    steer = {
        s.name: math.atan(wheelbase / (radius + (-front_track / 2 if s.side == "left" else front_track / 2))) * s.sign
        for s in base.steering
    }
    wheels = {w.name: v * (radius - (w.centre[1] - base.axle_centre[1])) / radius / w.radius * w.spin for w in driven}
    seconds = min(rules.STEER_MAX_SECONDS, 0.5 * math.pi * radius / v + 1.0)  # a quarter circle and 1 s
    return Commands(wheels, steer, seconds, v, radius=radius)


def axle_path(asset: Asset, trace: BaseTrace) -> np.ndarray:
    """Rows (t, x, y, yaw, tilt) of the driven axle's centre. Yaw and tilt in rad."""
    root = asset.bodies[asset.root_body].pose[:3, 3]
    base = asset.wheeled
    # The axle centre in the root body's frame. At rest the robot's links are not turned.
    offset = np.array([base.axle_centre[0], base.axle_centre[1], root[2]]) - root
    rows = []
    for t, position, rotation in zip(trace.times, trace.positions, trace.rotations, strict=True):
        point = position + rotation @ offset
        yaw = math.atan2(rotation[1, 0], rotation[0, 0])
        tilt = math.acos(max(-1.0, min(1.0, rotation[2, 2])))
        rows.append((t, point[0], point[1], yaw, tilt))
    return np.array(rows, float)


def evaluate(base: WheeledBase, check_id: str, sent: Commands, path: np.ndarray) -> tuple[bool, str, list]:
    """The verdict, the detail text and the measurements of one wheeled check.

    The verdict is True when every measurement is ok. A path that is not finite has no measurements.
    """
    if not np.all(np.isfinite(path)):
        return False, "the simulation became unstable (NaN)", []
    t, x, y, yaw, tilt = path[:, 0], path[:, 1], path[:, 2], np.unwrap(path[:, 3]), path[:, 4]
    after = t >= min(rules.STARTUP_S, rules.STARTUP_FRACTION * t[-1])  # after the start-up
    span = t[after][-1] - t[after][0]
    if check_id == "STAND":
        speed = math.hypot(x[-1] - x[-2], y[-1] - y[-2]) / (t[-1] - t[-2])
        tilt_deg = math.degrees(tilt[-1])
        found = [
            _asset("tilt", tilt[-1], math.radians(rules.STAND_TILT_DEG), "rad", tilt_deg < rules.STAND_TILT_DEG),
            _asset("speed", speed, rules.STAND_SPEED, "m/s", speed < rules.STAND_SPEED),
        ]
        return _all_ok(found), f"tilt {tilt_deg:.2f} deg, speed {speed * 1000:.1f} mm/s after the drop", found
    if check_id == "DRIVE":
        dx, dy = x[after][-1] - x[after][0], y[after][-1] - y[after][0]
        speed = math.hypot(dx, dy) / span
        turn = math.degrees(abs(yaw[-1] - yaw[0]))
        detail = (
            f"speed {speed:.3f} m/s (commanded {sent.speed:.3f}), sideways drift {abs(dy) * 1000:.0f} mm "
            f"over {abs(dx):.2f} m, heading change {turn:.1f} deg"
        )
        forward = dx > 0 and abs(dy) <= abs(dx)
        error, allowed = abs(speed - sent.speed), rules.DRIVE_SPEED_TOL * sent.speed
        drift, most_drift = abs(dy), rules.DRIVE_DRIFT_TOL * abs(dx)
        found = [
            _asset("distance along +X", dx, 0.0, "m", forward, "min"),
            _asset("speed error", error, allowed, "m/s", error <= allowed),
            _asset("sideways drift", drift, most_drift, "m", drift <= most_drift),
            _asset("heading change", math.radians(turn), math.radians(rules.DRIVE_YAW_TOL_DEG), "rad",
                   turn <= rules.DRIVE_YAW_TOL_DEG),
        ]  # fmt: skip
        if not forward:
            side = "-X" if abs(dx) >= abs(dy) else ("+Y" if dy > 0 else "-Y")
            return False, detail + f"; the robot drove toward {side}: turn the model so its front faces +X", found
        return _all_ok(found), detail, found
    if check_id == "TURN":
        rate = (yaw[after][-1] - yaw[after][0]) / span
        drift = float(np.max(np.hypot(x - x[0], y - y[0])))
        detail = (
            f"yaw rate {math.degrees(rate):.1f} deg/s (expected {math.degrees(sent.yaw_rate):.1f}), "
            f"centre moved {drift * 1000:.0f} mm"
        )
        if base.drive == "skid_steer":
            # A skid-steer robot turns by sliding its wheels sideways, so its yaw rate and the point it
            # turns about depend on the engine's friction model. Ask for a clear left turn within one
            # track width.
            least = rules.SKID_TURN_MIN * sent.yaw_rate
            found = [
                _asset("yaw rate", rate, least, "rad/s", rate > least, "min"),
                _asset("centre drift", drift, base.track, "m", drift <= base.track),
            ]
        else:
            error, allowed = abs(rate - sent.yaw_rate), rules.TURN_TOL * sent.yaw_rate
            found = [
                _asset("yaw rate error", error, allowed, "rad/s", error <= allowed),
                _asset("centre drift", drift, rules.TURN_DRIFT, "m", drift <= rules.TURN_DRIFT),
            ]
        return _all_ok(found), detail, found
    if check_id == "STEER":
        # The least-squares circle through the path after the start-up.
        xs, ys = x[after], y[after]
        lhs = np.c_[2 * xs, 2 * ys, np.ones(len(xs))]
        cx, cy, c = np.linalg.lstsq(lhs, xs**2 + ys**2, rcond=None)[0]
        radius = math.sqrt(c + cx**2 + cy**2)
        rate = (yaw[after][-1] - yaw[after][0]) / span
        detail = f"turning radius {radius:.2f} m (expected {sent.radius:.2f}), yaw rate {math.degrees(rate):.1f} deg/s"
        error, allowed = abs(radius - sent.radius), rules.TURN_TOL * sent.radius
        found = [
            _asset("turning radius error", error, allowed, "m", error <= allowed),
            _asset("yaw rate", rate, 0.0, "rad/s", rate > 0, "min"),  # it turns left
        ]
        return _all_ok(found), detail, found
    raise ValueError(check_id)


def _asset(quantity: str, value: float, limit: float, unit: str, ok, bound="max") -> Measurement:
    """A measurement of the whole robot: the path of its driven axle's centre."""
    return Measurement("", "", quantity, float(value), float(limit), unit, bool(ok), bound)


def _all_ok(found: list[Measurement]) -> bool:
    return all(m.ok for m in found)


def wheeled(engine: Engine, asset: Asset, check_id: str) -> CheckResult:
    sent = commands(asset.wheeled, check_id)
    lift = rules.DROP_HEIGHT if check_id == "STAND" else 0.0
    trace = engine.drive(sent.wheels, sent.steer, sent.seconds, lift, rules.BASE_SAMPLE_DT)
    ok, detail, found = evaluate(asset.wheeled, check_id, sent, axle_path(asset, trace))
    return judge(check_id, ok, detail, found)
