# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import math

import numpy as np
import pytest
import usd_assets
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from proofmass_check.usd_reader import AssetError, choose_variants, read_asset


def test_the_arm_in_si_units(arm):
    assert arm.name == "unit_arm" and arm.articulated
    assert {b.name: b.mass for b in arm.bodies.values()} == {"base": 8.0, "arm": pytest.approx(1.44)}
    assert [(j.name, j.kind) for j in arm.joints] == [("root_joint", "fixed"), ("arm_joint", "revolute")]
    hinge = arm.joint("arm_joint")
    assert (hinge.lower, hinge.upper) == (pytest.approx(math.radians(-30)), pytest.approx(math.radians(30)))
    assert hinge.max_speed == pytest.approx(math.radians(90))
    # the USD gives the drive per degree; the reader gives it per radian
    assert hinge.drive.stiffness == pytest.approx(100.0 * 180 / math.pi)
    assert hinge.drive.damping == pytest.approx(2.0 * 180 / math.pi)
    assert hinge.drive.max_force == 50.0 and hinge.drive_kind == "position"
    assert hinge.pivot == pytest.approx([0, 0, 0.25]) and hinge.direction == pytest.approx([0, 1, 0])
    assert arm.world_fixed == ("root_joint",) and arm.root_body == "/unit_arm/base"


def test_an_mjc_actuator_is_the_drive_of_a_joint_without_one(actuated_arm, tmp_path):
    drive = actuated_arm.joint("arm_joint").drive
    assert (drive.stiffness, drive.damping, drive.max_force) == (5730.0, 115.0, 50.0)  # MuJoCo gives it per radian
    assert drive.kind == "position"

    def drive_with(name, change):
        stage = Usd.Stage.Open(str(usd_assets.actuated_arm(tmp_path / f"{name}.usda")))
        change(stage, stage.GetPrimAtPath("/unit_arm/arm_actuator"))
        stage.Save()
        return read_asset(tmp_path / f"{name}.usda").joint("arm_joint").drive

    velocity = drive_with("velocity", lambda stage, prim: prim.GetAttribute("mjc:biasPrm").Set([0, 0, -5730.0]))
    assert (velocity.stiffness, velocity.damping, velocity.kind) == (0.0, 5730.0, "velocity")
    # a motor, an actuator with dynamics and one that is not active are not drives
    assert drive_with("motor", lambda stage, prim: prim.GetAttribute("mjc:biasType").Set("none")) is None
    assert drive_with("spring", lambda stage, prim: prim.GetAttribute("mjc:biasPrm").Set([0, -100.0, 0])) is None
    filtered = drive_with(
        "filtered", lambda stage, prim: prim.CreateAttribute("mjc:dynType", Sdf.ValueTypeNames.Token).Set("filter")
    )
    assert filtered is None
    assert drive_with("inactive", lambda stage, prim: prim.SetActive(False)) is None
    # PhysicsDriveAPI comes first
    both = drive_with(
        "both", lambda stage, prim: usd_assets.drive(stage.GetPrimAtPath("/unit_arm/arm_joint"), "angular", 100.0, 2.0)
    )
    assert both.stiffness == pytest.approx(100.0 * 180 / math.pi)


def test_the_gripper_site(gripper):
    (site,) = gripper.sites
    assert site.body == "/unit_gripper/hand"
    assert site.centre == pytest.approx([0, 0, 0.08])
    assert (site.forward, site.line) == (pytest.approx([0, 0, 1]), pytest.approx([0, 1, 0]))
    assert site.closing == pytest.approx([-1, 0, 0])  # forward x line
    assert (site.opening, site.pad, site.payload) == (pytest.approx(0.06), pytest.approx(0.02), 1.0)


