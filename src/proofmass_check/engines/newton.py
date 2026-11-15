# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The Newton engine (experimental): the asset as Newton's own USD importer reads it.

Newton runs on NVIDIA Warp with the MuJoCo Warp solver, on the GPU. Runs of steps are captured as
CUDA graphs, which makes a step several times faster.

Not done yet:
- SPEED: it needs a run at another physics step.
- STAND, DRIVE, TURN, STEER: driving the wheels.
- The axes of a D6 joint: Newton builds a D6 joint as one joint with several degrees of freedom,
  and we do not address them one by one yet. The run's notes list these joints.
"""

import math

import newton
import numpy as np
import warp as wp
from pxr import Usd

from proofmass_check.checks import TITLES
from proofmass_check.engines.base import DropOutcome, GripOutcome, GripSetup, JointState, LoadOutcome, Motion
from proofmass_check.geometry import quat_to_matrix
from proofmass_check.model import Asset
from proofmass_check.rules import GRAVITY

STEP = 0.002  # s: 500 Hz, the MuJoCo Warp solver's step here
CHUNK = 50  # steps in one CUDA graph. An even number, so the two states end in their first order.
DEVICE = "cuda:0"


def create() -> "NewtonEngine":
    return NewtonEngine()


class NewtonEngine:
    name = "newton"
    variant_sets = ("Newton", "MuJoCo")

    def __init__(self):
        self.asset: Asset | None = None
        self.floor: float | None = None
        self.hold_base: float | None = None
        self.sim: _Sim | None = None

    @property
    def supported(self) -> frozenset[str]:
        checks = set(TITLES) - {"SPEED", "STAND", "DRIVE", "TURN", "STEER"}
        if self.sim is not None and not self.sim.free:
            checks.discard("DROP")  # Newton built no free joint, so there is nothing to lift
        return frozenset(checks)

    def version(self):
        return {"newton": newton.__version__, "warp": wp.__version__, "device": str(wp.get_device(DEVICE))}

    def open(self, asset: Asset, floor: float | None, hold_base: float | None = None) -> None:
        self.asset, self.floor, self.hold_base = asset, floor, hold_base
        self.sim = _Sim(asset, floor, hold_base=hold_base)

    def close(self, exit_code: int = 0) -> None:
        self.sim = None

    def load(self) -> LoadOutcome:
        """Newton: every moving joint of the USD must be a joint of Newton's model.

        An axis of a D6 joint counts as built when Newton built the D6 joint.
        """
        sim = self.sim
        missing, not_addressable = [], []
        for joint in self.asset.joints:
            if not joint.moves or joint.name in sim.q_at:
                continue
            (not_addressable if joint.d6 in sim.q_at else missing).append(joint.name)
        masses, coms = sim.model.body_mass.numpy(), sim.model.body_com.numpy()
        built = {path: i for path, i in sim.bodies.items() if path in self.asset.bodies}
        return LoadOutcome(
            missing=tuple(missing),
            masses={path: float(masses[i]) for path, i in built.items()},
            coms={path: np.array(coms[i], float) for path, i in built.items()},
            not_addressable=tuple(not_addressable),
        )

    def drop(self, height: float, seconds: float) -> DropOutcome:
        sim = self.sim
        sim.reset(lift=height)
        sim.targets({})
        sim.run(seconds)
        body_q, body_qd = sim.s0.body_q.numpy(), sim.s0.body_qd.numpy()
        poses = {}
        for path, i in sim.bodies.items():
            if path in self.asset.bodies:
                x, y, z, w = body_q[i][3:]
                poses[path] = (quat_to_matrix((w, x, y, z)), np.array(body_q[i][:3], float))
        speed = float(np.linalg.norm(body_qd[sim.bodies[self.asset.root_body]][:3]))
        return DropOutcome(poses=poses, root_speed=speed, finite=bool(np.all(np.isfinite(body_q))))

    def settle(self, targets, seconds) -> JointState:
        sim = self.sim
        sim.reset()
        sim.targets(targets)
        sim.run(seconds)
        q = sim.s0.joint_q.numpy()
        names = list(sim.q_at)
        return JointState(
            positions={n: float(q[sim.q_at[n]]) for n in names},
            finite=bool(np.all(np.isfinite(q))),
            max_speed=float(np.max(np.abs(sim.s0.joint_qd.numpy()), initial=0.0)),
        )

    def drive(self, wheels, steer, seconds, lift, sample):
        raise NotImplementedError("the newton engine does not drive wheels yet")

    def move(self, targets, seconds, step) -> Motion:
        raise NotImplementedError("the newton engine does not run SPEED yet")

    def push(self, joint: str, effort: float, seconds: float) -> float:
        sim = self.sim
        sim.reset()
        sim.targets({})
        forces = np.zeros(sim.model.joint_dof_count, np.float32)
        forces[sim.qd_at[joint]] = effort
        sim.control.joint_f.assign(forces)
        sim.run(seconds)
        return float(sim.s0.joint_q.numpy()[sim.q_at[joint]])

    def grip_scene(self, setup: GripSetup) -> "NewtonGrip":
        return NewtonGrip(self, setup)


class _Sim:
    """The asset as one Newton model, with two states, a control and a CUDA graph of CHUNK steps.

    The initial state is kept for resets. With a grip box, MuJoCo gets settings for grasping:
    an elliptic friction cone, impratio 10, and several contacts per pair.
    """

    def __init__(self, asset: Asset, floor: float | None, box=None, hold_base: float | None = None):
        stage = Usd.Stage.Open(asset.file)  # keep the stage alive until the model is built
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            for name, value in asset.variants.items():
                stage.GetDefaultPrim().GetVariantSet(name).SetVariantSelection(value)
        builder = newton.ModelBuilder()
        newton.solvers.SolverMuJoCo.register_custom_attributes(builder)  # so the importer reads the mjc: data
        # A wheeled robot's base is held up: the importer fixes the root to the world, lifted by hold_base.
        import_options = {}
        if hold_base:
            import_options = {"floating": False, "xform": wp.transform((0.0, 0.0, hold_base), wp.quat_identity())}
        info = builder.add_usd(stage, **import_options)
        if floor is not None:
            builder.add_ground_plane(height=floor)
        self.box = _add_box(builder, box) if box else None
        self.model = model = builder.finalize(device=DEVICE)
        # One contact per finger lets the box sink in and turn. Newton's default is 1 contact per pair,
        # MuJoCo's own default is 4, and multiccd gives several.
        options = {"cone": "elliptic", "impratio": 10.0, "enable_multiccd": True} if box else {}
        self.solver = newton.solvers.SolverMuJoCo(model, **options)
        self.control = model.control()
        self.target0 = model.joint_target_q.numpy().copy()
        names = [label.rsplit("/", 1)[-1] for label in model.joint_label]
        # joint_q_start can hold one entry more than there are joints, so zip is not strict here.
        self.q_at = dict(zip(names, model.joint_q_start.numpy().tolist(), strict=False))
        self.qd_at = dict(zip(names, model.joint_qd_start.numpy().tolist(), strict=False))
        free = int(newton.JointType.FREE)
        self.free = [n for n, t in zip(names, model.joint_type.numpy().tolist(), strict=True) if t == free]
        self.bodies = dict(info["path_body_map"])  # USD path: body index
        self.init = model.state()
        self.s0, self.s1 = model.state(), model.state()
        self.graph = None

    def _step(self):
        self.solver.step(self.s0, self.s1, self.control, None, STEP)
        self.s0, self.s1 = self.s1, self.s0

    def reset(self, lift: float = 0.0):
        """The initial state, with every free joint lifted by lift (m)."""
        self.s0.assign(self.init)
        self.s1.assign(self.init)
        if lift:
            q = self.s0.joint_q.numpy()
            for name in self.free:
                q[self.q_at[name] + 2] += lift  # a free joint's coordinates start with x, y, z
            self.s0.joint_q.assign(q)
            newton.eval_fk(self.model, self.s0.joint_q, self.s0.joint_qd, self.s0)
        self.control.joint_f.zero_()
        zero = np.zeros((self.model.body_count, 6), np.float32)
        self.s0.body_f.assign(zero)
        self.s1.body_f.assign(zero)

    def run(self, seconds: float):
        n = 2 * round(seconds / STEP / 2)
        if self.graph is None:
            with wp.ScopedCapture() as capture:
                for _ in range(CHUNK):
                    self._step()
            self.graph = capture.graph
            n -= CHUNK  # capturing the graph also ran its steps
        for _ in range(n // CHUNK):
            wp.capture_launch(self.graph)
        for _ in range(n % CHUNK):
            self._step()

    def targets(self, values):
        """Position targets, by joint name. The other joints keep the model's own targets."""
        target = self.target0.copy()
        for name, value in values.items():
            target[self.q_at[name]] = value
        self.control.joint_target_q.assign(target)


