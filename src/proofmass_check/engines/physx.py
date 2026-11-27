# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The PhysX engine: Isaac Sim 6.1, headless and without a renderer.

Run proofmass-check in Isaac Sim's own Python environment. Isaac Sim asks you to accept the NVIDIA
Omniverse License Agreement the first time it starts. This module never accepts it for you.

Each group of checks gets a new stage with the floor and the asset. An articulated asset (one
with PhysicsArticulationRootAPI) is driven through its articulation. Joints between free rigid
bodies can only be pushed, so only LOAD, DROP and PASSIVE run on them.
"""

import math
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

import isaacsim  # must come before any omni or pxr import
import numpy as np

from proofmass_check import replay
from proofmass_check.engines.base import (
    BaseTrace,
    DropOutcome,
    GripOutcome,
    GripSetup,
    JointState,
    LoadOutcome,
    Motion,
)
from proofmass_check.engines.capabilities import CAPABILITIES, supported
from proofmass_check.geometry import matrix_to_quat, quat_to_matrix
from proofmass_check.model import Asset, Joint
from proofmass_check.replay import Recorder
from proofmass_check.rules import GRAVITY

STEP = 1 / 240  # s
ROOT = "/World/asset"  # where the asset is referenced on the test stage

# A small Kit app: USD, PhysX, Isaac Sim's core API and robot schema, no renderer. It starts in
# about 7 s instead of 20 s or more for the full app.
EXPERIENCE = """[package]
title = "proofmass-check"
description = "Isaac Sim without rendering: USD, PhysX, the core API and Isaac Sim's robot schema"
version = "1.0.0"

[dependencies]
"isaacsim.core.api" = {{}}
"isaacsim.robot.schema" = {{}}
"omni.kit.loop-isaac" = {{}}  # Kit's run loop. Without it, Kit 110 stops at startup.

[settings.app]
name = "Isaac-Sim Python"
version = "6.1.0"
settings.persistent = false
enableDeveloperWarnings = false

