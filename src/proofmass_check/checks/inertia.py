# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""INERTIA: each body's inertia fits its mass and the size of its colliders.

The check reads the file and runs nothing, so it gives the same result in every engine. A body's
inertia can be what it wants within a range: its mass can sit near its middle or near its rim.
Outside that range by a factor of 100, the number is wrong, as when a unit is: Isaac Sim's Franka
Panda gives each link about 1e-6 kg m^2 for 2 to 3 kg, as if its mass sat within 0.6 mm of a point.
"""

import math

import numpy as np

from proofmass_check import rules
from proofmass_check.checks import CheckResult, Measurement
from proofmass_check.model import Asset, Body
from proofmass_check.wheels import collider_points


def judged_bodies(asset: Asset) -> list[Body]:
    """The bodies whose mass and inertia the USD gives, and that have colliders."""
    return [b for b in asset.bodies.values() if b.mass and b.inertia is not None and b.colliders]


def reference(body: Body) -> float:
    """The trace of the inertia of the body's mass spread equally over its collider points, about their centroid.

    The points are on the colliders' surface (hull points, cylinder rims, sphere points), so this is up to about
    three times the inertia of the solid colliders: a box's 8 corners give three times a solid box's.
    """
    points = collider_points(body)
    centred = points - points.mean(axis=0)
    return 2.0 * body.mass * float(np.mean(np.sum(centred * centred, axis=1)))  # trace of sum m (r.r I - r r^T)


def inertia(asset: Asset) -> CheckResult:
    """The trace of each body's inertia, over the reference, must be within INERTIA_MIN_RATIO .. INERTIA_MAX_RATIO."""
    rows, measurements = [], []
    for body in judged_bodies(asset):
        ref = reference(body)
        ratio = float(np.sum(body.inertia)) / ref if ref > 0 else math.inf
        ok = math.isfinite(ratio) and rules.INERTIA_MIN_RATIO <= ratio <= rules.INERTIA_MAX_RATIO
        bound, limit = ("min", rules.INERTIA_MIN_RATIO) if ratio < 1 else ("max", rules.INERTIA_MAX_RATIO)
        measurements.append(
            Measurement(body.name, "", "inertia over its colliders' inertia", ratio, limit, "1", ok, bound)
        )
        rows.append(f"{body.name} {ratio:.2g}{'' if ok else ' FAIL'}")
    verdict = "PASS" if all(m.ok for m in measurements) else "FAIL"
    return CheckResult("INERTIA", verdict, "; ".join(rows), tuple(measurements))
