#!/usr/bin/env python3
"""Sync linked issue state after a PR merge.

This script is designed for the DriftShield issue-driven workflow:
- find the primary linked issue(s) from the merged PR body
- mark relevant issue checkboxes complete
- close the linked issue as completed
- update the parent issue checklist entry when possible
- move the project item to Done when possible
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
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
    Path(summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def mark_relevant_checkboxes_complete(body: str) -> str:
    marker = "\n## Human Approval Required"
    if marker in body:
        before, after = body.split(marker, maxsplit=1)
        before = re.sub(r"(^\s*[-*]\s*)\[\s\]", r"\1[x]", before, flags=re.MULTILINE)
        return before + marker + after
    return re.sub(r"(^\s*[-*]\s*)\[\s\]", r"\1[x]", body, flags=re.MULTILINE)


def extract_parent_issue(body: str) -> IssueRef | None:
    for line in body.splitlines():
        if "Parent issue:" not in line:
            continue
        url_match = re.search(r"https://github\.com/([^/\s)]+/[^/\s)]+)/issues/(\d+)", line)
        if url_match:
            return IssueRef(repo=url_match.group(1), number=int(url_match.group(2)))
    return None


def mark_parent_checklist_entry(parent_body: str, child_issue_url: str) -> tuple[str, bool]:
    changed = False
    lines: list[str] = []
    for line in parent_body.splitlines():
        if child_issue_url in line and "- [ ]" in line:
            line = line.replace("- [ ]", "- [x]", 1)
            changed = True
        lines.append(line)
    return "\n".join(lines), changed


def write_temp_file(content: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
    handle.write(content)
    handle.flush()
    handle.close()
    return handle.name


def update_issue_body(repo: str, number: int, body: str, token: str) -> None:
    path = write_temp_file(body)
    try:
        run_gh(["issue", "edit", str(number), "-R", repo, "--body-file", path], token)
    finally:
        Path(path).unlink(missing_ok=True)


def close_issue(repo: str, number: int, token: str) -> None:
    run_gh(["issue", "close", str(number), "-R", repo, "--reason", "completed"], token)


def get_project_done_metadata(owner: str, number: str, token: str) -> tuple[str, str, str]:
    project = gh_json(["project", "view", number, "--owner", owner, "--format", "json"], token)
    project_id = project["id"]
    fields = gh_json(["project", "field-list", number, "--owner", owner, "--format", "json"], token)

    status_field = next(field for field in fields["fields"] if field["name"] == "Status")
    done_option = next(option for option in status_field["options"] if option["name"] == "Done")
    return project_id, status_field["id"], done_option["id"]


def move_project_item_to_done(owner: str, number: str, issue_url: str, token: str) -> bool:
    project_id, status_field_id, done_option_id = get_project_done_metadata(owner, number, token)
    items = gh_json(["project", "item-list", number, "--owner", owner, "--format", "json"], token)
    item_id = next((item["id"] for item in items["items"] if item["content"]["url"] == issue_url), None)
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
            done_option_id,
        ],
        token,
    )
    return True


def main() -> int:
    current_repo = os.environ["REPO"]
    pr_number = os.environ["PR_NUMBER"]
    current_token = os.environ["CURRENT_TOKEN"]
    automation_token = os.getenv("AUTOMATION_TOKEN", "")
    project_owner = os.getenv("PROJECT_OWNER", "")
    project_number = os.getenv("PROJECT_NUMBER", "")

    summary: list[str] = [f"## PR Merge Sync", f"- PR: #{pr_number} in `{current_repo}`"]

    pr = gh_json(
        [
            "pr",
            "view",
            pr_number,
            "--repo",
            current_repo,
            "--json",
            "number,title,body,url,mergedAt",
        ],
        current_token,
    )

    issue_refs = parse_issue_refs_from_body(pr.get("body", ""), current_repo)
    if not issue_refs:
        summary.append("- No linked issue references were found in the PR body; nothing to sync.")
        append_summary(summary)
        return 0

    summary.append("- Linked issues:")
    for ref in issue_refs:
        summary.append(f"  - `{ref.repo}#{ref.number}`")

    for ref in issue_refs:
        token_for_issue = current_token if ref.repo == current_repo or not automation_token else automation_token
        issue = gh_json(
            ["issue", "view", str(ref.number), "-R", ref.repo, "--json", "number,body,url,state,title"],
            token_for_issue,
        )

        updated_body = mark_relevant_checkboxes_complete(issue["body"])
        if updated_body != issue["body"]:
            update_issue_body(ref.repo, ref.number, updated_body, token_for_issue)
            summary.append(f"- Updated checklist body for `{ref.repo}#{ref.number}`")

        if issue["state"] != "CLOSED":
            close_issue(ref.repo, ref.number, token_for_issue)
            summary.append(f"- Closed `{ref.repo}#{ref.number}` as completed")
        else:
            summary.append(f"- `{ref.repo}#{ref.number}` was already closed")

        parent_ref = extract_parent_issue(updated_body)
        if parent_ref:
            if automation_token:
                parent = gh_json(
                    [
                        "issue",
                        "view",
                        str(parent_ref.number),
                        "-R",
                        parent_ref.repo,
                        "--json",
                        "number,body,url,title",
                    ],
                    automation_token,
                )
                new_parent_body, changed = mark_parent_checklist_entry(parent["body"], issue["url"])
                if changed:
                    update_issue_body(parent_ref.repo, parent_ref.number, new_parent_body, automation_token)
                    summary.append(
                        f"- Marked parent checklist entry complete in `{parent_ref.repo}#{parent_ref.number}`"
                    )
                else:
                    summary.append(
                        f"- Parent issue `{parent_ref.repo}#{parent_ref.number}` found, but no matching checklist entry needed an update"
                    )
            else:
                summary.append(
                    f"- Skipped parent issue sync for `{parent_ref.repo}#{parent_ref.number}` because `DRIFTSHIELD_AUTOMATION_TOKEN` is not configured"
                )

        if project_owner and project_number:
            if automation_token:
                moved = move_project_item_to_done(project_owner, project_number, issue["url"], automation_token)
                if moved:
                    summary.append(f"- Moved project item for `{ref.repo}#{ref.number}` to `Done`")
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