def test_a_package_from_another_maker(tmp_path):
    """Polygons, a mass left to the engine, a joint that targets a mesh inside a body, a body nested
    in a body, a rest position, a speed limit in a variant, a PhysX mimic joint and a disabled joint."""
    path = tmp_path / "other.usda"
    stage = Usd.Stage.CreateNew(str(path))
    root = UsdGeom.Xform.Define(stage, "/other").GetPrim()
    stage.SetDefaultPrim(root)
    UsdPhysics.RigidBodyAPI.Apply(UsdGeom.Xform.Define(stage, "/other/base").GetPrim())  # no MassAPI
    for b in ("/other/base", "/other/base/link"):
        hull = UsdGeom.Mesh.Define(stage, f"{b}/hull")
        hull.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1)])
        hull.CreateFaceVertexCountsAttr([4, 3])  # a quad and a triangle
        hull.CreateFaceVertexIndicesAttr([0, 1, 2, 3, 0, 1, 4])
        UsdPhysics.CollisionAPI.Apply(hull.GetPrim())
    link = stage.GetPrimAtPath("/other/base/link")
    UsdPhysics.RigidBodyAPI.Apply(link)
    UsdPhysics.MassAPI.Apply(link).CreateMassAttr(2.0)
    j = UsdPhysics.RevoluteJoint.Define(stage, "/other/hinge")
    j.CreateBody0Rel().SetTargets(["/other/base/hull"])
    j.CreateBody1Rel().SetTargets(["/other/base/link"])
    j.CreateAxisAttr("Z")
    j.CreateLowerLimitAttr(-10.0)
    j.CreateUpperLimitAttr(10.0)
    j.GetPrim().CreateAttribute("state:angular:physics:position", Sdf.ValueTypeNames.Float).Set(5.0)
    j.GetPrim().CreateAttribute("physxMimicJoint:rotZ:gearing", Sdf.ValueTypeNames.Float).Set(1.0)
    j.GetPrim().CreateRelationship("physxMimicJoint:rotZ:referenceJoint").SetTargets(["/other/off"])
    UsdPhysics.FixedJoint.Define(stage, "/other/off").CreateJointEnabledAttr(False)
    sets = root.GetVariantSets().AddVariantSet("PhysX")
    for v in ("Enabled", "Disabled"):
        sets.AddVariant(v)
    sets.SetVariantSelection("Enabled")
    with sets.GetVariantEditContext():
        stage.OverridePrim("/other/hinge").CreateAttribute("physxJoint:maxJointVelocity", Sdf.ValueTypeNames.Float).Set(
            90.0
        )
    sets.SetVariantSelection("Disabled")
    stage.Save()

    asset = read_asset(path)
    assert asset.bodies["/other/base"].mass is None and asset.bodies["/other/base/link"].mass == 2.0
    assert [h.name for h in asset.bodies["/other/base"].hulls] == ["hull"]  # the link's hull is the link's
    assert asset.bodies["/other/base"].hulls[0].triangles.tolist() == [[0, 1, 2], [0, 2, 3], [0, 1, 4]]
    (hinge,) = asset.joints  # the disabled joint is left out
    assert (hinge.body0, hinge.body1) == ("/other/base", "/other/base/link")
    assert (hinge.rest, hinge.max_speed) == (pytest.approx(math.radians(5)), math.inf)
    assert (hinge.mimic.leader, hinge.mimic.ratio) == ("off", -1.0)  # PhysX: follower + gearing x leader = 0
    assert read_asset(path, {"PhysX": "Enabled"}).joints[0].max_speed == pytest.approx(math.radians(90))
    assert choose_variants(path, ["Newton", "PhysX"], []) == {"PhysX": "Enabled"}
    assert choose_variants(path, ["PhysX"], ["PhysX=Disabled"]) == {"PhysX": "Disabled"}
    with pytest.raises(AssetError, match="no variant 'PhysX=Off'"):
        choose_variants(path, [], ["PhysX=Off"])


