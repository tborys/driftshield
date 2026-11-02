#!/usr/bin/env python3
"""PreToolUse and ConfigChange guard for a delivery run (cloud routine only).

GitHub writes are an allowlist: exactly the five that lead.md uses, on this
run's repository, issue, branch and PR. Everything else that writes is
refused, including merges, issue edits, comment deletes and dependency
links. Git pushes go only to the run's branch, never forced. The checker
may only read. Builder and checker launches stop at the round cap, on
agent:stop, on an open blocker, or when GitHub cannot be read.

This is a seatbelt. The lock is GitHub's branch protection on main (admins
included) and the proxy's GraphQL block. The guard lives in files the agent
could change; the Stop hook records the kit's state so DriftShield can flag
a breach after the fact.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the kit folder clean
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dslib  # noqa: E402

DONT_RETRY = " Do not retry or work around this. If the run cannot go on without it, escalate."
PROTECTED = (".claude/", ".git/hooks/", ".github/", ".driftshield/ledger.jsonl", ".driftshield/run.json",
             ".driftshield/state.json", ".driftshield/agents.json", ".driftshield/verdicts/", ".driftshield/out/")
RAW_MARKS = tuple(p for p in PROTECTED if p != ".github/") + (".github/ISSUE_TEMPLATE", ".github/workflows")
READ_CMDS = {"cat", "head", "tail", "ls", "wc", "grep", "diff", "stat", "file", "nl", "sha256sum", "md5sum", "test", "true"}
CHECKER_CMDS = {"cat", "head", "tail", "wc", "ls", "grep", "nl", "stat", "file"}
CHECKER_GIT = {"diff", "log", "show", "status", "rev-parse", "ls-files", "blame", "cat-file"}
GIT_READ = CHECKER_GIT | {"branch", "fetch", "merge-base", "describe", "for-each-ref", "ls-remote", "show-ref", "grep"}
PUSH_FLAGS = {"-u", "--set-upstream", "-q", "--quiet", "-v", "--verbose", "--progress", "--porcelain"}
ALLOWED_WRITES = ("POST issues/<n>/comments with --input, POST issues/<n>/labels, DELETE issues/<n>/labels/<name>, "
                  "POST pulls with draft true, PATCH pulls/<n> with body or title only")


def rel(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(dslib.root().resolve()))
    except ValueError:
        return path.removeprefix("./")


def protected(path: str) -> bool:
    r = rel(path)
    return any(r == p.rstrip("/") or r.startswith(p) for p in PROTECTED)


def check_path(path: str, agent: str) -> str | None:
    if agent == "checker":
        return "The checker is read only." + DONT_RETRY
    if path and protected(path):
        return "The kit, .github/ and the run's own evidence files are read only in a delivery run." + DONT_RETRY
    return None


# ---------- git ----------

def check_push(args: list[str]) -> str | None:
    run = dslib.run_info()
    if not run.get("issue"):
        return "Claim the issue before pushing."
    args = dslib.normalise(args, short_with_value="o")
    positional, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "--push-option"):
            i += 2
            continue
        if a.startswith("-") and a not in PUSH_FLAGS:
            return f"`git push {a}` is not allowed. Push plain: git push -u origin HEAD." + DONT_RETRY
        if not a.startswith("-"):
            positional.append(a)
        i += 1
    if positional and positional[0] != "origin":
        return "Push only to origin." + DONT_RETRY
    current = dslib.branch()
    for spec in positional[1:] or ["HEAD"]:
        if spec.startswith(("+", ":")):
            return "Force pushes and deletes are not allowed." + DONT_RETRY
        dst = spec.split(":")[-1]
        dst = current if dst == "HEAD" else dst.removeprefix("refs/heads/")
        if not dslib.branch_ok(dst, run.get("repository"), run["issue"]):
            want = f"auto/{dslib.branch_slug(run.get('repository') or '')}/issue-{run['issue']}-r<k>"
            return f"Push only to this run's branch, {want}, not {dst}." + DONT_RETRY
    return None


def check_git(words: list[str]) -> str | None:
    args = list(words[1:])
    while args[:1] == ["-C"] and len(args) > 1:
        args = args[2:]
    if args and args[0].startswith("-"):
        return f"git global option {args[0]} is not allowed; run git commands plainly." + DONT_RETRY
    sub, rest = (args[0], args[1:]) if args else ("", [])
    if sub == "push":
        return check_push(rest)
    if sub == "commit" and any(a in ("--no-verify", "-n") or a.startswith("--author") for a in rest):
        return "Commits must pass the commit-msg check with the run's identity." + DONT_RETRY
    if sub == "config" and not set(rest) & {"--get", "--get-all", "--list", "-l", "--get-regexp"}:
        return "git config is set by the kit at session start. Do not change it." + DONT_RETRY
    if sub == "remote" and rest[:1] not in ([], ["-v"], ["get-url"], ["show"]):
        return "Remotes are fixed for a delivery run." + DONT_RETRY
    if sub in ("update-ref", "symbolic-ref", "replace", "filter-branch", "filter-repo", "send-pack", "hook"):
        return f"git {sub} is not allowed in a delivery run." + DONT_RETRY
    if sub in ("checkout", "restore", "rm", "mv", "clean") and any(protected(a) for a in rest if not a.startswith("-")):
        return "Kit files are read only in a delivery run." + DONT_RETRY
    return None


# ---------- GitHub writes: an allowlist ----------

def body_fields(call: dict) -> dict:
    """The write's payload, from --input or from -f/-F fields."""
    data = dict(dslib.input_body(call["input"]) or {})
    for k, values in call["fields"].items():
        data[k] = values if k.endswith("[]") else values[-1]
    return data


