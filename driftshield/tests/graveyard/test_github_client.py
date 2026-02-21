import json

from driftshield.graveyard.github_client import GhCliClient


def test_list_issues_paginates_until_limit(monkeypatch):
    calls = []

    def fake_check_output(cmd, text=True):
        calls.append(cmd)
        query = cmd[-1]
        if "page=1" in query:
            rows = [{"number": 1, "title": "a", "body": "", "html_url": "u1"}]
        else:
            rows = [{"number": 2, "title": "b", "body": "", "html_url": "u2"}]
        return json.dumps(rows)

    monkeypatch.setattr("subprocess.check_output", fake_check_output)

    client = GhCliClient()
    issues = client.list_issues("org/repo", limit=2)

    assert len(issues) == 2
    assert len(calls) == 2


def test_list_issue_comments_returns_empty_on_bad_payload(monkeypatch):
    monkeypatch.setattr("subprocess.check_output", lambda *_, **__: "not-json")

    client = GhCliClient()
    comments = client.list_issue_comments("org/repo", 1)

    assert comments == []
