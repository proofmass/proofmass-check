# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import math

import numpy as np
import pytest

from proofmass_check.geometry import floor_height, lowest_collider, matrix_to_quat, quat_to_matrix, run_floor
from proofmass_check.model import Body, Cylinder, Sphere
from proofmass_check.rules import Settings


def test_lowest_collider_of_the_arm(arm):
    bar = arm.bodies["/unit_arm/arm"]
    assert lowest_collider(bar, np.eye(3), np.array([0, 0, 0.25])) == pytest.approx(0.22)
    down = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)  # 90 deg about Y: the bar points down
    assert lowest_collider(bar, down, np.array([0, 0, 0.25])) == pytest.approx(-0.15)
    # 1 mm below the base. The scale in the file is single precision, so compare to 1e-6 m.
    assert floor_height(arm.bodies.values()) == pytest.approx(-0.001, abs=1e-6)


def test_no_floor_under_an_asset_fixed_to_the_world(arm, prop):
    assert arm.world_fixed and run_floor(arm, Settings()) is None  # spec 0.4: a fixed arm reaches through a floor
    assert run_floor(prop, Settings()) == pytest.approx(floor_height(prop.bodies.values()))
    assert run_floor(prop, Settings(floor=False)) is None


def test_no_floor_under_an_asset_the_checks_hold(loose_arm):
    assert loose_arm.held and run_floor(loose_arm, Settings()) is None  # spec 0.5: held as a fixed arm


def test_matrix_to_quat_undoes_quat_to_matrix():
    rng = np.random.default_rng(0)
    quats = rng.normal(size=(200, 4))
    for q in [*quats / np.linalg.norm(quats, axis=1)[:, None], (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)]:
        r = quat_to_matrix(q)
        assert quat_to_matrix(matrix_to_quat(r)) == pytest.approx(r, abs=1e-12)


def test_lowest_collider_of_a_wheel():
    wheel = Body(
        path="/w", name="w", pose=np.eye(4), world=np.eye(4), mass=1.0, com=np.zeros(3),
        cylinders=(Cylinder("tyre", np.zeros(3), np.array([0.0, 1.0, 0.0]), 0.05, 0.02),),
    )  # fmt: skip
    assert lowest_collider(wheel, np.eye(3), np.array([0, 0, 0.05])) == pytest.approx(0.0)
    on_its_side = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)  # the axis turned to +Z
    assert lowest_collider(wheel, on_its_side, np.array([0, 0, 0.05])) == pytest.approx(0.04)
    bare = Body(path="/b", name="b", pose=np.eye(4), world=np.eye(4), mass=1.0, com=np.zeros(3))
    assert lowest_collider(bare, np.eye(3), np.zeros(3)) == math.inf


def test_lowest_collider_of_a_ball():
    caster = Body(
        path="/c", name="c", pose=np.eye(4), world=np.eye(4), mass=0.1, com=np.zeros(3),
        spheres=(Sphere("ball", np.array([0.1, 0.0, 0.0]), 0.02),),
    )  # fmt: skip
    assert lowest_collider(caster, np.eye(3), np.array([0, 0, 0.02])) == pytest.approx(0.0)
    turned = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)  # the off-centre ball swings below the origin
    assert lowest_collider(caster, turned, np.array([0, 0, 0.02])) == pytest.approx(-0.1)


def test_the_floor_follows_the_rotation_in_the_file(arm):
    """A body turned in the file is measured turned. The bar pointing down reaches z = -0.15."""
    bar = arm.bodies["/unit_arm/arm"]
    pose = bar.pose.copy()
    pose[:3, :3] = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)
    turned = Body(path=bar.path, name=bar.name, pose=pose, world=pose, mass=bar.mass, com=bar.com, hulls=bar.hulls)
    assert floor_height([turned]) == pytest.approx(-0.151)
