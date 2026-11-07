import json
import time
import urllib.error
import urllib.request

import pytest

import dev_server


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
        return response.status, response.read().decode("utf-8")


@pytest.fixture(scope="module")
def server():
    srv = dev_server.serve(0, run_tests=False)
    import threading

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    deadline = time.time() + 30
    while srv.live.sim_version == 0 and not srv.live.sim_error and time.time() < deadline:
        time.sleep(0.1)
    yield srv
    srv.shutdown()


def test_only_listens_on_this_computer(server):
    assert server.server_address[0] == "127.0.0.1"


def test_serves_dashboard_and_real_simulation(server):
    port = server.server_address[1]
    assert "Dream Chess live" in get(port, "/")[1]
    page = get(port, "/simulation")[1]
    assert page.startswith("<!doctype html>")
    assert "Checkmate. White wins." in page


def test_state_reports_simulation_and_progress(server):
    state = json.loads(get(server.server_address[1], "/state.json")[1])
    assert state["simError"] == ""
    assert state["simSteps"] > 0
    assert state["progress"]["counts"]["todo"] > 0


def test_unknown_paths_are_refused(server):
    with pytest.raises(urllib.error.HTTPError) as err:
        get(server.server_address[1], "/../requirements.txt")
    assert err.value.code == 404


def test_broken_code_keeps_the_last_good_simulation(monkeypatch):
    live = dev_server.LiveState(run_tests=False)
    live.build_simulation()
    good = live.sim_html
    assert good
    monkeypatch.setattr(dev_server, "RECORD_GAME", "raise ValueError('broken agent code')")
    live.build_simulation()
    assert "broken agent code" in live.sim_error
    assert live.sim_html == good


def test_summarizes_passing_and_failing_tests():
    assert dev_server.summarize_tests("....\n4 passed in 1s\n", 0) == {
        "state": "passed", "summary": "4 passed in 1s", "failures": [],
    }
    failed = dev_server.summarize_tests("F\nFAILED tests/a.py::b - boom\n1 failed in 1s\n", 1)
    assert failed["state"] == "failed"
    assert failed["failures"] == ["tests/a.py::b - boom"]


def test_watcher_notices_a_changed_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_server, "WATCHED", ("*.py",))
    code = tmp_path / "x.py"
    code.write_text("a")
    before = dev_server.snapshot(tmp_path)
    code.write_text("b")
    import os

    os.utime(code, (time.time() + 5, time.time() + 5))
    assert dev_server.snapshot(tmp_path) != before


def test_bad_status_file_is_reported_not_fatal(tmp_path):
    bad = tmp_path / "status.json"
    bad.write_text("{not json")
    result = dev_server.load_progress(bad)
    assert "error" in result and result["groups"] == []


def test_status_file_only_uses_known_states():
    groups = dev_server.load_progress()["groups"]
    states = {item["state"] for group in groups for item in group["items"]}
    assert states <= {"done", "simulated", "todo"}
