# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import json

import usd_assets
from fake_engine import IdealEngine

from proofmass_check import cli, engines


def test_list_checks(capsys):
    assert cli.main(["list-checks"]) == cli.PASSED
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("LOAD") and len(lines) == 14


def test_a_missing_file(tmp_path, capsys):
    assert cli.main(["run", str(tmp_path / "none.usda")]) == cli.ERROR
    assert "no file" in capsys.readouterr().err


def test_an_engine_that_is_not_installed(tmp_path, capsys, monkeypatch):
    def unavailable(name):
        raise engines.EngineUnavailableError(f"the {name} engine needs it")

    monkeypatch.setattr(engines, "create", unavailable)
    assert cli.main(["run", str(usd_assets.prop(tmp_path / "prop.usda"))]) == cli.ERROR
    assert "the physx engine needs it" in capsys.readouterr().err


def test_a_run(tmp_path, capsys, monkeypatch):
    engine = IdealEngine()
    monkeypatch.setattr(engines, "create", lambda name: engine)
    asset = usd_assets.prop(tmp_path / "prop.usda")
    assert cli.main(["run", str(asset), "--out", str(tmp_path / "out")]) == cli.PASSED
    out = capsys.readouterr().out
    assert "PASS LOAD" in out and "PASS DROP" in out and "N/A  HOLD" in out
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert data["passed"] is True and data["asset"]["variants"] == {}
    assert engine.closed_with == cli.PASSED  # Isaac Sim ends the process with the status it gets here


def test_a_bad_variant_writes_results_with_the_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(engines, "create", lambda name: IdealEngine())
    asset = usd_assets.prop(tmp_path / "prop.usda")
    assert cli.main(["run", str(asset), "--variant", "PhysX=On", "--out", str(tmp_path / "out")]) == cli.ERROR
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert data["passed"] is False and "no variant 'PhysX=On'" in data["error"]
