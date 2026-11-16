# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Small test assets, built in code so that every number in the tests can be traced to a line here.

All assets are Z-up, in metres.
"""

from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, Vt


def new_stage(path: Path, name: str) -> Usd.Stage:
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, f"/{name}").GetPrim())
    return stage


def body(stage, path, position, mass, com=None) -> Usd.Prim:
    xform = UsdGeom.Xform.Define(stage, path)
    xform.AddTranslateOp().Set(Gf.Vec3d(*position))
    prim = xform.GetPrim()
    UsdPhysics.RigidBodyAPI.Apply(prim)
    api = UsdPhysics.MassAPI.Apply(prim)
    api.CreateMassAttr(mass)
    if com is not None:
        api.CreateCenterOfMassAttr(Gf.Vec3f(*com))
    return prim


def box_collider(stage, path, centre, half) -> None:
    """A box collider: a Cube of size 2, moved to centre and scaled to the half sizes."""
    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(2.0)
    cube.AddTranslateOp().Set(Gf.Vec3d(*centre))
    cube.AddScaleOp().Set(Gf.Vec3f(*half))
    UsdPhysics.CollisionAPI.Apply(cube.GetPrim())


def fix_to_world(stage, path, target) -> None:
    UsdPhysics.FixedJoint.Define(stage, path).CreateBody1Rel().SetTargets([target])


def drive(joint_prim, dof, stiffness, damping, max_force=None) -> None:
    api = UsdPhysics.DriveAPI.Apply(joint_prim, dof)
    api.CreateStiffnessAttr(stiffness)
    api.CreateDampingAttr(damping)
    if max_force is not None:
        api.CreateMaxForceAttr(max_force)


def joint(stage, cls, path, body0, body1, pos0, axis, lower=None, upper=None):
    """A revolute or prismatic joint whose frame sits at body1's origin."""
    j = cls.Define(stage, path)
    j.CreateBody0Rel().SetTargets([body0])
    j.CreateBody1Rel().SetTargets([body1])
    j.CreateLocalPos0Attr(Gf.Vec3f(*pos0))
    j.CreateLocalPos1Attr(Gf.Vec3f(0, 0, 0))
    j.CreateAxisAttr(axis)
    if lower is not None:
        j.CreateLowerLimitAttr(lower)
        j.CreateUpperLimitAttr(upper)
    return j.GetPrim()


def prop(path: Path) -> Path:
    """A 2 kg box, 0.2 m on each side, standing on z = 0."""
    stage = new_stage(path, "unit_box")
    body(stage, "/unit_box/box", (0, 0, 0.1), 2.0)
    box_collider(stage, "/unit_box/box/collider", (0, 0, 0), (0.1, 0.1, 0.1))
    stage.Save()
    return path


def arm(path: Path) -> Path:
    """A base fixed to the world, and a 0.4 m bar on a hinge about Y, 0.25 m up.

    base: 8 kg, a 0.2 m box from z = 0 to 0.2.
    arm: 1.44 kg, centre of mass 0.2 m out along X, 0.06 m thick.
    arm_joint: -30 to 30 deg, a position drive of 100 N m/deg and 2 N m s/deg, at most 90 deg/s.
    """
    stage = new_stage(path, "unit_arm")
    UsdPhysics.ArticulationRootAPI.Apply(stage.GetDefaultPrim())
    body(stage, "/unit_arm/base", (0, 0, 0), 8.0)
    box_collider(stage, "/unit_arm/base/collider", (0, 0, 0.1), (0.1, 0.1, 0.1))
    body(stage, "/unit_arm/arm", (0, 0, 0.25), 1.44, com=(0.2, 0, 0))
    box_collider(stage, "/unit_arm/arm/collider", (0.2, 0, 0), (0.2, 0.03, 0.03))
    fix_to_world(stage, "/unit_arm/root_joint", "/unit_arm/base")
    hinge = joint(
        stage, UsdPhysics.RevoluteJoint, "/unit_arm/arm_joint", "/unit_arm/base", "/unit_arm/arm", (0, 0, 0.25), "Y",
        -30.0, 30.0,
    )  # fmt: skip
    drive(hinge, "angular", 100.0, 2.0, 50.0)
    hinge.CreateAttribute("physxJoint:maxJointVelocity", Sdf.ValueTypeNames.Float).Set(90.0)
    stage.Save()
    return path


