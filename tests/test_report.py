import json

from verifier import cli


def test_show_replays_saved_report(tmp_path, monkeypatch, capsys):
    report = {"task": "task-x", "decision": "MERGE", "attempts": 0,
              "flags": [], "tests": {"exit_code": 0, "summary": "8 passed"},
              "risk": {"score": 1, "reason": "low", "areas": []},
              "steps": [{"n": 1, "kind": "tool_call", "tool": "bash",
                         "detail": "pytest -q", "files": [], "result": "8 passed",
                         "ok": True}],
              "seconds": 1.0, "cost_usd": None}
    monkeypatch.setattr(cli, "REPORTS", str(tmp_path))
    (tmp_path / "task-x.json").write_text(json.dumps(report))
    assert cli.main(["show", "task-x"]) == 0
    out = capsys.readouterr().out
    assert "MERGE" in out and "replay: 1 steps" in out
