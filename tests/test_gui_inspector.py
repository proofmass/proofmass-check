# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The GUI's inspector: proofmass-check inspect in a process of its own."""

import sys

import pytest
import usd_assets

from proofmass_check.gui import inspector
from proofmass_check.gui.batches import BatchError
from proofmass_check.gui.settings import GuiSettings


def test_inspect_runs_in_a_python_with_pxr(tmp_path):
    arm = usd_assets.arm(tmp_path / "arm.usda")
    found = inspector.Inspector()
    data = found.inspect({"file": str(arm), "engine": "physx"}, GuiSettings())
    assert data["name"] == "unit_arm" and data["bodies"][0]["hulls"]  # with the geometry, for the 3D view
    assert found.inspect({"file": f'"{arm}"', "engine": "physx"}, GuiSettings()) is data  # kept, not run again


def test_requests_the_inspector_refuses(tmp_path):
    arm = usd_assets.arm(tmp_path / "arm.usda")
    found = inspector.Inspector()
    for body, message in (
        ({"file": str(tmp_path / "none.usda")}, "no USD file"),
        ({"file": str(arm), "engine": "bullet"}, "no engine bullet"),
        ({"file": str(arm), "variants": ["PhysX"]}, "a variant is SET=VALUE"),
        ({"file": str(arm), "variants": ["PhysX=On"]}, "no variant 'PhysX=On'"),
    ):
        with pytest.raises(BatchError, match=message):
            found.inspect(body, GuiSettings())


def test_the_python_that_runs_inspect(monkeypatch):
    assert inspector.python_with_pxr(GuiSettings()) == sys.executable  # the tests' Python has usd-core
    monkeypatch.setattr(inspector.importlib.util, "find_spec", lambda name: None)
    assert inspector.python_with_pxr(GuiSettings(pythons={"newton": "C:/newton/python.exe"})) == "C:/newton/python.exe"
    with pytest.raises(BatchError, match="inspect needs a Python with pxr"):
        inspector.python_with_pxr(GuiSettings(pythons={"physx": "C:/isaac/python.exe"}))
