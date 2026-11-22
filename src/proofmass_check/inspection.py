# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""proofmass-check inspect: what the reader reads from an asset, and the plan, without an engine.

docs/gui.md, section 5.3. It shows, before a run, which checks will run and why the others will
not, and the joints, drives and masses they will test. It needs pxr, but no engine: in Isaac Sim's
Python pxr exists only after Isaac Sim starts, so it runs in another Python, with usd-core.

The plan is "expected": two things only a built engine knows. LOAD decides whether the other checks
run. And Newton runs DROP only when it builds a free joint.

All values are in SI units, as in results.json. A value that is not finite is None.
"""

import math
from pathlib import Path

import numpy as np

from proofmass_check import __version__, usd_reader
from proofmass_check.checks import TITLES
from proofmass_check.checks.passive import lever
from proofmass_check.engines.capabilities import CAPABILITIES, supported
from proofmass_check.geometry import floor_height
from proofmass_check.model import Asset, Body, Joint
from proofmass_check.plan import make_plan
from proofmass_check.rules import GRAVITY, SPEC_VERSION, Settings

CYLINDER_SIDES = 16  # a 3D view draws a cylinder collider as a prism with this many sides


def inspect_asset(file: Path, engine: str, requested: list[str], settings: Settings, geometry: bool) -> dict:
    """What the reader reads from the asset and the expected plan, as a dict for JSON."""
    capabilities = CAPABILITIES[engine]
    variants = usd_reader.choose_variants(file, capabilities.variant_sets, requested)
    asset = usd_reader.read_asset(file, variants)
    if capabilities.reads_mjc_actuators:
        asset = asset.with_mjc_drives()
    plan = make_plan(asset, engine, supported(engine, asset), settings)
    prims = usd_reader.authored(file, variants, [j.prim for j in asset.joints])
    return {
        "tool": {"name": "proofmass-check", "version": __version__},
        "spec_version": SPEC_VERSION,
        "engine": engine,
        "file": str(file),
        "name": asset.name,
        "variant_sets": usd_reader.variant_sets(file),
        "variants": dict(variants),
        "floor": _number(floor_height(asset.bodies.values())) if settings.floor else None,
        "articulated": asset.articulated,
        "root_body": asset.root_body,
        "world_fixed": list(asset.world_fixed),
        "plan": [{"id": c, "title": TITLES[c], "runs": plan.runs(c), "reason": plan.skip.get(c)} for c in TITLES],
        "notes": list(plan.notes),
        "bodies": [_body(b, geometry) for b in asset.bodies.values()],
        "joints": [_joint(asset, j, prims.get(j.prim, {})) for j in asset.joints],
        "sites": [_site(s) for s in asset.sites],
        "wheeled": _wheeled(asset),
    }


def _number(value) -> float | None:
    return float(value) if value is not None and math.isfinite(value) else None


def _vector(values) -> list | None:
    return None if values is None else [_number(v) for v in np.asarray(values, float).ravel()]


def _body(body: Body, geometry: bool) -> dict:
    data = {
        "path": body.path,
        "name": body.name,
        "mass": _number(body.mass),  # None: the engine computes it
        "com": _vector(body.com),
        "pose": [_vector(row) for row in body.pose],  # body frame to world, 4x4, for column vectors
        "colliders": len(body.hulls) + len(body.cylinders),
    }
    if geometry:
        data["hulls"] = [
            {"name": h.name, "points": [_vector(p) for p in h.points], "triangles": h.triangles.tolist()}
            for h in body.hulls
        ]
        data["cylinders"] = [
            {"name": c.name, "centre": _vector(c.centre), "axis": _vector(c.axis), "radius": c.radius,
             "height": c.height}
            for c in body.cylinders
        ]  # fmt: skip
    return data


def _joint(asset: Asset, joint: Joint, prim: dict) -> dict:
    drive = joint.drive
    source = None
    if drive is not None:
        source = "MjcActuator" if drive is joint.mjc_drive else "PhysicsDriveAPI"
    return {
        "name": joint.name,
        "prim": joint.prim,
        "kind": joint.kind,
        "usd_type": joint.usd_type,
        "body0": joint.body0,
        "body1": joint.body1,
        "axis": joint.axis,
        "pivot": _vector(joint.pivot),
        "direction": _vector(joint.direction),
        "lower": _number(joint.lower),
        "upper": _number(joint.upper),
        "rest": _number(joint.rest),
        "max_speed": _number(joint.max_speed),
        "drive": None if drive is None else {
            "stiffness": drive.stiffness, "damping": drive.damping, "max_force": _number(drive.max_force)
        },
        "drive_from": source,
        "mimic": None if joint.mimic is None else {"leader": joint.mimic.leader, "ratio": joint.mimic.ratio},
        "d6": joint.d6,
        **_load(asset, joint),
        "schemas": prim.get("schemas", []),
        "attributes": prim.get("attributes", {}),
    }  # fmt: skip


def _load(asset: Asset, joint: Joint) -> dict:
    """The mass a joint carries, the distance of its centre from the axis, and its largest gravity load.

    The gravity load is the term PASSIVE starts its push from (checks/passive.py, base_push), without
    the factor: N m for a revolute joint, N for a prismatic one. It is a number to read next to the
    drive's max force. It decides nothing.
    """
    if not joint.moves or joint.pivot is None or joint.direction is None:
        return {"carried_mass": None, "lever": None, "gravity_load": None}
    try:
        mass, distance = lever(asset, joint)
    except ValueError:  # a mass that only the engine computes
        return {"carried_mass": None, "lever": None, "gravity_load": None}
    axis = joint.direction
    if joint.revolute:
        tilt = float(np.linalg.norm(np.cross(axis, [0.0, 0.0, 1.0])))  # 0 for a vertical axis
        load = mass * GRAVITY * distance * tilt
    else:
        load = mass * GRAVITY * abs(float(axis[2]))
    return {
        "carried_mass": _number(mass),
        "lever": _number(distance) if joint.revolute else None,
        "gravity_load": _number(load),
    }


def _site(site) -> dict:
    return {
        "name": site.name,
        "body": site.body,
        "centre": _vector(site.centre),
        "forward": _vector(site.forward),
        "line": _vector(site.line),
        "closing": _vector(site.closing),
        "opening": _number(site.opening),
        "pad": _number(site.pad),
        "payload": _number(site.payload),
    }


def _wheeled(asset: Asset) -> dict | None:
    base = asset.wheeled
    if base is None:
        return None
    return {
        "drive": base.drive,
        "radius": _number(base.radius),
        "track": _number(base.track),
        "axle_centre": _vector(base.axle_centre),
        "wheels": [
            {
                "name": w.name,
                "side": w.side,
                "driven": w.driven,
                "radius": _number(w.radius),
                "centre": _vector(w.centre),
            }
            for w in base.wheels
        ],
        "steering": [s.name for s in base.steering],
    }
