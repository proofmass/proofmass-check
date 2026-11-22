# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The command line.

    proofmass-check run asset.usd --engine physx
    proofmass-check run a.usd b.usd --engine newton --out results --events progress.jsonl
    proofmass-check list-checks
    proofmass-check gui folder-with-results

Exit status: 0 when no check failed, 1 when a check failed, 2 when the run could not finish.
"""

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from proofmass_check import __version__, engines, report
from proofmass_check.checks import TITLES
from proofmass_check.events import Events, asset_events
from proofmass_check.rules import SETTLE_S, SPEC_VERSION, Settings

PASSED, FAILED, ERROR = 0, 1, 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.func(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proofmass-check", description="Physics checks for SimReady OpenUSD assets.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__} (spec {SPEC_VERSION})")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run every check on one asset, or on several in one start of the engine")
    run.add_argument("assets", nargs="+", type=Path, metavar="asset", help="the asset's root USD file")
    run.add_argument("--engine", choices=sorted(engines.ENGINES), default="physx")
    run.add_argument(
        "--variant",
        action="append",
        default=[],
        metavar="SET=VALUE",
        help="select a variant, for example Physics=PhysX (repeat for more than one)",
    )
    run.add_argument(
        "--no-floor", action="store_true", help="no floor: for a pinned arm whose links reach below its base"
    )
    run.add_argument(
        "--settle", type=float, default=SETTLE_S, help=f"seconds a drive gets for a move (spec: {SETTLE_S})"
    )
    run.add_argument(
        "--out",
        type=Path,
        help="folder for results.json, or with several assets for a folder per asset "
        "(default: ./proofmass-check-<asset name>)",
    )
    run.add_argument("--events", type=Path, metavar="FILE", help="write the progress to FILE as JSON Lines")
    run.set_defaults(func=_run)

    inspect = sub.add_parser(
        "inspect", help="print what the reader reads from an asset, and the expected plan, as JSON; no engine starts"
    )
    inspect.add_argument("asset", type=Path, help="the asset's root USD file")
    inspect.add_argument("--engine", choices=sorted(engines.ENGINES), default="physx", help="the engine to plan for")
    inspect.add_argument("--variant", action="append", default=[], metavar="SET=VALUE", help="as for run")
    inspect.add_argument("--no-floor", action="store_true", help="as for run")
    inspect.add_argument("--geometry", action="store_true", help="add the colliders, for a 3D view")
    inspect.add_argument("--out", type=Path, help="write the JSON to this file (default: stdout)")
    inspect.set_defaults(func=_inspect)

    listing = sub.add_parser("list-checks", help="list the checks and what each one tests")
    listing.set_defaults(func=_list_checks)

    gui = sub.add_parser("gui", help="show results files in a page in the browser (docs/gui.md)")
    gui.add_argument("folders", nargs="*", type=Path, help="folders with results files to open")
    gui.add_argument("--port", type=int, default=0, help="the port on 127.0.0.1 (default: a free port)")
    gui.add_argument("--no-browser", action="store_true", help="print the page's address, but do not open it")
    gui.add_argument(
        "--workspace", type=Path, help="the folder of the batches, for this session only (default: the GUI's settings)"
    )
    gui.set_defaults(func=_gui)
    return parser


def _list_checks(_args) -> int:
    for check_id, title in TITLES.items():
        print(f"{check_id:8} {title}")
    return PASSED


def _inspect(args) -> int:
    if not args.asset.is_file():
        print(f"proofmass-check: no file {args.asset}", file=sys.stderr)
        return ERROR
    try:
        from proofmass_check import inspection, usd_reader
    except ImportError as e:
        print(
            f"proofmass-check: inspect needs pxr ({e}). Install proofmass-check[usd] in this Python. In Isaac "
            "Sim's Python, pxr exists only after Isaac Sim starts: use another Python.",
            file=sys.stderr,
        )
        return ERROR
    settings = Settings(floor=not args.no_floor)
    try:
        data = inspection.inspect_asset(args.asset, args.engine, args.variant, settings, args.geometry)
    except usd_reader.AssetError as e:
        print(f"proofmass-check: {e}", file=sys.stderr)
        return ERROR
    text = json.dumps(data, allow_nan=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return PASSED


def _gui(args) -> int:
    from proofmass_check.gui import server

    try:
        return server.serve(args.folders, args.port, open_browser=not args.no_browser, workspace=args.workspace)
    except OSError as e:  # a folder that does not exist, or a port that is taken
        print(f"proofmass-check: {e}", file=sys.stderr)
        return ERROR


def _run(args) -> int:
    """Every asset in one start of the engine. The status is the highest status of the assets' runs.

    Starting Isaac Sim can take a minute, so a batch of assets starts it once. An asset that stops
    with an error gets results.json with the error, and the next asset runs.
    """
    problem = _assets_problem(args.assets)
    if problem:
        print(f"proofmass-check: {problem}", file=sys.stderr)
        return ERROR
    settings = Settings(settle_s=args.settle, floor=not args.no_floor)
    events = Events(args.events)
    events("start", assets=[str(a) for a in args.assets], engine=args.engine, tool=__version__, spec=SPEC_VERSION)
    started = time.monotonic()
    try:
        engine = engines.create(args.engine)
    except engines.EngineUnavailableError as e:
        print(f"proofmass-check: {e}", file=sys.stderr)
        events("error", error=str(e))
        events("exit", status=ERROR)
        events.close()
        return ERROR
    events("engine", versions=dict(engine.version()), seconds=round(time.monotonic() - started, 1))
    codes = []
    try:
        for asset in args.assets:
            if len(args.assets) > 1:
                print(f"== {asset}")
            codes.append(_run_in(engine, asset, args, settings, _out(args, asset), asset_events(events, str(asset))))
    finally:
        code = max(codes) if len(codes) == len(args.assets) else ERROR
        events("exit", status=code)
        events.close()
        engine.close(code)  # Isaac Sim ends the process here, with this status
    return code


def _assets_problem(assets: list[Path]) -> str | None:
    """Why the assets cannot run, or None.

    With several assets, each gets a folder with the name of its file. So two files of one name,
    in different folders, would write to the same place: run them one at a time.
    """
    missing = [str(a) for a in assets if not a.is_file()]
    if missing:
        return f"no file {', '.join(missing)}"
    names = [a.stem for a in assets]
    twice = sorted({n for n in names if names.count(n) > 1})
    if len(assets) > 1 and twice:
        return f"several assets have the same file name ({', '.join(twice)}): run them one at a time"
    return None


def _out(args, asset: Path) -> Path:
    """The folder for one asset's results.json."""
    if args.out is None:
        return Path(f"proofmass-check-{asset.stem}")
    return args.out / asset.stem if len(args.assets) > 1 else args.out


