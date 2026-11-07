"""A live development dashboard. It only listens on this computer.

    python dev_server.py
    # then open http://127.0.0.1:8765

Whenever code changes, it replays the simulation and re-runs the tests, and the page updates by
itself. Edit docs/status.json to update the progress list.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DASHBOARD = ROOT / "dreamchess" / "dashboard.html"
STATUS = ROOT / "docs" / "status.json"
WATCHED = ("*.py", "dreamchess/*.py", "dreamchess/*.html", "tests/*.py", "docs/status.json")
RECORD_GAME = (
    "import json; from dreamchess.replay import DEMO_FEN, DEMO_SCRIPT, record_game; "
    "print(json.dumps(record_game(DEMO_FEN, script=list(DEMO_SCRIPT))))"
)


def run(command: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def snapshot(root: Path = ROOT) -> dict[str, float]:
    return {str(p): p.stat().st_mtime for pattern in WATCHED for p in root.glob(pattern) if p.is_file()}


def summarize_tests(output: str, returncode: int) -> dict:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    failures = [line[7:] for line in lines if line.startswith("FAILED ") or line.startswith("ERROR ")]
    summary = lines[-1].strip("= ") if lines else "no output"
    return {"state": "passed" if returncode == 0 else "failed", "summary": summary, "failures": failures[:10]}


def load_progress(path: Path = STATUS) -> dict:
    try:
        groups = json.loads(path.read_text(encoding="utf-8"))["groups"]
    except (OSError, ValueError, KeyError) as err:
        return {"error": f"Can't read {path.name}: {err}", "groups": [], "counts": {}}
    counts = {"done": 0, "simulated": 0, "todo": 0}
    for group in groups:
        for item in group["items"]:
            counts[item["state"]] = counts.get(item["state"], 0) + 1
    return {"groups": groups, "counts": counts}


def git_info() -> dict:
    try:
        branch = run(["git", "branch", "--show-current"]).stdout.strip()
        commit = run(["git", "log", "-1", "--format=%h %s"]).stdout.strip()
        dirty = len(run(["git", "status", "--short"]).stdout.splitlines())
        refs = run(["git", "for-each-ref", "refs/remotes/origin", "--format=%(refname:short)"]).stdout.split()
        names = [r for r in refs if r not in ("origin", "origin/HEAD", "origin/main")]
        merged = run(["git", "branch", "-r", "--merged", "origin/main"]).stdout.split()
        branches = [{"name": n.removeprefix("origin/"), "merged": n in merged} for n in names]
        return {"branch": branch, "commit": commit, "uncommitted": dirty, "branches": branches}
    except (OSError, subprocess.SubprocessError) as err:
        return {"error": str(err), "branches": []}


class LiveState:
    def __init__(self, run_tests: bool = True):
        self.lock = threading.Lock()
        self.run_tests = run_tests
        self.sim_version = 0
        self.sim_html = ""
        self.sim_error = ""
        self.sim_steps = 0
        self.tests = {"state": "waiting", "summary": "Not run yet", "failures": []}
        self.tests_wanted = threading.Event()

    def build_simulation(self) -> None:
        """Run in a new process, so it always uses the latest code and a crash can't stop the server."""
        try:
            from visualize import page_fragment

            result = run([sys.executable, "-c", RECORD_GAME], timeout=60)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no output")
            frames = json.loads(result.stdout)
            head = '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
            head += '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            html = head + page_fragment(frames)
            with self.lock:
                self.sim_html, self.sim_error, self.sim_steps = html, "", len(frames)
                self.sim_version += 1
        except Exception as err:  # keep showing the last good version, with the error beside it
            with self.lock:
                self.sim_error = str(err)

    def test_worker(self) -> None:
        while True:
            self.tests_wanted.wait()
            self.tests_wanted.clear()
            with self.lock:
                self.tests = {**self.tests, "state": "running"}
            try:
                command = [sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider"]
                result = run(command, timeout=900)
                outcome = summarize_tests(result.stdout, result.returncode)
            except (OSError, subprocess.SubprocessError) as err:
                outcome = {"state": "failed", "summary": str(err), "failures": []}
            with self.lock:
                self.tests = {**outcome, "finished": time.strftime("%H:%M:%S")}

    def changed(self) -> None:
        self.build_simulation()
        if self.run_tests:
            self.tests_wanted.set()

    def watch(self, interval: float = 1.0) -> None:
        seen = snapshot()
        self.changed()
        while True:
            time.sleep(interval)
            current = snapshot()
            if current != seen:
                seen = current
                self.changed()

    def state(self) -> dict:
        with self.lock:
            return {
                "simVersion": self.sim_version,
                "simError": self.sim_error,
                "simSteps": self.sim_steps,
                "tests": self.tests,
                "progress": load_progress(),
                "git": git_info(),
            }


def make_handler(live: LiveState):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: str, content_type: str, status: int = 200) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path == "/":
                self._send(DASHBOARD.read_text(encoding="utf-8"), "text/html")
            elif path == "/simulation":
                with live.lock:
                    html = live.sim_html
                self._send(html or "<p>Building the simulation...</p>", "text/html")
            elif path == "/state.json":
                self._send(json.dumps(live.state()), "application/json")
            else:
                self._send("Not found", "text/plain", 404)

        def log_message(self, *args) -> None:
            pass  # the page polls every couple of seconds, so request logs would be noise

    return Handler


def serve(port: int, run_tests: bool = True) -> ThreadingHTTPServer:
    live = LiveState(run_tests)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(live))
    server.live = live
    threading.Thread(target=live.test_worker, daemon=True).start()
    threading.Thread(target=live.watch, daemon=True).start()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-tests", action="store_true", help="only rebuild the simulation")
    args = parser.parse_args()
    server = serve(args.port, not args.no_tests)
    print(f"Dashboard: http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
