# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The numbers behind every check.

docs/spec.md explains each number. A unit test compares the two files, so they cannot drift apart.
A change here is a change of the spec: raise SPEC_VERSION and add a line to CHANGELOG.md.

Values are in SI units (m, kg, s, N) unless the name says otherwise.
"""

import math
from dataclasses import dataclass

SPEC_VERSION = "0.5"
SEED = 0  # every random choice uses numpy.random.default_rng(SEED)
GRAVITY = 9.81  # m/s2, along -Z

# Defaults that the command line can change (--settle). A run with other values says so in its results.
SETTLE_S = 1.5  # time a drive gets to reach a target
LINEAR_TOL = 0.002  # a prismatic joint is "at" a target within this distance
ANGULAR_TOL_DEG = 0.5  # a revolute joint is "at" a target within this angle
RANDOM_POSES = 50  # STABLE: poses tried

# Scene
FLOOR_BELOW = 0.001  # the floor is this far below the lowest collider in the file pose

# LOAD
MASS_TOL = 0.01  # the engine's total mass may differ from the USD's by this fraction

# INERTIA: a body's inertia, over that of its mass spread on its collider points (traces), is within these
INERTIA_MIN_RATIO = 0.01
INERTIA_MAX_RATIO = 100.0

# DROP
DROP_HEIGHT = 0.1  # the asset is lifted this far, then let go
DROP_SECONDS = 3.0
REST_SPEED = 0.05  # m/s: slower than this counts as at rest
FLOOR_TOL = 0.002  # the lowest collider ends within this distance of the floor, above or below

# HOLD, TRACK, LIMIT, STABLE
TRACK_AT = (0.25, 0.75)  # TRACK targets, as fractions of the joint range
OVERSHOOT = 0.2  # LIMIT commands a joint this fraction of its range past the upper limit
LIMIT_TOL = 2  # "at a limit" means within this many joint tolerances of it
UNSTABLE_SPEED = 50.0  # rad/s or m/s: a joint faster than this is unstable

# SPEED
SPEED_DT = 1 / 60  # s: Isaac Sim's default physics step
SPEED_SECONDS = 2.0  # each move lasts this long
SPEED_SKIP_STEPS = 5  # the first steps of a move are not measured
SPEED_TOL = 0.05  # a joint may go this fraction over its speed limit
SPEED_MARGIN = 0.05  # the target stops this fraction of the range short of the far limit

# PASSIVE
PUSH_SETTLE = 2  # a push lasts this many SETTLE_S
PUSH_GRAVITY_FACTOR = 1.5  # the base push is this many times the gravity load the joint carries
PUSH_ACCEL_LINEAR = 2.0  # m/s2 added to the base push of a prismatic joint
PUSH_ACCEL_ANGULAR = 4.0  # rad/s2 added to the base push of a revolute joint
PUSH_MIN_LEVER = 0.05  # m: the shortest lever used for a revolute joint
PUSH_STEP = 4.0  # a push that does not reach the limit is tried again this many times stronger
HAND_FORCE = 50.0  # N: the most a hand adds at a handle

# GRIP, SHAKE
GRIP_WIDTH = 0.7  # the box is this fraction of gripper_maxOpening across the pads
GRIP_FRICTION = 2.0  # static and dynamic friction of the box
GRIP_LOAD = 0.85  # the load to hold, as a fraction of gripper_maxPayload
GRIP_LOADS = (0.25, 0.5, 0.85, 1.0, 1.5, 2.0)  # loads tried, as fractions of gripper_maxPayload
GRIP_SLIP = 0.005  # the box moving this far along the pads is a slip
GRIP_HOLD_S = 2.0  # a pull lasts this long
GRIP_MIN_TRAVEL = 0.001  # a joint that moves a finger less than this toward the box does not close the gripper
PAD_WIDTH = 0.02  # pad size when the site has no gripper_grip_line
SHAKE_HZ = 2.0  # the pull is load x g x (1 + sin(2 pi f t)), so up to 2 g

# Wheeled robots: STAND, DRIVE, TURN, STEER
BASE_LIFT = 0.05  # the joint checks of a wheeled robot hold its base this far up, wheels off the floor
BASE_SAMPLE_DT = 0.02  # s: the base pose is recorded this often
WHEEL_SPEED = 0.5  # m/s: the test speed, unless the wheels cannot go that fast
WHEEL_LIMIT_FRACTION = 0.5  # ... then this fraction of the slowest driven wheel's speed limit
STARTUP_S = 1.5  # results are measured after the start-up: this long ...
STARTUP_FRACTION = 0.4  # ... or this fraction of the run, when that is shorter
STAND_SECONDS = 3.0
STAND_TILT_DEG = 2.0  # the most a standing robot may lean
STAND_SPEED = 0.02  # m/s: slower than this counts as standing still
DRIVE_SECONDS = 4.0
DRIVE_SPEED_TOL = 0.1  # the speed may differ from the command by this fraction
DRIVE_YAW_TOL_DEG = 3.0  # the most the heading may change
TURN_SECONDS = 4.0
TURN_TOL = 0.15  # TURN: yaw rate, STEER: turning radius, within this fraction of the expected value
TURN_DRIFT = 0.05  # m: the centre may move this far while the robot turns in place
SKID_TURN_MIN = 0.1  # skid steer: the yaw rate must be above this fraction of the no-slip rate
STEER_FRACTION = 0.5  # STEER: the inner front wheel turns this fraction of its steering range
STEER_MAX_SECONDS = 8.0


@dataclass(frozen=True)
class Settings:
    """The values a run may change. The defaults are the spec's values."""

    settle_s: float = SETTLE_S
    linear_tol: float = LINEAR_TOL
    angular_tol: float = math.radians(ANGULAR_TOL_DEG)  # rad
    random_poses: int = RANDOM_POSES
    floor: bool = True  # False: no floor under any asset; one fixed to the world never gets one

    def tolerance(self, revolute: bool) -> float:
        """The tolerance of one joint: rad for a revolute joint, m for a prismatic joint."""
        return self.angular_tol if revolute else self.linear_tol

    def changes(self) -> list[str]:
        """Each value that differs from the spec, as text for the results."""
        spec = Settings()
        return [
            f"{name} is {getattr(self, name)} (spec: {getattr(spec, name)})"
            for name in ("settle_s", "linear_tol", "angular_tol", "random_poses", "floor")
            if getattr(self, name) != getattr(spec, name)
        ]
