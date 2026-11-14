"""Regression check for serve.py: starts it on a free port over a throwaway project and probes what it must refuse.

    python test_serve.py      # exit code = failed checks
"""
import http.client
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

SERVE = Path(__file__).with_name("serve.py")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    project = Path(tempfile.mkdtemp())
    for folder in ["docs/mockups/feat", "docs/mockups/my feat é", "docs/mockups/feat/sub", "Packages"]:
        (project / folder).mkdir(parents=True)
        (project / folder / "manifest.json").write_text("{}")
    (project / "docs/mockups/kit").mkdir()
    port = free_port()
    good_host, good_origin = f"127.0.0.1:{port}", f"http://localhost:{port}"
    server = subprocess.Popen([sys.executable, str(SERVE), "--port", str(port), "--root", str(project)], stdout=subprocess.DEVNULL)
    failures = []

    def request(method, path, body=b"", host=good_host, origin=good_origin, ctype="application/json", length=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"Host": host, "Content-Type": ctype, "Content-Length": str(len(body) if length is None else length)}
        if origin:
            headers["Origin"] = origin
        try:
            conn.request(method, path, body, headers)
            return conn.getresponse().status
        except OSError as error:
            return type(error).__name__
        finally:
            conn.close()

    def save(path, **kw):
        return request("POST", "/__save", json.dumps({"path": path, "data": {"ok": 1}}).encode(), **kw)

    def check(name, got, want):
        print(f"{'ok  ' if got == want else 'FAIL'} {name}: {got} (want {want})")
        if got != want:
            failures.append(name)

    try:
        for _ in range(50):
            if request("GET", "/__preview") == 200:
                break
            time.sleep(0.1)
        check("GET file", request("GET", "/docs/mockups/feat/manifest.json"), 200)
        check("GET foreign Host (rebinding)", request("GET", "/docs/mockups/feat/manifest.json", host=f"evil.test:{port}"), 403)
        check("GET directory listing", request("GET", "/docs/mockups/"), 404)
        check("save", save("/docs/mockups/feat/values.json"), 200)
        check("save draft", save("/docs/mockups/feat/values.draft.json"), 200)
        check("save, folder with space + non-ASCII, percent-encoded", save(quote("/docs/mockups/my feat é/values.json")), 200)
        check("saved file", (project / "docs/mockups/my feat é/values.json").is_file(), True)
        check("no temp files left", sorted(p.name for p in (project / "docs/mockups/feat").iterdir()),
              ["manifest.json", "sub", "values.draft.json", "values.json"])
        check("save, no Origin", save("/docs/mockups/feat/values.json", origin=None), 403)
        check("save, foreign Origin (CSRF)", save("/docs/mockups/feat/values.json", origin="http://evil.test"), 403)
        check("save, foreign Host", save("/docs/mockups/feat/values.json", host=f"evil.test:{port}"), 403)
        check("save, text/plain", save("/docs/mockups/feat/values.json", ctype="text/plain"), 415)
        check("save, traversal", save("/docs/mockups/feat/../../../values.json"), 403)
        check("save, outside root", save("/../values.json"), 403)
        check("save, Unity Packages/manifest.json", save("/Packages/values.json"), 403)
        check("save, nested folder", save("/docs/mockups/feat/sub/values.json"), 403)
        check("save, folder without manifest", save("/docs/mockups/kit/values.json"), 403)
        check("save, other file name", save("/docs/mockups/feat/manifest.json"), 403)
        check("Content-Length negative", request("POST", "/__save", length=-1), 413)
        check("Content-Length zero", request("POST", "/__save", length=0), 413)
        check("Content-Length oversized", request("POST", "/__save", length=2_000_000), 413)
        check("Content-Length missing", request("POST", "/__save", length=""), 411)
        for name, body in [("not JSON", b"nope"), ("list body", b"[]"), ("path not a string", b'{"path": 5, "data": {}}'),
                           ("no data", b'{"path": "/docs/mockups/feat/values.json"}')]:
            check(f"bad body, {name}", request("POST", "/__save", body), 400)
        check("still serving", request("GET", "/__preview"), 200)
        check("nothing written outside previews", sorted(p.name for p in project.rglob("values*.json")),
              ["values.draft.json", "values.json", "values.json"])
    finally:
        server.terminate()
        server.wait()
        shutil.rmtree(project, ignore_errors=True)
    print(f"{len(failures)} failed" if failures else "all passed")
    sys.exit(len(failures))


if __name__ == "__main__":
    main()
