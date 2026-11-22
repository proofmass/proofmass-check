# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""A report of runs: one HTML file that opens without the GUI or a network, and a CSV file.

The report leaves out nothing from results.json and adds no verdict of its own (docs/gui.md,
section 6.8). It gives the asset's file name only, unless asked for the full path: the path in
results.json can hold the user's name.
"""

import csv
import io
import re
from datetime import datetime
from html import escape

from proofmass_check import __version__
from proofmass_check.gui.runs import Run, check_order, details

CSV_FIELDS = (
    "run", "asset", "file", "sha256", "engine", "engine_versions", "tool_version", "spec_version", "passed",
    "error", "check", "verdict", "detail", "subject", "case", "quantity", "value", "limit", "bound", "unit", "ok",
)  # fmt: skip
SIGNS = {"PASS": "✓", "FAIL": "✕", "N/A": "·"}
ASSET = "<span class=na>asset</span>"  # a measurement with no subject is of the whole asset
NEWTON_NOTE = "Newton is experimental: its results can differ from run to run (spec.md, section 5)."


def file_name(file: str, full_paths: bool) -> str:
    return file if full_paths else re.split(r"[\\/]", file)[-1]


# --- CSV


def to_csv(runs: list[Run], full_paths: bool = False) -> str:
    """One row for each check of each run, and one more for each measurement. Values in SI units."""
    out = io.StringIO()
    writer = csv.DictWriter(out, CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for run in runs:
        d = details(run)
        base = {
            "run": run.id,
            "asset": d["asset"],
            "file": file_name(d["file"], full_paths),
            "sha256": d["sha256"],
            "engine": d["engine"],
            "engine_versions": " ".join(f"{k}={v}" for k, v in d["engine_versions"].items()),
            "tool_version": d["tool_version"],
            "spec_version": d["spec_version"],
            "passed": d["passed"],
            "error": d["error"] or "",
        }
        rows = [base] if not d["checks"] else []
        for check in d["checks"]:
            row = base | {"check": check["id"], "verdict": check["verdict"]}
            rows.append(row | {"detail": check["detail"]})
            rows += [row | {k: m[k] for k in CSV_FIELDS[13:]} for m in check["measurements"]]
        writer.writerows({k: _cell(v) for k, v in row.items()} for row in rows)
    return out.getvalue()


def _cell(value):
    """A spreadsheet runs text that starts with "=", "+" or "@" as a formula. A quote before it stops that.

    Results files can come from anyone, so a crafted name must not run as a formula. Numbers stay as
    they are.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "@", "\t", "\r"):
        return "'" + value
    return value


# --- HTML


def to_html(runs: list[Run], title: str = "proofmass-check results", full_paths: bool = False, made=None) -> str:
    """The report as one HTML page with its CSS in it. made: when it was made, for the page's first line."""
    made = made or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    runs_details = [details(run) for run in runs]
    passed = sum(d["passed"] for d in runs_details)
    errors = sum(bool(d["error"]) for d in runs_details)
    parts = [
        f"<h1>{escape(title)}</h1>",
        f"<p class=lede>Made {escape(made)} with proofmass-check {escape(__version__)}. {len(runs)} runs: "
        f"{passed} passed, {len(runs) - passed - errors} failed, {errors} stopped with an error. "
        "Each check follows docs/spec.md of the version its run gives.</p>",
        _matrix(runs_details),
    ]
    parts += [_run_section(i, d, full_paths) for i, d in enumerate(runs_details)]
    return _PAGE.format(title=escape(title), css=_CSS, body="\n".join(parts))


def _verdict(verdict: str) -> str:
    css = {"PASS": "pass", "FAIL": "fail"}.get(verdict, "na")
    return f'<span class="v {css}">{SIGNS.get(verdict, "?")} {escape(verdict)}</span>'


