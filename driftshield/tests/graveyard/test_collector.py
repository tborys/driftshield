from dataclasses import dataclass

from driftshield.graveyard.collector import GraveyardCollector


@dataclass
class FakeIssue:
    number: int
    title: str
    body: str
    html_url: str


class FakeClient:
    def list_issues(self, repo: str, limit: int):
        return [
            FakeIssue(
                number=1,
                title="Agent drift in multi-step workflow",
                body="Agent used wrong variable then wrote to CRM",
                html_url=f"https://github.com/{repo}/issues/1",
            ),
            FakeIssue(
                number=2,
                title="UI button colour wrong",
                body="CSS issue only",
                html_url=f"https://github.com/{repo}/issues/2",
            ),
        ]

    def list_issue_comments(self, repo: str, issue_number: int):
        if issue_number == 1:
            return ["Tool error occurred and was ignored"]
        return ["frontend bug"]


def test_collector_returns_filtered_candidates():
    collector = GraveyardCollector(client=FakeClient())

    result = collector.collect(repos=["org/repo"], limit_per_repo=10)

    assert result.total_issues == 2
    assert result.candidate_count == 1
    assert len(result.candidates) == 1
    assert result.candidates[0].issue_url.endswith("/issues/1")