def tooled_arm(path: Path) -> Path:
    """The arm with a 0.1 kg tool fixed to its tip: a fixed joint after the last moving joint.

    tool: a 0.02 m box from x = 0.4 to 0.42, thinner than the arm, so at 30 deg it stays above the floor.
    """
    stage = Usd.Stage.Open(str(arm(path)))
    body(stage, "/unit_arm/tool", (0.4, 0, 0.25), 0.1)
    box_collider(stage, "/unit_arm/tool/collider", (0.01, 0, 0), (0.01, 0.01, 0.01))
    fixed = UsdPhysics.FixedJoint.Define(stage, "/unit_arm/tool_joint")
    fixed.CreateBody0Rel().SetTargets(["/unit_arm/arm"])
    fixed.CreateBody1Rel().SetTargets(["/unit_arm/tool"])
    fixed.CreateLocalPos0Attr(Gf.Vec3f(0.4, 0, 0))
    fixed.CreateLocalPos1Attr(Gf.Vec3f(0, 0, 0))
    stage.Save()
    return path


def gripper(path: Path) -> Path:
    """A hand fixed to the world with two fingers that close along X on a site 0.08 m up.

    The site allows 0.06 m opening and 1 kg payload. Its grip line is 0.02 m long, along Y.
    finger_l starts at x = -0.03 and closes to 0.025; finger_r starts at x = 0.03 and closes to -0.025.
    """
    stage = new_stage(path, "unit_gripper")
    UsdPhysics.ArticulationRootAPI.Apply(stage.GetDefaultPrim())
    body(stage, "/unit_gripper/hand", (0, 0, 0), 0.5)
    box_collider(stage, "/unit_gripper/hand/collider", (0, 0, 0), (0.05, 0.02, 0.01))
    fix_to_world(stage, "/unit_gripper/root_joint", "/unit_gripper/hand")
    site = UsdGeom.Xform.Define(stage, "/unit_gripper/hand/grasp")
    site.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0.08))
    site.GetPrim().CreateAttribute("gripper_maxOpening", Sdf.ValueTypeNames.Float).Set(0.06)
    site.GetPrim().CreateAttribute("gripper_maxPayload", Sdf.ValueTypeNames.Float).Set(1.0)
    for name, points in (
        ("gripper_forward_axis", [(0, 0, 0), (0, 0, 0.05)]),
        ("gripper_grip_line", [(0, -0.01, 0), (0, 0.01, 0)]),
    ):
        UsdGeom.BasisCurves.Define(stage, f"/unit_gripper/hand/grasp/{name}").CreatePointsAttr(points)
    for side, x, lower, upper in (("l", -0.03, 0.0, 0.025), ("r", 0.03, -0.025, 0.0)):
        finger = f"/unit_gripper/finger_{side}"
        body(stage, finger, (x, 0, 0.08), 0.05)
        box_collider(stage, f"{finger}/collider", (0, 0, 0), (0.005, 0.01, 0.01))
        slide = joint(
            stage, UsdPhysics.PrismaticJoint, f"/unit_gripper/finger_{side}_joint", "/unit_gripper/hand", finger,
            (x, 0, 0.08), "X", lower, upper,
        )  # fmt: skip
        drive(slide, "linear", 1000.0, 10.0, 20.0)
    stage.Save()
    return path


def mimic_gripper(path: Path) -> Path:
    """The gripper, half closed in the file, with finger_l a PhysX mimic follower of finger_r.

    Each finger rests 0.01 m toward the centre: finger_l at joint position 0.01, finger_r at -0.01.
    finger_l has no drive: PhysX holds finger_l + 1 x finger_r = 0.
    """
    stage = Usd.Stage.Open(str(gripper(path)))
    for side, rest in (("l", 0.01), ("r", -0.01)):
        finger = stage.GetPrimAtPath(f"/unit_gripper/finger_{side}")
        start = finger.GetAttribute("xformOp:translate").Get()
        finger.GetAttribute("xformOp:translate").Set(start + Gf.Vec3d(rest, 0, 0))
        slide = stage.GetPrimAtPath(f"/unit_gripper/finger_{side}_joint")
        slide.AddAppliedSchema("PhysicsJointStateAPI:linear")
        slide.CreateAttribute("state:linear:physics:position", Sdf.ValueTypeNames.Float).Set(rest)
    follower = stage.GetPrimAtPath("/unit_gripper/finger_l_joint")
    follower.RemoveAPI(UsdPhysics.DriveAPI, "linear")
    follower.AddAppliedSchema("PhysxMimicJointAPI:rotX")
    follower.CreateAttribute("physxMimicJoint:rotX:gearing", Sdf.ValueTypeNames.Float).Set(1.0)
    follower.CreateAttribute("physxMimicJoint:rotX:offset", Sdf.ValueTypeNames.Float).Set(0.0)
    follower.CreateRelationship("physxMimicJoint:rotX:referenceJoint").SetTargets(["/unit_gripper/finger_r_joint"])
    stage.Save()
    return path


