# SPDX-FileCopyrightText: 2026 The proofmass-check authors
# SPDX-License-Identifier: Apache-2.0
import dataclasses

import numpy as np
import pytest
from fake_engine import IdealEngine

from proofmass_check.checks.drop import drop, resting
from proofmass_check.checks.load import load, with_engine_masses
from proofmass_check.engines.base import DropOutcome, LoadOutcome
from proofmass_check.geometry import floor_height


def test_load_compares_joints_and_mass(arm):
    masses = {"/unit_arm/base": 8.0, "/unit_arm/arm": 1.44}
    result = load(arm, LoadOutcome(masses=masses))
    assert result.verdict == "PASS"
    assert result.detail == "1 joints (1 position, 0 velocity drives), mass in the engine 9.44 kg, in the USD 9.44 kg"
    heavier = load(arm, LoadOutcome(masses={**masses, "/unit_arm/arm": 1.6}))
    assert heavier.verdict == "FAIL"  # 0.16 kg more is 1.7 %
    missing = load(arm, LoadOutcome(missing=("arm_joint",), unknown=("extra",), masses=masses))
    assert missing.verdict == "FAIL"
    assert missing.detail.endswith(
        "; joints the engine did not build: ['arm_joint']; engine joints that are not in the USD: ['extra']"
    )


def test_masses_the_usd_leaves_to_the_engine(arm):
    base = dataclasses.replace(arm.bodies["/unit_arm/base"], mass=None)
    asset = dataclasses.replace(arm, bodies={**arm.bodies, "/unit_arm/base": base})
    outcome = LoadOutcome(masses={"/unit_arm/base": 7.5, "/unit_arm/arm": 1.44}, coms={"/unit_arm/base": np.ones(3)})
    assert "(the USD gives it for 1 of 2 bodies)" in load(asset, outcome).detail
    filled = with_engine_masses(asset, outcome)
    assert filled.bodies["/unit_arm/base"].mass == 7.5
    assert filled.bodies["/unit_arm/base"].com == pytest.approx([1, 1, 1])
    assert filled.bodies["/unit_arm/arm"] is asset.bodies["/unit_arm/arm"]  # the USD's own mass stays


def test_resting():
    assert resting(True, 0.01, -0.001)
    assert not resting(True, 0.01, 0.005)  # 5 mm above the floor
    assert not resting(True, 0.2, 0.0)
    assert not resting(False, 0.0, 0.0)


def test_drop(prop):
    floor = floor_height(prop.bodies.values())
    engine = IdealEngine()
    engine.open(prop, floor)
    result = drop(engine, prop, floor)
    assert result.verdict == "PASS"
    assert result.detail == "final speed 0.0000 m/s, lowest collider +0.00 mm from the floor, tilted 0 deg"

    class Sinks(IdealEngine):
        def drop(self, height, seconds):
            outcome = super().drop(height, seconds)
            poses = {path: (r, t - [0.0, 0.0, 0.5]) for path, (r, t) in outcome.poses.items()}
            return DropOutcome(poses=poses, root_speed=2.0, finite=True)

    engine = Sinks()
    engine.open(prop, floor)
    sunk = drop(engine, prop, floor)
    assert sunk.verdict == "FAIL" and sunk.detail.startswith("final speed 2.0000 m/s, lowest collider -500.00 mm")
