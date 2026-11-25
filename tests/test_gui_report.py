# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import csv
import io
import math
import re
from pathlib import Path

from results_files import error_results, measured, results

from proofmass_check.gui import report
from proofmass_check.gui.runs import Run


def _run(name, data) -> Run:
    return Run(name, Path(name), data)


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_has_a_row_for_each_check_and_each_measurement():
    data = results(
        verdicts={"LOAD": "PASS", "HOLD": "FAIL", "GRIP": "N/A"},
        measurements={"HOLD": [measured("elbow", 0.03, math.radians(0.5), False)]},
    )
    text = report.to_csv([_run("arm.json", data), _run("stopped.json", error_results())])
    assert text.splitlines()[0] == ",".join(report.CSV_FIELDS)
    rows = _rows(text)
    assert [(r["run"], r["check"], r["verdict"], r["subject"]) for r in rows] == [
        ("arm.json", "LOAD", "PASS", ""),
        ("arm.json", "HOLD", "FAIL", ""),
        ("arm.json", "HOLD", "FAIL", "elbow"),
        ("arm.json", "GRIP", "N/A", ""),
        ("stopped.json", "", "", ""),
    ]
    assert rows[2]["value"] == "0.03" and rows[2]["unit"] == "rad" and rows[2]["ok"] == "False"
    assert rows[4]["error"].endswith("the engine stopped")


def test_csv_gives_the_file_name_unless_asked_for_the_path():
    run = _run("arm.json", results())
    assert _rows(report.to_csv([run]))[0]["file"] == "arm.usda"
    assert _rows(report.to_csv([run], full_paths=True))[0]["file"] == "C:\\Users\\someone\\assets\\arm.usda"


def test_csv_text_never_runs_as_a_formula():
    data = results(details={"LOAD": '=HYPERLINK("http://example.com")'}, file="C:\\=evil.usda")
    row = _rows(report.to_csv([_run("arm.json", data)]))[0]
    assert row["detail"].startswith("'=") and row["asset"] == "'=evil"


def test_html_escapes_the_text_of_results_files():
    data = results(asset="<b>arm</b>", details={"LOAD": "<script>alert(1)</script>"}, notes=["<i>note</i>"])
    page = report.to_html([_run("arm.json", data)], title="A & B", made="2026-11-22 10:00")
    assert "<script>alert" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<b>arm</b>" not in page and "<i>note</i>" not in page
    assert "<title>A &amp; B</title>" in page


def test_html_marks_a_pass_that_does_not_cover_every_check():
    wheeled = {"LOAD": "PASS", "STAND": "N/A", "DRIVE": "N/A", "TURN": "N/A"}
    rover = results("rover", "newton", verdicts=wheeled, engine_cannot_run=["STAND", "DRIVE", "TURN"])
    page = report.to_html([_run("rover.json", rover), _run("arm.json", results())], made="today")
    assert '<span class="v pass">✓ passed</span> <span class=badge' in page
    assert ">3 not run: STAND, DRIVE, TURN</span>" in page
    assert '<th class=c title="LOAD: the engine builds the asset as the USD describes it">LOAD</th>' in page
    assert "The newton engine cannot run STAND, DRIVE, TURN on this asset yet" in page
    assert "1 of these runs did not run every check their asset needs" in page
    assert page.count(" not run: ") == 2  # the matrix and the rover's section; the arm has no mark
    assert "did not run every check" not in report.to_html([_run("arm.json", results())], made="today")


def test_html_marks_wheels_that_were_not_checked():
    wheels = ["left_wheel", "right_wheel"]
    rover = results("rover", verdicts={"LOAD": "PASS", "DROP": "PASS"}, wheels_without_mobile=wheels)
    page = report.to_html([_run("rover.json", rover), _run("arm.json", results())], made="today")
    assert '✓ passed</span> <span class=badge title="left_wheel, right_wheel look like wheels' in page
    assert page.count(">wheels not checked</span>") == 2  # the matrix and the rover's section
    assert "1 of these assets have joints that look like wheels" in page


def test_html_shows_every_verdict_reason_and_note():
    data = results(
        engine="newton",
        verdicts={"LOAD": "PASS", "PASSIVE": "FAIL", "GRIP": "N/A"},
        details={"PASSIVE": "door@upper 27.670 deg from the limit FAIL; door@lower 0.000 deg from the limit",
                 "GRIP": "the asset has no gripper site (gripper_maxOpening)"},
        notes=["settings differ from the spec: settle_s is 3.0 (spec: 1.5)"],
    )  # fmt: skip
    page = report.to_html([_run("arm.json", data), _run("stopped.json", error_results())], made="today")
    assert "the asset has no gripper site (gripper_maxOpening)" in page
    assert '<span class="fail">door@upper 27.670 deg from the limit FAIL</span><br>door@lower' in page
    assert "settle_s is 3.0 (spec: 1.5)" in page
    assert "Newton is experimental" in page
    assert "RuntimeError: the engine stopped" in page
    assert '<div class="stat ok"><b>0</b>' not in page and '<div class="stat bad"><b>1</b><span>Failed</span>' in page
    assert '<div class="stat bad"><b>1</b><span>Stopped with an error</span>' in page
    assert "someone" not in page  # no full path, so no user name


def test_html_gives_the_settings_in_mm_and_deg():
    data = results()
    data["settings"] |= {"angular_tol": math.radians(0.5), "floor": None, "new_setting": 3}
    page = report.to_html([_run("arm.json", data)], made="today")
    assert (
        "settle 1.5 s · linear tolerance 2 mm · angular tolerance 0.5 deg · 50 random poses · no floor · new_setting 3"
        in page
    )


def test_html_is_one_file_in_the_look_of_proofmass_com():
    page = report.to_html([_run("arm.json", results())], made="today")
    assert 'class="logo-mark"' in page and 'class="logo-word"' in page
    assert page.count("src:url(data:font/woff2;base64,") == 3  # Archivo, IBM Plex Mono 400 and 500
    assert '<link rel="icon" href="data:image/svg+xml;base64,' in page
    # It loads nothing: the only addresses are two links a reader can follow.
    assert re.findall(r"https?://[^\s\"'<>)]+", page) == [
        "https://proofmass.com",
        "https://github.com/proofmass/proofmass-check",
    ]
