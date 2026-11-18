# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Read the physics of an asset from its USD into the classes of model.py.

The reader must work on packages from any maker. So:

- It selects variants in the stage's session layer. The file on disk does not change.
- A body's colliders stop where a body nested in it starts.
- A joint that targets a prim inside a body, such as a mesh, means that body.
- Polygons are split into triangles. A box collider (UsdGeom.Cube) becomes its 8 corners.
- A mass the USD leaves to the engine reads as None.
- A generic (D6) joint becomes one Joint per free axis, as in PhysX.
- A joint without PhysicsDriveAPI can get its drive from an MjcActuator, as in Newton.

Import this module only after the engine has started. In Isaac Sim, pxr cannot be imported before.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pxr import Gf, Usd, UsdGeom, UsdPhysics

from proofmass_check import usd_names
from proofmass_check.geometry import quat_to_matrix
from proofmass_check.model import (
    Asset,
    Body,
    Cylinder,
    Drive,
    GripperSite,
    Hull,
    Joint,
    Mimic,
    SteeringJoint,
    Wheel,
    WheeledBase,
)
from proofmass_check.rules import PAD_WIDTH

AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
D6_AXES = ("transX", "transY", "transZ", "rotX", "rotY", "rotZ")
JOINT_KINDS = {"PhysicsRevoluteJoint": "revolute", "PhysicsPrismaticJoint": "prismatic", "PhysicsFixedJoint": "fixed"}

CUBE_CORNERS = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float)
CUBE_TRIANGLES = np.array(
    [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
     [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]]
)  # fmt: skip


class AssetError(ValueError):
    """The file cannot be read as an asset: no default prim, or a variant that does not exist."""


def choose_variants(file: str | Path, engine_sets: Iterable[str], requested: Iterable[str]) -> dict[str, str]:
    """The variant selections for a run.

    The engine's own variant set comes first: the first set in engine_sets that the default prim
    has with an "Enabled" variant. Then each "SET=VALUE" in requested, which must exist.
    """
    stage = _open_stage(file)
    sets = stage.GetDefaultPrim().GetVariantSets()
    chosen = next(
        (
            {name: "Enabled"}
            for name in engine_sets
            if sets.HasVariantSet(name) and "Enabled" in sets.GetVariantSet(name).GetVariantNames()
        ),
        {},
    )
    for item in requested:
        name, _, value = item.partition("=")
        if not sets.HasVariantSet(name) or value not in sets.GetVariantSet(name).GetVariantNames():
            have = {n: sets.GetVariantSet(n).GetVariantNames() for n in sets.GetNames()}
            raise AssetError(f"no variant {item!r} in {Path(file).name}; its variant sets: {have}")
        chosen[name] = value
    return chosen


def read_asset(file: str | Path, variants: Mapping[str, str] | None = None) -> Asset:
    """Read bodies, joints and gripper sites of the asset in file, with variants selected."""
    variants = dict(variants or {})
    stage = _open_stage(file)
    default_prim = stage.GetDefaultPrim()
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        for name, value in variants.items():
            default_prim.GetVariantSet(name).SetVariantSelection(value)
    cache = UsdGeom.XformCache()
    prims = list(Usd.PrimRange(default_prim, Usd.TraverseInstanceProxies()))
    bodies = {}
    for prim in prims:
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            body = _read_body(prim, cache)
            bodies[body.path] = body
    if not bodies:
        raise AssetError(f"{Path(file).name} has no rigid body (PhysicsRigidBodyAPI) with these variants: {variants}")
    actuators = _read_actuators(prims)
    joints = []
    for prim in prims:
        if prim.IsA(UsdPhysics.Joint):
            joints += _read_joint(prim, stage, cache, bodies, actuators.get(prim.GetPath()))
    return Asset(
        file=str(file),
        name=default_prim.GetName(),
        variants=variants,
        bodies=bodies,
        joints=tuple(joints),
        sites=tuple(_read_site(prim, cache) for prim in prims if _has_value(prim, usd_names.GRIPPER_MAX_OPENING)),
        articulated=any(prim.HasAPI(UsdPhysics.ArticulationRootAPI) for prim in prims),
        wheeled=_read_wheeled(stage.GetRootLayer()),
    )


def _open_stage(file: str | Path) -> Usd.Stage:
    stage = Usd.Stage.Open(str(file))
    if not stage:
        raise AssetError(f"cannot open {file}")
    if not stage.GetDefaultPrim():
        raise AssetError(f"{Path(file).name} has no default prim")
    return stage


def _matrix(m: Gf.Matrix4d) -> np.ndarray:
    """A Gf matrix as a numpy transform for column vectors. Gf uses row vectors."""
    return np.array(m).T


