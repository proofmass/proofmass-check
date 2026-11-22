# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The command line.

    proofmass-check run asset.usd --engine physx
    proofmass-check list-checks
    proofmass-check gui folder-with-results

Exit status: 0 when no check failed, 1 when a check failed, 2 when the run could not finish.
"""

import argparse
import sys
import traceback
from pathlib import Path

from proofmass_check import __version__, engines, report
from proofmass_check.checks import TITLES
from proofmass_check.rules import SETTLE_S, SPEC_VERSION, Settings

PASSED, FAILED, ERROR = 0, 1, 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.func(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proofmass-check", description="Physics checks for SimReady OpenUSD assets.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__} (spec {SPEC_VERSION})")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run every check on one asset")
    run.add_argument("asset", type=Path, help="the asset's root USD file")
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
    run.add_argument("--out", type=Path, help="folder for results.json (default: ./proofmass-check-<asset name>)")
    run.set_defaults(func=_run)

    listing = sub.add_parser("list-checks", help="list the checks and what each one tests")
    listing.set_defaults(func=_list_checks)

    gui = sub.add_parser("gui", help="show results files in a page in the browser (docs/gui.md)")
    gui.add_argument("folders", nargs="*", type=Path, help="folders with results files to open")
    gui.add_argument("--port", type=int, default=0, help="the port on 127.0.0.1 (default: a free port)")
    gui.add_argument("--no-browser", action="store_true", help="print the page's address, but do not open it")
    gui.set_defaults(func=_gui)
    return parser


def _list_checks(_args) -> int:
    for check_id, title in TITLES.items():
        print(f"{check_id:8} {title}")
    return PASSED


def _gui(args) -> int:
    from proofmass_check.gui import server

    try:
        return server.serve(args.folders, args.port, open_browser=not args.no_browser)
    except OSError as e:  # a folder that does not exist, or a port that is taken
        print(f"proofmass-check: {e}", file=sys.stderr)
        return ERROR


def _run(args) -> int:
    if not args.asset.is_file():
        print(f"proofmass-check: no file {args.asset}", file=sys.stderr)
        return ERROR
    out = args.out or Path(f"proofmass-check-{args.asset.stem}")
    settings = Settings(settle_s=args.settle, floor=not args.no_floor)
    try:
        engine = engines.create(args.engine)
    except engines.EngineUnavailableError as e:
        print(f"proofmass-check: {e}", file=sys.stderr)
        return ERROR
    code = ERROR
    try:
        code = _run_in(engine, args, settings, out)
    finally:
        engine.close(code)  # Isaac Sim ends the process here, with this status
    return code


def _run_in(engine, args, settings: Settings, out: Path) -> int:
    # The reader imports pxr, which Isaac Sim provides only after it has started. So it is
    # imported here, after engines.create(), and not at the top of the file.
    from proofmass_check import runner, usd_reader

    try:
        variants = usd_reader.choose_variants(args.asset, engine.variant_sets, args.variant)
        asset = usd_reader.read_asset(args.asset, variants)
        run = runner.run_checks(engine, asset, settings)
    except usd_reader.AssetError as e:
        print(f"proofmass-check: {e}", file=sys.stderr)
        report.write(report.error_dict(args.asset, args.engine, str(e)), out)
        return ERROR
    except Exception:  # noqa: BLE001  the user needs results.json with the error, whatever it is
        error = traceback.format_exc()
        print(error, file=sys.stderr)
        report.write(report.error_dict(args.asset, args.engine, error[-4000:]), out)
        return ERROR
    path = report.write(report.to_dict(run), out)
    for result in run.results:
        print(f"{result.verdict:4} {result.id:8} {result.detail}")
    for note in run.notes:
        print(f"note: {note}")
    failed = sum(r.verdict == "FAIL" for r in run.results)
    print(f"{'PASSED' if run.passed else f'FAILED ({failed})'} in {run.seconds} s; results in {path}")
    return PASSED if run.passed else FAILED


if __name__ == "__main__":
    sys.exit(main())
