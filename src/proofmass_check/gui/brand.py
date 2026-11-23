# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The look of proofmass.com for the GUI's page and its HTML report: the Proofmass logo, the favicon and the fonts.

The logo is in logo.svg only. The server puts it in the page, and the report puts it in its file.
The fonts are in static/fonts (SIL OFL 1.1, see NOTICE). The page loads them from its own server;
a report carries them in its file, so that it looks the same on a computer without them.
"""

import base64
from functools import cache
from pathlib import Path

HERE = Path(__file__).parent
STATIC = HERE / "static"
# A report carries the latin files only, as the reports on proofmass.com do: a letter outside them
# takes a font of the computer. (family, weights, file)
REPORT_FONTS = (
    ("Archivo", "100 900", "archivo-latin-standard-normal.woff2"),
    ("IBM Plex Mono", "400", "ibm-plex-mono-latin-400-normal.woff2"),
    ("IBM Plex Mono", "500", "ibm-plex-mono-latin-500-normal.woff2"),
)


@cache
def logo() -> str:
    """The logo as inline SVG. CSS colours its parts: `.logo-word` the text, `.logo-mark` the brand orange."""
    svg = (HERE / "logo.svg").read_text(encoding="utf-8").strip()
    svg = svg.replace(' xmlns="http://www.w3.org/2000/svg"', "", 1)  # SVG in HTML needs no namespace
    return svg.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1)


@cache
def favicon() -> str:
    """The favicon of proofmass.com as a data URL, for a page that is one file."""
    return "data:image/svg+xml;base64," + base64.b64encode((STATIC / "favicon.svg").read_bytes()).decode("ascii")


@cache
def report_fonts() -> str:
    """The @font-face rules of a report, with the fonts in them as data URLs."""
    rules = []
    for family, weights, name in REPORT_FONTS:
        data = base64.b64encode((STATIC / "fonts" / name).read_bytes()).decode("ascii")
        stretch = "font-stretch:62% 125%;" if family == "Archivo" else ""  # one variable file with a width axis
        rules.append(
            f'@font-face{{font-family:"{family}";font-weight:{weights};{stretch}font-display:swap;'
            f'src:url(data:font/woff2;base64,{data}) format("woff2")}}'
        )
    return "\n".join(rules)
