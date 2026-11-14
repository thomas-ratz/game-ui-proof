"""Serves the project root for UI previews, and lets the preview pages save their tuning next to themselves.

    python docs/mockups/kit/serve.py              # from the project root, http://127.0.0.1:8765/
    python docs/mockups/kit/serve.py --port 9000 --root path/to/project --mockups design/previews

A page's tuning panel saves every change to <feature>/values.draft.json (so the current tuning can be read at any
time) and, on Save, writes <feature>/values.json (the approved spec). Only those two files, only directly inside
<root>/<mockups>/<feature>/ where a manifest.json exists, only from pages this server served. Stdlib only.
"""
import argparse
import functools
import http.server
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import unquote

WRITABLE = {"values.json", "values.draft.json"}
MAX_BODY = 1_000_000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, mockups, **kwargs):
        self.mockups = mockups
        super().__init__(*args, **kwargs)

    def hosts(self):
        port = self.server.server_address[1]
        return {f"localhost:{port}", f"127.0.0.1:{port}"}

    def parse_request(self):
        if not super().parse_request():
            return False
        # DNS rebinding: a foreign page whose domain now points at 127.0.0.1 still sends its own Host.
        if self.headers.get("Host") not in self.hosts():
            self.send_error(403, "unexpected Host")
            return False
        return True

    def end_headers(self):
        # Previews are edited while open: never serve a stale page, kit file or values.json.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/__preview":
            return self.reply(200, {"ok": True})
        super().do_GET()

    def do_POST(self):
        if self.path != "/__save":
            return self.reply(404, {"error": "unknown endpoint"})
        if self.headers.get("Origin") not in {f"http://{host}" for host in self.hosts()}:
            return self.reply(403, {"error": "saves are only accepted from pages this server served"})
        # Forms can't send JSON, so this also keeps out cross-site "simple" requests.
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.reply(415, {"error": "expected application/json"})
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.reply(411, {"error": "missing Content-Length"})
        if not 0 < length <= MAX_BODY:
            return self.reply(413, {"error": f"body must be 1..{MAX_BODY} bytes"})
        try:
            body = json.loads(self.rfile.read(length))
            target = (self.root() / unquote(body["path"]).lstrip("/")).resolve()
            if (target.name not in WRITABLE or target.parent.parent != self.root() / self.mockups
                    or not (target.parent / "manifest.json").is_file()):
                return self.reply(403, {"error": f"not a preview values file: {body['path']}"})
            text = json.dumps(body["data"], indent=2, ensure_ascii=False) + "\n"
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False) as tmp:
                tmp.write(text)
            try:
                os.replace(tmp.name, target)
            except OSError:
                os.unlink(tmp.name)
                raise
            self.reply(200, {"saved": target.relative_to(self.root()).as_posix()})
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
            self.reply(400, {"error": str(error)})

    def root(self):
        return Path(self.directory).resolve()

    def reply(self, status, data):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root", default=".")
    parser.add_argument("--mockups", default="docs/mockups", help="the previews folder, from the root")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    mockups = (root / args.mockups).resolve().relative_to(root)
    handler = functools.partial(Handler, directory=str(root), mockups=mockups)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Serving {root} at http://127.0.0.1:{server.server_address[1]}/ (previews in {mockups.as_posix()} can save their values)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
