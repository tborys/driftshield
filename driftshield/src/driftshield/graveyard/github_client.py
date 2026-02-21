import json
import subprocess

from driftshield.graveyard.collector import GitHubClientProtocol, GitHubIssue


class GhCliClient(GitHubClientProtocol):
    def list_issues(self, repo: str, limit: int) -> list[GitHubIssue]:
        issues: list[GitHubIssue] = []
        page = 1

        while len(issues) < limit:
            per_page = min(100, limit - len(issues))
            cmd = [
                "gh",
                "api",
                f"repos/{repo}/issues?state=all&per_page={per_page}&page={page}",
            ]
            try:
                output = subprocess.check_output(cmd, text=True)
                payload = json.loads(output)
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                break

            if not isinstance(payload, list) or not payload:
                break

            added = 0
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
                added += 1
                if len(issues) >= limit:
                    break

            if added == 0:
                break
            page += 1

        return issues

    def list_issue_comments(self, repo: str, issue_number: int) -> list[str]:
        cmd = ["gh", "api", f"repos/{repo}/issues/{issue_number}/comments"]
        try:
            output = subprocess.check_output(cmd, text=True)
            payload = json.loads(output)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [row.get("body", "") for row in payload if isinstance(row, dict)]