def cabinet(path: Path) -> Path:
    """A cabinet fixed to the world with a drawer and a door, both without drives.

    frame: 10 kg, only a back panel behind the drawer.
    drawer: 2 kg, slides 0 to 0.4 m along X, with 20 N s/m of damping and no stiffness (a closer).
    Without damping it would bounce between its limits in Newton, whose default joint limits are
    soft springs, and never come to rest at a limit.
    door: 3 kg, its centre of mass 0.25 m from a vertical hinge, turns 0 to 90 deg.
    """
    stage = new_stage(path, "unit_cabinet")
    UsdPhysics.ArticulationRootAPI.Apply(stage.GetDefaultPrim())
    body(stage, "/unit_cabinet/frame", (0, 0, 0), 10.0)
    box_collider(stage, "/unit_cabinet/frame/collider", (-0.32, 0, 0.3), (0.02, 0.3, 0.3))
    fix_to_world(stage, "/unit_cabinet/root_joint", "/unit_cabinet/frame")
    body(stage, "/unit_cabinet/drawer", (0, 0, 0.1), 2.0)
    box_collider(stage, "/unit_cabinet/drawer/collider", (0, 0, 0), (0.25, 0.25, 0.05))
    slide = joint(
        stage, UsdPhysics.PrismaticJoint, "/unit_cabinet/drawer_joint", "/unit_cabinet/frame", "/unit_cabinet/drawer",
        (0, 0, 0.1), "X", 0.0, 0.4,
    )  # fmt: skip
    drive(slide, "linear", 0.0, 20.0)
    body(stage, "/unit_cabinet/door", (0.3, -0.25, 0.4), 3.0, com=(0, 0.25, 0))
    box_collider(stage, "/unit_cabinet/door/collider", (0, 0.25, 0), (0.01, 0.25, 0.2))
    joint(
        stage, UsdPhysics.RevoluteJoint, "/unit_cabinet/door_joint", "/unit_cabinet/frame", "/unit_cabinet/door",
        (0.3, -0.25, 0.4), "Z", 0.0, 90.0,
    )  # fmt: skip
    stage.Save()
    return path


def rover(path: Path) -> Path:
    """A differential-drive rover described by SimReady_Metadata.mobile.

    base: 4 kg, a 0.4 m box with its bottom 0.05 m up. Two driven wheels of radius 0.1 m at
    y = +-0.2 m on continuous joints about Y, with velocity drives. The driven axle is at x = y = 0.
    """
    stage = new_stage(path, "rover")
    UsdPhysics.ArticulationRootAPI.Apply(stage.GetDefaultPrim())
    body(stage, "/rover/base", (0, 0, 0.1), 4.0)
    box_collider(stage, "/rover/base/collider", (0, 0, 0.05), (0.2, 0.15, 0.05))
    wheels = {}
    for side, y in (("left", 0.2), ("right", -0.2)):
        wheel = f"/rover/{side}_wheel"
        body(stage, wheel, (0, y, 0.1), 0.5)
        cylinder = UsdGeom.Cylinder.Define(stage, f"{wheel}/collider")
        cylinder.CreateAxisAttr("Y")
        cylinder.CreateRadiusAttr(0.1)
        cylinder.CreateHeightAttr(0.04)
        UsdPhysics.CollisionAPI.Apply(cylinder.GetPrim())
        hinge = joint(
            stage, UsdPhysics.RevoluteJoint, f"/rover/{side}_wheel_joint", "/rover/base", wheel, (0, y, 0), "Y"
        )
        drive(hinge, "angular", 0.0, 1.0)
        wheels[f"{side}_wheel_joint"] = {
            "side": side,
            "driven": True,
            "radius": 0.1,
            "spin": 1,
            "center": Vt.DoubleArray([0.0, y, 0.1]),
        }
    stage.GetRootLayer().customLayerData = {
        "SimReady_Metadata": {
            "mobile": {
                "drive": "differential",
                "radius": 0.1,
                "track": 0.4,
                "axle_center": Vt.DoubleArray([0.0, 0.0]),
                "wheels": wheels,
                "steering": {},
            }
        }
    }
    stage.Save()
    return path
