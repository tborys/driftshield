#!/usr/bin/env python3
"""Build and post the work records body (`driftshield-work-evidence.v1`) for one issue.

Used three ways, one copy of the code:
  - the delivery worker's Stop hook calls `deliver()` for its own issue after the transcripts and session links;
  - the `delivery-records` workflow runs it when a lineage PR is merged:  records.py --pull <PR number>
  - by hand, to debug one issue:  records.py --only owner/repo#N [--dry-run]

It reads GitHub through the `gh` CLI, with whatever token `gh` already has (the cloud worker's, the
workflow's GITHUB_TOKEN, or your own login), and posts with the DriftShield API key. No new token.

Variables: DRIFTSHIELD_API_KEY (not needed for --dry-run), DS_DRIFTSHIELD_API_BASE (default
https://api.driftshield.ai), DS_REVIEW_PRODUCER (the one value the receiving contract accepts for the
review producer; temporary, see REVIEW_PRODUCER_ENV), DS_REVIEWER_LOGINS (comma separated GitHub logins
whose reviews count; required, never guessed from the repository owner), DS_PROFILE (default
.claude/delivery/profile.json, whose `records_required_checks` names the checks the work must pass).
A missing setting is "not configured": the merge workflow skips with exit 0, the Stop hook records not_sent.
The key is never printed. Standard library only. The receiving side validates the body; its 422 list is
passed on as the error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dslib  # noqa: E402

DEFAULT_API_BASE = "https://api.driftshield.ai"
ROUTE = "/v1/teams/work/evidence"
RETRY_DELAYS = (0, 3, 10, 30)  # seconds before each attempt; the first call in an hour can hit a cold start

EVIDENCE_SCHEMA = "driftshield-work-evidence.v1"
RESULT_SCHEMA = "driftshield-work-evidence-result.v1"
POLICY_VERSION = "coding-acceptance.v2"
# TEMPORARY. The receiving contract (v1) accepts exactly one value for `acceptance.required_review_producer`,
# a name from the old review lane. We rely on our own reviewer, the delivery checker, so that name must not
# live in a public file (the sync refuses it). It is read from this variable instead, set in the private
# cloud environment and as a variable on each delivery repository. This is the only place it is used.
# Remove it when the contract accepts a generic reviewer producer.
REVIEW_PRODUCER_ENV = "DS_REVIEW_PRODUCER"

# Comments kept when a body is over the limit: the kit's own markers (dslib.py).
MARKERS = ("driftshield-agent-review:v1", "driftshield-claim:v1", "driftshield-delivery-blocked:v1")

# What the receiving route enforces that the kit must respect to send anything at all. Everything else is
# validated by the receiver, and its error list comes back in the outcome.
MAX_BODY_BYTES = 2_097_152
MAX_COMMENTS = 1000
OBJECTIVE_CHARS = 8000

REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
ORIGINAL_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}
ONLY_RE = re.compile(r"^([A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100})#(\d+)$")


class GitHubError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class OutOfTime(GitHubError):
    """The deadline passed; nothing was left to read or send with."""


class AcceptanceError(Exception):
    pass


class NotConfigured(AcceptanceError):
    """A setting this repository has not made yet. Not a failure: the merge workflow skips."""


class CollectError(Exception):
    pass


# ---------------------------------------------------------------- small helpers

def scrub(text, secrets) -> str:
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def is_time(value) -> bool:
    if not (isinstance(value, str) and TIME_RE.match(value)):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def time_or_none(value):
    return value if is_time(value) else None


def positive_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def rfc3339(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_only(text):
    if not text:
        return None
    match = ONLY_RE.match(text.strip())
    if not match:
        raise ValueError(f"--only must look like owner/repo#123, got {text!r}")
    return match.group(1), int(match.group(2))



# ---------------------------------------------------------------- GitHub reads

class GhCli:
    """Read only `gh api` calls. The token is whatever `gh` finds (GH_TOKEN, GITHUB_TOKEN or a login).
    With a deadline, every call is capped at the time left and refused once it has passed."""

    def __init__(self, gh: str | None = None, timeout: int = 30, deadline: float | None = None):
        self.gh, self.timeout, self.deadline = gh or os.environ.get("DS_GH", "gh"), timeout, deadline

    def call_timeout(self) -> float:
        if self.deadline is None:
            return self.timeout
        left = self.deadline - time.time()
        if left <= 1:
            raise OutOfTime("out of time")
        return min(self.timeout, left)

    def get(self, path: str):
        why, status = "no attempt", None
        for attempt in range(2):
            if attempt:
                time.sleep(float(os.environ.get("DS_RETRY_WAIT", "2")))
            try:
                proc = subprocess.run([self.gh, "api", path], capture_output=True, text=True, timeout=self.call_timeout())
            except (OSError, subprocess.TimeoutExpired) as exc:
                why = type(exc).__name__
                continue
            if proc.returncode == 0:
                try:
                    return json.loads(proc.stdout)
                except ValueError:
                    why = "not JSON"
                    continue
            found = re.search(r"HTTP (\d{3})", proc.stderr or "")
            status = int(found.group(1)) if found else None
            why = f"gh exit {proc.returncode}" + (f", http {status}" if status else "")
            if status in (403, 404, 410):
                break
        raise GitHubError(f"GET {path}: {why}", status)

    def pages(self, path: str, key: str | None = None, max_pages: int = 50):
        joiner = "&" if "?" in path else "?"
        for page in range(1, max_pages + 1):
            data = self.get(f"{path}{joiner}per_page=100&page={page}")
            items = data[key] if key else data
            yield from items
            if len(items) < 100:
                return


def pull_issue(repository: str, branch, head_repository):
    """The issue a pull request belongs to, from its branch (`auto/` or `fm/`), if it was pushed from the
    repository itself. The slug in the branch is not compared: the head repository check is the real one,
    and it keeps a PR opened before the repository changed owner."""
    if head_repository != repository:
        return None
    return dslib.lineage_issue(branch, repository, strict=False, prefixes=("auto", "fm"))


def find_issues(gh, repository: str, issue: int) -> list[int]:
    """Numbers of the lineage pull requests of one issue, read from the repository's pull request list."""
    return [p["number"] for p in gh.pages(f"repos/{repository}/pulls?state=all&sort=updated&direction=desc")
            if pull_issue(repository, p["head"]["ref"], (p["head"].get("repo") or {}).get("full_name")) == issue]


