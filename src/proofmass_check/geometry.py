# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Small geometry helpers on numpy arrays. Transforms are 4x4, for column vectors."""

import math

import numpy as np

from proofmass_check.model import Body
from proofmass_check.rules import FLOOR_BELOW


def apply(m: np.ndarray, point) -> np.ndarray:
    """A point moved by the transform m."""
    return m[:3, :3] @ np.asarray(point, float) + m[:3, 3]


def turn(v: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """v turned by angle (rad) about the unit vector axis (Rodrigues' formula)."""
    c, s = math.cos(angle), math.sin(angle)
    return v * c + np.cross(axis, v) * s + axis * (axis @ v) * (1 - c)


def quat_to_matrix(q) -> np.ndarray:
    """The 3x3 rotation of a unit quaternion (w, x, y, z)."""
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def matrix_to_quat(r: np.ndarray) -> np.ndarray:
    """The unit quaternion (w, x, y, z), w >= 0, of a 3x3 rotation: the inverse of quat_to_matrix."""
    r = np.asarray(r, float)
    # Shepperd's method: start from the largest of w, x, y, z, so the division is never by a small number.
    trace = np.trace(r)
    k = int(np.argmax([trace, r[0, 0], r[1, 1], r[2, 2]]))
    if k == 0:
        w = math.sqrt(1 + trace) / 2
        q = [w, (r[2, 1] - r[1, 2]) / (4 * w), (r[0, 2] - r[2, 0]) / (4 * w), (r[1, 0] - r[0, 1]) / (4 * w)]
    else:
        i, j, m = k - 1, k % 3, (k + 1) % 3
        v = [0.0, 0.0, 0.0]
        v[i] = math.sqrt(1 + 2 * r[i, i] - trace) / 2
        v[j] = (r[j, i] + r[i, j]) / (4 * v[i])
        v[m] = (r[m, i] + r[i, m]) / (4 * v[i])
        q = [(r[m, j] - r[j, m]) / (4 * v[i]), *v]
    q = np.array(q) / np.linalg.norm(q)
    return q if q[0] >= 0 else -q


def tilt(r0: np.ndarray, r1: np.ndarray) -> float:
    """The angle (rad) between the Z axes of two rotations."""
    return math.acos(float(np.clip(r0[:, 2] @ r1[:, 2], -1.0, 1.0)))


def lowest_collider(body: Body, rotation: np.ndarray, position: np.ndarray) -> float:
    """The height of the lowest collider point of a body at a pose, or inf for a body without colliders."""
    lows = [float((hull.points @ rotation.T)[:, 2].min() + position[2]) for hull in body.hulls]
    for cyl in body.cylinders:
        # The lowest point of a cylinder: its centre, minus the radius times how far the axis is
        # from vertical, minus half the height times how far the axis is from horizontal.
        az = float((rotation @ cyl.axis)[2])
        centre_z = float((rotation @ cyl.centre)[2] + position[2])
        lows.append(centre_z - cyl.radius * math.sqrt(max(0.0, 1 - az**2)) - cyl.height / 2 * abs(az))
    lows += [float((rotation @ s.centre)[2] + position[2]) - s.radius for s in body.spheres]
    return min(lows, default=math.inf)


def run_floor(asset, settings) -> float | None:
    """The floor of a run: under an asset that stands free, none under one fixed to the world or held
    (spec, section 1).

    A fixed arm needs no floor, and one in its file pose can reach through it: a floor there stops the
    arm, not its drives. An arm the checks hold is the same.
    """
    if not settings.floor or asset.world_fixed or asset.held:
        return None
    return floor_height(asset.bodies.values())


def floor_height(bodies) -> float:
    """Where the checks put the floor.

    FLOOR_BELOW under the lowest collider in the file pose, and never above z = 0. A part that only
    touches the floor in the file, such as a fingertip or the carriage of a pinned robot, then does
    not drag on it.
    """
    low = min(lowest_collider(b, b.pose[:3, :3], b.pose[:3, 3]) for b in bodies)
    return min(low, 0.0) - FLOOR_BELOW