def _points(m: Gf.Matrix4d, points) -> np.ndarray:
    """Points moved by a Gf matrix."""
    rows = np.array(m)
    return np.asarray(points, float) @ rows[:3, :3] + rows[3, :3]


def _has_value(prim: Usd.Prim, name: str) -> bool:
    attr = prim.GetAttribute(name)
    return bool(attr) and attr.HasAuthoredValue()


def _value(prim: Usd.Prim, name: str, default=None):
    return prim.GetAttribute(name).Get() if _has_value(prim, name) else default


def _body_of(prim: Usd.Prim) -> Usd.Prim | None:
    """The rigid body a prim belongs to: the prim itself or its nearest ancestor with RigidBodyAPI."""
    while prim and not prim.IsPseudoRoot():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            return prim
        prim = prim.GetParent()
    return None


def _read_body(prim: Usd.Prim, cache: UsdGeom.XformCache) -> Body:
    world = cache.GetLocalToWorldTransform(prim)
    pose = world.RemoveScaleShear()
    to_body = pose.GetInverse()
    mass, com = None, np.zeros(3)
    if prim.HasAPI(UsdPhysics.MassAPI):
        api = UsdPhysics.MassAPI(prim)
        mass = api.GetMassAttr().Get() or None  # 0 means "let the engine compute it"
        given = api.GetCenterOfMassAttr().Get()
        if given is not None and all(map(math.isfinite, given)):  # unset reads as -inf
            com = _points(world * to_body, [given])[0]
    hulls, cylinders = _read_colliders(prim, cache, to_body)
    return Body(
        path=str(prim.GetPath()),
        name=prim.GetName(),
        pose=_matrix(pose),
        world=_matrix(world),
        mass=mass,
        com=com,
        hulls=tuple(hulls),
        cylinders=tuple(cylinders),
    )


def _read_colliders(body: Usd.Prim, cache: UsdGeom.XformCache, to_body: Gf.Matrix4d):
    """The colliders under a body prim, in the body's frame. They stop at a body nested in it."""
    hulls, cylinders = [], []
    below = iter(Usd.PrimRange(body, Usd.TraverseInstanceProxies()))
    for prim in below:
        if prim != body and prim.HasAPI(UsdPhysics.RigidBodyAPI):
            below.PruneChildren()
            continue
        if not prim.HasAPI(UsdPhysics.CollisionAPI):
            continue
        rel = cache.GetLocalToWorldTransform(prim) * to_body
        if prim.IsA(UsdGeom.Cylinder):
            cyl = UsdGeom.Cylinder(prim)
            axis = np.array(rel.TransformDir(Gf.Vec3d(*AXES[cyl.GetAxisAttr().Get()])))
            cylinders.append(
                Cylinder(
                    name=prim.GetName(),
                    centre=_points(rel, [(0.0, 0.0, 0.0)])[0],
                    axis=axis / np.linalg.norm(axis),
                    radius=cyl.GetRadiusAttr().Get(),
                    height=cyl.GetHeightAttr().Get(),
                )
            )
        elif prim.IsA(UsdGeom.Cube):
            half = UsdGeom.Cube(prim).GetSizeAttr().Get() / 2
            hulls.append(Hull(prim.GetName(), _points(rel, half * CUBE_CORNERS), CUBE_TRIANGLES))
        elif prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            hulls.append(Hull(prim.GetName(), _points(rel, mesh.GetPointsAttr().Get()), _triangles(mesh)))
    return hulls, cylinders


def _triangles(mesh: UsdGeom.Mesh) -> np.ndarray:
    """A mesh's faces as triangles. A polygon is fanned from its first corner."""
    indices = np.array(mesh.GetFaceVertexIndicesAttr().Get())
    counts = np.array(mesh.GetFaceVertexCountsAttr().Get())
    if np.all(counts == 3):
        return indices.reshape(-1, 3)
    triangles, start = [], 0
    for count in counts:
        triangles += [(indices[start], indices[start + i], indices[start + i + 1]) for i in range(1, count - 1)]
        start += count
    return np.array(triangles)


@dataclass(frozen=True, eq=False)
class _Side:
    """One side of a joint: the body, and the joint frame in the body's frame and in the world."""

    body: str | None  # None means the world
    position: np.ndarray  # in the body's frame (in the world for an empty side), m
    rotation: np.ndarray  # 3x3
    world_position: np.ndarray
    world_rotation: np.ndarray