def cross_referenced_pulls(repository: str, timeline) -> list[int]:
    numbers = set()
    for event in timeline or []:
        source = (event.get("source") or {}).get("issue") or {}
        if event.get("event") != "cross-referenced" or not source.get("pull_request"):
            continue
        name = (source.get("repository") or {}).get("full_name")
        if str(name or "").lower() == repository.lower() and positive_int(source.get("number")):
            numbers.add(source["number"])
    return sorted(numbers)


def dismissals(timeline) -> dict:
    found: dict[int, dict] = {}
    for event in timeline or []:
        if event.get("event") != "review_dismissed":
            continue
        review = event.get("dismissed_review") or {}
        review_id, at = positive_int(review.get("review_id")), time_or_none(event.get("created_at"))
        if review_id is None or at is None:
            continue
        state = str(review.get("state") or "").upper()
        if review_id not in found or parse_time(at) >= parse_time(found[review_id]["dismissed_at"]):
            found[review_id] = {"original_state": state if state in ORIGINAL_STATES else None, "dismissed_at": at}
    return found


def head_shas(pull, commits, timeline, reviews) -> list[str]:
    ordered: list[str] = []

    def add(sha):
        if isinstance(sha, str) and SHA_RE.match(sha) and sha not in ordered:
            ordered.append(sha)

    add(pull["head"].get("sha"))
    for commit in commits:
        add(commit.get("sha"))
    for event in timeline:
        if event.get("event") == "head_ref_force_pushed":
            add(event.get("commit_id"))
    for review in reviews:
        add(review.get("commit_id"))
    return ordered


# ---------------------------------------------------------------- mapping to the v1 body

OBJECTIVE_HEADING = re.compile(r"^#{1,6}\s*(objective|goal|why|problem)\b", re.I)
ANY_HEADING = re.compile(r"^#{1,6}\s")
PREAMBLE = re.compile(r"^(parent|parents|depends on|blocked by|blocking|closes|part of|consumer of|planning parent)\b", re.I)


def objective_from_issue(body) -> str:
    lines = str(body or "").replace("\r\n", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if OBJECTIVE_HEADING.match(line.strip())), None)
    if start is not None:
        section = []
        for line in lines[start + 1:]:
            if ANY_HEADING.match(line.strip()):
                break
            section.append(line)
        text = "\n".join(section).strip()
        if text:
            return text[:OBJECTIVE_CHARS]
    paragraphs = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
    first = next((p for p in paragraphs if not ANY_HEADING.match(p) and not p.startswith("<!--") and not PREAMBLE.match(p)), "")
    return first[:OBJECTIVE_CHARS]