def scan(*texts: str) -> str | None:
    found = sorted({c for t in texts if t for c in dslib.unsafe(str(t))})
    return f"This text would go public and contains {' and '.join(found)}. Remove it and try again." if found else None


def pr_ready_problem(run: dict) -> str | None:
    head = dslib.git("rev-parse", "HEAD")
    verdicts = [e for e in dslib.ledger() if e["type"] == "review.verdict"]
    if not verdicts or verdicts[-1].get("status") != "approve" or verdicts[-1].get("head_sha") != head:
        return "agent:pr-ready needs the latest checker verdict to approve the current HEAD."
    data = dslib.gh_json(f"repos/{run['repository']}/issues/{run['issue']}", retry=True)
    if not isinstance(data, dict):
        return "Could not read the issue to check the required checks; try once more, then escalate."
    size = dslib.parse_issue(data.get("body") or "")["size"]
    done = {(e.get("data") or {}).get("check_id") for e in dslib.ledger() if e.get("head_sha") == head and (
        (e["type"] == "check.completed" and e.get("status") == "passed")
        or (e["type"] == "check.skipped" and (e.get("data") or {}).get("reason") == "not_applicable"))}
    missing = [c for c in dslib.required_checks(size) if c not in done]
    if missing:
        return f"agent:pr-ready needs every required check passed on HEAD; run ds-check --required {size or 'small'} (missing: {', '.join(missing)})."
    number = dslib.run_pr()
    pr = dslib.gh_json(f"repos/{run['repository']}/pulls/{number}", retry=True) if number else None
    if not isinstance(pr, dict) or (pr.get("head") or {}).get("sha") != head:
        return "agent:pr-ready needs the PR head on GitHub to equal HEAD. Push first."
    return None


