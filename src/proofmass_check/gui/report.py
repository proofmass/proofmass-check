# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""A report of runs: one HTML file that opens without the GUI or a network, and a CSV file.

The report leaves out nothing from results.json and adds no verdict of its own (docs/gui.md,
section 6.8). It gives the asset's file name only, unless asked for the full path: the path in
results.json can hold the user's name.
"""

import csv
import io
import math
import re
from datetime import datetime
from html import escape

from proofmass_check import __version__
from proofmass_check.checks import TITLES
from proofmass_check.gui import brand
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
    """The report as one HTML page with its CSS, fonts and logo in it, in the look of the reports on proofmass.com.

    made: when it was made, for the first lines of the page.
    """
    made = made or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    runs_details = [details(run) for run in runs]
    passed = sum(d["passed"] for d in runs_details)
    errors = sum(bool(d["error"]) for d in runs_details)
    failed = len(runs) - passed - errors
    engines = sorted({d["engine"] for d in runs_details})
    meta = [f"Made {made}", f"proofmass-check {__version__}", *engines]
    stats = [
        (len(runs), "Runs", ""),
        (passed, "Passed", "ok" if passed else ""),
        (failed, "Failed", "bad" if failed else ""),
        (errors, "Stopped with an error", "bad" if errors else ""),
    ]
    parts = [
        "<section class=hero><p class=eyebrow>proofmass-check results</p>",
        f"<h1>{escape(title)}</h1>",
        "<ul class=meta>" + "".join(f"<li>{escape(m)}</li>" for m in meta) + "</ul>",
        "<p class=lead>Each check follows docs/spec.md of the version its run gives. A check that does not "
        "apply to an asset is N/A, with the reason, and does not fail the run.</p></section>",
        "<div class=stats>"
        + "".join(f'<div class="stat {kind}"><b>{n}</b><span>{label}</span></div>' for n, label, kind in stats)
        + "</div>",
        "<h2>Runs</h2><p class=sub>A column for each check: ✓ passed, ✕ failed, · N/A.</p>",
        _matrix(runs_details),
    ]
    incomplete = sum(bool(d.get("engine_cannot_run")) for d in runs_details)
    if incomplete:
        parts.append(
            f"<p class=callout>{incomplete} of these runs did not run every check their asset needs: their engine "
            "cannot run it yet. They carry the mark &quot;not run&quot;, and a pass does not cover those checks.</p>"
        )
    ungripped = sum(bool(d.get("gripper_without_site")) for d in runs_details)
    if ungripped:
        parts.append(
            f"<p class=callout>{ungripped} of these assets have joints that look like a gripper's fingers but no "
            "gripper site, so GRIP and SHAKE did not run. They carry the mark &quot;grip not checked&quot;.</p>"
        )
    undescribed = sum(bool(d.get("wheels_without_mobile")) for d in runs_details)
    if undescribed:
        parts.append(
            f"<p class=callout>{undescribed} of these assets have joints that look like wheels but no "
            "SimReady_Metadata.mobile, so their wheeled checks did not run. They carry the mark "
            "&quot;wheels not checked&quot;.</p>"
        )
    parts += [_run_section(i, d, full_paths) for i, d in enumerate(runs_details)]
    return _PAGE.format(
        title=escape(title),
        favicon=brand.favicon(),
        css=brand.report_fonts() + _CSS,
        logo=brand.logo(),
        body="\n".join(parts),
        version=escape(__version__),
    )


def _verdict(verdict: str) -> str:
    css = {"PASS": "pass", "FAIL": "fail"}.get(verdict, "na")
    return f'<span class="v {css}">{SIGNS.get(verdict, "?")} {escape(verdict)}</span>'


def _result(d: dict) -> str:
    """The result of a run: passed, failed with the number of failed checks, or stopped with an error.

    A run whose engine could not run every check its asset needs carries "N not run" next to it, and an asset
    whose joints look like wheels but that has no mobile description carries "wheels not checked".
    """
    if d["error"]:
        main = '<span class="v err">error</span>'
    elif d["passed"]:
        main = '<span class="v pass">✓ passed</span>'
    else:
        main = f'<span class="v fail">✕ failed ({d["failed"]})</span>'
    marks = []
    gaps = d.get("engine_cannot_run", [])
    if gaps:
        names = ", ".join(gaps)
        why = f"The {d['engine']} engine cannot run {names} on this asset yet, so this result does not cover them."
        marks.append(f'<span class=badge title="{escape(why)}">{len(gaps)} not run: {escape(names)}</span>')
    wheels = d.get("wheels_without_mobile", [])
    if wheels:
        why = (
            f"{', '.join(wheels)} look like wheels, but the asset has no SimReady_Metadata.mobile, so STAND, "
            "DRIVE, TURN and STEER did not run."
        )
        marks.append(f'<span class=badge title="{escape(why)}">wheels not checked</span>')
    fingers = d.get("gripper_without_site", [])
    if fingers:
        why = (
            f"{', '.join(fingers)} look like a gripper's fingers, but the asset has no gripper site, so GRIP and "
            "SHAKE did not run."
        )
        marks.append(f'<span class=badge title="{escape(why)}">grip not checked</span>')
    return " ".join([main, *marks])


def _matrix(runs_details: list[dict]) -> str:
    ids = check_order(i for d in runs_details for i in d["verdicts"])
    head = "".join(f'<th class=c title="{escape(i)}: {escape(TITLES.get(i, ""))}">{escape(i)}</th>' for i in ids)
    rows = []
    for n, d in enumerate(runs_details):
        cells = "".join(
            f'<td class="c {_css(d["verdicts"].get(i))}" title="{escape(i)}">{SIGNS.get(d["verdicts"].get(i), "")}</td>'
            for i in ids
        )
        rows.append(
            f'<tr><td><a href="#run-{n}">{escape(d["asset"])}</a></td><td>{escape(d["engine"])}</td>'
            f"<td class=mono>{escape(d['tool_version'])}</td><td class=mono>{escape(d['spec_version'])}</td>{cells}"
            f"<td>{_result(d)}</td></tr>"
        )
    return (
        f"<div class=scroll><table class=matrix><thead><tr><th>Asset</th><th>Engine</th><th>Tool</th><th>Spec</th>"
        f"{head}<th>Result</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
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
        ("Settings", _settings(d["settings"])),
        ("Time", f"{d['seconds']} s" if d["seconds"] is not None else "not recorded"),
    ]
    if d.get("replay"):  # docs/gui.md, section 6.8: the motion is too large for a report that opens by itself
        facts.append(("Replay", "recorded next to the results file, where the GUI plays it; not in this report"))
    out = [
        f'<section class=run id="run-{n}"><h2>{escape(d["asset"])} '
        f"<small>{escape(d['engine'])} · {escape(d['id'])}</small> {_result(d)}</h2>",
        "<dl class=facts>" + "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in facts) + "</dl>",
    ]
    if d["engine"] == "newton":
        out.append(f"<p class=callout>{NEWTON_NOTE}</p>")
    if d["notes"]:
        out.append("<ul class=notes>" + "".join(f"<li>{escape(str(note))}</li>" for note in d["notes"]) + "</ul>")
    if d["error"]:
        out.append(f"<p>The run stopped with an error:</p><pre>{escape(d['error'])}</pre>")
    checks = sorted(d["checks"], key=lambda c: c["verdict"] == "N/A")  # N/A last, each with its reason
    if checks:
        rows = "".join(
            f"<tr><td><span class=mono>{escape(c['id'])}</span><br><span class=na>{escape(c['title'])}</span></td>"
            f"<td>{_verdict(c['verdict'])}</td><td class=detail>{_detail(c['detail'])}</td></tr>"
            for c in checks
        )
        out.append(f"<div class=scroll><table class=checks><thead><tr><th>Check</th><th>Verdict</th><th>Detail</th>"
                   f"</tr></thead><tbody>{rows}</tbody></table></div>")  # fmt: skip
    if d["measurements"]:
        rows = "".join(
            f"<tr><td class=mono>{escape(m['subject']) or ASSET}</td><td class=mono>{escape(m['check'])}</td>"
            f"<td>{escape(m['case'])}</td><td>{escape(m['quantity'])}</td>"
            f"<td class=num>{escape(m['shown_value'])}</td><td class=num>{_limit(m)}</td>"
            f"<td class=mono>{escape(m['shown_unit'])}</td><td class=num>{_margin(m['margin'])}</td>"
            f"<td>{_verdict('PASS' if m['ok'] else 'FAIL')}</td></tr>"
            for m in d["measurements"]
        )
        out.append(
            "<div class=scroll><table class=measurements><thead><tr><th>Subject</th><th>Check</th><th>Case</th>"
            "<th>Quantity</th><th class=num>Value</th><th class=num>Limit</th><th>Unit</th>"
            "<th class=num title='How much of its limit the value uses'>Margin</th><th></th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )
    out.append("</section>")
    return "\n".join(out)


def _settings(settings: dict) -> str:
    """A run's settings as the GUI gives them: tolerances in mm and deg, the floor in mm. Any other as written."""
    parts, rest = [], dict(settings)

    def number(key):
        value = rest.pop(key, None)
        return value if isinstance(value, int | float) and not isinstance(value, bool) else None

    if (value := number("settle_s")) is not None:
        parts.append(f"settle {value:g} s")
    if (value := number("linear_tol")) is not None:
        parts.append(f"linear tolerance {round(value * 1000, 3):g} mm")
    if (value := number("angular_tol")) is not None:
        parts.append(f"angular tolerance {round(math.degrees(value), 3):g} deg")
    if (value := number("random_poses")) is not None:
        parts.append(f"{value:g} random poses")
    if "floor" in rest:
        floor = number("floor")
        parts.append("no floor" if floor is None else f"floor at {floor * 1000:.1f} mm")
    parts += [f"{key} {value}" for key, value in rest.items()]
    return " · ".join(parts) or "not recorded"


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
    """How much of its limit a value uses, as the GUI shows it: 100 % is at the limit."""
    return "" if value is None else f"{value:.0%}"


