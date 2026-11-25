# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""proofmass-check inspect: what the reader reads and the expected plan, without an engine."""

import json
import math

import numpy as np
import pytest
import usd_assets

from proofmass_check import cli
from proofmass_check.engines.capabilities import supported
from proofmass_check.inspection import inspect_asset
from proofmass_check.rules import GRAVITY, Settings


def plan_of(data: dict) -> dict:
    return {p["id"]: (p["runs"], p["reason"]) for p in data["plan"]}


def test_inspect_the_arm(tmp_path):
    data = inspect_asset(usd_assets.arm(tmp_path / "arm.usda"), "physx", [], Settings(), geometry=False)
    json.dumps(data, allow_nan=False)  # strict JSON: no NaN or infinity
    assert data["name"] == "unit_arm" and data["articulated"] and data["world_fixed"] == ["root_joint"]
    plan = plan_of(data)
    assert plan["HOLD"] == (True, None) and plan["SPEED"] == (True, None)
    assert plan["DROP"] == (False, "the asset is fixed to the world by root_joint")
    hinge = next(j for j in data["joints"] if j["name"] == "arm_joint")
    assert hinge["prim"] == "/unit_arm/arm_joint" and hinge["drive_from"] == "PhysicsDriveAPI"
    assert hinge["lower"] == pytest.approx(-math.radians(30)) and hinge["max_speed"] == pytest.approx(math.radians(90))
    # The bar of 1.44 kg has its centre 0.2 m from the horizontal axis.
    assert hinge["carried_mass"] == pytest.approx(1.44) and hinge["lever"] == pytest.approx(0.2)
    assert hinge["gravity_load"] == pytest.approx(1.44 * GRAVITY * 0.2)
    assert hinge["schemas"] == ["PhysicsDriveAPI:angular"]
    assert hinge["attributes"]["physxJoint:maxJointVelocity"] == "90.0"
    assert "hulls" not in data["bodies"][0]


def test_geometry_for_a_3d_view(tmp_path):
    data = inspect_asset(usd_assets.rover(tmp_path / "rover.usda"), "physx", [], Settings(), geometry=True)
    hulls = [h for b in data["bodies"] for h in b["hulls"]]
    cylinders = [c for b in data["bodies"] for c in b["cylinders"]]
    assert hulls and all(len(h["points"]) >= 4 and h["triangles"] for h in hulls)
    assert cylinders and all(c["radius"] > 0 for c in cylinders)
    assert data["wheeled"]["drive"] == "differential" and len(data["bodies"][0]["pose"]) == 4
    assert all(b["spheres"] == [] for b in data["bodies"])  # the rover has no ball: the key is there, empty


def test_the_plan_depends_on_the_engine(tmp_path):
    asset = usd_assets.actuated_arm(tmp_path / "actuated_arm.usda")
    physx = inspect_asset(asset, "physx", [], Settings(), geometry=False)
    newton = inspect_asset(asset, "newton", [], Settings(), geometry=False)
    assert plan_of(physx)["HOLD"] == (False, "no joint has a position drive")  # PhysX reads no MjcActuator
    assert plan_of(newton)["HOLD"] == (True, None)
    assert plan_of(newton)["SPEED"] == (False, "the newton engine cannot run this check on this asset yet")
    hinge = next(j for j in newton["joints"] if j["name"] == "arm_joint")
    assert hinge["drive_from"] == "MjcActuator" and hinge["drive"]["max_force"] == pytest.approx(50.0)


def test_what_each_engine_supports(prop, arm):
    assert supported("physx", prop) == {"LOAD", "DROP", "PASSIVE"}  # no PhysicsArticulationRootAPI
    assert "HOLD" in supported("physx", arm) and "SPEED" in supported("physx", arm)
    assert not {"SPEED", "STAND", "DRIVE", "TURN", "STEER"} & supported("newton", arm)


def test_the_inspect_command(tmp_path, capsys):
    arm = usd_assets.arm(tmp_path / "arm.usda")
    assert cli.main(["inspect", str(arm), "--out", str(tmp_path / "arm.json"), "--geometry"]) == cli.PASSED
    assert json.loads((tmp_path / "arm.json").read_text(encoding="utf-8"))["bodies"][0]["hulls"]
    assert cli.main(["inspect", str(arm), "--no-floor"]) == cli.PASSED
    assert json.loads(capsys.readouterr().out)["floor"] is None
    assert cli.main(["inspect", str(arm), "--variant", "PhysX=On"]) == cli.ERROR
    assert "no variant 'PhysX=On'" in capsys.readouterr().err
    assert cli.main(["inspect", str(tmp_path / "none.usda")]) == cli.ERROR


def test_which_joints_the_checks_test(tmp_path):
    arm = inspect_asset(usd_assets.arm(tmp_path / "arm.usda"), "physx", [], Settings(), geometry=False)
    hinge = next(j for j in arm["joints"] if j["name"] == "arm_joint")
    assert (hinge["driven"], hinge["pushed"], hinge["limited"]) == (True, False, True)
    # The centre of what the hinge carries is 0.2 m from its axis: a 3D view draws the arc of its range there.
    arm_out = np.subtract(hinge["carried_centre"], hinge["pivot"])
    assert np.linalg.norm(np.cross(arm_out, hinge["direction"])) == pytest.approx(0.2)
    cabinet = inspect_asset(usd_assets.cabinet(tmp_path / "cabinet.usda"), "physx", [], Settings(), geometry=False)
    assert {j["name"] for j in cabinet["joints"] if j["pushed"]} == {"drawer_joint", "door_joint"}
    assert not any(j["driven"] for j in cabinet["joints"])


def test_the_grip_box_of_a_gripper_site(tmp_path):
    data = inspect_asset(usd_assets.gripper(tmp_path / "gripper.usda"), "physx", [], Settings(), geometry=False)
    box = data["sites"][0]["grip_box"]
    assert box["size"] == pytest.approx([0.042, 0.02, 0.02])  # 0.7 of the 60 mm opening, and the pad size
    assert box["centre"] == pytest.approx([0.0, 0.0, 0.08]) and np.linalg.det(box["rotation"]) == pytest.approx(1.0)
