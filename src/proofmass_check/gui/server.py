# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The local HTTP server of the GUI (docs/gui.md, section 4).

It listens on 127.0.0.1 only. The page and its files need no token. Every API request must carry
the token from the page's URL, so that another web page in the same browser cannot use the API.
The server also checks the Host header, which stops DNS rebinding, and the Origin header, and it
sends no CORS headers (docs/gui.md, section 4.2).
"""

import hmac
import json
import secrets
import sys
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from proofmass_check import __version__
from proofmass_check.gui import report, runs
from proofmass_check.rules import SPEC_VERSION

STATIC = Path(__file__).parent / "static"
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}
MAX_BODY = 1_000_000  # bytes: a request body is a short JSON object
# The page runs only its own files. The token is in the page's URL, so no page it links to may
# receive that URL as a referrer.
HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
}


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status


class App:
    """What the server keeps between requests: the token and the folders opened in this session."""

    def __init__(self, token: str):
        self.token = token
        self.folders: dict[str, runs.Folder] = {}
        self._lock = threading.Lock()
        self._next_id = 1

    def open(self, path: str | Path) -> str:
        """Read a folder, and give its ID. A folder that is open already is read again."""
        folder = runs.scan(path)
        with self._lock:
            for folder_id, known in self.folders.items():
                if known.path == folder.path:
                    self.folders[folder_id] = folder
                    return folder_id
            folder_id = f"f{self._next_id}"
            self._next_id += 1
            self.folders[folder_id] = folder
            return folder_id

    def close(self, folder_id: str) -> None:
        with self._lock:
            self.folders.pop(folder_id, None)

    def folder(self, folder_id) -> runs.Folder:
        try:
            return self.folders[folder_id]
        except (KeyError, TypeError):
            raise ApiError(HTTPStatus.NOT_FOUND, f"no open folder {folder_id}") from None

    def run(self, ref) -> runs.Run:
        """A run from [folder ID, run ID]."""
        if not isinstance(ref, list | tuple) or len(ref) != 2:
            raise ApiError(HTTPStatus.BAD_REQUEST, "a run is [folder ID, run ID]")
        try:
            return self.folder(ref[0]).run(ref[1])
        except KeyError:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no run {ref[1]} in folder {ref[0]}") from None

    def folder_json(self, folder_id: str) -> dict:
        folder = self.folder(folder_id)
        return {
            "id": folder_id,
            "path": str(folder.path),
            "name": folder.path.name or str(folder.path),
            "runs": [runs.summary(run) for run in folder.runs],
            "problems": [{"file": file, "why": why} for file, why in folder.problems],
            "truncated": folder.truncated,
        }

    def state(self) -> dict:
        return {
            "version": __version__,
            "spec_version": SPEC_VERSION,
            "folders": [self.folder_json(folder_id) for folder_id in list(self.folders)],
        }


class Handler(BaseHTTPRequestHandler):
    app: App  # set on the subclass that make_server() makes
    server_version = "proofmass-check"

    def log_message(self, format, *args):
        """Only errors go to the terminal, not every request."""

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method: str) -> None:
        url = urlsplit(self.path)
        if not self._host_ok():
            return self._send_json(HTTPStatus.FORBIDDEN, {"error": "the Host header is not this server"})
        if not url.path.startswith("/api/"):
            if method != "GET":
                return self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": f"{method} is not allowed here"})
            return self._static(url.path)
        if not self._origin_ok():
            return self._send_json(HTTPStatus.FORBIDDEN, {"error": "the request comes from another site"})
        if not hmac.compare_digest(self.headers.get("X-Token", ""), self.app.token):
            return self._send_json(HTTPStatus.FORBIDDEN, {"error": "no token, or a wrong one"})
        try:
            body = self._body() if method == "POST" else {}
            status, kind, payload = self._api(method, url.path, parse_qs(url.query), body)
        except ApiError as e:
            return self._send_json(e.status, {"error": str(e)})
        except Exception:  # noqa: BLE001  the page must get an answer, whatever went wrong
            traceback.print_exc(file=sys.stderr)
            return self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "the server failed: see its terminal"})
        if kind == "json":
            return self._send_json(status, payload)
        return self._send(status, kind, payload.encode("utf-8"))

    # --- checks on every request

    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self._allowed_hosts()

    def _origin_ok(self) -> bool:
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{host}" for host in self._allowed_hosts()}

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Content-Length is not a number") from None
        if length > MAX_BODY:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "the request is too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(HTTPStatus.BAD_REQUEST, "the request is not JSON") from None
        if not isinstance(body, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "the request is not a JSON object")
        return body

    # --- the API

    def _api(self, method: str, path: str, query: dict, body: dict) -> tuple[HTTPStatus, str, object]:
        """The answer to an API request: (status, "json" or a content type, payload)."""
        routes = {
            ("GET", "/api/state"): lambda: self.app.state(),
            ("POST", "/api/open"): lambda: self._open(body),
            ("POST", "/api/reload"): lambda: self.app.folder_json(
                self.app.open(self.app.folder(body.get("folder")).path)
            ),
            ("POST", "/api/close"): lambda: self._close(body),
            ("GET", "/api/run"): lambda: runs.details(self.app.run([_one(query, "folder"), _one(query, "run")])),
            ("POST", "/api/compare"): lambda: runs.compare(self._runs(body, at_least=2)),
            ("POST", "/api/pair"): lambda: runs.pair_folders(
                self.app.folder(body.get("a")), self.app.folder(body.get("b"))
            ),
            ("POST", "/api/report"): lambda: self._report(body),
        }
        if (method, path) not in routes:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no API {method} {path}")
        answer = routes[method, path]()
        return answer if isinstance(answer, tuple) else (HTTPStatus.OK, "json", answer)

    def _open(self, body: dict) -> dict:
        path = str(body.get("path", "")).strip().strip('"')
        if not path:
            raise ApiError(HTTPStatus.BAD_REQUEST, "give the path of a folder")
        try:
            return self.app.folder_json(self.app.open(path))
        except OSError as e:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(e)) from None

    def _close(self, body: dict) -> dict:
        self.app.close(body.get("folder"))
        return self.app.state()

    def _runs(self, body: dict, at_least: int) -> list[runs.Run]:
        refs = body.get("runs")
        if not isinstance(refs, list) or len(refs) < at_least:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"this needs {at_least} runs or more")
        return [self.app.run(ref) for ref in refs]

    def _report(self, body: dict) -> tuple[HTTPStatus, str, str]:
        chosen = self._runs(body, at_least=1)
        full_paths = bool(body.get("full_paths", False))
        if body.get("format") == "csv":
            return HTTPStatus.OK, "text/csv; charset=utf-8", report.to_csv(chosen, full_paths)
        title = str(body.get("title") or "proofmass-check results")
        return HTTPStatus.OK, "text/html; charset=utf-8", report.to_html(chosen, title, full_paths)

    # --- answers

    def _static(self, path: str) -> None:
        name = "index.html" if path == "/" else path.lstrip("/")
        file = STATIC / name
        # Only the files directly in static/: a name with a "/" or ".." never leaves that folder.
        if "/" in name or "\\" in name or file.suffix not in TYPES or not file.is_file():
            return self._send_json(HTTPStatus.NOT_FOUND, {"error": f"no file {path}"})
        self._send(HTTPStatus.OK, TYPES[file.suffix], file.read_bytes())

    def _send_json(self, status: HTTPStatus, payload) -> None:
        body = json.dumps(runs.finite_json(payload), allow_nan=False).encode("utf-8")
        self._send(status, "application/json", body)

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def _one(query: dict, name: str) -> str:
    """One value of a URL's query, or "" when it has none."""
    return query.get(name, [""])[0]


def make_server(app: App, port: int = 0) -> ThreadingHTTPServer:
    """A server on 127.0.0.1. Port 0 takes a free port."""
    handler = type("AppHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def serve(folders: list[Path], port: int = 0, open_browser: bool = True) -> int:
    """Open the folders, serve the page until Ctrl+C, and give the exit status."""
    app = App(secrets.token_urlsafe(24))
    for folder in folders:
        app.open(folder)
    server = make_server(app, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/?token={app.token}"
    print(f"proofmass-check GUI: {url}\nPress Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
