# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import dataclasses
import json

import numpy as np
import pytest
import usd_assets
from pxr import Sdf

from proofmass_check import cli, wheels
from proofmass_check.inspection import inspect_asset
from proofmass_check.rules import Settings
from proofmass_check.usd_reader import read_asset


def bare_rover(tmp_path):
    """The rover of usd_assets without its SimReady_Metadata.mobile, as another maker would give it."""
    path = usd_assets.rover(tmp_path / "rover.usda")
    layer = Sdf.Layer.FindOrOpen(str(path))
    layer.customLayerData = {}
    layer.Save()
    return path


def test_the_derived_description_is_the_rovers_own(rover):
    mobile, notes = wheels.derive(dataclasses.replace(rover, wheeled=None))
    assert mobile["drive"] == "differential" and mobile["steering"] == {}
    assert mobile["radius"] == pytest.approx(rover.wheeled.radius)
    assert mobile["track"] == pytest.approx(rover.wheeled.track)
    assert mobile["axle_center"] == pytest.approx(list(rover.wheeled.axle_centre))
    for wheel in rover.wheeled.wheels:
        got = mobile["wheels"][wheel.name]
        assert (got["side"], got["driven"], got["spin"]) == (wheel.side, wheel.driven, wheel.spin)
        assert got["radius"] == pytest.approx(wheel.radius) and got["center"] == pytest.approx(list(wheel.centre))
    assert any("a proposal" in n for n in notes)


def test_the_layer_gives_the_reader_the_description(tmp_path):
    path = bare_rover(tmp_path)
    assert read_asset(path).wheeled is None
    mobile, _ = wheels.derive(read_asset(path))
    layer = wheels.write_layer(path, mobile)
    assert layer == tmp_path / "rover_mobile.usda"
    described = read_asset(layer).wheeled
    assert described.drive == "differential" and described.track == pytest.approx(0.4)
    assert [w.name for w in described.wheels] == ["left_wheel_joint", "right_wheel_joint"]
    assert read_asset(path).wheeled is None  # the asset itself does not change


def test_no_description_without_a_driven_wheel_on_each_side(rover):
    left = next(j for j in rover.joints if j.name == "left_wheel_joint")
    one_sided = dataclasses.replace(rover, wheeled=None, joints=(left,))
    mobile, notes = wheels.derive(one_sided)
    assert mobile is None and "no driven wheel on each side" in notes[-1]


def test_steering_joints_need_their_maker(rover):
    left = next(j for j in rover.joints if j.name == "left_wheel_joint")
    knuckle = dataclasses.replace(left, name="knuckle", direction=np.array([0.0, 0.0, 1.0]), drive=dataclasses.replace(
        left.drive, stiffness=100.0))  # fmt: skip
    mobile, notes = wheels.derive(dataclasses.replace(rover, wheeled=None, joints=(*rover.joints, knuckle)))
    assert mobile is None and notes[0].startswith("knuckle look like steering joints")


def test_describe_wheels_prints_and_writes(tmp_path, capsys):
    path = bare_rover(tmp_path)
    assert cli.main(["describe-wheels", str(path)]) == cli.PASSED
    out = capsys.readouterr()
    assert json.loads(out.out)["track"] == pytest.approx(0.4) and "note: a proposal" in out.err
    assert not (tmp_path / "rover_mobile.usda").exists()
    assert cli.main(["describe-wheels", str(path), "--write"]) == cli.PASSED
    assert read_asset(tmp_path / "rover_mobile.usda").wheeled is not None
    described = usd_assets.rover(tmp_path / "described.usda")
    assert cli.main(["describe-wheels", str(described), "--write"]) == cli.ERROR  # it has its own: never hidden
    assert not (tmp_path / "described_mobile.usda").exists()


def test_inspect_proposes_a_description(tmp_path):
    data = inspect_asset(bare_rover(tmp_path), "physx", [], Settings(), geometry=False)
    assert data["derived_mobile"]["mobile"]["drive"] == "differential"
    described = inspect_asset(usd_assets.rover(tmp_path / "described.usda"), "physx", [], Settings(), geometry=False)
    assert described["derived_mobile"] is None
