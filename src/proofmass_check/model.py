# SPDX-FileCopyrightText: 2026 The proofmass-check authors
# SPDX-License-Identifier: Apache-2.0
"""What the checks know about an asset: its bodies, joints and gripper sites.

usd_reader.py fills these classes from the USD. Every value is in SI units: metres, kilograms,
seconds and radians. The USD stores revolute joint angles in degrees, and the reader converts
them, so no other module has to.

Transforms are 4x4 numpy arrays for column vectors: a point p goes to `m[:3, :3] @ p + m[:3, 3]`.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

JointKind = Literal["revolute", "prismatic", "fixed", "other"]
DriveKind = Literal["position", "velocity"]


@dataclass(frozen=True, eq=False)
class Hull:
    """A collider made of points, in the frame of its body. A box collider is its 8 corners."""

    name: str
    points: np.ndarray  # (n, 3), m
    triangles: np.ndarray  # (k, 3), indices into points


@dataclass(frozen=True, eq=False)
class Cylinder:
    """A cylinder collider, such as a wheel, in the frame of its body."""

    name: str
    centre: np.ndarray  # m
    axis: np.ndarray  # unit vector
    radius: float  # m
    height: float  # m


@dataclass(frozen=True, eq=False)
class Body:
    """A rigid body, in the pose it has in the file.

    The body's frame is the prim's position and rotation without its scale. Engines report body
    poses in this frame, so the colliders and the centre of mass are stored in it too.
    """

    path: str
    name: str
    pose: np.ndarray  # 4x4, body frame to world, without scale
    world: np.ndarray  # 4x4, the prim's full local-to-world transform, with scale
    mass: float | None  # kg, or None when the USD leaves the mass to the engine
    com: np.ndarray  # centre of mass in the body's frame, m (the origin when the USD does not give it)
    hulls: tuple[Hull, ...] = ()
    cylinders: tuple[Cylinder, ...] = ()


@dataclass(frozen=True)
class Drive:
    """A joint drive, per radian for a revolute joint (the USD gives it per degree)."""

    stiffness: float  # N/m, or N m/rad
    damping: float  # N s/m, or N m s/rad
    max_force: float | None  # N, or N m

    @property
    def kind(self) -> DriveKind | None:
        """What the drive does.

        "position" when it has stiffness. "velocity" when it has only damping: a driven wheel, or a
        door closer. None when it exerts nothing.
        """
        if self.stiffness > 0:
            return "position"
        if self.damping > 0:
            return "velocity"
        return None


@dataclass(frozen=True)
class Mimic:
    """A joint that follows another one: follower position = ratio x leader position."""

    leader: str
    ratio: float


@dataclass(frozen=True, eq=False)
class Joint:
    """A joint with at most one degree of freedom.

    The reader splits a generic (D6) joint into one Joint per free axis, as PhysX does. `d6` then
    names the joint it came from.
    """

    name: str
    kind: JointKind
    usd_type: str  # for example "PhysicsRevoluteJoint"
    body0: str | None  # body path, or None for the world
    body1: str | None
    # The joint frame in each body's frame (in the world for an empty side). The reader converts
    # it from the prim the joint targets, which can be a mesh inside the body.
    local_pos0: np.ndarray  # m
    local_rot0: np.ndarray  # 3x3
    local_pos1: np.ndarray
    local_rot1: np.ndarray
    axis: Literal["X", "Y", "Z"] | None = None
    pivot: np.ndarray | None = None  # joint position in the world, file pose, m
    direction: np.ndarray | None = None  # joint axis in the world, file pose, unit vector
    lower: float = -math.inf  # rad or m
    upper: float = math.inf
    rest: float = 0.0  # PhysicsJointStateAPI position, else 0
    max_speed: float = math.inf  # rad/s or m/s
    drive: Drive | None = None
    mimic: Mimic | None = None
    d6: str | None = None

    @property
    def revolute(self) -> bool:
        return self.kind == "revolute"

    @property
    def moves(self) -> bool:
        """True for a revolute or prismatic joint."""
        return self.kind in ("revolute", "prismatic")

    @property
    def limited(self) -> bool:
        return math.isfinite(self.lower) and math.isfinite(self.upper)

    @property
    def drive_kind(self) -> DriveKind | None:
        return self.drive.kind if self.drive else None


@dataclass(frozen=True, eq=False)
class GripperSite:
    """A gripper site: the prim with gripper_maxOpening (NVIDIA SimReady rules GR.001 to GR.004).

    Directions are unit vectors in the world, at the file pose.
    """

    name: str
    body: str | None  # the body the site is on
    centre: np.ndarray  # grasp centre, m
    forward: np.ndarray  # approach direction: from the hand toward the part
    line: np.ndarray  # grip line: along the pads
    closing: np.ndarray  # forward x line: the direction the fingers close in
    opening: float  # gripper_maxOpening, m
    pad: float  # pad size along the grip line, m
    payload: float | None  # gripper_maxPayload, kg


@dataclass(frozen=True, eq=False)
class Wheel:
    """A wheel of a wheeled robot, as SimReady_Metadata.mobile describes it."""

    name: str  # the wheel's joint
    side: str  # "left", "right" or "centre"
    driven: bool  # True when its joint has a velocity drive
    radius: float  # m
    spin: int  # +1 or -1: the sign of the joint speed that rolls the robot forward
    centre: np.ndarray  # m, in the file pose
    max_speed: float | None = None  # rad/s


@dataclass(frozen=True)
class SteeringJoint:
    """A steering joint of an Ackermann robot: revolute about Z, with a wheel below it."""

    name: str
    side: str  # "left" or "right"
    x: float  # m, position of the joint
    y: float
    sign: int  # +1 when a positive angle turns the wheel left
    lower: float  # rad
    upper: float  # rad


@dataclass(frozen=True, eq=False)
class WheeledBase:
    """The base of a wheeled robot. The front faces +X, left is +Y, up is +Z (ROS REP-103)."""

    drive: str  # "differential", "skid_steer" or "ackermann"
    radius: float  # m, mean radius of the driven wheels
    track: float  # m, between the left and the right driven wheels
    axle_centre: np.ndarray  # (x, y) of the driven axle's centre, m. The robot turns about it.
    wheels: tuple[Wheel, ...]
    steering: tuple[SteeringJoint, ...] = ()
    wheelbase: float | None = None  # m, Ackermann only: from the driven axle to the steering joints
    front_track: float | None = None  # m, Ackermann only: between the steering joints


@dataclass(frozen=True, eq=False)
class Asset:
    """Everything the checks read from one USD file."""

    file: str
    name: str  # the default prim's name
    variants: Mapping[str, str]  # the variant selections the reader used
    bodies: Mapping[str, Body]  # by path, in file order
    joints: tuple[Joint, ...]
    sites: tuple[GripperSite, ...] = ()
    articulated: bool = False  # some prim has PhysicsArticulationRootAPI
    wheeled: WheeledBase | None = None  # from SimReady_Metadata.mobile; None for a robot without wheels
    _by_name: dict[str, Joint] = field(init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "_by_name", {j.name: j for j in self.joints})

    def joint(self, name: str) -> Joint:
        return self._by_name[name]

    @property
    def world_fixed(self) -> tuple[str, ...]:
        """Fixed joints with one side empty: they hold the asset to the world."""
        return tuple(j.name for j in self.joints if j.kind == "fixed" and (j.body0 is None) != (j.body1 is None))

    @property
    def root_body(self) -> str:
        """The first body that no joint carries."""
        carried = {j.body1 for j in self.joints if j.body0 and j.body1}
        return next((path for path in self.bodies if path not in carried), next(iter(self.bodies)))

    def carried(self, body: str) -> list[str]:
        """The bodies that `body` carries through joints (body0 to body1), itself first."""
        below: dict[str | None, list[str | None]] = {}
        for j in self.joints:
            below.setdefault(j.body0, []).append(j.body1)
        found, todo = [], [body]
        while todo:
            b = todo.pop()
            if b is None or b in found:
                continue
            found.append(b)
            todo += below.get(b, [])
        return found