def _add_box(builder, box) -> int:
    """The grip box: a free 1 kg body. A trial sets its mass and cancels its weight."""
    from proofmass_check.rules import GRIP_FRICTION

    q = wp.quat_from_matrix(wp.mat33(*np.asarray(box.rotation).ravel().tolist()))
    sx, sy, sz = box.size
    inertia = np.diag([sy * sy + sz * sz, sx * sx + sz * sz, sx * sx + sy * sy]) / 12  # of a 1 kg box
    body = builder.add_body(
        xform=wp.transform(tuple(box.centre), q), mass=1.0, inertia=wp.mat33(*inertia.ravel()), label="grip_box"
    )
    config = newton.ModelBuilder.ShapeConfig(density=0.0, mu=GRIP_FRICTION)
    builder.add_shape_box(body, hx=sx / 2, hy=sy / 2, hz=sz / 2, cfg=config)
    return body


class NewtonGrip:
    """GRIP and SHAKE on a model with the grip box."""

    def __init__(self, engine: NewtonEngine, setup: GripSetup):
        self.setup = setup
        self.sim = sim = _Sim(engine.asset, engine.floor, box=setup.box, hold_base=engine.hold_base)
        self.hand = sim.bodies[setup.site.body]
        driven = {**setup.hold, **setup.close}
        self.goal = {n: v for n, v in driven.items() if n in sim.q_at}
        self.inertia = sim.model.body_inertia.numpy()[sim.box].copy()  # of the 1 kg box

    def _in_hand(self):
        """The box's position in the hand's frame, and the hand's rotation."""
        body_q = self.sim.s0.body_q.numpy()
        x, y, z, w = body_q[self.hand][3:]
        r = quat_to_matrix((w, x, y, z))
        return r.T @ (body_q[self.sim.box][:3] - body_q[self.hand][:3]), r

    def _set_mass(self, mass: float):
        m, box = self.sim.model, self.sim.box
        for array, value in (
            (m.body_mass, mass),
            (m.body_inv_mass, 1.0 / mass),
            (m.body_inertia, self.inertia * mass),
            (m.body_inv_inertia, np.linalg.inv(self.inertia) / mass),
        ):
            a = array.numpy()
            a[box] = value
            array.assign(a)
        self.sim.solver.notify_model_changed(newton.ModelFlags.BODY_INERTIAL_PROPERTIES)

    def _force(self, force):
        self.sim.s0.body_f.assign(force)
        self.sim.s1.body_f.assign(force)

    def trial(self, mass: float, direction, shake: bool) -> GripOutcome:
        sim, setup = self.sim, self.setup
        self._set_mass(mass)
        sim.reset()
        sim.targets(self.goal)
        force = np.zeros((sim.model.body_count, 6), np.float32)
        force[sim.box, 2] = mass * GRAVITY  # cancels the box's weight
        self._force(force)
        sim.run(setup.close_seconds)
        q = sim.s0.joint_q.numpy()
        closed = {n: float(q[sim.q_at[n]]) for n in setup.close if n in sim.q_at}
        start = self._in_hand()[0]
        pull = mass * GRAVITY * np.asarray(direction)
        if not shake:
            force[sim.box, :3] += pull
            self._force(force)
            sim.run(setup.pull_seconds)
        else:
            # The force changes every 4 steps. An even count keeps the CUDA graph's state order.
            for k in range(0, round(setup.pull_seconds / STEP), 4):
                shaken = force.copy()
                shaken[sim.box, :3] += pull * (1 + math.sin(2 * math.pi * setup.shake_hz * k * STEP))
                self._force(shaken)
                for _ in range(4):
                    sim._step()
        position, rotation = self._in_hand()
        return GripOutcome(
            motion=rotation @ (position - start), closed=closed, finite=bool(np.all(np.isfinite(position)))
        )