@dataclass(frozen=True)
class _Dof:
    """One degree of freedom as the USD gives it, before the conversion to SI units."""

    name: str
    kind: str  # "revolute" or "prismatic"
    axis: str  # "X", "Y" or "Z"
    attribute_axis: str  # how its PhysX attributes name it: "angular", "linear", or a D6 axis such as "rotX"
    lower: float | None  # deg or m
    upper: float | None
    d6: str | None = None


def _read_actuators(prims: Iterable[Usd.Prim]) -> dict:
    """The drive each MjcActuator gives, by the path of the joint it targets.

    Newton turns an actuator into a joint drive when it has the shape of MuJoCo's <position> or
    <velocity> shortcut, and so does the reader. Such an actuator has gain type "fixed", bias type
    "affine", no dynamics and gear 1. With gain kp and bias (b0, b1, b2):

    - position: b0 = 0, b1 = -kp, b2 <= 0. The stiffness is kp, the damping is -b2.
    - velocity: b0 = 0, b1 = 0, b2 = -kp. The damping is kp.

    Any other actuator is a motor that the user commands directly. It is not a drive. MuJoCo's
    values are per radian, as the Drive class is.
    """
    drives = {}
    for prim in prims:
        if prim.GetTypeName() != usd_names.MJC_ACTUATOR:
            continue
        targets = prim.GetRelationship(usd_names.MJC_ACTUATOR_TARGET).GetTargets()
        gear = list(_value(prim, usd_names.MJC_ACTUATOR_GEAR, (1.0,)))
        if (
            len(targets) != 1
            or _value(prim, usd_names.MJC_ACTUATOR_GAIN_TYPE, "fixed") != "fixed"
            or _value(prim, usd_names.MJC_ACTUATOR_BIAS_TYPE, "none") != "affine"
            or _value(prim, usd_names.MJC_ACTUATOR_DYN_TYPE, "none") != "none"
            or not math.isclose(gear[0], 1.0)
            or any(gear[1:])
        ):
            continue
        kp = float([*_value(prim, usd_names.MJC_ACTUATOR_GAIN, ()), 1.0][0])  # MuJoCo's default gain is 1
        b0, b1, b2 = [*_value(prim, usd_names.MJC_ACTUATOR_BIAS, ()), 0.0, 0.0, 0.0][:3]
        if kp <= 0 or not math.isclose(b0, 0.0, abs_tol=1e-9):
            continue
        if math.isclose(b1, -kp) and b2 <= 0:
            stiffness, damping = kp, -float(b2)
        elif math.isclose(b1, 0.0, abs_tol=1e-9) and math.isclose(b2, -kp):
            stiffness, damping = 0.0, kp
        else:
            continue
        low = _value(prim, usd_names.MJC_ACTUATOR_FORCE_MIN)
        high = _value(prim, usd_names.MJC_ACTUATOR_FORCE_MAX)
        limited = low is not None and high is not None and low < high
        drives[targets[0]] = Drive(stiffness, damping, max(abs(low), abs(high)) if limited else None)
    return drives


def _read_joint(prim: Usd.Prim, stage: Usd.Stage, cache: UsdGeom.XformCache, bodies, actuator=None) -> list[Joint]:
    """One Joint, or one per free axis of a D6 joint. A disabled joint gives none.

    actuator: the drive an MjcActuator gives this joint. A joint with one axis uses it when it has
    no PhysicsDriveAPI.
    """
    api = UsdPhysics.Joint(prim)
    if api.GetJointEnabledAttr().Get() is False:
        return []
    side0 = _side(stage, cache, bodies, api.GetBody0Rel(), api.GetLocalPos0Attr(), api.GetLocalRot0Attr())
    side1 = _side(stage, cache, bodies, api.GetBody1Rel(), api.GetLocalPos1Attr(), api.GetLocalRot1Attr())
    common = {
        "usd_type": prim.GetTypeName(),
        "body0": side0.body,
        "body1": side1.body,
        "local_pos0": side0.position,
        "local_rot0": side0.rotation,
        "local_pos1": side1.position,
        "local_rot1": side1.rotation,
        "mimic": _mimic(prim),
    }
    type_name = prim.GetTypeName()
    if type_name in ("PhysicsRevoluteJoint", "PhysicsPrismaticJoint"):
        dofs = [_single_dof(prim)]
    elif type_name == "PhysicsJoint":
        dofs = _d6_dofs(prim)
    else:
        return [Joint(name=prim.GetName(), kind=JOINT_KINDS.get(type_name, "other"), **common)]
    # The joint's position and axis in the world come from body1's side, or from body0's side when
    # body1 is the world.
    frame = side1 if side1.body else side0
    return [_dof_joint(prim, dof, frame, common, actuator if len(dofs) == 1 else None) for dof in dofs]