def check_gh(words: list[str]) -> str | None:
    if len(words) < 2 or words[1] != "api":
        if words[1:2] in (["--version"], ["version"]) or words[1:3] == ["auth", "status"]:
            return None
        return "Use gh api with REST only; other gh commands use GraphQL, which is blocked here." + DONT_RETRY
    call = dslib.gh_api_call(words)
    if call["method"] == "GET":
        return None
    run = dslib.run_info()
    slug = (run.get("repository") or "").lower()
    path = call["path"].lower()
    if not slug or not path.startswith(f"repos/{slug}/"):
        return f"GitHub writes go only to this run's repository. Allowed: {ALLOWED_WRITES}." + DONT_RETRY
    tail = call["path"][len(f"repos/{slug}/"):]
    method, data = call["method"], body_fields(call)
    if call["input"] == "-":
        return "Write the body to a file under .driftshield/ and pass --input <file>."
    m = re.fullmatch(r"issues/(\d+)/comments", tail)
    if m and method == "POST":
        if call["fields"] or set(data) != {"body"}:
            return "Post a comment as {\"body\": ...} with --input .driftshield/body.json."
        number, body = int(m.group(1)), str(data["body"])
        first = re.search(rf"<!-- (?:{dslib.CLAIM_MARKER}|{dslib.BLOCKED_MARKER}) run={run.get('nonce')} -->", body)
        if number != run.get("issue") and not (run.get("issue") is None and first):
            return "Comment only on this run's issue. The first comment must be the claim or the blocked note with this run's nonce."
        return scan(body)
    m = re.fullmatch(r"issues/(\d+)/labels", tail)
    if m and method == "POST":
        if int(m.group(1)) != run.get("issue"):
            return "Label only this run's issue." + DONT_RETRY
        labels = data.get("labels[]") or data.get("labels") or []
        labels = [labels] if isinstance(labels, str) else labels
        wrong = [l for l in labels if l not in dslib.LEAD_ADDS]
        if wrong or not labels:
            return f"The lead may add only {', '.join(sorted(dslib.LEAD_ADDS))}." + DONT_RETRY
        if "agent:running" in labels:
            status, winner = dslib.claim_status(run["issue"], run.get("nonce", ""))
            if status != "won":
                return (f"The claim is {status}" + (f" (run {winner} holds it)" if winner else "") +
                        ". End the run without changing anything else.")
        if "agent:pr-ready" in labels:
            return pr_ready_problem(run)
        return None
    m = re.fullmatch(r"issues/(\d+)/labels/[^/]+", tail)
    if m and method == "DELETE":
        if int(m.group(1)) != run.get("issue") or dslib.label_of(tail) not in dslib.LEAD_REMOVES:
            return f"The lead may remove only {', '.join(sorted(dslib.LEAD_REMOVES))} from this run's issue." + DONT_RETRY
        return None
    if tail == "pulls" and method == "POST":
        if str(data.get("draft")).lower() != "true":
            return "Open pull requests as drafts: \"draft\": true in the JSON, or -F draft=true."
        if not dslib.branch_ok(str(data.get("head", "")), run.get("repository"), run.get("issue")):
            return "The PR head must be this run's branch." + DONT_RETRY
        return scan(str(data.get("title", "")), str(data.get("body", "")))
    m = re.fullmatch(r"pulls/(\d+)", tail)
    if m and method == "PATCH":
        if int(m.group(1)) != dslib.run_pr() or not data or set(data) - {"body", "title"}:
            return "Change only the body or title of this run's PR." + DONT_RETRY
        return scan(str(data.get("title", "")), str(data.get("body", "")))
    return f"That GitHub write is not allowed. Allowed: {ALLOWED_WRITES}." + DONT_RETRY


# ---------- Bash ----------

def checker_may_run(words: list[str]) -> bool:
    name = Path(words[0]).name
    if name == "git":
        sub = words[1] if len(words) > 1 else ""
        return sub in CHECKER_GIT and not any(w.startswith(("--output", "-o", "--ext-diff")) for w in words[2:])
    if name == "gh":
        call = dslib.gh_api_call(words)
        return call is not None and call["method"] == "GET"
    if name == "ds-check":
        return words[1:] == ["--list"]
    return name in CHECKER_CMDS


def read_only(words: list[str]) -> bool:
    name = Path(words[0]).name
    if name == "git":
        return len(words) > 1 and words[1] in GIT_READ
    if name == "gh":
        call = dslib.gh_api_call(words)
        return call is not None and call["method"] == "GET"
    return name in READ_CMDS or (name == "ds-check" and words[1:2] == ["--list"])


def touches_protected(command: str, segs: list[list[str]]) -> bool:
    """A protected path as an argument, or inside an interpreter's code string."""
    text = re.sub(r"(\./)?\.claude/bin/ds-check", "", command)
    return any(protected(w) for seg in segs for w in seg[1:]) or any(m in text for m in RAW_MARKS)


def check_bash(command: str, agent: str) -> str | None:
    segs, targets = dslib.parse_command(command)
    substitution = "$(" in command or "`" in command
    if agent == "checker":
        if targets or substitution or not all(checker_may_run(w) for w in segs):
            return ("The checker is read only: cat head tail wc ls grep nl stat file, git diff log show status "
                    "rev-parse ls-files blame cat-file, gh api GET and ds-check --list." + DONT_RETRY)
    if substitution and any(Path(w[0]).name in ("git", "gh", "curl", "wget") for w in segs):
        return "No command substitution in git, gh or curl commands: write the values out." + DONT_RETRY
    if any(protected(t) for t in targets):
        return "Kit and evidence files are read only in a delivery run." + DONT_RETRY
    if touches_protected(command, segs) and not all(read_only(w) for w in segs):
        return "Commands that touch .claude/, .github/ or the run's evidence files may only read them." + DONT_RETRY
    for words in segs:
        name = Path(words[0]).name
        if name == "git":
            reason = check_git(words)
        elif name == "gh":
            reason = check_gh(words)
        elif name in ("curl", "wget", "http") and re.search(r"(api|uploads)\.github\.com", " ".join(words)):
            reason = "Reach GitHub only through gh api." + DONT_RETRY
        else:
            reason = None
        if reason:
            return reason
    return None


