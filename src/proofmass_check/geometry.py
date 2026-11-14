# SPDX-FileCopyrightText: 2026 The proofmass-check authors
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
    return min(lows, default=math.inf)


def floor_height(bodies) -> float:
    """Where the checks put the floor.

    FLOOR_BELOW under the lowest collider in the file pose, and never above z = 0. A part that only
    touches the floor in the file, such as a fingertip or the carriage of a pinned robot, then does
    not drag on it.
    """
    low = min(lowest_collider(b, b.pose[:3, :3], b.pose[:3, 3]) for b in bodies)
    return min(low, 0.0) - FLOOR_BELOW