def map_comment(c) -> dict:
    return {"id": c.get("id"), "url": c.get("html_url"), "author_login": (c.get("user") or {}).get("login"),
            "created_at": c.get("created_at"), "updated_at": time_or_none(c.get("updated_at")), "body": c.get("body") or ""}


def map_pull(repository: str, pull) -> dict:
    merged = pull.get("merged") is True
    return {"number": pull.get("number"), "url": f"https://github.com/{repository}/pull/{pull.get('number')}",
            "head_sha": pull["head"].get("sha"), "base": (pull.get("base") or {}).get("ref"),
            "state": "closed" if pull.get("state") == "closed" else "open", "merged": merged,
            "merge_commit_sha": pull.get("merge_commit_sha") if merged else None, "merged_at": pull.get("merged_at") if merged else None}


def map_check_run(repository: str, run, workflows: dict) -> dict:
    prefix = f"https://github.com/{repository}/"
    url = run.get("html_url")
    return {"id": run.get("id"), "name": run.get("name"), "workflow": workflows.get((run.get("check_suite") or {}).get("id")),
            "head_sha": run.get("head_sha"), "status": run.get("status"), "conclusion": run.get("conclusion"),
            "started_at": time_or_none(run.get("started_at")), "completed_at": time_or_none(run.get("completed_at")),
            "url": url if isinstance(url, str) and url.startswith(prefix) else f"{prefix}runs/{run.get('id')}",
            "app": (run.get("app") or {}).get("slug")}


def map_review(repository: str, pull_number: int, review, dismissed: dict):
    """(record, None) or (None, why it was left out)."""
    state = str(review.get("state") or "").upper()
    commit = review.get("commit_id")
    if not (isinstance(commit, str) and SHA_RE.match(commit)):
        return None, {"id": review.get("id"), "pull_request": pull_number, "reason": "review_without_commit_sha"}
    dismissal = None
    if state == "DISMISSED":
        dismissal = dismissed.get(review.get("id"))
        if dismissal is None:
            return None, {"id": review.get("id"), "pull_request": pull_number, "reason": "dismissal_event_missing"}
    return {"id": review.get("id"), "pull_request": pull_number, "author_login": (review.get("user") or {}).get("login"),
            "state": state, "commit_id": commit, "submitted_at": time_or_none(review.get("submitted_at")),
            "url": review.get("html_url") or f"https://github.com/{repository}/pull/{pull_number}#pullrequestreview-{review.get('id')}",
            "dismissal": dismissal}, None


def review_producer(env) -> str:
    value = (env.get(REVIEW_PRODUCER_ENV) or "").strip()
    if not value:
        raise NotConfigured(f"{REVIEW_PRODUCER_ENV} is not set (the contract needs a review producer name)")
    return value


def required_checks_from_profile(profile) -> list[str]:
    checks = (profile or {}).get("records_required_checks")
    if not isinstance(checks, list) or not checks:
        raise NotConfigured("the profile has no records_required_checks")
    return checks


def acceptance_for(repository: str, checks, logins, producer: str, revision=None) -> dict:
    if not checks or not all(isinstance(name, str) and name.strip() for name in checks):
        raise AcceptanceError(f"the required checks for {repository} are empty or blank")
    logins = [str(x).strip() for x in logins if str(x).strip()]
    if not logins:
        raise AcceptanceError("no reviewer logins")
    return {"policy_version": POLICY_VERSION, "required_checks": list(checks), "required_review_producer": producer,
            "merge_required": True, "review_producer_logins": logins, "manifest_revision": revision}


