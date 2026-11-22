# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""proofmass-check inspect: what the reader reads and the expected plan, without an engine."""

import json
import math

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
