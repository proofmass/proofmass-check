# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The GUI and the replay of a run (docs/gui.md, section 6.11): which file it reads, the API, the report."""

import http.client
import json
import threading

import pytest
import usd_assets
from results_files import results, write

from proofmass_check import replay
from proofmass_check import report as results_report
from proofmass_check.gui import report, runs, server
from proofmass_check.inspection import inspect_asset
from proofmass_check.rules import Settings

TOKEN = "test-token"
POSE = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]


def recorded(folder) -> str:
    """A replay of one clip in folder/replay.bin. Gives its id."""
    recorder = replay.Recorder(["/arm/base"])
    recorder.start("HOLD", "settle", {"targets": {}, "seconds": 1.5})
    recorder.frame(0.0, [POSE])
    recorder.end()
    replay.write(recorder, folder, "physx", "a" * 64)
    return recorder.id


def run_with_replay(tmp_path, file="replay.bin", id_=None) -> runs.Run:
    data = results("arm")
    folder = tmp_path / "run"
    folder.mkdir(parents=True, exist_ok=True)
    made = recorded(folder)
    data["replay"] = {"file": file, "id": id_ or made}
    path = write(tmp_path, "run/results.json", data)
    return runs.Run("run/results.json", path, data)


def test_a_run_with_its_replay(tmp_path):
    run = run_with_replay(tmp_path)
    assert runs.replay_path(run) == tmp_path / "run" / "replay.bin"
    assert runs.details(run)["replay"] is True
    assert runs.replay_bytes(run) == (tmp_path / "run" / "replay.bin").read_bytes()


@pytest.mark.parametrize("name", ["../replay.bin", "sub/replay.bin", "sub\\replay.bin", "..", "", None, 7, "none.bin"])
def test_only_a_file_next_to_the_results_is_read(tmp_path, name):
    run = run_with_replay(tmp_path, file=name)
    assert runs.replay_path(run) is None and runs.details(run)["replay"] is False
    with pytest.raises(LookupError):
        runs.replay_bytes(run)


def test_a_replay_of_another_run_is_refused(tmp_path):
    """A run without --replay into the same folder leaves the older replay.bin there."""
    run = run_with_replay(tmp_path, id_="0" * 32)
    with pytest.raises(ValueError, match="from another run"):
        runs.replay_bytes(run)


def test_a_file_that_is_not_a_replay_is_refused(tmp_path):
    run = run_with_replay(tmp_path)
    (tmp_path / "run" / "replay.bin").write_bytes(b"not a replay at all")
    with pytest.raises(ValueError, match="not a replay file"):
        runs.replay_bytes(run)


def test_results_without_a_replay(tmp_path):
    path = write(tmp_path, "results.json", results("arm"))
    run = runs.Run("results.json", path, results("arm"))
    assert runs.details(run)["replay"] is False


@pytest.fixture
def gui(tmp_path):
    """A running server with a folder of two runs: one with its replay, one with the replay of another run."""
    good = recorded(tmp_path / "lab" / "good")
    write(tmp_path, "lab/good/results.json", results("arm") | {"replay": {"file": "replay.bin", "id": good}})
    recorded(tmp_path / "lab" / "stale")
    write(tmp_path, "lab/stale/results.json", results("arm") | {"replay": {"file": "replay.bin", "id": "0" * 32}})
    write(tmp_path, "lab/none/results.json", results("arm"))
    app = server.App(TOKEN, settings_path=tmp_path / "settings" / "gui.json", workspace=tmp_path / "ws")
    folder_id = app.open(tmp_path / "lab")
    httpd = server.make_server(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], folder_id
    httpd.shutdown()
    httpd.server_close()


def get(port, path, token=TOKEN) -> tuple[int, dict, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": f"127.0.0.1:{port}"} | ({"X-Token": token} if token else {})
    connection.request("GET", path, headers=headers)
    response = connection.getresponse()
    answer = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return answer


def test_the_api_sends_a_runs_replay(gui, tmp_path):
    port, folder = gui
    status, headers, body = get(port, f"/api/replay?folder={folder}&run=good/results.json")
    assert status == 200 and headers["Content-Type"] == "application/octet-stream"
    assert body == (tmp_path / "lab" / "good" / "replay.bin").read_bytes()
    assert headers["Cache-Control"] == "no-store" and "Content-Security-Policy" in headers
    _, _, run = get(port, f"/api/run?folder={folder}&run=good/results.json")
    assert json.loads(run)["replay"] is True


def test_the_api_says_why_it_sends_no_replay(gui):
    port, folder = gui
    assert get(port, f"/api/replay?folder={folder}&run=good/results.json", token=None)[0] == 403
    status, _, body = get(port, f"/api/replay?folder={folder}&run=stale/results.json")
    assert status == 409 and "from another run" in json.loads(body)["error"]
    status, _, body = get(port, f"/api/replay?folder={folder}&run=none/results.json")
    assert status == 404 and "no replay" in json.loads(body)["error"]
    assert get(port, f"/api/replay?folder={folder}&run=other/results.json")[0] == 404


def test_the_report_says_that_a_run_has_a_replay(tmp_path):
    text = report.to_html([run_with_replay(tmp_path)])
    assert "<dt>Replay</dt><dd>recorded next to the results file" in text
    plain = write(tmp_path, "plain/results.json", results("arm"))
    assert "<dt>Replay</dt>" not in report.to_html([runs.Run("plain/results.json", plain, results("arm"))])


def test_inspect_gives_the_sha256_a_replay_compares(tmp_path):
    asset = usd_assets.arm(tmp_path / "arm.usda")
    assert inspect_asset(asset, "physx", [], Settings(), geometry=False)["sha256"] == results_report.sha256(asset)
