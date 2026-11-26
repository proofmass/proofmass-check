# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""A wheeled robot's description (SimReady_Metadata.mobile), derived from its wheel joints and colliders.

proofmass-check runs STAND, DRIVE, TURN and STEER only on an asset that has the description, and
other makers do not write it (docs/wheeled-robots.md). This module proposes one from what the USD
gives. It is a proposal: a person checks it, above all the spin of each wheel and that the robot's
front faces +X, because a wheel whose axis is the wrong way round would get spin -1 and look right.

Differential and skid-steer robots only. An Ackermann robot needs its steering range and the sign
of each steering joint from its maker.
"""

import math
from pathlib import Path

import numpy as np

from proofmass_check import usd_names
from proofmass_check.model import Asset, Body, Joint

# A wheel's axis is within about 17 deg of horizontal: the z of its unit vector is below this. Not a rule of
# the spec: it decides only the note on wheels that are not checked, and what is proposed here.
WHEEL_AXIS_TILT = 0.3
STEERING_AXIS = 0.7  # a steering joint's axis is closer to vertical: the z of its unit vector is above this
SIDE_TOL = 0.01  # m: a wheel this close to y = 0 is in the centre
GROUND_TOL = 0.001  # m: the lowest wheel point may be this far from z = 0 before a note says so


def is_wheel_joint(joint: Joint) -> bool:
    """A revolute joint without limits about a near horizontal axis. Driven or not: a caster is a wheel too."""
    return (
        joint.revolute
        and not joint.limited
        and joint.direction is not None
        and abs(joint.direction[2]) < WHEEL_AXIS_TILT
    )


def collider_points(body: Body) -> np.ndarray:
    """Points of the body's colliders in the world, in the file pose: hull points, cylinder rims, sphere points."""
    r, t = body.pose[:3, :3], body.pose[:3, 3]
    pts = [hull.points for hull in body.hulls]
    for c in body.cylinders:
        axis = np.asarray(c.axis, float) / np.linalg.norm(c.axis)
        a = np.cross(axis, [1.0, 0.0, 0.0] if abs(axis[0]) < 0.9 else [0.0, 1.0, 0.0])
        a /= np.linalg.norm(a)
        b = np.cross(axis, a)
        angles = np.linspace(0.0, 2 * math.pi, 16, endpoint=False)
        ring = c.radius * (np.outer(np.cos(angles), a) + np.outer(np.sin(angles), b))
        pts += [np.asarray(c.centre) + axis * s * c.height + ring for s in (-0.5, 0.5)]
    grid = np.array([(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1) if (x, y, z) != (0, 0, 0)])
    directions = grid / np.linalg.norm(grid, axis=1)[:, None]  # 26 points on each sphere
    pts += [np.asarray(s.centre) + s.radius * directions for s in body.spheres]
    if not pts:
        return np.zeros((0, 3))
    return np.vstack(pts) @ r.T + t


