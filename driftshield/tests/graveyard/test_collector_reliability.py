from dataclasses import dataclass

from driftshield.graveyard.collector import GraveyardCollector


@dataclass
class FakeIssue:
    number: int
    title: str
    body: str
    html_url: str


class FlakyClient:
    def list_issues(self, repo: str, limit: int):
        return [
            FakeIssue(1, "Agent drift", "tool error", "https://github.com/org/repo/issues/1"),
            FakeIssue(1, "Agent drift duplicate", "tool error", "https://github.com/org/repo/issues/1"),
        ]

    def list_issue_comments(self, repo: str, issue_number: int):
        raise RuntimeError("rate limited")


def test_collector_deduplicates_and_tolerates_comment_fetch_errors():
    collector = GraveyardCollector(client=FlakyClient())

    result = collector.collect(["org/repo"], limit_per_repo=10)

    assert result.total_issues == 2
    assert result.candidate_count == 1
    assert len(result.candidates) == 1
