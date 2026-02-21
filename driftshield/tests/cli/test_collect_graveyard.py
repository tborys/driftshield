import json

from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()


class _FakeClient:
    def list_issues(self, repo: str, limit: int):
        return [
            type("Issue", (), {
                "number": 1,
                "title": "Agent drift after tool error",
                "body": "agent used fallback and wrote wrong output",
                "html_url": f"https://github.com/{repo}/issues/1",
            })(),
            type("Issue", (), {
                "number": 2,
                "title": "Frontend CSS bug",
                "body": "button style",
                "html_url": f"https://github.com/{repo}/issues/2",
            })(),
        ]

    def list_issue_comments(self, repo: str, issue_number: int):
        if issue_number == 1:
            return ["Tool schema mismatch ignored"]
        return ["pure ui issue"]


def test_collect_graveyard_command_writes_candidates(tmp_path, monkeypatch):
    from driftshield.cli.commands import collect_graveyard as cmd

    monkeypatch.setattr(cmd, "GhCliClient", lambda: _FakeClient())

    out = tmp_path / "candidates.jsonl"
    result = runner.invoke(
        app,
        [
            "collect-graveyard",
            "--repo",
            "org/repo",
            "--limit-per-repo",
            "20",
            "--output",
            str(out),
        ],
    )

    assert result.exit_code == 0
    assert "Candidates: 1" in result.output
    payload = json.loads(out.read_text().strip())
    assert payload["issue_number"] == 1
