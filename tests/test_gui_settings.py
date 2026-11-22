# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import sys

from proofmass_check.gui import settings


def test_settings_without_a_file_are_the_defaults(tmp_path):
    found = settings.load(tmp_path / "none.json")
    assert found.pythons == {} and found.workspace.endswith("proofmass-check")


def test_settings_are_read_back(tmp_path):
    path = tmp_path / "gui.json"
    settings.save(settings.GuiSettings(pythons={"physx": "C:/isaac/python.exe"}, workspace="D:/batches"), path)
    found = settings.load(path)
    assert found.python("physx") == "C:/isaac/python.exe" and found.python("newton") == ""
    assert found.workspace == "D:/batches"


def test_a_settings_file_that_cannot_be_read(tmp_path):
    path = tmp_path / "gui.json"
    path.write_text("{ not JSON", encoding="utf-8")
    assert settings.load(path) == settings.GuiSettings()
    path.write_text('{"pythons": {"bullet": "python", "newton": "py"}, "workspace": " "}', encoding="utf-8")
    found = settings.load(path)
    assert found.pythons == {"newton": "py"} and found.workspace == settings.GuiSettings().workspace


def test_check_a_python():
    ok, text = settings.check_python(sys.executable)
    assert ok and text.startswith("proofmass-check ")
    assert settings.check_python("") == (False, "no Python set")
    assert settings.check_python("C:/no/python.exe") == (False, "no file C:/no/python.exe")
