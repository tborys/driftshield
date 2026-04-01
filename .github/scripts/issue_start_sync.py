#!/usr/bin/env python3
"""Move linked issue project items to In Progress when work starts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IssueRef:
    repo: str
    number: int


def run_gh(args: list[str], token: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    return subprocess.run(
        ["gh", *args],
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def gh_json(args: list[str], token: str) -> Any:
    result = run_gh(args, token)
    return json.loads(result.stdout)


def append_summary(lines: list[str]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary_file:
        summary_file.write("\n".join(lines) + "\n")


def parse_issue_refs_from_body(body: str, default_repo: str) -> list[IssueRef]:
    refs: list[IssueRef] = []
    seen: set[tuple[str, int]] = set()

    keyword_re = re.compile(
        r"(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)\s+"
        r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<num>\d+)\b"
    )
    url_re = re.compile(r"https://github\.com/(?P<repo>[^/\s)]+/[^/\s)]+)/issues/(?P<num>\d+)")

    for match in keyword_re.finditer(body):
        repo = match.group("repo") or default_repo
        num = int(match.group("num"))
        key = (repo, num)
        if key not in seen:
            seen.add(key)
            refs.append(IssueRef(repo=repo, number=num))

    for match in url_re.finditer(body):
        repo = match.group("repo")
        num = int(match.group("num"))
        key = (repo, num)
        if key not in seen:
            seen.add(key)
            refs.append(IssueRef(repo=repo, number=num))

    return refs


def parse_issue_ref_from_branch(branch: str, default_repo: str) -> IssueRef | None:
    patterns = [
        r"(?:^|[/-])issue[-_/](?P<num>\d+)(?:$|[-_/])",
        r"(?:^|[/-])issues[-_/](?P<num>\d+)(?:$|[-_/])",
        r"#(?P<num>\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, branch)
        if match:
            return IssueRef(repo=default_repo, number=int(match.group("num")))
    return None


def get_project_in_progress_metadata(owner: str, number: str, token: str) -> tuple[str, str, str]:
    project = gh_json(["project", "view", number, "--owner", owner, "--format", "json"], token)
    project_id = project["id"]
    fields = gh_json(["project", "field-list", number, "--owner", owner, "--format", "json"], token)

    status_field = next((field for field in fields["fields"] if field["name"] == "Status"), None)
    if status_field is None:
        raise ValueError(f"Project {owner}/{number} is missing a 'Status' field")

    in_progress_option = next(
        (option for option in status_field.get("options", []) if option["name"] == "In Progress"),
        None,
    )
    if in_progress_option is None:
        raise ValueError(f"Project {owner}/{number} status field is missing an 'In Progress' option")

    return project_id, status_field["id"], in_progress_option["id"]


def move_project_item_to_in_progress(owner: str, number: str, issue_url: str, token: str) -> bool:
    project_id, status_field_id, in_progress_option_id = get_project_in_progress_metadata(owner, number, token)
    items = gh_json(["project", "item-list", number, "--owner", owner, "--format", "json"], token)
    item_id = next(
        (
            item["id"]
            for item in items["items"]
            if item.get("content") and item["content"].get("url") == issue_url
        ),
        None,
    )
    if not item_id:
        return False

    run_gh(
        [
            "project",
            "item-edit",
            "--id",
            item_id,
            "--project-id",
            project_id,
            "--field-id",
            status_field_id,
            "--single-select-option-id",
            in_progress_option_id,
        ],
        token,
    )
    return True


def collect_issue_refs(current_repo: str, current_token: str) -> tuple[list[IssueRef], str]:
    event_name = os.getenv("EVENT_NAME", "")
    action = os.getenv("ACTION", "")
    issue_number = os.getenv("ISSUE_NUMBER", "")
    issue_repo = os.getenv("ISSUE_REPO", current_repo) or current_repo
    comment_body = os.getenv("COMMENT_BODY", "")
    pr_number = os.getenv("PR_NUMBER", "")
    ref_name = os.getenv("REF_NAME", "")

    if event_name == "workflow_dispatch" and issue_number:
        return [IssueRef(repo=issue_repo, number=int(issue_number))], "workflow_dispatch input"

    if event_name == "issues" and issue_number and action == "assigned":
        return [IssueRef(repo=issue_repo, number=int(issue_number))], "issue assigned"

    if event_name == "issue_comment" and issue_number:
        if "/pickup" in comment_body or "/start" in comment_body or "/in-progress" in comment_body:
            issue_is_pr = os.getenv("ISSUE_IS_PR", "").lower() == "true"
            if issue_is_pr and pr_number:
                pr = gh_json(
                    ["pr", "view", pr_number, "--repo", current_repo, "--json", "body,headRefName"],
                    current_token,
                )
                refs = parse_issue_refs_from_body(pr.get("body", ""), current_repo)
                if not refs:
                    branch_ref = parse_issue_ref_from_branch(pr.get("headRefName", ""), current_repo)
                    if branch_ref:
                        refs = [branch_ref]
                return refs, "PR comment pickup command"
            return [IssueRef(repo=issue_repo, number=int(issue_number))], "issue comment pickup command"
        return [], "issue comment ignored"

    if event_name == "pull_request" and pr_number:
        pr = gh_json(
            ["pr", "view", pr_number, "--repo", current_repo, "--json", "body,headRefName"],
            current_token,
        )
        refs = parse_issue_refs_from_body(pr.get("body", ""), current_repo)
        if refs:
            return refs, "linked PR body reference"
        branch_ref = parse_issue_ref_from_branch(pr.get("headRefName", ""), current_repo)
        if branch_ref:
            return [branch_ref], "issue-style PR branch name"
        return [], "PR without linked issue"

    if event_name == "push" and ref_name:
        branch_ref = parse_issue_ref_from_branch(ref_name, current_repo)
        if branch_ref:
            return [branch_ref], "issue-style pushed branch name"
        return [], "push without issue-style branch name"

    return [], "unsupported event"


def main() -> int:
    current_repo = os.environ["REPO"]
    current_token = os.environ["CURRENT_TOKEN"]
    automation_token = os.getenv("AUTOMATION_TOKEN", "")
    project_owner = os.getenv("PROJECT_OWNER", "")
    project_number = os.getenv("PROJECT_NUMBER", "")

    summary: list[str] = ["## Issue Start Sync", f"- Event: `{os.getenv('EVENT_NAME', '')}`"]
    issue_refs, reason = collect_issue_refs(current_repo, current_token)
    summary.append(f"- Detection: {reason}")

    if not issue_refs:
        summary.append("- No issue refs found; nothing to sync.")
        append_summary(summary)
        return 0

    for ref in issue_refs:
        summary.append(f"- Candidate issue: `{ref.repo}#{ref.number}`")
        token_for_issue = current_token if ref.repo == current_repo or not automation_token else automation_token
        issue = gh_json(
            ["issue", "view", str(ref.number), "-R", ref.repo, "--json", "number,url,title,state"],
            token_for_issue,
        )

        if project_owner and project_number:
            if automation_token:
                moved = move_project_item_to_in_progress(
                    project_owner,
                    project_number,
                    issue["url"],
                    automation_token,
                )
                if moved:
                    summary.append(f"- Moved project item for `{ref.repo}#{ref.number}` to `In Progress`")
                else:
                    summary.append(f"- No project item found for `{ref.repo}#{ref.number}`")
            else:
                summary.append(
                    "- Skipped project status update because `DRIFTSHIELD_AUTOMATION_TOKEN` is not configured"
                )

    append_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