def _side(stage, cache, bodies, rel, pos_attr, rot_attr) -> _Side:
    """The joint frame of one side. The USD gives it relative to the prim the joint targets."""
    targets = rel.GetTargets()
    target = stage.GetPrimAtPath(targets[0]) if targets else None
    body_prim = _body_of(target) if target else None
    body = bodies.get(str(body_prim.GetPath())) if body_prim else None
    target_world = cache.GetLocalToWorldTransform(target) if target else Gf.Matrix4d(1.0)
    rot = rot_attr.Get()
    world_position = _points(target_world, [pos_attr.Get()])[0]
    world_rotation = _matrix(target_world.RemoveScaleShear())[:3, :3] @ quat_to_matrix(
        (rot.GetReal(), *rot.GetImaginary())
    )
    if body is None:
        return _Side(None, world_position, world_rotation, world_position, world_rotation)
    r, t = body.pose[:3, :3], body.pose[:3, 3]
    return _Side(body.path, r.T @ (world_position - t), r.T @ world_rotation, world_position, world_rotation)


def _single_dof(prim: Usd.Prim) -> _Dof:
    revolute = prim.GetTypeName() == "PhysicsRevoluteJoint"
    typed = UsdPhysics.RevoluteJoint(prim) if revolute else UsdPhysics.PrismaticJoint(prim)
    return _Dof(
        name=prim.GetName(),
        kind="revolute" if revolute else "prismatic",
        axis=typed.GetAxisAttr().Get(),
        attribute_axis="angular" if revolute else "linear",
        lower=typed.GetLowerLimitAttr().Get(),
        upper=typed.GetUpperLimitAttr().Get(),
    )


def _d6_dofs(prim: Usd.Prim) -> list[_Dof]:
    """The free axes of a D6 joint.

    An axis without PhysicsLimitAPI is free and has no limits. An axis whose low limit is above its
    high limit is locked, and is left out. Each axis is named as Isaac Sim names it (mjcf:<axis>:name).
    Without that name, it is the joint's name when only one axis is free, else "<joint>:<axis>".
    """
    free = []
    for axis in D6_AXES:
        low = high = None
        if prim.HasAPI(UsdPhysics.LimitAPI, axis):
            limit = UsdPhysics.LimitAPI(prim, axis)
            low, high = limit.GetLowAttr().Get(), limit.GetHighAttr().Get()
            if low is not None and high is not None and low > high:
                continue
        free.append((axis, low, high))
    return [
        _Dof(
            name=_value(prim, usd_names.D6_AXIS_NAME.format(axis=axis))
            or (prim.GetName() if len(free) == 1 else f"{prim.GetName()}:{axis}"),
            kind="revolute" if axis.startswith("rot") else "prismatic",
            axis=axis[-1],
            attribute_axis=axis,
            lower=low,
            upper=high,
            d6=prim.GetName(),
        )
        for axis, low, high in free
    ]


def _dof_joint(prim: Usd.Prim, dof: _Dof, frame: _Side, common: dict, actuator: Drive | None) -> Joint:
    """A revolute or prismatic Joint in SI units."""
    to_si = math.pi / 180 if dof.kind == "revolute" else 1.0  # the USD gives angles in degrees
    drive = actuator
    if prim.HasAPI(UsdPhysics.DriveAPI, dof.attribute_axis):
        api = UsdPhysics.DriveAPI(prim, dof.attribute_axis)
        drive = Drive(
            stiffness=(api.GetStiffnessAttr().Get() or 0.0) / to_si,  # per degree to per radian
            damping=(api.GetDampingAttr().Get() or 0.0) / to_si,
            max_force=api.GetMaxForceAttr().Get(),
        )
    direction = frame.world_rotation @ np.array(AXES[dof.axis])
    rest = _value(prim, usd_names.JOINT_STATE_POSITION.format(dof=dof.attribute_axis), 0.0)
    return Joint(
        name=dof.name,
        kind=dof.kind,
        axis=dof.axis,
        pivot=frame.world_position,
        direction=direction / np.linalg.norm(direction),
        lower=-math.inf if dof.lower is None else dof.lower * to_si,
        upper=math.inf if dof.upper is None else dof.upper * to_si,
        rest=float(rest) * to_si,
        max_speed=float(_value(prim, usd_names.PHYSX_MAX_JOINT_VELOCITY, math.inf)) * to_si,
        drive=drive,
        d6=dof.d6,
        **common,
    )


