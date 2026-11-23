# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
import http.client
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from results_files import results, write

from proofmass_check import cli
from proofmass_check.gui import batches, server

TOKEN = "test-token"


@pytest.fixture
def gui(tmp_path):
    """A running server with one open folder of two runs. Gives (port, the folder's ID)."""
    write(tmp_path, "lab/physx/results.json", results("arm", engine="physx"))
    write(
        tmp_path, "lab/newton/results.json", results("arm", engine="newton", verdicts={"LOAD": "PASS", "HOLD": "FAIL"})
    )
    app = server.App(TOKEN, settings_path=tmp_path / "settings" / "gui.json", workspace=tmp_path / "ws")
    folder_id = app.open(tmp_path / "lab")
    httpd = server.make_server(app)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1], folder_id
    httpd.shutdown()
    httpd.server_close()


def request(port, method, path, body=None, token=TOKEN, headers=None):
    """Send one request. Gives (status, headers, body as text)."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    sent = {"Host": f"127.0.0.1:{port}"}
    if token is not None:
        sent["X-Token"] = token
    if body is not None:
        sent["Content-Type"] = "application/json"
    sent |= headers or {}
    connection.request(method, path, body=None if body is None else json.dumps(body), headers=sent)
    response = connection.getresponse()
    answer = response.status, dict(response.getheaders()), response.read().decode("utf-8")
    connection.close()
    return answer


def api(port, method, path, body=None):
    status, _, text = request(port, method, path, body)
    assert status == 200, text
    return json.loads(text)


def test_the_page_needs_no_token(gui):
    port, _ = gui
    status, headers, text = request(port, "GET", "/", token=None)
    assert status == 200 and headers["Content-Type"].startswith("text/html") and "app.js" in text
    assert 'class="logo-mark"' in text and "<!--logo-->" not in text  # the server put the logo in
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert request(port, "GET", "/app.js", token=None)[0] == 200


def test_the_api_needs_the_token(gui):
    port, _ = gui
    assert request(port, "GET", "/api/state", token=None)[0] == 403
    assert request(port, "GET", "/api/state", token="wrong")[0] == 403
    state = api(port, "GET", "/api/state")
    assert [len(folder["runs"]) for folder in state["folders"]] == [2]


def test_another_host_or_site_is_refused(gui):
    port, _ = gui
    assert request(port, "GET", "/", headers={"Host": "evil.example"})[0] == 403  # DNS rebinding
    assert request(port, "GET", "/api/state", headers={"Origin": "http://evil.example"})[0] == 403
    assert request(port, "GET", "/api/state", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert request(port, "GET", "/api/state", headers={"Origin": f"http://localhost:{port}"})[0] == 200


def test_only_the_files_of_the_page_are_served(gui):
    port, _ = gui
    for path in (
        "/../server.py", "/..%2Fserver.py", "/server.py", "/static/app.js", "/nothing.js", "/fonts/../app.css",
        "/fonts/LICENSE-archivo.txt", "/fonts/none.woff2", "/fonts/../fonts/archivo-latin-standard-normal.woff2",
    ):  # fmt: skip
        assert request(port, "GET", path, token=None)[0] == 404, path
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("GET", "/fonts/archivo-latin-standard-normal.woff2", headers={"Host": f"127.0.0.1:{port}"})
    font = connection.getresponse()
    assert font.status == 200 and font.getheader("Content-Type") == "font/woff2" and font.read(4) == b"wOF2"
    connection.close()
    assert request(port, "POST", "/", token=None)[0] == 405


def test_a_run_a_comparison_and_a_report(gui):
    port, folder_id = gui
    run = api(port, "GET", f"/api/run?folder={folder_id}&run=newton/results.json")
    assert run["engine"] == "newton" and [c["id"] for c in run["checks"]] == ["LOAD", "HOLD"]
    refs = [[folder_id, "physx/results.json"], [folder_id, "newton/results.json"]]
    comparison = api(port, "POST", "/api/compare", {"runs": refs})
    assert [row["differs"] for row in comparison["checks"]] == [False, True]
    status, headers, text = request(port, "POST", "/api/report", {"runs": refs, "format": "csv"})
    assert status == 200 and headers["Content-Type"].startswith("text/csv") and text.count("\n") == 5
    status, headers, text = request(port, "POST", "/api/report", {"runs": refs, "title": "Lab"})
    assert status == 200 and "<title>Lab</title>" in text


def test_requests_that_cannot_be_answered(gui):
    port, folder_id = gui
    assert request(port, "GET", f"/api/run?folder={folder_id}&run=none.json")[0] == 404
    assert request(port, "GET", "/api/run?folder=f9&run=x")[0] == 404
    assert request(port, "POST", "/api/compare", {"runs": [[folder_id, "physx/results.json"]]})[0] == 400
    assert request(port, "POST", "/api/compare", {"runs": "all"})[0] == 400
    assert request(port, "GET", "/api/nothing")[0] == 404
    status, _, text = request(port, "POST", "/api/open", {"path": "C:/no/such/folder"})
    assert status == 400 and "no folder" in json.loads(text)["error"]


def test_open_a_folder_twice(gui, tmp_path):
    port, folder_id = gui
    folder = api(port, "POST", "/api/open", {"path": f'"{tmp_path / "lab"}"'})  # pasted with quotes
    assert folder["id"] == folder_id
    write(tmp_path, "other/results.json", results("door"))
    other = api(port, "POST", "/api/open", {"path": str(tmp_path / "other")})
    assert other["id"] != folder_id and [r["asset"] for r in other["runs"]] == ["door"]
    state = api(port, "POST", "/api/close", {"folder": other["id"]})
    assert [f["id"] for f in state["folders"]] == [folder_id]


def test_answers_are_strict_json(gui, tmp_path):
    port, _ = gui
    write(tmp_path, "nan/results.json", json.dumps(results() | {"seconds": float("nan")}))  # Python writes NaN
    folder = api(port, "POST", "/api/open", {"path": str(tmp_path / "nan")})
    assert folder["runs"][0]["seconds"] == "nan"


def test_the_gui_command_refuses_a_missing_folder(tmp_path, capsys):
    assert cli.main(["gui", str(tmp_path / "none"), "--no-browser"]) == cli.ERROR
    assert "no folder" in capsys.readouterr().err


def test_settings_are_saved_in_their_file(gui, tmp_path):
    port, _ = gui
    found = api(port, "GET", "/api/settings")
    assert found["pythons"] == {} and found["workspace"] == str(tmp_path / "ws") and found["workspace_for_session"]
    assert [e["name"] for e in found["engines"]] == ["physx", "newton"]
    saved = api(port, "POST", "/api/settings", {"pythons": {"newton": f'"{sys.executable}"'}, "workspace": "elsewhere"})
    assert saved["pythons"] == {"newton": sys.executable}
    on_disk = json.loads((tmp_path / "settings" / "gui.json").read_text(encoding="utf-8"))
    assert on_disk == {"pythons": {"newton": sys.executable}, "workspace": "elsewhere"}
    assert request(port, "POST", "/api/settings", {"pythons": {"bullet": "python"}})[0] == 400


def test_check_the_python_of_an_engine(gui):
    port, _ = gui
    assert api(port, "POST", "/api/check-python", {"engine": "physx"})["text"] == "no Python set"
    api(port, "POST", "/api/settings", {"pythons": {"physx": sys.executable}})
    found = api(port, "POST", "/api/check-python", {"engine": "physx"})
    assert found["ok"] and found["same_version"] and found["text"].startswith("proofmass-check ")


def test_a_batch_that_cannot_start_says_why(gui, tmp_path):
    port, _ = gui
    asset = write(tmp_path, "assets/arm.usda", "#usda 1.0\n")
    body = {"assets": [str(asset)], "engines": ["physx"]}
    status, _, text = request(port, "POST", "/api/batch-preview", body)
    assert status == 400 and json.loads(text)["error"] == "set the Python of physx in the settings first"
    api(port, "POST", "/api/settings", {"pythons": {"physx": sys.executable}})
    [preview] = api(port, "POST", "/api/batch-preview", body)
    assert (
        preview["run"] == "physx" and "proofmass_check run" in preview["command"] and "--events" in preview["command"]
    )
    found = api(port, "POST", "/api/usd-files", {"path": str(tmp_path / "assets")})
    assert [f["name"] for f in found["files"]] == ["arm.usda"]
    assert api(port, "GET", "/api/batches") == []
    assert request(port, "GET", "/api/batch?id=..%2Fws")[0] == 400


def test_a_batch_folder_shows_results_that_ended_while_no_page_followed_it(gui, tmp_path, monkeypatch):
    port, _ = gui
    worker = Path(__file__).parent / "fake_worker.py"
    monkeypatch.setattr(batches, "check_python", lambda python: (True, "proofmass-check 0.3.0 (spec 0.3)"))
    monkeypatch.setattr(batches, "command", lambda python, engine, assets, run_dir, events, *_: [
        sys.executable, str(worker), str(events), str(run_dir), *assets
    ])  # fmt: skip
    api(port, "POST", "/api/settings", {"pythons": {"physx": sys.executable}})
    asset = write(tmp_path, "assets/arm.usda", "#usda 1.0\n")

    def runs_of(folder_id):
        return next(f for f in api(port, "GET", "/api/state")["folders"] if f["id"] == folder_id)["runs"]

    def ran(batch):  # waits on the files: a request for the batch would read the folder again
        events = Path(batch["path"]) / "physx" / "events-1.jsonl"
        deadline = time.monotonic() + 30
        while not (events.is_file() and '"exit"' in events.read_text(encoding="utf-8")):
            assert time.monotonic() < deadline, "the worker did not end"
            time.sleep(0.05)

    first = api(port, "POST", "/api/batches", {"assets": [str(asset)], "engines": ["physx"]})
    ran(first)
    assert runs_of(first["folder"]) == []  # read when the batch started
    api(port, "GET", "/api/batches")  # the home page lists the batches before it lists the folders
    assert len(runs_of(first["folder"])) == 1
    second = api(port, "POST", "/api/batches", {"name": "again", "assets": [str(asset)], "engines": ["physx"]})
    ran(second)
    found = api(port, "GET", f"/api/batch?id={Path(second['path']).name}")  # the batch's page asks for it
    assert runs_of(found["folder"])[0]["verdicts"]["LOAD"] == "PASS"


def test_inspect_an_asset(gui, tmp_path):
    import usd_assets

    port, _ = gui
    arm = usd_assets.arm(tmp_path / "arm.usda")
    found = api(port, "POST", "/api/inspect", {"file": str(arm), "engine": "newton"})
    assert found["engine"] == "newton" and [j["name"] for j in found["joints"]] == ["root_joint", "arm_joint"]
    status, _, text = request(port, "POST", "/api/inspect", {"file": str(tmp_path / "none.usda")})
    assert status == 400 and json.loads(text)["error"].startswith("no USD file")
