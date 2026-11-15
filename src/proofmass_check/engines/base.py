# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""What an engine must do for the checks.

An engine only runs the simulation. It does not decide which checks run or whether they pass:
plan.py and the modules in checks/ do that, the same way for every engine. So an engine gives a
few small operations, each starting from the asset's rest pose, and reports what it measured.

All values are in SI units, and joint values are in radians or metres.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from proofmass_check.model import Asset, GripperSite


@dataclass(frozen=True)
class LoadOutcome:
    """How the engine built the asset.

    `missing` and `unknown` compare the engine's joints with the USD's. What an engine can compare
    depends on how it builds the asset, so each engine's docstring says what it compares.
    """

    missing: tuple[str, ...] = ()  # USD joints the engine did not build
    unknown: tuple[str, ...] = ()  # engine joints the reader does not know
    masses: Mapping[str, float] = field(default_factory=dict)  # kg, by body path
    coms: Mapping[str, np.ndarray] = field(default_factory=dict)  # centre of mass in the body's frame, m
    # Joints the engine builds but cannot drive or measure one by one yet. The run leaves them out
    # of every check and says so in its notes, so they never pass by default.
    not_addressable: tuple[str, ...] = ()


@dataclass(frozen=True, eq=False)
class DropOutcome:
    """The asset after a drop."""

    poses: Mapping[str, tuple[np.ndarray, np.ndarray]]  # body path: (3x3 rotation, position)
    root_speed: float  # m/s, of the root body
    finite: bool  # False when any value became NaN or infinite


@dataclass(frozen=True)
class JointState:
    """The joints after a settle."""

    positions: Mapping[str, float]  # rad or m, by joint name
    finite: bool
    max_speed: float  # the fastest joint at the end, rad/s or m/s


@dataclass(frozen=True, eq=False)
class Motion:
    """A move measured at every step."""

    speeds: Mapping[str, np.ndarray]  # each moved joint's speed at every step, rad/s or m/s
    positions: Mapping[str, float]  # every driven joint at the end
    finite: bool


@dataclass(frozen=True, eq=False)
class GripBox:
    """The box a gripper closes on: a full size along (closing, grip line, approach), in m."""

    size: tuple[float, float, float]
    centre: np.ndarray
    rotation: np.ndarray  # 3x3, columns: the box's axes in the world


@dataclass(frozen=True, eq=False)
class GripSetup:
    """What a grip scene needs."""

    site: GripperSite
    box: GripBox
    close: Mapping[str, float]  # finger joints and the limit each one closes to
    hold: Mapping[str, float]  # the other position-driven joints and their rest positions
    close_seconds: float  # time the fingers get to close
    pull_seconds: float  # how long a pull lasts
    shake_hz: float  # frequency of the shaking pull


@dataclass(frozen=True, eq=False)
class GripOutcome:
    """One pull on the box."""

    motion: np.ndarray  # how the box moved relative to the hand during the pull, in the world, m
    closed: Mapping[str, float]  # finger joint positions after closing, before the pull
    finite: bool


@dataclass(frozen=True, eq=False)
class BaseTrace:
    """The root body of a wheeled robot, recorded while it drives."""

    times: np.ndarray  # (n,), s
    positions: np.ndarray  # (n, 3), m
    rotations: np.ndarray  # (n, 3, 3)


class GripScene(Protocol):
    def trial(self, mass: float, direction: np.ndarray, shake: bool) -> GripOutcome:
        """From the rest pose, close the fingers on a box of this mass, then pull the box.

        The box has no weight. The pull is mass x g along direction for pull_seconds. With shake,
        it is mass x g x (1 + sin(2 pi shake_hz t)).
        """
        ...


class Engine(Protocol):
    name: str  # as on the command line: "physx", "newton"
    variant_sets: tuple[str, ...]  # the asset's variant sets this engine reads, preferred first
    supported: frozenset[str]  # the check IDs this engine can run

    def version(self) -> Mapping[str, str]:
        """The versions that affect results, for example {"isaacsim": "6.1.0"}."""
        ...

    def open(self, asset: Asset, floor: float | None, hold_base: float | None = None) -> None:
        """Load the asset with its variants. floor is the floor height in m, or None for no floor.

        hold_base, for a wheeled robot: load, settle, move, push and the grip scene hold the root body
        fixed this far (m) above its file pose, so the wheels do not touch the floor. drive does not.
        """
        ...

    def load(self) -> LoadOutcome: ...

    def drop(self, height: float, seconds: float) -> DropOutcome:
        """Lift every free body by height, then let the asset fall for seconds."""
        ...

    def settle(self, targets: Mapping[str, float], seconds: float) -> JointState:
        """Drive the position-driven joints to targets for seconds."""
        ...

    def move(self, targets: Mapping[str, float], seconds: float, step: float) -> Motion:
        """Like settle, but with the physics step `step`, and measured at every step."""
        ...

    def push(self, joint: str, effort: float, seconds: float) -> float:
        """Push one joint with a force (N) or torque (N m) for seconds; return where it ends."""
        ...

    def grip_scene(self, setup: GripSetup) -> GripScene: ...

    def drive(
        self, wheels: Mapping[str, float], steer: Mapping[str, float], seconds: float, lift: float, sample: float
    ) -> BaseTrace:
        """A wheeled robot, free on the floor, from its rest pose lifted by lift (m).

        Wheel joints get these speeds (rad/s) and steering joints these angles (rad). The root
        body's pose is recorded every `sample` seconds.
        """
        ...

    def close(self, exit_code: int = 0) -> None:
        """Stop the engine. After this, no other call is allowed.

        Isaac Sim ends the process here, so exit_code is the status the process ends with.
        """
        ...