def encode_body(body) -> bytes:
    """The one serialisation: these bytes are measured, trimmed to fit and sent."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def has_marker(comment) -> bool:
    return any(marker in comment["body"] for marker in MARKERS)


def body_digest(body) -> str:
    """Same records, same digest: `observed_at` is the time of the read, not a record."""
    rest = {k: v for k, v in body.items() if k != "observed_at"}
    return hashlib.sha256(json.dumps(rest, sort_keys=True).encode()).hexdigest()


@dataclass
class Collected:
    body: dict
    data: bytes
    omitted_reviews: list = field(default_factory=list)
    dropped_comment_ids: list = field(default_factory=list)


def collect_issue(gh, repository: str, issue_number: int, acceptance: dict, now: datetime, known_pulls=(), deadline=None, clock=time.time) -> Collected:
    """Read one issue and everything on it, and build its body. Raises on a read that fails, on no lineage PR, and
    OutOfTime when the deadline passes (checked before each read of a pull request and of a head)."""
    def tick():
        if deadline is not None and clock() >= deadline:
            raise OutOfTime("out of time")

    tick()
    issue = gh.get(f"repos/{repository}/issues/{issue_number}")
    issue_comments = list(gh.pages(f"repos/{repository}/issues/{issue_number}/comments"))
    issue_timeline = list(gh.pages(f"repos/{repository}/issues/{issue_number}/timeline"))
    candidates = sorted({*known_pulls, *cross_referenced_pulls(repository, issue_timeline)})

    pulls, comments, omitted, reviews_out, checks_by_id = [], {}, [], [], {}
    workflows: dict = {}
    for c in issue_comments:
        comments[c["id"]] = map_comment(c)
    for number in candidates:
        tick()
        pull = gh.get(f"repos/{repository}/pulls/{number}")
        if pull_issue(repository, pull["head"]["ref"], (pull["head"].get("repo") or {}).get("full_name")) != issue_number:
            continue
        timeline = list(gh.pages(f"repos/{repository}/issues/{number}/timeline"))
        commits = list(gh.pages(f"repos/{repository}/pulls/{number}/commits"))
        reviews = list(gh.pages(f"repos/{repository}/pulls/{number}/reviews"))
        for c in gh.pages(f"repos/{repository}/issues/{number}/comments"):
            comments[c["id"]] = map_comment(c)
        dismissed = dismissals(timeline)
        for review in reviews:
            record, why = map_review(repository, number, review, dismissed)
            omitted.append(why) if why else reviews_out.append(record)
        for sha in head_shas(pull, commits, timeline, reviews):
            tick()
            for run in gh.pages(f"repos/{repository}/actions/runs?head_sha={sha}", "workflow_runs"):
                if positive_int(run.get("check_suite_id")) and str(run.get("name") or "").strip():
                    workflows[run["check_suite_id"]] = run["name"].strip()
            for run in gh.pages(f"repos/{repository}/commits/{sha}/check-runs?filter=all", "check_runs"):
                checks_by_id[run["id"]] = run
        pulls.append(pull)
    if not pulls:
        raise CollectError(f"no lineage pull request for {repository}#{issue_number}")

    def by_time(key):
        return lambda item: (str(item.get(key) or ""), item["id"])

    body = {
        "schema": EVIDENCE_SCHEMA, "observed_at": rfc3339(now),
        "source": {"repository": repository, "issue_number": issue["number"],
                   "issue_url": f"https://github.com/{repository}/issues/{issue['number']}", "title": issue.get("title") or "",
                   "objective": objective_from_issue(issue.get("body")), "created_at": issue.get("created_at")},
        "acceptance": acceptance,
        "comments": sorted(comments.values(), key=by_time("created_at")),
        "pull_requests": sorted((map_pull(repository, p) for p in pulls), key=lambda p: p["number"]),
        "check_runs": sorted((map_check_run(repository, r, workflows) for r in checks_by_id.values()),
                             key=lambda r: (str(r["started_at"] or r["completed_at"] or ""), r["id"])),
        "reviews": sorted(reviews_out, key=by_time("submitted_at")),
    }
    data, dropped = encode_body(body), []
    if len(data) > MAX_BODY_BYTES or len(body["comments"]) > MAX_COMMENTS:
        dropped = [c["id"] for c in body["comments"] if not has_marker(c)]
        body["comments"] = [c for c in body["comments"] if has_marker(c)]
        data = encode_body(body)
    return Collected(body, data, omitted, dropped)


# ---------------------------------------------------------------- posting

@dataclass
class PostResult:
    ok: bool
    status: int | None = None
    detail: str = ""
    result: dict | None = None


def check_api_base(api_base: str) -> str | None:
    """Why this base may not carry the key, or None. https, or http to this machine for tests."""
    parts = urlsplit(api_base or "")
    if parts.scheme == "https" and parts.hostname:
        return None
    if parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost"):
        return None
    return "the API base must be an https URL"


def post_body(api_url: str, key: str, body, sleep=time.sleep, timeout: int = 60, deadline: float | None = None,
              expect_schema: str | None = RESULT_SCHEMA) -> PostResult:
    """The one client for the work evidence route (records and session links). `body` is a dict or the bytes
    from encode_body. Waits of 0, 3, 10 and 30 seconds before the attempts, on a 5xx, a 429 or a transport
    error; any other status is final. Each attempt is capped at the time left. The key goes in a header and
    only to an https base (or this machine); the returned detail is scrubbed."""
    refused = check_api_base(api_url)
    if refused:
        return PostResult(False, None, refused)
    data = body if isinstance(body, bytes) else encode_body(body)
    result = PostResult(False, None, "no attempt")
    for delay in RETRY_DELAYS:
        delay = 0 if os.environ.get("DS_RETRY_WAIT") == "0" else delay  # tests turn the waits off, as for gh
        if deadline is not None and time.time() + delay >= deadline:
            return PostResult(False, result.status, f"{result.detail}; out of time".strip("; "))
        if delay:
            sleep(delay)
        request = urllib.request.Request(api_url.rstrip("/") + ROUTE, data=data, method="POST", headers={
            "Content-Type": "application/json", "X-API-Key": key, "User-Agent": "driftshield-records"})
        try:
            with urllib.request.urlopen(request, timeout=min(timeout, max(1.0, deadline - time.time())) if deadline else timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
            error.close()
        except (urllib.error.URLError, TimeoutError, OSError):
            result = PostResult(False, None, "network error")
            continue
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        if 200 <= status < 300:
            if expect_schema and payload.get("schema") != expect_schema:
                return PostResult(False, status, f"http {status} without the {expect_schema} schema")
            return PostResult(True, status, "", payload)
        errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
        parts = [str(payload.get("detail") or payload.get("message") or "")]
        parts += [f"{e.get('loc')}: {e.get('msg')}" for e in errors[:5] if isinstance(e, dict)]
        result = PostResult(False, status, scrub("; ".join(p for p in parts if p) or f"http {status}", [key])[:300])
        if status < 500 and status != 429:
            return result
    return result


# ---------------------------------------------------------------- deliver one issue

def deliver(gh, repository: str, issue: int, *, key, api_base, acceptance, now, known_pulls=(), dry_run=False,
            previous_digest=None, sleep=time.sleep, deadline=None) -> dict:
    """Collect and post one issue's body. Never raises on GitHub or the network: the outcome says what happened.
    status is one of posted, stale_ignored, unchanged, dry_run, failed. The key never appears in the outcome."""
    outcome = {"repository": repository, "issue": issue, "status": "failed"}
    refused = None if dry_run else check_api_base(api_base)
    if refused:
        outcome["error"] = refused
        return outcome
    try:
        got = collect_issue(gh, repository, issue, acceptance, now, known_pulls=known_pulls, deadline=deadline)
    except (GitHubError, CollectError, KeyError, TypeError, ValueError) as error:
        outcome["error"] = scrub(error, [key])[:300]
        return outcome
    body = got.body
    outcome.update(bytes=len(got.data), digest=body_digest(body), dropped_comments=len(got.dropped_comment_ids),
                   omitted_reviews=len(got.omitted_reviews), **{k: len(body[k]) for k in ("comments", "pull_requests", "reviews", "check_runs")})
    if dry_run:
        outcome["status"] = "dry_run"
        return outcome
    if previous_digest and previous_digest == outcome["digest"]:
        outcome["status"] = "unchanged"
        return outcome
    posted = post_body(api_base, key, got.data, sleep=sleep, deadline=deadline)
    outcome["http"] = posted.status
    if not posted.ok:
        outcome["error"] = f"post failed, http {posted.status}: {scrub(posted.detail, [key])}"
        return outcome
    result = posted.result or {}
    outcome.update(status="stale_ignored" if result.get("declaration") == "stale_ignored" else "posted",
                   records_appended=result.get("records_appended"), changed=result.get("changed"), declaration=result.get("declaration"))
    return outcome


def describe(outcome: dict) -> str:
    label = f"{outcome['repository']}#{outcome['issue']}"
    if outcome["status"] == "failed":
        return f"FAILED {label}: {outcome.get('error')}"
    counts = " ".join(f"{k}={outcome[k]}" for k in ("comments", "pull_requests", "reviews", "check_runs"))
    extra = "".join(f" {k}={outcome[k]}" for k in ("dropped_comments", "omitted_reviews") if outcome.get(k))
    line = f"{label} {outcome['bytes']} bytes {counts}{extra}"
    if outcome["status"] == "dry_run":
        return f"{line} (dry run, not posted)"
    if outcome["status"] == "unchanged":
        return f"{line} unchanged since the last post, skipped"
    if outcome["status"] == "stale_ignored":
        return f"{line} NOT applied: the receiver ignored the acceptance declaration as stale (declaration=stale_ignored)"
    return f"{line} posted records_appended={outcome.get('records_appended')} changed={outcome.get('changed')} declaration={outcome.get('declaration')}"


def settings_from_env(env: dict, profile: dict, repository: str, revision=None) -> dict:
    """Acceptance for a repository from the environment and the profile. Raises NotConfigured for a missing setting."""
    checks = required_checks_from_profile(profile)
    producer = review_producer(env)
    logins = [x for x in (env.get("DS_REVIEWER_LOGINS") or "").split(",") if x.strip()]
    if not logins:
        raise NotConfigured("DS_REVIEWER_LOGINS is not set (the GitHub logins whose reviews count)")
    return acceptance_for(repository, checks, logins, producer, revision)


def load_profile(env: dict):
    """(profile, revision): the profile JSON and the git blob SHA of the file that was read, the same in every
    sender. ({}, None) when there is no readable profile."""
    path = Path(env.get("DS_PROFILE") or Path(__file__).resolve().parent.parent / "delivery" / "profile.json")
    try:
        data = path.read_bytes()
        return json.loads(data), "blob:" + hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    except (OSError, ValueError):
        return {}, None


def write_summary(env: dict, text: str) -> None:
    path = env.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as handle:
            handle.write(f"## Delivery records\n\n{text}\n")


def main(argv: list[str], env: dict | None = None, gh=None) -> int:
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="one issue, owner/repo#N")
    ap.add_argument("--pull", type=int, default=0, help="a merged lineage pull request number, in GITHUB_REPOSITORY")
    ap.add_argument("--dry-run", action="store_true", help="read GitHub, print sizes and counts, post nothing")
    args = ap.parse_args(argv)
    try:
        only = parse_only(args.only)
    except ValueError as error:
        raise SystemExit(str(error))
    if bool(only) == bool(args.pull):
        raise SystemExit("give exactly one of --only owner/repo#N or --pull N")
    key = env.get("DRIFTSHIELD_API_KEY", "")
    api_base = (env.get("DS_DRIFTSHIELD_API_BASE") or DEFAULT_API_BASE).rstrip("/")
    refused = check_api_base(api_base)
    if refused:
        raise SystemExit(f"DS_DRIFTSHIELD_API_BASE: {refused}")
    repository = env.get("GITHUB_REPOSITORY", "") if args.pull else only[0]
    if not REPO_RE.match(repository):
        raise SystemExit("--pull needs GITHUB_REPOSITORY (owner/repo)")
    try:  # a repository that has not been set up is skipped (exit 0) by the merge workflow; a manual run says so (exit 1)
        if not key and not args.dry_run:
            raise NotConfigured("DRIFTSHIELD_API_KEY is not set (only --dry-run runs without it)")
        profile, revision = load_profile(env)
        acceptance = settings_from_env(env, profile, repository, revision)
    except NotConfigured as error:
        print(f"not configured, nothing posted: {error}")
        write_summary(env, f"Skipped, not configured: {error}")
        return 0 if args.pull else 1
    gh = gh or GhCli()
    known: list[int] = []
    try:
        if args.pull:
            pull = gh.get(f"repos/{repository}/pulls/{args.pull}")
            issue = pull_issue(repository, pull["head"]["ref"], (pull["head"].get("repo") or {}).get("full_name"))
            if not pull.get("merged") or issue is None:
                print(f"{repository}#{args.pull}: not a merged lineage pull request of this repository, nothing to post")
                return 0
            known = [args.pull]
        else:
            issue = only[1]
            known = find_issues(gh, repository, issue)
    except (GitHubError, KeyError) as error:
        print(f"FAILED {repository}: {scrub(error, [key])}")
        return 1
    outcome = deliver(gh, repository, issue, key=key, api_base=api_base, acceptance=acceptance, now=datetime.now(timezone.utc),
                      known_pulls=known, dry_run=args.dry_run)
    print(describe(outcome))
    write_summary(env, describe(outcome))
    return 1 if outcome["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
