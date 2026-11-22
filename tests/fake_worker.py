# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""A worker without an engine, for the tests of the GUI's batches: it writes events and results as `run` does.

    python fake_worker.py <events file> <run folder> <asset> ...

An asset whose file name holds "crash" ends the process in the middle of it, as an engine that
crashes would. One whose name holds "slow" waits 30 s, for a test that cancels it.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from results_files import results


def main(events_path: str, run_dir: str, *assets: str) -> int:
    with open(events_path, "w", encoding="utf-8") as events:

        def emit(event, **fields):
            events.write(json.dumps({"event": event, "t": 0.1} | fields) + "\n")
            events.flush()

        emit("start", assets=list(assets), engine="physx")
        emit("engine", versions={"fake": "1"}, seconds=0.1)
        for asset in assets:
            name = Path(asset).stem
            emit("asset", asset=asset)
            emit("check", asset=asset, id="LOAD", total=None)
            if "crash" in name:
                os._exit(3)
            if "slow" in name:
                time.sleep(30)
            path = Path(run_dir) / name / "results.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(results(name, file=asset)), encoding="utf-8")
            emit("result", asset=asset, id="LOAD", verdict="PASS")
            emit("end", asset=asset, passed=True, failed=0, results=str(path), seconds=0.1)
        emit("exit", status=0)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
