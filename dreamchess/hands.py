"""The hand tracker's samples, for the app: runs tools/hand_watch.py in the Dream library's Python and keeps its lines.

The watcher needs the arm model (MuJoCo, in ~/dream-env); the app doesn't have it, so this starts the watcher as a
separate program and reads what it prints. Samples arrive about once a second while the station runs a move.
"""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

WATCHER = Path(__file__).resolve().parent.parent / "tools" / "hand_watch.py"


class HandFeed:
    def __init__(self, python: str, fit: str, script: Path = WATCHER):
        self.python, self.fit = Path(python).expanduser(), Path(fit).expanduser()
        self.lock = threading.Lock()
        self.samples: list[dict] = []  # everything since the app started; a {"run_start": True} begins each run
        self.problem = ""
        self.process: subprocess.Popen | None = None
        if not self.python.exists():
            self.problem = f"no Dream library Python at {self.python}"
        elif not self.fit.exists():
            self.problem = f"no board calibration at {self.fit}: run tools/fit_board.py first"
        else:
            self.process = subprocess.Popen([str(self.python), "-W", "ignore", str(script), str(self.fit)],
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            threading.Thread(target=self._read, daemon=True).start()

    @property
    def ready(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _read(self) -> None:
        for line in self.process.stdout:
            try:
                sample = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                self.samples.append(sample)

    def mark(self) -> int:
        """Where the feed is now; since() returns what arrives after it."""
        with self.lock:
            return len(self.samples)

    def since(self, mark: int) -> tuple[list[dict], int]:
        with self.lock:
            return list(self.samples[mark:]), len(self.samples)

    def latest(self) -> dict | None:
        with self.lock:
            for sample in reversed(self.samples):
                if "t" in sample:
                    return sample
        return None

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