# The page links to nothing it loads: its CSS, fonts, logo and favicon are in it.
_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>{title}</title><link rel="icon" href="{favicon}">
<style>{css}</style></head>
<body><header class=top><div class=wrap><a class=brand href="https://proofmass.com" aria-label="Proofmass">{logo}</a>
<span class=kind>proofmass-check report</span></div></header>
<main class=wrap>
{body}
</main>
<footer><div class=wrap><span>Made with proofmass-check {version}</span>
<a href="https://github.com/proofmass/proofmass-check">github.com/proofmass/proofmass-check</a></div></footer>
</body></html>
"""

# The CSS of the reports on proofmass.com: ash paper, white tables, one orange, square corners.
_CSS = """
:root{--bg:#F4F4F1;--raised:#FFFFFF;--fg:#141414;--muted:#474744;--dim:#5F5E5A;--line:#D3D3CF;
--accent:#AE4207;--fill:#E85D0E;--ok:#1E6B34;--ok-bg:#E3EFE4;--bad:#A3221B;--bad-bg:#F6E1DE;--warn:#8A5300;
--f-body:"Archivo",system-ui,-apple-system,"Segoe UI",sans-serif;
--f-mono:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,monospace;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#161D25;--raised:#1C242E;--fg:#EEF1F4;--muted:#A6B0BB;--dim:#8A95A1;
--line:#2E3844;--accent:#F2762E;--fill:#F2762E;--ok:#6FD08C;--ok-bg:#1B3326;--bad:#FF8A80;--bad-bg:#3A2124;
--warn:#F5C26B}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 var(--f-body)}
.wrap{max-width:1120px;margin:0 auto;padding:0 16px}
header.top{border-bottom:1px solid var(--line)}
header.top .wrap{display:flex;justify-content:space-between;align-items:center;height:52px}
.brand{display:inline-flex;align-items:center;color:var(--fg);text-decoration:none}
.brand svg{display:block;height:17px;width:auto;aspect-ratio:605/74}
.logo-word{fill:currentColor}.logo-mark{fill:var(--fill)}
.kind{font:12px var(--f-mono);color:var(--dim)}
.hero{padding:36px 0 8px}
.eyebrow{font:500 12px var(--f-mono);color:var(--accent);letter-spacing:.08em;text-transform:uppercase;margin:0 0 8px}
h1{font-weight:700;font-stretch:90%;font-size:34px;line-height:1.1;margin:0 0 10px;letter-spacing:-.01em;
overflow-wrap:anywhere}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;font:13px var(--f-mono);color:var(--dim);margin:0;padding:0;
list-style:none}
.lead{max-width:760px;color:var(--muted);margin:16px 0 0}
h2{font-weight:650;font-stretch:95%;font-size:20px;margin:40px 0 4px;display:flex;flex-wrap:wrap;align-items:baseline;
gap:6px 12px;overflow-wrap:anywhere}
h2 small{font:13px var(--f-mono);color:var(--dim)}
.sub{color:var(--dim);font-size:13px;margin:4px 0 12px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);
border:1px solid var(--line);margin:24px 0 0}
.stat{background:var(--raised);padding:14px 16px}
.stat b{display:block;font:500 26px/1.2 var(--f-mono)}
.stat span{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
.stat.ok b{color:var(--ok)}.stat.bad b{color:var(--bad)}
section.run{border-top:1px solid var(--line);margin-top:48px}
section.run h2{margin-top:20px}
.scroll{overflow-x:auto;border:1px solid var(--line);background:var(--raised);margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:8px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:0}
th{font:500 11.5px var(--f-mono);color:var(--dim);text-transform:uppercase;letter-spacing:.06em;white-space:nowrap;
background:var(--bg)}
td.num,th.num{text-align:right;font-family:var(--f-mono);white-space:nowrap}
td.c,th.c{text-align:center;padding-left:4px;padding-right:4px}
td.c{font-family:var(--f-mono)}
td.detail{font:12.5px/1.6 var(--f-mono);overflow-wrap:anywhere}
.mono,code{font-family:var(--f-mono);font-size:.92em}
.v{display:inline-block;font:500 11.5px/1 var(--f-mono);padding:4px 7px;text-transform:uppercase;letter-spacing:.05em;
white-space:nowrap}
.v.pass{color:var(--ok);background:var(--ok-bg)}.v.fail,.v.err{color:var(--bad);background:var(--bad-bg)}
.v.na{color:var(--dim);padding-left:0}
.badge{display:inline-block;font:500 11px/18px var(--f-mono);padding:0 6px;border:1px solid var(--accent);
color:var(--accent);white-space:nowrap}
.pass{color:var(--ok)}.fail{color:var(--bad)}.na{color:var(--dim)}
dl.facts{display:grid;grid-template-columns:max-content 1fr;gap:4px 18px;margin:16px 0;font-size:14px}
dt{color:var(--dim)}dd{margin:0;font:13px var(--f-mono);overflow-wrap:anywhere}
.callout{border-left:3px solid var(--fill);background:var(--raised);padding:12px 16px;margin:16px 0}
ul.notes{padding-left:18px;color:var(--warn)}ul.notes li{margin:4px 0}
pre{white-space:pre-wrap;background:var(--raised);border:1px solid var(--bad);padding:12px;font:12px/1.45 var(--f-mono)}
a{color:var(--accent)}
footer{margin:56px 0 0;border-top:1px solid var(--line)}
footer .wrap{padding:16px;font:12px var(--f-mono);color:var(--dim);display:flex;justify-content:space-between;gap:12px;
flex-wrap:wrap}
@media print{body{background:#fff}.scroll{overflow:visible}}
"""
