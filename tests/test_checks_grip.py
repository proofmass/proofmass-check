# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import dataclasses

import numpy as np
import pytest
from fake_engine import IdealEngine, IdealGrip

from proofmass_check.checks.grip import choose_site, closing_targets, grip_and_shake, grip_box, gripped
from proofmass_check.engines.base import GripOutcome
from proofmass_check.rules import Settings

SETTINGS = Settings()


def run_grip(asset, trial=None):
    """GRIP and SHAKE with the ideal grip, or with trial(scene, mass, direction, shake) instead of its trial."""

    class Engine(IdealEngine):
        def grip_scene(self, setup):
            scene = IdealGrip(setup)
            if trial:
                scene.trial = lambda mass, direction, shake: trial(scene, mass, direction, shake)
            self.scene = scene
            return scene

    engine = Engine()
    engine.open(asset, floor=0.0)
    (site,) = asset.sites
    grip, shake = grip_and_shake(engine, asset, site, SETTINGS)
    return grip, shake, engine.scene


def test_the_finger_targets_and_the_box(gripper):
    (site,) = gripper.sites
    assert closing_targets(gripper, site) == {
        "finger_l_joint": pytest.approx(0.025),
        "finger_r_joint": pytest.approx(-0.025),
    }
    box = grip_box(site)
    assert box.size == pytest.approx((0.042, 0.02, 0.02))
    assert np.linalg.det(box.rotation) == pytest.approx(1.0)


def test_the_load_rises_to_the_first_slip(gripper):
    def trial(scene, mass, direction, shake):
        IdealGrip.trial(scene, mass, direction, shake)
        closed = {name: limit / 2 for name, limit in scene.setup.close.items()}
        return GripOutcome(np.asarray(direction) * (0.001 if mass <= 2.0 else 0.2), closed, finite=True)

    grip, shake, scene = run_grip(gripper, trial)
    assert grip.verdict == "PASS"
    assert grip.detail == (
        "site grasp, payload 1 kg: out of the fingers holds 2 kg (0.25 kg slid 1.0 mm, 0.5 kg slid 1.0 mm, "
        "0.85 kg slid 1.0 mm, 1 kg slid 1.0 mm, 1.5 kg slid 1.0 mm, 2 kg slid 1.0 mm); along the grip line holds "
        "2 kg (0.25 kg slid 1.0 mm, 0.5 kg slid 1.0 mm, 0.85 kg slid 1.0 mm, 1 kg slid 1.0 mm, 1.5 kg slid 1.0 mm, "
        "2 kg slid 1.0 mm)"
    )
    assert shake.verdict == "PASS" and shake.detail == "0.85 kg at 2 Hz: slid 1.0 mm"
    assert scene.trials[0] == (0.25, (0.0, 0.0, 1.0), False)  # out of the fingers: along the approach direction
    assert scene.trials[6] == (0.25, (0.0, 1.0, 0.0), False)
    assert scene.trials[-1] == (0.85, (0.0, 0.0, 1.0), True)


def test_a_gripper_that_misses_or_drops_the_box(gripper):
    def misses(scene, mass, direction, shake):  # the fingers close to their limits: past the box
        return GripOutcome(np.zeros(3), dict(scene.setup.close), finite=True)

    grip, shake, _ = run_grip(gripper, misses)
    assert grip.verdict == "FAIL" and "0.25 kg slid 0.0 mm NOT GRIPPED" in grip.detail
    assert shake.detail == "0.85 kg at 2 Hz: slid 0.0 mm NOT GRIPPED"

    def drops(scene, mass, direction, shake):
        closed = {name: limit / 2 for name, limit in scene.setup.close.items()}
        return GripOutcome(np.asarray(direction) * (0.2 if mass > 0.5 else 0.0), closed, finite=True)

    grip, _, _ = run_grip(gripper, drops)
    assert grip.verdict == "FAIL" and "out of the fingers holds 0.5 kg" in grip.detail
    assert "0.85 kg the box is lost SLIP" in grip.detail


def test_drift_with_the_fingers_is_not_a_slip(gripper):
    """Two fingers that both push with their force limit carry the box along the closing axis."""

    def drifts(scene, mass, direction, shake):
        closed = {name: limit / 2 for name, limit in scene.setup.close.items()}
        return GripOutcome(np.array([0.009, 0.0, 0.001]), closed, finite=True)

    grip, _, _ = run_grip(gripper, drifts)
    assert grip.verdict == "PASS"
    assert "0.25 kg slid 1.0 mm, drifted 9.0 mm with the fingers" in grip.detail


def test_choose_site(gripper):
    (site,) = gripper.sites
    no_payload = dataclasses.replace(site, name="a", payload=None)
    second = dataclasses.replace(site, name="b")
    asset = dataclasses.replace(gripper, sites=(no_payload, site, second))
    found, notes = choose_site(asset)
    assert found is site
    assert notes == [
        "gripper site a: no gripper_maxPayload, so GRIP does not test it",
        "gripper site b: GRIP tests one site, grasp, so GRIP does not test it",
    ]
    free = dataclasses.replace(gripper, joints=tuple(j for j in gripper.joints if j.kind != "fixed"))
    assert free.held and choose_site(free)[0] is site  # spec 0.5: the checks hold a free gripper with position drives
    undriven = dataclasses.replace(free, joints=tuple(dataclasses.replace(j, drive=None) for j in free.joints))
    assert choose_site(undriven) == (
        None,
        ["gripper site grasp: the gripper is not fixed to the world, so GRIP does not test it"],
    )


def test_gripped(gripper):
    fingers = [gripper.joint("finger_l_joint"), gripper.joint("finger_r_joint")]
    targets = {"finger_l_joint": 0.025, "finger_r_joint": -0.025}
    assert gripped(fingers, {"finger_l_joint": 0.009, "finger_r_joint": -0.009}, targets, SETTINGS)
    # carried onto one finger's limit: the other finger still holds the box against it
    assert gripped(fingers, {"finger_l_joint": 0.0245, "finger_r_joint": -0.0005}, targets, SETTINGS)
    # both at their limits: closed past the box
    assert not gripped(fingers, {"finger_l_joint": 0.0245, "finger_r_joint": -0.0245}, targets, SETTINGS)
