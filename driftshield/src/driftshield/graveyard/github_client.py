import json
import subprocess

from driftshield.graveyard.collector import GitHubClientProtocol, GitHubIssue


class GhCliClient(GitHubClientProtocol):
    def list_issues(self, repo: str, limit: int) -> list[GitHubIssue]:
        cmd = [
            "gh",
            "api",
            f"repos/{repo}/issues?state=all&per_page={limit}",
        ]
        output = subprocess.check_output(cmd, text=True)
        payload = json.loads(output)

        issues: list[GitHubIssue] = []
        for row in payload:
            if "pull_request" in row:
                continue
            issues.append(
                GitHubIssue(
                    number=int(row["number"]),
                    title=row.get("title", ""),
                    body=row.get("body") or "",
                    html_url=row.get("html_url", ""),
                )
            )
        return issues

    def list_issue_comments(self, repo: str, issue_number: int) -> list[str]:
        cmd = ["gh", "api", f"repos/{repo}/issues/{issue_number}/comments"]
        output = subprocess.check_output(cmd, text=True)
        payload = json.loads(output)
        return [row.get("body", "") for row in payload]