[settings.app.exts.folders]
'++' = ["{apps}", "{apps}/../exts", "{apps}/../extscache", "{apps}/../extsUser", "{apps}/../extsDeprecated"]
"""


def create() -> "PhysxEngine":
    return PhysxEngine()


class PhysxEngine:
    name = "physx"
    variant_sets = CAPABILITIES["physx"].variant_sets
    reads_mjc_actuators = CAPABILITIES["physx"].reads_mjc_actuators
    recorder: Recorder | None = None  # the runner sets it for a run with a replay

    def __init__(self):
        apps = (Path(isaacsim.__file__).parent / "apps").as_posix()
        kit_file = Path(tempfile.mkdtemp(prefix="proofmass_check_")) / "proofmass_check.kit"
        kit_file.write_text(EXPERIENCE.format(apps=apps), encoding="utf-8")
        # Kit reads sys.argv as its own options and stops at one it does not know, such as "-m".
        # So it starts with no arguments, and gets ours back after.
        stdout, argv = sys.stdout, sys.argv
        sys.argv = argv[:1]
        try:
            self.app = isaacsim.SimulationApp({"headless": True, "multi_gpu": False}, experience=str(kit_file))
        finally:
            sys.argv = argv
        # Kit sends print() to its log. Give the terminal back to the command's own output.
        sys.stdout = stdout
        self.asset: Asset | None = None
        self.floor: float | None = None
        self.hold_base: float | None = None
        self._scene = None
        self._scene_key = None

    @property
    def supported(self) -> frozenset[str]:
        return supported("physx", self.asset)

    def version(self):
        return {"isaacsim": version("isaacsim")}

    def open(self, asset: Asset, floor: float | None, hold_base: float | None = None) -> None:
        self.asset, self.floor, self.hold_base = asset, floor, hold_base
        self._scene = self._scene_key = None  # a stage of an asset opened before must not be used again

    def close(self, exit_code: int = 0) -> None:
        self.app.close(exit_code=exit_code)  # Isaac Sim ends the process with this status

    # --- scenes

    def scene(self, step: float = STEP, box=None, held: bool = True):
        """The current stage, or a new one when the asset, the step, the grip box or the base hold changes.

        held: hold the base as open's hold_base says. Only drop and drive leave it free.
        """
        hold = self.hold_base if held else None
        key = (id(self.asset), step, id(box), hold)
        if self._scene_key != key:
            self._scene = _Scene(self.asset, self.floor, step, box, hold)
            self._scene_key = key
        self._scene.recorder = self.recorder
        return self._scene

    # --- the operations of the Engine protocol

    def load(self) -> LoadOutcome:
        """PhysX: the articulation's degrees of freedom must all be joints of the USD.

        A USD joint that is not in the articulation (a loop-closing joint, for example) is not
        compared, because PhysX keeps such joints outside the articulation on purpose.
        """
        scene = self.scene()
        masses = np.asarray(scene.bodies.get_masses()).reshape(-1)
        coms = np.asarray(scene.bodies.get_coms()[0]).reshape(-1, 3)
        known = {j.name for j in self.asset.joints if j.moves}
        return LoadOutcome(
            unknown=tuple(n for n in scene.names if n not in known),
            masses={path: float(m) for path, m in zip(scene.body_paths, masses, strict=True)},
            coms={path: c for path, c in zip(scene.body_paths, coms, strict=True)},
        )

    def drop(self, height: float, seconds: float) -> DropOutcome:
        scene = self.scene(held=False)
        scene.world.reset()
        lift = np.array([0.0, 0.0, height])
        if scene.art is not None:
            position, rotation = scene.art.get_world_pose()
            scene.art.set_world_pose(position + lift, rotation)
        else:
            positions, rotations = scene.bodies.get_world_poses()
            scene.bodies.set_world_poses(np.asarray(positions) + lift, np.asarray(rotations))
        scene.begin()
        scene.run(seconds)
        scene.end()
        moving = scene.art if scene.art is not None else scene.root
        speed = float(np.linalg.norm(moving.get_linear_velocity()))
        poses = scene.body_poses()
        finite = all(np.all(np.isfinite(r)) and np.all(np.isfinite(t)) for r, t in poses.values())
        return DropOutcome(poses=poses, root_speed=speed, finite=finite and math.isfinite(speed))

    def settle(self, targets, seconds) -> JointState:
        scene = self.scene()
        scene.world.reset()
        action = scene.action(targets)
        scene.begin()
        for _ in range(int(seconds / scene.step)):
            scene.controller.apply_action(action)
            scene.advance()
        scene.end()
        q, v = scene.joint_state()
        return JointState(
            positions=dict(zip(scene.names, q.tolist(), strict=True)),
            finite=bool(np.all(np.isfinite(q))),
            max_speed=float(np.max(np.abs(v))) if len(v) else 0.0,
        )

    def move(self, targets, seconds, step) -> Motion:
        scene = self.scene(step)
        scene.world.reset()
        action = scene.action(targets)
        index = {n: scene.names.index(n) for n in targets}
        speeds = {n: [] for n in targets}
        scene.begin()
        for _ in range(int(seconds / step)):
            scene.controller.apply_action(action)
            scene.advance()
            v = np.asarray(scene.art.get_joint_velocities())
            for n, i in index.items():
                speeds[n].append(float(v[i]))
        scene.end()
        q, _ = scene.joint_state()
        return Motion(
            speeds={n: np.array(s) for n, s in speeds.items()},
            positions=dict(zip(scene.names, q.tolist(), strict=True)),
            finite=bool(np.all(np.isfinite(q))),
        )

    def push(self, joint: str, effort: float, seconds: float) -> float:
        scene = self.scene()
        scene.world.reset()
        scene.begin()
        if scene.art is not None:
            efforts = np.zeros(len(scene.names))
            efforts[scene.names.index(joint)] = effort
            for _ in range(int(seconds / scene.step)):
                scene.art.set_joint_efforts(efforts)
                scene.advance()
            position = float(scene.joint_state()[0][scene.names.index(joint)])
        else:
            position = _push_free_bodies(scene, self.asset.joint(joint), effort, seconds)
        scene.end()
        return position

    def grip_scene(self, setup: GripSetup) -> "PhysxGrip":
        return PhysxGrip(self, setup)

    def drive(self, wheels, steer, seconds, lift, sample) -> BaseTrace:
        from isaacsim.core.utils.types import ArticulationAction

        scene = self.scene(held=False)
        scene.world.reset()
        if lift:
            position, rotation = scene.art.get_world_pose()
            scene.art.set_world_pose(position + np.array([0.0, 0.0, lift]), rotation)
        actions = [
            ArticulationAction(
                joint_velocities=np.array(list(wheels.values()), float),
                joint_indices=np.array([scene.names.index(n) for n in wheels]),
            )
        ]
        if steer:
            actions.append(scene.action(steer))
        every = max(1, round(sample / scene.step))
        times, positions, rotations = [], [], []
        scene.begin()
        for k in range(int(seconds / scene.step)):
            for action in actions:
                scene.controller.apply_action(action)
            scene.advance()
            if k % every == 0:
                position, quat = scene.art.get_world_pose()
                times.append((k + 1) * scene.step)
                positions.append(np.asarray(position, float))
                # In double precision: the tilt is acos of a value close to 1, which single precision rounds.
                rotations.append(quat_to_matrix(np.asarray(quat, float)))
        scene.end()
        return BaseTrace(np.array(times), np.array(positions), np.array(rotations))


class _Scene:
    """A new stage with the floor and the asset, stepped at `step`. It also has the grip box when box is given."""

    def __init__(self, asset: Asset, floor: float | None, step: float, box=None, hold: float | None = None):
        from isaacsim.core.api import World
        from isaacsim.core.api.objects.ground_plane import GroundPlane
        from isaacsim.core.prims import RigidPrim, SingleArticulation, SingleRigidPrim
        from isaacsim.core.utils.stage import add_reference_to_stage, create_new_stage, get_current_stage
        from pxr import UsdPhysics

        self.asset, self.step = asset, step
        self.recorder: Recorder | None = None  # PhysxEngine.scene() sets it
        self._every = replay.every(step)
        self._steps = self._recorded_at = 0
        World.clear_instance()
        create_new_stage()
        self.world = World(stage_units_in_meters=1.0, physics_dt=step, rendering_dt=step)
        if floor is not None:
            GroundPlane(prim_path="/World/ground", z_position=floor)
        prim = add_reference_to_stage(asset.file, ROOT)
        for name, value in asset.variants.items():
            prim.GetVariantSets().GetVariantSet(name).SetVariantSelection(value)
        for path in asset.free_roots:  # left out by the reader: the checks hold the base instead
            UsdPhysics.Joint(get_current_stage().GetPrimAtPath(self.stage_path(path))).CreateJointEnabledAttr(False)
        if hold is not None:
            self._hold_base(hold)
        self.box = _add_box(self.world, box, asset) if box else None
        self.body_paths = list(asset.bodies)
        stage_paths = [self.stage_path(p) for p in self.body_paths]
        self.bodies = RigidPrim(prim_paths_expr=stage_paths, name="bodies")
        self.world.scene.add(self.bodies)
        # The view may list the bodies in another order than we asked for.
        order = {stage: i for i, stage in enumerate(self.bodies.prim_paths)}
        self._index = [order[s] for s in stage_paths]
        self.art = None
        if asset.articulated:
            self.art = SingleArticulation(prim_path=ROOT, name="asset")
            self.world.scene.add(self.art)
        else:
            self.root = SingleRigidPrim(prim_path=self.stage_path(asset.root_body), name="root")
            self.world.scene.add(self.root)
        self.world.reset()
        self.names = list(self.art.dof_names) if self.art is not None else []
        self.controller = self.art.get_articulation_controller() if self.art is not None else None
        if self.art is not None:
            self._reset_to_file_pose()

    def _reset_to_file_pose(self) -> None:
        """Make every reset put each joint at its rest position, as the file has it.

        Isaac Sim 6.1 does not do this for every joint by itself: it resets a PhysX mimic follower
        to 0, whatever its PhysicsJointStateAPI position is. A finger that jumps to 0 at a reset
        can start inside the grip box and push it away before the test starts.
        """
        rest = {j.name: j.rest for j in self.asset.joints}
        current = np.asarray(self.art.get_joint_positions(), float)
        positions = np.array([rest.get(name, q) for name, q in zip(self.names, current, strict=True)])
        self.art.set_joints_default_state(positions=positions)
        self.world.reset()

    def _hold_base(self, lift: float) -> None:
        """A fixed joint that holds the root body lift (m) above its file pose, turned as the file turns it."""
        from isaacsim.core.utils.stage import get_current_stage
        from pxr import Gf, UsdPhysics

        pin = UsdPhysics.FixedJoint.Define(get_current_stage(), f"{ROOT}/proofmass_check_hold_base")
        pin.CreateBody1Rel().SetTargets([self.stage_path(self.asset.root_body)])
        pose = self.asset.bodies[self.asset.root_body].pose
        x, y, z = pose[:3, 3]
        pin.CreateLocalPos0Attr(Gf.Vec3f(float(x), float(y), float(z + lift)))
        w, qx, qy, qz = (float(v) for v in matrix_to_quat(pose[:3, :3]))
        pin.CreateLocalRot0Attr(Gf.Quatf(w, qx, qy, qz))
        pin.CreateLocalPos1Attr(Gf.Vec3f(0, 0, 0))
        pin.CreateLocalRot1Attr(Gf.Quatf(1, 0, 0, 0))

    def stage_path(self, body_path: str) -> str:
        """Where a body of the file is on the test stage."""
        return ROOT + body_path[len(self.asset.name) + 1 :]

    def run(self, seconds: float) -> None:
        for _ in range(int(seconds / self.step)):
            self.advance()

    # --- steps, and the frames of a replay

    def begin(self) -> None:
        """An operation starts, after its reset: the first frame of its clip."""
        self._steps = 0
        self._record()

    def advance(self) -> None:
        """One physics step. Every few steps, a frame of the replay (replay.every)."""
        self.world.step(render=False)
        self._steps += 1
        if self._steps % self._every == 0:
            self._record()

    def end(self) -> None:
        """An operation ends: its last frame, unless the last step gave it."""
        if self._recorded_at != self._steps:
            self._record()

    def _record(self) -> None:
        if self.recorder is None:
            return
        positions, quats = (np.asarray(a, float) for a in self.bodies.get_world_poses())
        poses = np.hstack([positions[self._index], quats[self._index]])  # Isaac Sim's quaternions are w, x, y, z
        if self.box is not None:
            position, quat = (np.asarray(a, float)[0] for a in self.box[1].get_world_poses())
            poses = np.vstack([poses, np.concatenate([position, quat])])
        self.recorder.frame(self._steps * self.step, poses)
        self._recorded_at = self._steps

    def action(self, targets):
        from isaacsim.core.utils.types import ArticulationAction

        return ArticulationAction(
            joint_positions=np.array([targets[n] for n in targets], float),
            joint_indices=np.array([self.names.index(n) for n in targets]),
        )

    def joint_state(self):
        return np.asarray(self.art.get_joint_positions(), float), np.asarray(self.art.get_joint_velocities(), float)

    def body_poses(self):
        """Each body's (3x3 rotation, position), by its path in the file."""
        from isaacsim.core.utils.rotations import quat_to_rot_matrix

        positions, quats = (np.asarray(a) for a in self.bodies.get_world_poses())
        return {
            path: (quat_to_rot_matrix(quats[i]), positions[i])
            for path, i in zip(self.body_paths, self._index, strict=True)
        }