def _run_in(engine, file: Path, args, settings: Settings, out: Path, events) -> int:
    # The reader imports pxr, which Isaac Sim provides only after it has started. So it is
    # imported here, after engines.create(), and not at the top of the file.
    from proofmass_check import runner, usd_reader

    events("asset")
    started = time.monotonic()
    try:
        variants = usd_reader.choose_variants(file, engine.variant_sets, args.variant)
        asset = usd_reader.read_asset(file, variants)
        run = runner.run_checks(engine, asset, settings, events)
    except usd_reader.AssetError as e:
        print(f"proofmass-check: {e}", file=sys.stderr)
        return _stopped(file, args.engine, str(e), out, events, started)
    except Exception:  # noqa: BLE001  the user needs results.json with the error, whatever it is
        error = traceback.format_exc()
        print(error, file=sys.stderr)
        return _stopped(file, args.engine, error[-4000:], out, events, started)
    path = report.write(report.to_dict(run), out)
    for result in run.results:
        print(f"{result.verdict:4} {result.id:8} {result.detail}")
    for note in run.notes:
        print(f"note: {note}")
    failed = sum(r.verdict == "FAIL" for r in run.results)
    print(f"{'PASSED' if run.passed else f'FAILED ({failed})'} in {run.seconds} s; results in {path}")
    events("end", passed=run.passed, failed=failed, results=str(path), seconds=run.seconds)
    return PASSED if run.passed else FAILED


def _stopped(file: Path, engine: str, error: str, out: Path, events, started: float) -> int:
    """results.json and the "end" event of a run that stopped with an error."""
    path = report.write(report.error_dict(file, engine, error), out)
    seconds = round(time.monotonic() - started, 1)
    events("end", passed=False, error=(error.strip().splitlines() or [""])[-1], results=str(path), seconds=seconds)
    return ERROR


if __name__ == "__main__":
    sys.exit(main())
