# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""DROP: lifted and let go, the asset comes to rest on the floor."""

import math

import numpy as np

from proofmass_check.checks import CheckResult, Measurement, judge
from proofmass_check.engines.base import Engine
from proofmass_check.geometry import lowest_collider, tilt
from proofmass_check.model import Asset
from proofmass_check.rules import DROP_HEIGHT, DROP_SECONDS, FLOOR_TOL, REST_SPEED


def resting(finite: bool, speed: float, gap: float) -> bool:
    """At rest: slower than REST_SPEED, with the lowest collider within FLOOR_TOL of the floor."""
    return finite and speed < REST_SPEED and abs(gap) < FLOOR_TOL


def drop(engine: Engine, asset: Asset, floor: float) -> CheckResult:
    """The asset may end in any pose: a prop can also come to rest on its side.

    The tilt is reported, but it does not decide the result.
    """
    outcome = engine.drop(DROP_HEIGHT, DROP_SECONDS)
    lowest = min(
        (
            lowest_collider(asset.bodies[path], rotation, position)
            for path, (rotation, position) in outcome.poses.items()
        ),
        default=math.inf,
    )
    gap = lowest - floor
    root = asset.root_body
    turned = math.degrees(tilt(asset.bodies[root].pose[:3, :3], outcome.poses[root][0])) if outcome.finite else math.nan
    finite = outcome.finite and bool(np.isfinite(gap))
    gap_mm = round(gap * 1000, 2) + 0.0  # adding 0.0 turns -0.0 into 0.0, so the text never says "-0.00 mm"
    speed = outcome.root_speed
    measurements = (
        Measurement("", "", "final speed", speed, REST_SPEED, "m/s", finite and speed < REST_SPEED),
        Measurement("", "", "lowest collider from the floor", gap, FLOOR_TOL, "m", finite and abs(gap) < FLOOR_TOL),
        Measurement("", "", "tilt", math.radians(turned), None, "rad", True),  # reported, not judged
    )
    return judge(
        "DROP",
        resting(finite, speed, gap),
        f"final speed {speed:.4f} m/s, lowest collider {gap_mm:+.2f} mm from the floor, tilted {turned:.0f} deg",
        measurements,
    )
