from dataclasses import dataclass

from driftshield.graveyard.classifier import classify_thread
from driftshield.graveyard.models import GraveyardCandidate, GraveyardCollectResult


@dataclass(slots=True)
class GitHubIssue:
    number: int
    title: str
    body: str
    html_url: str


class GitHubClientProtocol:
    def list_issues(self, repo: str, limit: int) -> list[GitHubIssue]:
        raise NotImplementedError

    def list_issue_comments(self, repo: str, issue_number: int) -> list[str]:
        raise NotImplementedError


class GraveyardCollector:
    def __init__(self, client: GitHubClientProtocol):
        self._client = client

    def collect(self, repos: list[str], limit_per_repo: int = 100) -> GraveyardCollectResult:
        candidates: list[GraveyardCandidate] = []
        total_issues = 0

        for repo in repos:
            issues = self._client.list_issues(repo, limit_per_repo)
            total_issues += len(issues)
            for issue in issues:
                comments = self._client.list_issue_comments(repo, issue.number)
                evidence_text = "\n".join([issue.body or "", *comments])
                classification = classify_thread(issue.title, evidence_text)

                if not classification.is_candidate:
                    continue

                candidates.append(
                    GraveyardCandidate(
                        repo=repo,
                        issue_number=issue.number,
                        issue_url=issue.html_url,
                        title=issue.title,
                        evidence_text=evidence_text,
                        score=classification.score,
                        likelihood=classification.likelihood,
                        signals=classification.signals,
                    )
                )

        return GraveyardCollectResult(
            total_issues=total_issues,
            candidate_count=len(candidates),
            candidates=candidates,
        )