def _matrix(runs_details: list[dict]) -> str:
    ids = check_order(i for d in runs_details for i in d["verdicts"])
    head = "".join(f"<th>{escape(i)}</th>" for i in ids)
    rows = []
    for n, d in enumerate(runs_details):
        cells = "".join(
            f'<td class="c {_css(d["verdicts"].get(i))}" title="{escape(i)}">{SIGNS.get(d["verdicts"].get(i), "")}</td>'
            for i in ids
        )
        result = "error" if d["error"] else "passed" if d["passed"] else f"failed ({d['failed']})"
        rows.append(
            f'<tr><td><a href="#run-{n}">{escape(d["asset"])}</a></td><td>{escape(d["engine"])}</td>'
            f"<td>{escape(d['tool_version'])}</td><td>{escape(d['spec_version'])}</td>{cells}"
            f'<td class="{_css("FAIL" if not d["passed"] else "PASS")}">{result}</td></tr>'
        )
    return (
        f"<table class=matrix><thead><tr><th>Asset</th><th>Engine</th><th>Tool</th><th>Spec</th>{head}"
        f"<th>Result</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _css(verdict: str | None) -> str:
    return {"PASS": "pass", "FAIL": "fail", "N/A": "na"}.get(verdict, "")


def _run_section(n: int, d: dict, full_paths: bool) -> str:
    facts = [
        ("File", file_name(d["file"], full_paths)),
        ("SHA-256", d["sha256"]),
        ("Variants", ", ".join(f"{k}={v}" for k, v in d["variants"].items()) or "none"),
        ("Engine", " ".join([d["engine"], *(f"{k} {v}" for k, v in d["engine_versions"].items())])),
        ("Tool and spec", f"proofmass-check {d['tool_version']}, spec {d['spec_version']}"),
        ("Settings", ", ".join(f"{k} {v}" for k, v in d["settings"].items()) or "not recorded"),
        ("Time", f"{d['seconds']} s" if d["seconds"] is not None else "not recorded"),
    ]
    out = [
        f'<section id="run-{n}"><h2>{escape(d["asset"])} <small>{escape(d["engine"])} · {escape(d["id"])}</small> '
        f"{_verdict('PASS' if d['passed'] else 'FAIL')}</h2>",
        "<dl>" + "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in facts) + "</dl>",
    ]
    if d["engine"] == "newton":
        out.append(f"<p class=note>{NEWTON_NOTE}</p>")
    if d["notes"]:
        out.append("<ul class=notes>" + "".join(f"<li>{escape(str(note))}</li>" for note in d["notes"]) + "</ul>")
    if d["error"]:
        out.append(f"<p>The run stopped with an error:</p><pre>{escape(d['error'])}</pre>")
    checks = sorted(d["checks"], key=lambda c: c["verdict"] == "N/A")  # N/A last, each with its reason
    if checks:
        rows = "".join(
            f"<tr><td><b>{escape(c['id'])}</b><br><small>{escape(c['title'])}</small></td>"
            f"<td>{_verdict(c['verdict'])}</td><td>{_detail(c['detail'])}</td></tr>"
            for c in checks
        )
        out.append(f"<table class=checks><thead><tr><th>Check</th><th>Verdict</th><th>Detail</th></tr></thead>"
                   f"<tbody>{rows}</tbody></table>")  # fmt: skip
    if d["measurements"]:
        rows = "".join(
            f"<tr><td>{escape(m['subject']) or ASSET}</td><td>{escape(m['check'])}</td><td>{escape(m['case'])}</td>"
            f"<td>{escape(m['quantity'])}</td><td class=num>{escape(m['shown_value'])}</td>"
            f"<td class=num>{_limit(m)}</td>"
            f"<td>{escape(m['shown_unit'])}</td><td class=num>{_margin(m['margin'])}</td>"
            f"<td>{_verdict('PASS' if m['ok'] else 'FAIL')}</td></tr>"
            for m in d["measurements"]
        )
        out.append(
            "<table class=measurements><thead><tr><th>Subject</th><th>Check</th><th>Case</th><th>Quantity</th>"
            "<th>Value</th><th>Limit</th><th>Unit</th><th>Margin</th><th></th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    out.append("</section>")
    return "\n".join(out)


def _detail(detail: str) -> str:
    """The detail text as written, one part per line. A part that failed is marked."""
    return "<br>".join(
        f'<span class="fail">{escape(part)}</span>' if part.endswith(" FAIL") else escape(part)
        for part in detail.split("; ")
    )


def _limit(m: dict) -> str:
    """The rule's limit with its bound, or nothing for a number the check does not judge."""
    if m["shown_limit"] == "":
        return ""
    return f"{'≥' if m['bound'] == 'min' else '≤'} {escape(m['shown_limit'])}"


def _margin(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head>
<body><main>
{body}
</main></body></html>
"""

_CSS = """
:root{--bg:#E8E7E3;--raised:#F3F2EF;--line:#C4C2BC;--fg:#141414;--muted:#5F5E5A;--ok:#1E6B34;--bad:#A3221B;
--accent:#AE4207;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#161D25;--raised:#1C242E;--line:#2E3844;--fg:#EEF1F4;--muted:#A6B0BB;
--ok:#6FD08C;--bad:#FF8A80;--accent:#F2762E}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 Archivo,system-ui,"Segoe UI",sans-serif}
main{max-width:1200px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:32px;margin:0 0 8px}h2{font-size:20px;margin:40px 0 12px;padding-top:16px;border-top:2px solid var(--fg)}
h2 small{font-weight:400;color:var(--muted);font-size:14px}
.lede{color:var(--muted);margin:0 0 24px}
table{border-collapse:collapse;width:100%;margin:12px 0;background:var(--raised)}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-weight:600;font-size:13px}
.matrix td.c{text-align:center;font-family:"IBM Plex Mono",Consolas,monospace}
.checks td:nth-child(3){font-family:"IBM Plex Mono",Consolas,monospace;font-size:13px}
.num{text-align:right;font-family:"IBM Plex Mono",Consolas,monospace}
.pass{color:var(--ok)}.fail{color:var(--bad)}.na{color:var(--muted)}
.v{font-weight:600;white-space:nowrap}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 16px;margin:0 0 12px}
dt{color:var(--muted)}dd{margin:0;font-family:"IBM Plex Mono",Consolas,monospace;font-size:13px;overflow-wrap:anywhere}
.note,.notes{color:var(--accent)}
pre{white-space:pre-wrap;background:var(--raised);border:1px solid var(--line);padding:12px;font-size:12px}
"""
