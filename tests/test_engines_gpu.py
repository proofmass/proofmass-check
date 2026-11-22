# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""A real engine on the small test assets of usd_assets.py. Each asset is built to pass.

These tests need the engine's Python environment with pytest in it, and a GPU for Newton:

    pytest tests/test_engines_gpu.py -m gpu --engine physx
    pytest tests/test_engines_gpu.py -m gpu --engine newton
"""

import math

import pytest

pytestmark = pytest.mark.gpu


@pytest.fixture(scope="module")
def engine(request):
    """One engine for the whole module: Isaac Sim can start only once in a process.

    conftest.py closes it after pytest's summary, because Isaac Sim ends the process when it closes.
    """
    from conftest import ENGINE

    from proofmass_check import engines

    started = engines.create(request.config.getoption("--engine"))
    request.config.stash[ENGINE] = started
    return started


def verdicts(engine, asset):
    from proofmass_check.rules import Settings
    from proofmass_check.runner import run_checks

    run = run_checks(engine, asset, Settings())
    return {r.id: (r.verdict, r.detail) for r in run.results}


def expect(results, check_id, verdict="PASS"):
    assert results[check_id][0] == verdict, f"{check_id}: {results[check_id][1]}"


def test_a_prop_comes_to_rest(engine, prop):
    results = verdicts(engine, prop)
    expect(results, "LOAD")
    expect(results, "DROP")


def test_an_arm_follows_its_drive(engine, arm):
    results = verdicts(engine, arm)
    for check_id in ("LOAD", "HOLD", "TRACK", "LIMIT", "STABLE"):
        expect(results, check_id)
    expect(results, "SPEED", "PASS" if "SPEED" in engine.supported else "N/A")


def test_only_newton_drives_a_joint_from_its_mjc_actuator(engine, actuated_arm):
    results = verdicts(engine, actuated_arm)
    expect(results, "LOAD")
    if engine.reads_mjc_actuators:
        for check_id in ("HOLD", "TRACK", "LIMIT", "STABLE"):
            expect(results, check_id)
    else:  # PhysX: the joint has no drive, so it swings freely, as a door does
        for check_id in ("HOLD", "TRACK", "LIMIT", "STABLE", "SPEED"):
            expect(results, check_id, "N/A")
        expect(results, "PASSIVE")


def test_a_fixed_joint_after_the_last_moving_joint(engine, tooled_arm):
    results = verdicts(engine, tooled_arm)
    for check_id in ("LOAD", "HOLD", "TRACK", "LIMIT", "STABLE"):
        expect(results, check_id)


def test_a_drawer_and_a_door_open(engine, cabinet):
    results = verdicts(engine, cabinet)
    expect(results, "LOAD")
    expect(results, "PASSIVE")


def test_a_gripper_holds_its_payload(engine, gripper):
    results = verdicts(engine, gripper)
    for check_id in ("LOAD", "HOLD", "TRACK", "LIMIT", "GRIP", "SHAKE"):
        expect(results, check_id)


def test_a_reset_puts_a_mimic_follower_at_its_rest_position(engine, mimic_gripper):
    """Isaac Sim alone resets a PhysX mimic follower to 0: the finger would start inside the grip box."""
    if engine.name != "physx":
        pytest.skip("the asset couples its fingers with a PhysX mimic joint")
    engine.open(mimic_gripper, floor=None)
    after_reset = engine.settle({"finger_r_joint": -0.01}, seconds=0.0)
    assert after_reset.positions["finger_l_joint"] == pytest.approx(0.01, abs=1e-5)
    assert after_reset.positions["finger_r_joint"] == pytest.approx(-0.01, abs=1e-5)


def test_the_first_run_is_as_long_as_the_next(engine, arm):
    """The Newton engine records its steps as a CUDA graph in the first run. Recording does not run them."""
    if engine.name != "newton":
        pytest.skip("the fault was in the Newton engine")
    engine.open(arm, floor=None)
    first = engine.settle({"arm_joint": 0.2}, seconds=0.1)
    second = engine.settle({"arm_joint": 0.2}, seconds=0.1)
    assert first.positions["arm_joint"] > 0.1
    assert first.positions == pytest.approx(second.positions, abs=1e-6)


def test_a_run_that_ends_in_nan_does_not_spoil_the_next_run(engine, arm):
    """Newton's solver keeps some data from step to step. When a contact or a limit acts in the first step, the
    solver starts from that data, so a reset must clear it. Here the floor cuts through the bar: contacts act
    from the first step.
    """
    if engine.name != "newton":
        pytest.skip("the fault was in the Newton engine")
    engine.open(arm, floor=0.25)
    before = engine.settle({"arm_joint": 0.0}, seconds=0.2)
    assert math.isnan(engine.push("arm_joint", math.inf, seconds=0.1))  # an infinite effort ends in NaN
    after = engine.settle({"arm_joint": 0.0}, seconds=0.2)
    assert before.finite and after.finite
    assert after.positions == pytest.approx(before.positions, abs=1e-6)


def test_a_measurement_that_runs_out_of_a_solver_buffer_runs_again_with_a_larger_one(engine, arm, monkeypatch):
    """MuJoCo Warp leaves out the contacts and constraints that do not fit in its buffers. With buffers this small,
    and no larger ones, the bar would go through the floor to 0.3 rad.
    """
    if engine.name != "newton":
        pytest.skip("the buffers are MuJoCo Warp's")
    from proofmass_check.engines import newton as newton_engine

    engine.open(arm, floor=0.2)  # just under the bar
    newton_sizes = engine.settle({"arm_joint": 0.3}, seconds=0.5)  # drives the bar down onto the floor
    monkeypatch.setattr(newton_engine, "FIRST_SIZES", {"njmax": 4, "nconmax": 4})  # the move needs 24 and 16
    engine.open(arm, floor=0.2)
    small_sizes = engine.settle({"arm_joint": 0.3}, seconds=0.5)
    assert newton_sizes.positions["arm_joint"] < 0.1  # the floor stops the bar
    assert small_sizes.positions == pytest.approx(newton_sizes.positions, abs=1e-6)


def test_an_asset_after_another_gives_the_same_results(engine, arm, prop):
    """`run` with several assets runs them in one start of the engine, so a run must not depend on the one before.

    Newton's numbers can differ from run to run (docs/spec.md, section 5), so there only the verdicts must match.
    """
    first = verdicts(engine, arm)
    verdicts(engine, prop)
    again = verdicts(engine, arm)
    if engine.name == "newton":
        first, again = ({k: v for k, (v, _) in r.items()} for r in (first, again))
    assert again == first