def _mimic(prim: Usd.Prim) -> Mimic | None:
    """The joint this one follows, from whichever engine's schema the selected variant has."""
    for target, coef, enabled in (
        (usd_names.MJC_MIMIC_TARGET, usd_names.MJC_MIMIC_COEF, None),
        (usd_names.NEWTON_MIMIC_JOINT, usd_names.NEWTON_MIMIC_COEF, usd_names.NEWTON_MIMIC_ENABLED),
    ):
        rel = prim.GetRelationship(target)
        if rel and rel.GetTargets() and not (enabled and _value(prim, enabled) is False):
            return Mimic(leader=rel.GetTargets()[0].name, ratio=float(_value(prim, coef, 1.0)))
    for prop in prim.GetProperties():
        name = prop.GetName()
        if not (name.startswith(usd_names.PHYSX_MIMIC_PREFIX) and name.endswith(usd_names.PHYSX_MIMIC_REFERENCE)):
            continue
        targets = prim.GetRelationship(name).GetTargets()
        if targets:
            gearing = prim.GetAttribute(name.replace(usd_names.PHYSX_MIMIC_REFERENCE, usd_names.PHYSX_MIMIC_GEARING))
            value = gearing.Get() if gearing and gearing.Get() is not None else 1.0
            return Mimic(leader=targets[0].name, ratio=-float(value))  # PhysX: follower + gearing x leader = 0
    return None


def _read_site(prim: Usd.Prim, cache: UsdGeom.XformCache) -> GripperSite:
    """A gripper site at the file pose.

    The approach direction is the gripper_forward_axis curve, else the site's Z axis. The grip line
    is the gripper_grip_line curve, else the site's Y axis. The grip line's length is the pad size.
    """
    world = cache.GetLocalToWorldTransform(prim)

    def guide(child_name, default):
        child = prim.GetChild(child_name)
        points = UsdGeom.BasisCurves(child).GetPointsAttr().Get() if child and child.IsA(UsdGeom.BasisCurves) else None
        drawn = points is not None and len(points) > 1
        v = np.array(world.TransformDir(Gf.Vec3d(points[-1] - points[0]) if drawn else Gf.Vec3d(*default)))
        return v / np.linalg.norm(v), (float(np.linalg.norm(v)) if drawn else None)

    forward, _ = guide(usd_names.GRIPPER_FORWARD_AXIS, (0, 0, 1))
    line, pad = guide(usd_names.GRIPPER_GRIP_LINE, (0, 1, 0))
    closing = np.cross(forward, line)
    body = _body_of(prim)
    payload = _value(prim, usd_names.GRIPPER_MAX_PAYLOAD)
    return GripperSite(
        name=prim.GetName(),
        body=str(body.GetPath()) if body else None,
        centre=np.array(world.ExtractTranslation()),
        forward=forward,
        line=line,
        closing=closing / np.linalg.norm(closing),
        opening=float(_value(prim, usd_names.GRIPPER_MAX_OPENING)),
        pad=pad or PAD_WIDTH,
        payload=float(payload) if payload is not None else None,
    )


def _read_wheeled(layer) -> WheeledBase | None:
    """The wheeled base from the root layer's metadata, or None. docs/wheeled-robots.md gives the fields."""
    data = dict(layer.customLayerData).get(usd_names.LAYER_METADATA, {}).get(usd_names.LAYER_METADATA_MOBILE)
    if not data:
        return None
    try:
        wheels = tuple(
            Wheel(
                name=name,
                side=str(w["side"]),
                driven=bool(w["driven"]),
                radius=float(w["radius"]),
                spin=int(w["spin"]),
                centre=np.array(list(w["center"]), float),
                max_speed=float(w["max_speed"]) if "max_speed" in w else None,
            )
            for name, w in dict(data["wheels"]).items()
        )
        steering = tuple(
            SteeringJoint(
                name=name,
                side=str(s["side"]),
                x=float(s["x"]),
                y=float(s["y"]),
                sign=int(s["sign"]),
                lower=math.radians(float(s["lower"])),  # the metadata gives degrees
                upper=math.radians(float(s["upper"])),
            )
            for name, s in dict(data.get("steering", {})).items()
        )
        return WheeledBase(
            drive=str(data["drive"]),
            radius=float(data["radius"]),
            track=float(data["track"]),
            axle_centre=np.array(list(data["axle_center"])[:2], float),
            wheels=wheels,
            steering=steering,
            wheelbase=float(data["wheelbase"]) if "wheelbase" in data else None,
            front_track=float(data["front_track"]) if "front_track" in data else None,
        )
    except (KeyError, TypeError, ValueError) as e:
        raise AssetError(f"SimReady_Metadata.mobile is not complete: {e!r}") from e
