# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""A real engine on the small test assets of usd_assets.py. Each asset is built to pass.

These tests need the engine's Python environment with pytest in it, and a GPU for Newton:

    pytest tests/test_engines_gpu.py -m gpu --engine physx
    pytest tests/test_engines_gpu.py -m gpu --engine newton
"""

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


def test_a_drawer_and_a_door_open(engine, cabinet):
    results = verdicts(engine, cabinet)
    expect(results, "LOAD")
    expect(results, "PASSIVE")


def test_a_gripper_holds_its_payload(engine, gripper):
    results = verdicts(engine, gripper)
    for check_id in ("LOAD", "HOLD", "TRACK", "LIMIT", "GRIP", "SHAKE"):
        expect(results, check_id)