def _add_box(world, box, asset):
    """The grip box: free, 1 kg until a trial sets its mass, with gravity off."""
    from isaacsim.core.api.materials import PhysicsMaterial
    from isaacsim.core.api.objects import DynamicCuboid
    from isaacsim.core.prims import RigidPrim
    from isaacsim.core.utils.rotations import rot_matrix_to_quat
    from pxr import PhysxSchema

    from proofmass_check.rules import GRIP_FRICTION

    material = PhysicsMaterial(
        prim_path="/World/grip_box_material",
        static_friction=GRIP_FRICTION,
        dynamic_friction=GRIP_FRICTION,
        restitution=0.0,
    )
    cube = DynamicCuboid(
        prim_path="/World/grip_box",
        name="grip_box",
        position=box.centre,
        orientation=rot_matrix_to_quat(box.rotation),
        size=1.0,
        scale=np.array(box.size),
        mass=1.0,
        physics_material=material,
    )
    PhysxSchema.PhysxRigidBodyAPI.Apply(cube.prim).CreateDisableGravityAttr(True)
    pull = RigidPrim(prim_paths_expr="/World/grip_box", name="grip_pull")  # applies the pull force
    world.scene.add(cube)
    world.scene.add(pull)
    return cube, pull


def _joint_position(joint: Joint, poses) -> tuple[float, np.ndarray]:
    """A joint's position (rad or m) and its axis in the world, from the poses of its two bodies."""

    def frame(body, position, rotation):
        if body is None:  # the world
            return position, rotation
        r, x = poses[body]
        return x + r @ position, r @ rotation

    o0, r0 = frame(joint.body0, joint.local_pos0, joint.local_rot0)
    o1, r1 = frame(joint.body1, joint.local_pos1, joint.local_rot1)
    axis = "XYZ".index(joint.axis)
    if joint.kind == "prismatic":
        return float((o1 - o0) @ r0[:, axis]), r0[:, axis]
    u, v = [(1, 2), (2, 0), (0, 1)][axis]
    relative = r0.T @ r1
    return math.atan2(relative[v, u], relative[u, u]), r0[:, axis]


