# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Test assets as fixtures.

usd_assets and the reader import pxr. In Isaac Sim's Python, pxr exists only after Isaac Sim has
started, so this file imports them inside the fixtures and not at the top.
"""

import pytest

ENGINE = pytest.StashKey[object]()
EXIT_STATUS = pytest.StashKey[int]()


def pytest_addoption(parser):
    parser.addoption("--engine", default="physx", help="the engine for tests marked gpu: physx or newton")


def pytest_sessionfinish(session, exitstatus):
    session.config.stash[EXIT_STATUS] = int(exitstatus)


def pytest_unconfigure(config):
    """Close a real engine last, after pytest's summary: Isaac Sim ends the process when it closes."""
    engine = config.stash.get(ENGINE, None)
    if engine is not None:
        engine.close(config.stash.get(EXIT_STATUS, 1))


def _read(builder_name, tmp_path):
    import usd_assets

    from proofmass_check.usd_reader import read_asset

    return read_asset(getattr(usd_assets, builder_name)(tmp_path / f"{builder_name}.usda"))


@pytest.fixture
def arm(tmp_path):
    return _read("arm", tmp_path)


@pytest.fixture
def loose_arm(tmp_path):
    return _read("loose_arm", tmp_path)


@pytest.fixture
def actuated_arm(tmp_path):
    return _read("actuated_arm", tmp_path)


@pytest.fixture
def tooled_arm(tmp_path):
    return _read("tooled_arm", tmp_path)


@pytest.fixture
def gripper(tmp_path):
    return _read("gripper", tmp_path)


@pytest.fixture
def mimic_gripper(tmp_path):
    return _read("mimic_gripper", tmp_path)


@pytest.fixture
def cabinet(tmp_path):
    return _read("cabinet", tmp_path)


@pytest.fixture
def prop(tmp_path):
    return _read("prop", tmp_path)


@pytest.fixture
def rover(tmp_path):
    return _read("rover", tmp_path)