# ---------- Agent launches ----------

def check_agent(tool_input: dict, hook_input: dict) -> str | None:
    kind = tool_input.get("subagent_type") or ""
    if kind not in ("builder", "checker"):
        return None
    run = dslib.run_info()
    if not run.get("issue") or not dslib.branch_ok(dslib.branch(), run.get("repository"), run["issue"]):
        return f"Claim the issue and check out the run's branch, auto/{dslib.branch_slug(run.get('repository') or '')}/issue-<n>-r<k>, first."
    data = dslib.gh_json(f"repos/{run['repository']}/issues/{run['issue']}", retry=True)
    if not isinstance(data, dict):
        return "Could not read the issue from GitHub. Try once more; if it fails again, escalate."
    if "agent:stop" in {l.get("name") for l in data.get("labels", [])}:
        return "agent:stop is set on the issue. Post the escalation comment, remove agent:running and end the run."
    found = dslib.blockers(run["issue"])
    if found is None:
        return "Could not read the issue's blockers. Try once more; if it fails again, escalate."
    if any(not b["done"] for b in found):
        return "This issue is blocked by an issue that is not closed as completed. Post the blocked comment, remove agent:running and end the run."
    ok, pr = dslib.open_pr()
    if not ok:
        return "Could not read the run's pull request. Try once more; if it fails again, escalate."
    if kind == "checker" and pr is None:
        return "Push the first commit and open the draft PR before running the checker."
    markers = dslib.review_markers(pr["number"]) if pr else 0
    if markers is None:
        return "Could not read the PR's comments to count review rounds. Try once more; if it fails again, escalate."
    rounds = max(markers, sum(1 for e in dslib.ledger() if e["type"] == "review.verdict"))
    cap = dslib.cap_for(dslib.parse_issue(data.get("body") or "")["size"])
    if rounds >= cap:
        dslib.append_event("guard.blocked", actor=dslib.actor_from(hook_input), status="raised",
                           data={"kind": "round_cap", "cap": cap, "rounds": rounds, "subagent": kind})
        return (f"Review round cap reached ({rounds} of {cap}). Post the escalation comment from lead.md, "
                "add agent:escalated, remove agent:running, then end the run.")
    brief = tool_input.get("prompt") or ""
    dslib.append_event("agent.launched", actor={"role": dslib.role_of(kind), "agent_type": kind},
                       round=rounds + 1, pr=pr["number"] if pr else None, ac_refs=dslib.items_in(brief) or None,
                       data={"model_param": tool_input.get("model"), "brief_sha256": dslib.sha256(brief),
                             "finding_refs": sorted(set(dslib.FINDING.findall(brief))), "cap": cap})
    return None


def decide(hook_input: dict) -> str | None:
    if hook_input.get("hook_event_name") == "ConfigChange":
        return "configuration change" if hook_input.get("source") in ("project_settings", "local_settings", "skills") else None
    tool = hook_input.get("tool_name") or ""
    tool_input = hook_input.get("tool_input") or {}
    agent = hook_input.get("agent_type") or ""
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return check_path(tool_input.get("file_path") or tool_input.get("notebook_path") or "", agent)
    if tool == "Bash":
        return check_bash(tool_input.get("command") or "", agent)
    if tool == "Agent":
        return check_agent(tool_input, hook_input)
    if tool.startswith("mcp__") and re.search(r"create|update|delete|merge|push|add|remove|write|close|submit|request|assign", tool):
        return "GitHub writes go through gh api only, and only the allowed ones." + DONT_RETRY
    return None


def main() -> int:
    dslib.exit_unless_active()
    try:
        hook_input = json.load(sys.stdin)
    except ValueError:
        return 0
    reason = decide(hook_input)
    if not reason:
        return 0
    if "cap reached" not in reason:
        dslib.append_event("guard.blocked", actor=dslib.actor_from(hook_input), status="raised", data={
            "event": hook_input.get("hook_event_name"), "tool": hook_input.get("tool_name"),
            "source": hook_input.get("source"), "file_path": hook_input.get("file_path"), "reason": reason[:200]})
    print(f"Blocked by the delivery guard: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # a crashing guard blocks: onFailure is block in settings
        dslib.hook_error("guard", exc)
        sys.exit(2)