def derive(asset: Asset) -> tuple[dict | None, list[str]]:
    """The description in the form of SimReady_Metadata.mobile, or None, and notes for a person.

    A wheel's radius and centre come from a cylinder about its joint axis that holds its body's colliders.
    """
    notes = []
    steering = [j.name for j in asset.joints if _is_steering_joint(j)]
    if steering:
        return None, [f"{', '.join(steering)} look like steering joints: an Ackermann description needs the steering "
                      "range and the sign of each joint from the robot's maker (docs/wheeled-robots.md)"]  # fmt: skip
    wheels = {}
    for joint in asset.joints:
        if not is_wheel_joint(joint):
            continue
        body = asset.bodies.get(joint.body1)
        pts = collider_points(body) if body else np.zeros((0, 3))
        if len(pts) == 0:
            notes.append(f"{joint.name} looks like a wheel, but its body has no collider: it is left out")
            continue
        axis = np.asarray(joint.direction, float) / np.linalg.norm(joint.direction)
        rel = pts - joint.pivot
        t = rel @ axis
        centre = joint.pivot + axis * (t.max() + t.min()) / 2
        wheel = {
            "side": "left" if centre[1] > SIDE_TOL else "right" if centre[1] < -SIDE_TOL else "centre",
            "driven": joint.drive_kind == "velocity",
            "radius": float(np.linalg.norm(rel - np.outer(t, axis), axis=1).max()),
            # Turning about +Y rolls the wheel toward +X: a positive joint speed drives forward when the axis
            # points left.
            "spin": 1 if axis[1] > 0 else -1,
            "center": [float(v) for v in centre],
        }
        if math.isfinite(joint.max_speed):
            wheel["max_speed"] = float(joint.max_speed)
        wheels[joint.name] = wheel
    driven = [w for w in wheels.values() if w["driven"]]
    left = [w for w in driven if w["side"] == "left"]
    right = [w for w in driven if w["side"] == "right"]
    if not left or not right:
        return None, [*notes, "no driven wheel on each side: a joint with a velocity drive, without limits, about a "
                              "near horizontal axis, left (+Y) and right (-Y) of the robot"]  # fmt: skip
    mobile = {
        "drive": "differential" if len(driven) == 2 else "skid_steer",
        "radius": float(np.mean([w["radius"] for w in driven])),
        "track": float(np.mean([w["center"][1] for w in left]) - np.mean([w["center"][1] for w in right])),
        "axle_center": [float(np.mean([w["center"][i] for w in driven])) for i in (0, 1)],
        "wheels": wheels,
        "steering": {},
    }
    notes.append("a proposal: check that a positive speed of each wheel with spin +1 rolls the robot forward, and "
                 "that the robot's front faces +X")  # fmt: skip
    lowest = min(w["center"][2] - w["radius"] for w in wheels.values())
    if abs(lowest) > GROUND_TOL:
        notes.append(f"the lowest wheel point is at z = {lowest * 1000:.1f} mm: the convention puts wheels on z = 0")
    return mobile, notes


def _is_steering_joint(joint: Joint) -> bool:
    """A revolute joint with a position drive about a near vertical axis, as an Ackermann robot steers."""
    return (
        joint.revolute
        and joint.drive_kind == "position"
        and joint.direction is not None
        and abs(joint.direction[2]) > STEERING_AXIS
    )


def write_layer(root: str | Path, mobile: dict) -> Path:
    """A layer next to the root file that sublayers it and adds the description: <stem>_mobile.usda.

    The asset's own files do not change. The layer copies the root layer's metadata, because
    proofmass-check reads the description from the root layer of what it opens.
    """
    from pxr import Sdf, Vt

    def usd(value):
        if isinstance(value, dict):
            return {k: usd(v) for k, v in value.items()}
        if isinstance(value, list):
            return Vt.DoubleArray(value)
        return value

    root = Path(root)
    out = root.parent / f"{root.stem}_mobile.usda"
    base = Sdf.Layer.FindOrOpen(str(root))
    out.unlink(missing_ok=True)
    layer = Sdf.Layer.CreateNew(str(out))
    layer.subLayerPaths.append(root.name)
    layer.defaultPrim = base.defaultPrim
    for key in ("upAxis", "metersPerUnit", "kilogramsPerUnit"):
        if base.pseudoRoot.HasInfo(key):
            layer.pseudoRoot.SetInfo(key, base.pseudoRoot.GetInfo(key))
    data = dict(base.customLayerData)
    meta = dict(data.get(usd_names.LAYER_METADATA, {}))
    meta[usd_names.LAYER_METADATA_MOBILE] = usd(mobile)
    data[usd_names.LAYER_METADATA] = meta
    layer.customLayerData = data
    layer.comment = f"SimReady_Metadata.mobile for {root.name}, derived by proofmass-check describe-wheels"
    layer.Save()
    return out
