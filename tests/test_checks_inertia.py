# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import dataclasses

import numpy as np
import pytest
from fake_engine import IdealEngine

from proofmass_check.checks.inertia import inertia, reference
from proofmass_check.engines.base import LoadOutcome
from proofmass_check.plan import make_plan
from proofmass_check.rules import INERTIA_MAX_RATIO, INERTIA_MIN_RATIO, Settings
from proofmass_check.runner import run_checks

SOLID = 2.0 * (0.2**2 + 0.2**2) / 12  # each moment of the 2 kg box, 0.2 m on each side, as a solid


def with_inertia(asset, moments):
    bodies = {p: dataclasses.replace(b, inertia=np.array(moments, float)) for p, b in asset.bodies.items()}
    return dataclasses.replace(asset, bodies=bodies)


def test_the_reference_is_the_mass_on_the_collider_points(prop):
    """The box's 8 corners, 2 kg, each 0.03 m^2 from the centre squared: 2 * 2 * 0.03. That is three times the
    trace of the solid box."""
    box = prop.bodies["/unit_box/box"]
    assert reference(box) == pytest.approx(0.12, rel=1e-5) and reference(box) == pytest.approx(3 * 3 * SOLID, rel=1e-5)


@pytest.mark.parametrize(
    ("moments", "verdict"),
    [
        ((SOLID, SOLID, SOLID), "PASS"),  # a third of the reference
        ((2e-6, 2e-6, 2e-6), "FAIL"),  # Franka Panda: about 1e-6 kg m^2 for 2 to 3 kg
        ((SOLID * 1e4,) * 3, "FAIL"),  # kg cm^2 written as kg m^2
    ],
)
def test_inertia_against_the_colliders(prop, moments, verdict):
    result = inertia(with_inertia(prop, moments))
    (m,) = result.measurements
    assert result.verdict == verdict and m.ok is (verdict == "PASS") and m.subject == "box" and m.unit == "1"
    assert m.limit == (INERTIA_MIN_RATIO if m.value < 1 else INERTIA_MAX_RATIO)
    assert m.bound == ("min" if m.value < 1 else "max")


def test_no_inertia_in_the_file_is_not_judged(prop):
    assert prop.bodies["/unit_box/box"].inertia is None
    plan = make_plan(prop, "fake", IdealEngine.supported, Settings())
    assert plan.skip["INERTIA"] == "no body has its mass, its inertia (diagonalInertia) and colliders in the USD"


def test_inertia_runs_when_load_fails(arm):
    """It reads the file and runs nothing, so a failed LOAD does not stop it."""

    class DropsAJoint(IdealEngine):
        def load(self):
            return LoadOutcome(missing=("arm_joint",), masses={"/unit_arm/base": 8.0, "/unit_arm/arm": 1.44})

    run = run_checks(DropsAJoint(), with_inertia(arm, (1e-6, 1e-6, 1e-6)), Settings())
    by_id = {r.id: r for r in run.results}
    assert by_id["LOAD"].verdict == "FAIL" and by_id["INERTIA"].verdict == "FAIL" and by_id["HOLD"].verdict == "N/A"
    assert by_id["INERTIA"].detail == "base 6.2e-06 FAIL; arm 2.5e-05 FAIL"  # 3e-6 / 0.48 and 3e-6 / 0.12
