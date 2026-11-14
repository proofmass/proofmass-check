# SPDX-FileCopyrightText: 2026 The proofmass-check authors
# SPDX-License-Identifier: Apache-2.0
"""An engine without physics, for unit tests of the checks.

IdealEngine does what a perfect simulator would do: drives reach their targets, limits stop them,
a dropped asset lands flat on the floor, a gripper holds anything. A test that needs a bad engine
overrides one method.
"""

import math

import numpy as np

from proofmass_check.checks import TITLES
from proofmass_check.engines.base import BaseTrace, DropOutcome, GripOutcome, JointState, LoadOutcome, Motion
from proofmass_check.geometry import lowest_collider


class IdealEngine:
    name = "fake"
    variant_sets = ("PhysX",)
    supported = frozenset(TITLES)

    def __init__(self):
        self.asset = None
        self.floor = None
        self.calls = []  # (operation, arguments), in order

    def version(self):
        return {"fake": "1"}

    def open(self, asset, floor, hold_base=None):
        self.asset, self.floor, self.hold_base = asset, floor, hold_base

    def load(self):
        bodies = self.asset.bodies.values()
        return LoadOutcome(masses={b.path: b.mass or 1.0 for b in bodies}, coms={b.path: b.com for b in bodies})

    def drop(self, height, seconds):
        """Every body keeps its file rotation; the asset lands with its lowest collider on the floor."""
        bodies = self.asset.bodies.values()
        lowest = min(lowest_collider(b, b.pose[:3, :3], b.pose[:3, 3]) for b in bodies)
        shift = np.array([0.0, 0.0, self.floor - lowest])
        poses = {b.path: (b.pose[:3, :3], b.pose[:3, 3] + shift) for b in bodies}
        return DropOutcome(poses=poses, root_speed=0.0, finite=True)

    def _clip(self, name, value):
        j = self.asset.joint(name)
        return float(np.clip(value, j.lower, j.upper))

    def settle(self, targets, seconds):
        self.calls.append(("settle", dict(targets), seconds))
        return JointState({n: self._clip(n, v) for n, v in targets.items()}, finite=True, max_speed=0.0)

    def move(self, targets, seconds, step):
        """Each joint that moves goes at exactly its speed limit."""
        self.calls.append(("move", dict(targets), seconds))
        steps = round(seconds / step)
        speeds = {}
        for name, target in targets.items():
            j = self.asset.joint(name)
            moving = target != j.rest and math.isfinite(j.max_speed)
            speeds[name] = np.full(steps, j.max_speed if moving else 0.0)
        return Motion(speeds=speeds, positions={n: self._clip(n, v) for n, v in targets.items()}, finite=True)

    def push(self, joint, effort, seconds):
        self.calls.append(("push", joint, effort))
        j = self.asset.joint(joint)
        return j.upper if effort > 0 else j.lower

    def grip_scene(self, setup):
        return IdealGrip(setup)

    def drive(self, wheels, steer, seconds, lift, sample):
        """A robot on wheels that never slip: the left and right wheel speeds set its speed and yaw rate."""
        base = self.asset.wheeled
        by_name = {w.name: w for w in base.wheels}

        def side_speed(side):
            speeds = [v * by_name[n].radius * by_name[n].spin for n, v in wheels.items() if by_name[n].side == side]
            return sum(speeds) / len(speeds) if speeds else 0.0

        left, right = side_speed("left"), side_speed("right")
        speed, rate = (left + right) / 2, (right - left) / base.track
        root = self.asset.bodies[self.asset.root_body].pose[:3, 3]
        axle0 = np.array([base.axle_centre[0], base.axle_centre[1], root[2]])
        times, positions, rotations = [], [], []
        for k in range(round(seconds / sample) + 1):
            t = k * sample
            yaw = rate * t
            if rate:
                x, y = speed / rate * math.sin(yaw), speed / rate * (1 - math.cos(yaw))
            else:
                x, y = speed * t, 0.0
            r = np.array([[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]])
            times.append(t)
            positions.append(axle0 + np.array([x, y, 0.0]) - r @ (axle0 - root))
            rotations.append(r)
        return BaseTrace(np.array(times), np.array(positions), np.array(rotations))

    def close(self, exit_code=0):
        self.closed_with = exit_code


class IdealGrip:
    """Fingers that stop on the box halfway to their limits, and a box that moves 1 mm along the pull."""

    def __init__(self, setup):
        self.setup = setup
        self.trials = []

    def trial(self, mass, direction, shake):
        self.trials.append((mass, tuple(np.round(direction, 6)), shake))
        closed = {name: limit / 2 for name, limit in self.setup.close.items()}
        return GripOutcome(motion=0.001 * np.asarray(direction, float), closed=closed, finite=True)