def test_a_box_collider_with_scale(tmp_path):
    stage = usd_assets.new_stage(tmp_path / "box.usda", "root")
    usd_assets.body(stage, "/root/door", (0, 0, 1), 2.0)
    usd_assets.box_collider(stage, "/root/door/C001", (0, 0, 0), (0.3, 0.02, 0.2))
    stage.Save()
    (hull,) = read_asset(tmp_path / "box.usda").bodies["/root/door"].hulls
    assert hull.name == "C001" and hull.points.shape == (8, 3) and hull.triangles.shape == (12, 3)
    assert hull.points.min(axis=0) == pytest.approx([-0.3, -0.02, -0.2])
    assert hull.points.max(axis=0) == pytest.approx([0.3, 0.02, 0.2])


def test_a_scaled_body_keeps_its_scale_in_the_colliders(tmp_path):
    """Engines report a body's pose without scale, so the scale goes into the collider points."""
    stage = usd_assets.new_stage(tmp_path / "scaled.usda", "root")
    prim = usd_assets.body(stage, "/root/crate", (0, 0, 0.5), 1.0, com=(0, 0, 0.1))
    UsdGeom.Xform(prim).AddScaleOp().Set(Gf.Vec3f(2, 2, 2))
    usd_assets.box_collider(stage, "/root/crate/collider", (0, 0, 0), (0.1, 0.1, 0.1))
    stage.Save()
    crate = read_asset(tmp_path / "scaled.usda").bodies["/root/crate"]
    assert crate.pose[:3, :3] == pytest.approx(np.eye(3)) and crate.pose[:3, 3] == pytest.approx([0, 0, 0.5])
    assert crate.hulls[0].points.max(axis=0) == pytest.approx([0.2, 0.2, 0.2])
    assert crate.com == pytest.approx([0, 0, 0.2])


def test_d6_joint_axes(tmp_path):
    """Each free axis becomes a joint. A locked axis (low above high) is left out."""
    stage = usd_assets.new_stage(tmp_path / "d6.usda", "r")
    for name in ("a", "b"):
        UsdPhysics.RigidBodyAPI.Apply(UsdGeom.Xform.Define(stage, f"/r/{name}").GetPrim())
    handle = UsdPhysics.Joint.Define(stage, "/r/handle")
    handle.CreateBody0Rel().SetTargets(["/r/a"])
    handle.CreateBody1Rel().SetTargets(["/r/b"])
    prim = handle.GetPrim()
    for axis, low, high in (("transX", 1, -1), ("transY", 1, -1), ("transZ", 1, -1), ("rotZ", 1, -1),
                            ("rotX", -45, 45), ("rotY", 0, 28.6)):  # fmt: skip
        limit = UsdPhysics.LimitAPI.Apply(prim, axis)
        limit.CreateLowAttr(low)
        limit.CreateHighAttr(high)
    prim.CreateAttribute("mjcf:rotX:name", Sdf.ValueTypeNames.String).Set("handle_temp_joint")
    UsdPhysics.DriveAPI.Apply(prim, "rotY").CreateStiffnessAttr(2.0)
    stage.Save()
    asset = read_asset(tmp_path / "d6.usda")
    assert [(j.name, j.kind, j.axis, j.d6) for j in asset.joints] == [
        ("handle_temp_joint", "revolute", "X", "handle"),
        ("handle:rotY", "revolute", "Y", "handle"),
    ]
    rot_y = asset.joint("handle:rotY")
    assert rot_y.upper == pytest.approx(math.radians(28.6)) and rot_y.drive.stiffness == pytest.approx(
        2.0 * 180 / math.pi
    )
    assert asset.joint("handle_temp_joint").drive is None


def test_files_that_are_not_assets(tmp_path):
    empty = Usd.Stage.CreateNew(str(tmp_path / "empty.usda"))
    empty.Save()
    with pytest.raises(AssetError, match="no default prim"):
        read_asset(tmp_path / "empty.usda")
    stage = usd_assets.new_stage(tmp_path / "visual.usda", "visual")
    UsdGeom.Cube.Define(stage, "/visual/cube")
    stage.Save()
    with pytest.raises(AssetError, match="no rigid body"):
        read_asset(tmp_path / "visual.usda")
