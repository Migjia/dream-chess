"""A live view of a data collection session, on your laptop.

    # first, in Git Bash, keep the tunnel to the station's collector open:
    ssh -N -L 8080:127.0.0.1:8080 dream-nuc
    # then, in another terminal:
    python collect_watch.py            # open http://127.0.0.1:8770

It reads the collector's dashboard through the tunnel once a second and shows the episodes saved, whether one is
recording, and which demo of docs/COLLECTION_GAMES.md the current task text is, with the one after it. It only reads:
nothing is sent to the station.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLAN = Path(__file__).parent / "docs" / "COLLECTION_GAMES.md"


def load_plan(path: Path = PLAN) -> list[dict]:
    """Every demo of the plan, in order: game, number, arm, note, prompt, and the White move before it."""
    demos = []
    text = path.read_text(encoding="utf-8")
    for game, block in re.findall(r"## Game (\d+)\s+```text\n(.*?)```", text, flags=re.S):
        white = ""
        lines = block.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("WHITE:"):
                white = line[7:].strip()
            found = re.match(r"\s*DEMO (\d+)\s+\[(\w+) arm\]\s+(.*)", line)
            if found:
                number, arm, note = found.groups()
                demos.append({"game": int(game), "num": int(number), "arm": arm.lower(), "note": note,
                              "prompt": lines[i + 1].strip(), "white": white})
                white = ""
    return demos


def normalize(text: str) -> str:
    return " ".join((text or "").split()).rstrip(".").lower()


class Watcher:
    def __init__(self, url: str, plan: list[dict], host: str = "dream-nuc", dataset: str = "hackathon_data/chess-teleop"):
        self.url, self.plan, self.host, self.dataset = url.rstrip("/"), plan, host, dataset
        self.lock = threading.Lock()
        self.position = -1  # index in the plan of the demo the current task matches
        self.state: dict = {"connected": False, "message": "Starting..."}
        self.episodes: list[dict] = []  # index, seconds, task, as the dataset records them
        self.episodes_source = ""
        self._last_ssh = 0.0

    def fetch_episodes(self, connected: bool) -> None:
        """The saved episodes: from the collector while it runs, otherwise from the dataset over SSH every 15 s."""
        if connected:
            try:
                with urllib.request.urlopen(self.url + "/api/episodes", timeout=3) as reply:
                    rows = json.loads(reply.read())
                self.episodes = [{"index": r["index"], "seconds": r["seconds"], "task": "; ".join(r.get("tasks") or [])}
                                 for r in rows]
                self.episodes_source = "the collector"
                return
            except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError, OSError, KeyError):
                pass
        if time.monotonic() - self._last_ssh < 15:
            return
        self._last_ssh = time.monotonic()
        try:
            out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", self.host,
                                  f"cat ~/{self.dataset}/meta/episodes.jsonl"],
                                 capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return
        if out.returncode != 0:
            return
        rows = [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
        self.episodes = [{"index": r["episode_index"], "seconds": round(r.get("length", 0) / 30, 1),
                          "task": "; ".join(r.get("tasks") or [])} for r in rows]
        self.episodes_source = "the dataset on the station"

    def history(self) -> dict:
        """Each saved episode matched to its plan demo, in order, plus the plan demos with no episode yet."""
        counts = [0] * len(self.plan)
        rows, pointer = [], -1
        for episode in sorted(self.episodes, key=lambda e: e["index"]):
            key = normalize(episode["task"])
            matches = [i for i, d in enumerate(self.plan) if normalize(d["prompt"]) == key]
            after = [i for i in matches if i >= pointer]
            index = after[0] if after else (matches[-1] if matches else -1)
            if index >= 0:
                pointer = index
                counts[index] += 1
            demo = self.plan[index] if index >= 0 else None
            rows.append({**episode, "demo": demo, "retake": index >= 0 and counts[index] > 1})
        furthest = max((i for i, n in enumerate(counts) if n), default=-1)
        skipped = [self.plan[i] for i in range(furthest + 1) if counts[i] == 0]
        remaining = len(self.plan) - (furthest + 1)
        return {"episodes": list(reversed(rows)), "skipped": skipped, "remaining": remaining,
                "covered": sum(1 for n in counts if n), "furthest": furthest}

    def locate(self, task: str) -> int:
        """The plan demo with this task text: the next one at or after the current position, else the nearest before.

        Some prompts appear in more than one game (Nf6 opens two of them), so the position breaks the tie.
        """
        key = normalize(task)
        matches = [i for i, d in enumerate(self.plan) if normalize(d["prompt"]) == key]
        if not matches:
            return -1
        after = [i for i in matches if i >= self.position]
        return after[0] if after else matches[-1]

    def poll(self) -> None:
        try:
            with urllib.request.urlopen(self.url + "/api/status", timeout=3) as reply:
                status = json.loads(reply.read())
        except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError, OSError):
            self.fetch_episodes(connected=False)
            with self.lock:
                self.state = {"connected": False, "message": "The collector isn't running, so there's no live "
                              "session. Showing what's saved on the station.",
                              "history": self.history(), "source": self.episodes_source,
                              "plan_total": len(self.plan), "updated": time.strftime("%H:%M:%S")}
                furthest = self.state["history"]["furthest"]
                self.state["next_after_furthest"] = self.plan[furthest + 1] if furthest + 1 < len(self.plan) else None
            return
        self.fetch_episodes(connected=True)
        snap = status.get("snapshot") or {}
        task = snap.get("task") or status.get("task") or ""
        index = self.locate(task)
        history = self.history()
        with self.lock:
            if index >= 0:
                self.position = index
            current = self.plan[index] if index >= 0 else None
            if index >= 0:
                upcoming = self.plan[index + 1] if index < len(self.plan) - 1 else None
            else:
                # The task box holds something else (the kit's default, say): suggest the demo after the last saved one.
                after = history["furthest"] + 1
                upcoming = self.plan[after] if after < len(self.plan) else None
            self.state = {
                "connected": True,
                "phase": status.get("phase"),
                "mode": snap.get("mode"),
                "recording": bool(snap.get("recording")),
                "seconds": round(float(snap.get("seconds") or 0), 1),
                "episodes": snap.get("episodes"),
                "task": task,
                "current": current,
                "upcoming": upcoming,
                "plan_total": len(self.plan),
                "plan_index": index,
                "warnings": snap.get("warnings") or [],
                "updated": time.strftime("%H:%M:%S"),
                "history": history,
                "source": self.episodes_source,
            }

    def run(self) -> None:
        while True:
            try:
                self.poll()
            except Exception as err:  # one bad line in the dataset mustn't stop the view for good
                with self.lock:
                    self.state = {**self.state, "connected": False,
                                  "message": f"Couldn't read the latest status ({type(err).__name__}: {err}). Retrying."}
            time.sleep(1)

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.state)


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Collection live</title>
<style>
:root { --ground:#f1f3ee; --surface:#fff; --ink:#1d2721; --quiet:#5b6860; --rule:#d3dbd2; --left:#1f6b4c; --right:#8a4b12; --rec:#c0311a; }
@media (prefers-color-scheme: dark) { :root { --ground:#151b18; --surface:#1d2622; --ink:#e7ede8; --quiet:#a2b0a7; --rule:#34423b; --left:#5fc493; --right:#e0a066; --rec:#ff6b52; } }
body { margin:0; background:var(--ground); color:var(--ink); font:16px/1.45 "Segoe UI", system-ui, sans-serif; }
.wrap { max-width:760px; margin:0 auto; padding:20px max(16px, 3vw) 40px; display:grid; gap:14px; }
h1 { margin:0; font-size:22px; }
.row { display:flex; flex-wrap:wrap; gap:12px; }
.tile { flex:1 1 150px; background:var(--surface); border:1px solid var(--rule); border-radius:10px; padding:12px 14px; }
.tile small { display:block; color:var(--quiet); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
.tile b { font-size:34px; line-height:1.1; font-variant-numeric:tabular-nums; }
.rec b { color:var(--rec); }
.card { background:var(--surface); border:1px solid var(--rule); border-radius:10px; padding:14px; display:grid; gap:6px; }
.card h2 { margin:0; font-size:15px; color:var(--quiet); text-transform:uppercase; letter-spacing:.05em; }
.big { font-size:20px; font-weight:700; }
.arm { color:#fff; font-size:13px; font-weight:700; padding:2px 8px; border-radius:4px; }
.arm.left { background:var(--left); } .arm.right { background:var(--right); }
.prompt { font:14px/1.5 Consolas, monospace; background:var(--ground); border-radius:6px; padding:8px 10px; }
.quiet { color:var(--quiet); font-size:14px; }
.warn { color:var(--rec); }
table { width:100%; border-collapse:collapse; font-size:14px; }
td { padding:5px 6px; border-top:1px solid var(--rule); vertical-align:top; }
td.n { font-variant-numeric:tabular-nums; white-space:nowrap; color:var(--quiet); }
.tag { font-size:12px; font-weight:700; color:var(--rec); }
.copyrow { display:flex; gap:10px; align-items:center; }
button { font:600 15px "Segoe UI", system-ui, sans-serif; padding:8px 14px; border-radius:6px; border:1px solid var(--left);
  background:var(--left); color:#fff; cursor:pointer; }
button:disabled { opacity:.4; cursor:default; }
button:focus-visible { outline:3px solid var(--rec); outline-offset:2px; }
.ok { color:var(--left); font-size:14px; font-weight:600; }
</style>
<div class="wrap">
  <h1>Collection live</h1>
  <div class="row">
    <div class="tile"><small>Episodes saved</small><b id="eps">-</b></div>
    <div class="tile" id="rectile"><small>Recording</small><b id="rec">-</b></div>
    <div class="tile"><small>Plan position</small><b id="pos">-</b></div>
  </div>
  <div class="card"><h2>Next demo</h2><div id="nextwhite" class="quiet"></div><div id="next" class="big">-</div>
    <div id="nextprompt" class="prompt"></div>
    <div class="copyrow"><button id="copynext" type="button">Copy next prompt</button><span id="copiednext" class="ok"></span></div></div>
  <div class="card"><h2>Task on the dashboard now</h2><div id="now" class="big">-</div><div id="nowprompt" class="prompt"></div>
    <div class="copyrow"><button id="copynow" type="button">Copy this prompt</button><span id="copiednow" class="ok"></span></div></div>
  <div class="card"><h2>Recorded so far</h2><div id="summary" class="quiet"></div>
    <div id="skipped" class="quiet"></div><table id="eplist"></table></div>
  <div id="status" class="quiet"></div>
</div>
<script>
const $ = id => document.getElementById(id);
function label(d) { return d ? `Game ${d.game}, demo ${d.num} <span class="arm ${d.arm}">${d.arm} arm</span> <span class="quiet">${d.note.replace(/[<>&]/g, "")}</span>` : "-"; }
let nowText = "", nextText = "";
async function copyText(text, note, box) {
  if (!text) return;
  try { await navigator.clipboard.writeText(text); $(note).textContent = "Copied. Paste it into the dashboard's task box."; }
  catch { const r = document.createRange(); r.selectNodeContents($(box)); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    $(note).textContent = "Selected: press Ctrl+C"; }
  setTimeout(() => { $(note).textContent = ""; }, 3000);
}
document.addEventListener("DOMContentLoaded", () => {
  $("copynext").addEventListener("click", () => copyText(nextText, "copiednext", "nextprompt"));
  $("copynow").addEventListener("click", () => copyText(nowText, "copiednow", "nowprompt"));
});
function esc(t) { return String(t).replace(/[&<>]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"})[c]); }
function history(h, source) {
  if (!h) return;
  $("summary").textContent = `${h.episodes.length} episodes cover ${h.covered} of the plan's demos. ` +
    `${h.remaining} demos still to go after the furthest one recorded. Read from ${source || "nowhere yet"}.`;
  $("skipped").innerHTML = h.skipped.length ? "Skipped so far: " + h.skipped.map(d => `game ${d.game} demo ${d.num}`).join(", ") : "";
  $("eplist").innerHTML = h.episodes.map(e => `<tr><td class="n">#${e.index}</td><td class="n">${e.seconds}s</td><td>` +
    (e.demo ? `Game ${e.demo.game}, demo ${e.demo.num} <span class="arm ${e.demo.arm}">${e.demo.arm}</span> ${esc(e.demo.note)}` +
      (e.retake ? ` <span class="tag">retake</span>` : "") : `<span class="warn">Not in the plan:</span> ${esc(e.task)}`) + `</td></tr>`).join("");
}
async function tick() {
  try {
    const s = await (await fetch("/state", {cache: "no-store"})).json();
    history(s.history, s.source);
    if (!s.connected) { $("status").textContent = s.message; $("status").className = "warn";
      $("rec").textContent = "off"; $("now").textContent = "No live session"; $("nowprompt").textContent = "";
      nowText = ""; $("copynow").disabled = true;
      if (s.history) { $("eps").textContent = s.history.episodes.length;
        const f = s.history.furthest; $("pos").textContent = f >= 0 ? `${f + 1} / ${s.plan_total}` : "-";
        const up = s.next_after_furthest;
        $("next").innerHTML = up ? label(up) : "-";
        $("nextwhite").textContent = up && up.white ? `First, White plays by hand: ${up.white}` : "";
        nextText = up ? up.prompt : ""; $("nextprompt").textContent = nextText; $("copynext").disabled = !nextText; }
      return; }
    $("eps").textContent = s.episodes ?? "-";
    $("rec").textContent = s.recording ? `${s.seconds}s` : "no";
    $("rectile").classList.toggle("rec", s.recording);
    $("pos").textContent = s.plan_index >= 0 ? `${s.plan_index + 1} / ${s.plan_total}` : "?";
    $("now").innerHTML = s.current ? label(s.current) : "Task text isn't one of the plan's prompts";
    nowText = s.current ? s.current.prompt : (s.task || "");
    $("nowprompt").textContent = nowText;
    $("next").innerHTML = s.upcoming ? label(s.upcoming) : "-";
    nextText = s.upcoming ? s.upcoming.prompt : "";
    $("nextprompt").textContent = nextText;
    $("copynow").disabled = !nowText; $("copynext").disabled = !nextText;
    $("nextwhite").textContent = s.upcoming && s.upcoming.white ? `First, White plays by hand: ${s.upcoming.white}` : "";
    const warn = (s.warnings || []).join(" · ");
    $("status").textContent = `${s.mode || ""} · updated ${s.updated}` + (warn ? ` · ${warn}` : "");
    $("status").className = warn ? "warn" : "quiet";
  } catch { $("status").textContent = "This page lost its connection to collect_watch.py."; $("status").className = "warn"; }
}
tick(); setInterval(tick, 1000);
</script></html>"""


def serve(port: int, watcher: Watcher) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/state"):
                body, kind = json.dumps(watcher.snapshot()).encode(), "application/json"
            elif self.path in ("/", "/index.html"):
                body, kind = PAGE.encode(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collector", default="http://127.0.0.1:8080", help="the collector's dashboard, through the tunnel")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--dataset", default="hackathon_data/chess-teleop",
                        help="the dataset folder on the station, under the home folder, read when the collector is off")
    parser.add_argument("--from-game", type=int, default=1, help="leave out the plan's games before this one")
    args = parser.parse_args()
    plan = [demo for demo in load_plan() if demo["game"] >= args.from_game]
    watcher = Watcher(args.collector, plan, dataset=args.dataset)
    threading.Thread(target=watcher.run, daemon=True).start()
    server = serve(args.port, watcher)
    print(f"Collection live: http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