def _push_free_bodies(scene: _Scene, joint: Joint, effort: float, seconds: float) -> float:
    """Push body1 along (or about) the joint axis. Used for joints between free rigid bodies."""
    body1 = scene.body_paths.index(joint.body1)
    index = [scene._index[body1]]
    for _ in range(int(seconds / scene.step)):
        _, axis = _joint_position(joint, scene.body_poses())
        force, torque = np.zeros((1, 3)), np.zeros((1, 3))
        (force if joint.kind == "prismatic" else torque)[0] = effort * axis
        scene.bodies.apply_forces_and_torques_at_pos(forces=force, torques=torque, indices=index, is_global=True)
        scene.advance()
    return _joint_position(joint, scene.body_poses())[0]


class PhysxGrip:
    """GRIP and SHAKE on a stage with the grip box."""

    def __init__(self, engine: PhysxEngine, setup: GripSetup):
        from isaacsim.core.prims import RigidPrim

        self.setup = setup
        self.scene = engine.scene(box=setup.box)
        hand = RigidPrim(prim_paths_expr=self.scene.stage_path(setup.site.body), name="grip_hand")
        self.scene.world.scene.add(hand)
        self.scene.world.reset()
        self.hand = hand
        self.cube, self.pull = self.scene.box
        self.action = self.scene.action({**setup.hold, **setup.close})

    def _in_hand(self):
        """The box's position in the hand's frame, and the hand's rotation."""
        from isaacsim.core.utils.rotations import quat_to_rot_matrix

        xh, qh = (np.asarray(a)[0] for a in self.hand.get_world_poses())
        r = quat_to_rot_matrix(qh)
        return r.T @ (np.asarray(self.pull.get_world_poses()[0])[0] - xh), r

    def trial(self, mass: float, direction, shake: bool) -> GripOutcome:
        scene, setup = self.scene, self.setup
        scene.world.reset()
        self.cube.set_mass(mass)
        scene.begin()
        for _ in range(int(setup.close_seconds / scene.step)):
            scene.controller.apply_action(self.action)
            scene.advance()
        q, _ = scene.joint_state()
        closed = {n: float(q[scene.names.index(n)]) for n in setup.close}
        start = self._in_hand()[0]
        for k in range(int(setup.pull_seconds / scene.step)):
            g = 1 + math.sin(2 * math.pi * setup.shake_hz * k * scene.step) if shake else 1.0
            self.pull.apply_forces(np.array([mass * GRAVITY * g * np.asarray(direction)]), is_global=True)
            scene.controller.apply_action(self.action)
            scene.advance()
        scene.end()
        position, rotation = self._in_hand()
        return GripOutcome(
            motion=rotation @ (position - start), closed=closed, finite=bool(np.all(np.isfinite(position)))
        )
