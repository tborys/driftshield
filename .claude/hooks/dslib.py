"""Shared helpers for the delivery hooks. Standard library only, Python 3.12.

Every hook starts with `exit_unless_active()`: the kit does nothing outside
the cloud delivery routine, so a local Claude Code session in the same repo
is never touched.

Files under `.driftshield/` (git ignores the folder):
  run.json      the run's identity: session, nonce, repository, login, issue, PR
  state.json    the observer's bookkeeping (last seen HEAD, file digests, uploads)
  agents.json   subagent id to type, model and transcript
  ledger.jsonl  append only events, turned into the run record at Stop
All are read and written under one lock.
"""

from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

KIT = Path(__file__).resolve().parent.parent  # the .claude folder
REVIEW_MARKER = "driftshield-agent-review:v1"
CLAIM_MARKER = "driftshield-claim:v1"
BLOCKED_MARKER = "driftshield-delivery-blocked:v1"
END_MARKERS = ("questions", "plan", "blocked", "escalated", "done", "ended")
ITEM = re.compile(r"(?<![A-Za-z0-9])(ac|mnc)[-_]?(\d+)(?![0-9])", re.I)
FINDING = re.compile(r"\bF-\d+-\d+\b")
# Event and transcript ids derive from this namespace. Frozen: changing it changes every id.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:driftshield:delivery-kit:v1")
LEAD_ADDS = {"agent:running", "agent:needs-info", "agent:awaiting-approval", "agent:pr-ready",
             "agent:escalated", "agent:blocked-env"}
LEAD_REMOVES = LEAD_ADDS | {"agent:go", "agent:approved", "agent:interrupted"}


# ---------- the gate ----------

def active() -> bool:
    return os.environ.get("CLAUDE_CODE_REMOTE") == "true" and bool(os.environ.get("DS_ROUTINE_NAME"))


def exit_unless_active() -> None:
    if not active():
        sys.exit(0)


# ---------- files, lock, ledger ----------

def root() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or KIT.parent)


def work() -> Path:
    d = root() / ".driftshield"
    d.mkdir(parents=True, exist_ok=True)
    return d


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


_held = {"fd": None, "depth": 0}


@contextmanager
def lock():
    """One lock for every file under .driftshield/. Re-entrant in a process."""
    if _held["depth"] == 0:
        _held["fd"] = open(work() / ".lock", "a+")
        fcntl.flock(_held["fd"], fcntl.LOCK_EX)
    _held["depth"] += 1
    try:
        yield
    finally:
        _held["depth"] -= 1
        if _held["depth"] == 0:
            fcntl.flock(_held["fd"], fcntl.LOCK_UN)
            _held["fd"].close()


@contextmanager
def state(name: str):
    """Read, change and write back one JSON file under the lock."""
    with lock():
        path = work() / name
        data = read_json(path, {}) or {}
        yield data
        write_json(path, data)


def run_info() -> dict:
    return read_json(work() / "run.json", {}) or {}


def append_event(type_: str, *, actor: dict | None = None, tier: str = "H", at: str | None = None, **fields) -> dict:
    run = run_info()
    with lock():
        path = work() / "ledger.jsonl"
        seq = sum(1 for _ in open(path)) + 1 if path.exists() else 1
        event = {"event_id": sha256(f"{run.get('session_id', '')}:{run.get('nonce', '')}:{seq}"), "seq": seq,
                 "type": type_, "at": at or now(), "tier": tier, "actor": actor or {"role": "lead"}}
        event.update({k: v for k, v in fields.items() if v is not None})
        with open(path, "a") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def ledger() -> list[dict]:
    path = work() / "ledger.jsonl"
    out = []
    for line in (path.read_text().splitlines() if path.exists() else []):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def hook_error(hook: str, exc: BaseException) -> None:
    """Every hook's last resort: never block, but leave a trace."""
    try:
        append_event("hook.error", data={"hook": hook, "error": f"{type(exc).__name__}: {exc}"[:300]})
    except Exception:
        pass
    print(f"delivery kit {hook} failed: {exc}", file=sys.stderr)


def role_of(agent_type: str | None) -> str:
    return {"": "lead", None: "lead", "builder": "builder", "checker": "checker"}.get(agent_type, agent_type or "lead")


def norm_agent(agent_id: str | None) -> str | None:
    """The docs show agent ids both as `agent-abc123` and `abc123`."""
    return agent_id.removeprefix("agent-") if agent_id else agent_id


def actor_from(hook_input: dict) -> dict:
    agent_type = hook_input.get("agent_type") or ""
    actor = {"role": role_of(agent_type)}
    if hook_input.get("agent_id"):
        actor["agent_id"] = norm_agent(hook_input["agent_id"])
    if agent_type:
        actor["agent_type"] = agent_type
    return actor


def current_actor() -> dict:
    """Who is working now: subagents run one at a time, so the last launch
    without a matching finish is the active one, else the lead."""
    open_kind = None
    for e in ledger():
        if e["type"] == "agent.launched":
            open_kind = (e.get("actor") or {}).get("agent_type")
        elif e["type"] == "agent.finished":
            open_kind = None
    return {"role": role_of(open_kind), **({"agent_type": open_kind} if open_kind else {})}


def items_in(text: str) -> list[str]:
    """Checklist item ids in a test name, commit subject or brief.
    `test_ac1_ac2_x` and `AC-1, AC-2` both give ["AC-1", "AC-2"]."""
    seen: list[str] = []
    for kind, num in ITEM.findall(text or ""):
        ref = f"{kind.upper()}-{int(num)}"
        if ref not in seen:
            seen.append(ref)
    return seen


# ---------- git and run identity ----------

def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root(), capture_output=True, text=True)
    return proc.stdout.rstrip() if proc.returncode == 0 else ""  # keep the leading space of `git status` lines


def branch() -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD")


def repo_slug() -> str | None:
    """owner/name from the origin URL, else DS_REPO. Resolved once by
    session_start into run.json; other hooks read it from there."""
    url = git("remote", "get-url", "origin")
    m = re.search(r"([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else os.environ.get("DS_REPO")


def repo() -> str | None:
    return run_info().get("repository") or repo_slug()


def branch_slug(repository: str) -> str:
    """The repository part of a run branch: `acme/My.Widgets` gives
    `acme-my-widgets`. The same rule intel uses to link transcripts."""
    return re.sub(r"[^A-Za-z0-9]+", "-", repository).lower()


def branch_ok(name: str, repository: str | None, issue: int | None) -> bool:
    if not (name and repository and issue):
        return False
    return re.fullmatch(rf"auto/{re.escape(branch_slug(repository))}/issue-{issue}-r\d+", name) is not None


def kit_disk_digest() -> str:
    h = hashlib.sha256()
    for p in sorted(KIT.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(KIT)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def remote_heads() -> dict[str, str]:
    out = {}
    for line in git("ls-remote", "--heads", "origin").splitlines():
        sha, _, ref = line.partition("\t")
        out[ref] = sha
    return out


# ---------- GitHub through gh api ----------

def gh(*args: str, body: dict | None = None) -> tuple[int, str]:
    """`gh api ...`. A body always goes through --input, so markers reach GitHub unchanged."""
    cmd = [os.environ.get("DS_GH", "gh"), "api", *args]
    stdin = None
    if body is not None:
        cmd += ["--input", "-"]
        stdin = json.dumps(body)
    try:
        proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, proc.stdout


def gh_json(*args: str, body: dict | None = None, retry: bool = False):
    """Parsed JSON, or None when the call failed. With retry, one more try after 2 s."""
    for attempt in range(2 if retry else 1):
        if attempt:
            time.sleep(float(os.environ.get("DS_RETRY_WAIT", "2")))
        code, out = gh(*args, body=body)
        if code == 0:
            try:
                return json.loads(out)
            except ValueError:
                return None
    return None


def own(comment: dict, login: str | None) -> bool:
    """Written by this run's GitHub identity: the token's login, or the repo owner."""
    user = (comment.get("user") or {}).get("login")
    return user == login if login else comment.get("author_association") == "OWNER"


def comments(number: int) -> list[dict] | None:
    return gh_json(f"repos/{repo()}/issues/{number}/comments?per_page=100", retry=True)


def review_markers(pr_number: int) -> int | None:
    """Checker verdicts this identity posted on the PR. None when unreadable."""
    found = comments(pr_number)
    if found is None:
        return None
    login = run_info().get("login")
    return sum(1 for c in found if own(c, login) and f"<!-- {REVIEW_MARKER}" in
               (c.get("body") or "").replace("&lt;", "<"))


def open_pr(name: str | None = None) -> tuple[bool, dict | None]:
    """(read ok, the open PR for the branch or None)."""
    slug, name = repo(), name or branch()
    if not slug or not name:
        return False, None
    prs = gh_json(f"repos/{slug}/pulls?head={slug.split('/')[0]}:{name}&state=open", retry=True)
    if not isinstance(prs, list):
        return False, None
    return True, (prs[0] if prs else None)


def run_pr() -> int | None:
    """This run's PR: from run.json, else the open PR for the branch (and remember it)."""
    known = run_info().get("pr")
    if known:
        return known
    ok, pr = open_pr()
    if ok and pr:
        with state("run.json") as run:
            run["pr"] = pr["number"]
        return pr["number"]
    return None


def claim_status(number: int, nonce: str) -> tuple[str, str | None]:
    """('won' | 'lost' | 'missing' | 'unknown', winning nonce). A claim loses
    only to an earlier claim whose run has not posted an end marker."""
    found = comments(number)
    if found is None:
        return "unknown", None
    login = run_info().get("login")
    claims, ended = [], set()
    for c in sorted((c for c in found if own(c, login)), key=lambda c: (c.get("created_at", ""), c.get("id", 0))):
        body = (c.get("body") or "").replace("&lt;", "<")
        for m in re.finditer(r"<!-- driftshield-(claim|delivery-([a-z]+)):v1 run=([A-Za-z0-9]+)", body):
            if m.group(1) == "claim":
                claims.append(m.group(3))
            elif m.group(2) in END_MARKERS:
                ended.add(m.group(3))
    live = [n for n in claims if n not in ended or n == nonce]
    if nonce not in claims:
        return "missing", live[0] if live else None
    return ("won" if live[0] == nonce else "lost"), live[0]


def blocker_ref(blocker: dict, slug: str) -> str:
    m = re.search(r"repos/([^/]+/[^/]+)$", blocker.get("repository_url") or "")
    other = m.group(1) if m else slug
    return f"#{blocker.get('number')}" if other.lower() == slug.lower() else f"{other}#{blocker.get('number')}"


def is_done(issue: dict) -> bool:
    """A blocker is done only when closed as completed, not when a PR is open."""
    return issue.get("state") == "closed" and issue.get("state_reason") == "completed"


def blockers(number: int, slug: str | None = None) -> list[dict] | None:
    """Every native blocked by link on the issue. None when unreadable, which
    callers must treat as blocked."""
    slug = slug or repo()
    data = gh_json(f"repos/{slug}/issues/{number}/dependencies/blocked_by?per_page=100", retry=True) if slug else None
    if not isinstance(data, list):
        return None
    return [{"ref": blocker_ref(b, slug), "id": b.get("id"), "title": b.get("title"), "done": is_done(b)} for b in data]


# ---------- the issue template ----------

SECTION = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.M)
# The template's own placeholders. Other angle brackets (`analyze <file>`) are fine.
PLACEHOLDER = re.compile(r"<(?:outcome|behaviour or contract|path|tests/\.\.\.::test_name|question|answer|number|owner|repo"
                         r"|what this task must not touch)>")


def sections(body: str) -> dict[str, str]:
    """Headings to text. Accepts `##` (markdown template) and `###` (issue form)."""
    body = body or ""
    out: dict[str, str] = {}
    marks = list(SECTION.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out[m.group(1).strip().lower()] = body[m.end():end].strip()
    return out


def parse_issue(body: str) -> dict:
    s = sections(body)

    def pick(*names: str) -> str:
        return next((s[n] for n in names if n in s), "")

    items = []
    for m in re.finditer(r"^\s*-\s*\[[ xX]\]\s*(AC-\d+)\s*:\s*(.+)$", pick("checklist", "acceptance criteria"), re.M):
        text, _, proof = m.group(2).partition("Proof:")
        items.append({"id": m.group(1), "text": text.strip().rstrip("."), "proof": proof.strip().lower() or None})
    mnc = []
    for m in re.finditer(r"^\s*-\s*(MNC-\d+)\s*:\s*(.+)$", pick("must not change"), re.M):
        parts = re.split(r"\s*\b(Paths?|Guard tests?)\s*:\s*", m.group(2))
        entry = {"id": m.group(1), "text": parts[0].strip().rstrip("."), "paths": [], "guard_tests": []}
        for label, value in zip(parts[1::2], parts[2::2]):
            values = [v.strip(" `").removesuffix(".") for v in value.strip().split(",") if v.strip()]
            entry["paths" if label.lower().startswith("path") else "guard_tests"] += values
        mnc.append(entry)
    decisions = [{"id": m.group(2), "state": "open" if m.group(1) == " " else "decided", "text": m.group(3).strip()}
                 for m in re.finditer(r"^\s*-\s*\[([ xX])\]\s*(D-\d+)\s*:\s*(.+)$", pick("decisions"), re.M)]
    depends = [{"repo": m.group(1), "number": int(m.group(2))}
               for m in re.finditer(r"(?:^|\s)([A-Za-z0-9-]+/[A-Za-z0-9._-]+)?#(\d+)\b", pick("depends on"))]
    size = re.search(r"\b(small|large)\b", pick("size").lower())
    profile = pick("verification profile", "verification").splitlines()
    return {
        "problem": pick("problem"),
        "expected": pick("expected behaviour", "expected behavior"),
        "acceptance_criteria": items,
        "must_not_change": mnc,
        "decisions": decisions,
        "depends_on": depends,
        "size": size.group(1) if size else None,
        "profile": profile[0].replace("Profile:", "").strip() if profile and profile[0].strip() else None,
        "placeholders": sorted(set(PLACEHOLDER.findall(body or ""))),
    }


def template_gaps(parsed: dict) -> list[str]:
    gaps = []
    if not parsed["problem"]:
        gaps.append("Problem section is missing")
    if not parsed["acceptance_criteria"]:
        gaps.append("no checklist items in the form `- [ ] AC-1: <outcome>. Proof: test`")
    if any(not i["proof"] for i in parsed["acceptance_criteria"]):
        gaps.append("every checklist item needs `Proof: test | command | ci | manual`")
    if any(not (m["paths"] or m["guard_tests"]) for m in parsed["must_not_change"]):
        gaps.append("every must not change item needs `Paths:` or `Guard test:`")
    if parsed["size"] is None:
        gaps.append("Size must be small or large")
    if parsed["profile"] is None:
        gaps.append("Verification profile is missing")
    if parsed["placeholders"]:
        gaps.append(f"template placeholders left in: {', '.join(parsed['placeholders'][:5])}")
    return gaps


def profile() -> dict:
    return read_json(Path(os.environ.get("DS_PROFILE") or KIT / "delivery" / "profile.json"), {}) or {}


def cap_for(size: str | None) -> int:
    return int(profile().get("caps", {"small": 2, "large": 3}).get(size or "small", 2))


def required_checks(size: str | None) -> list[str]:
    return [c["id"] for c in profile().get("checks", []) if (size or "small") in c.get("required", [])]


# ---------- public safety ----------

def ipv4_public(text: str) -> bool:
    for cand in re.findall(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])", text):
        try:
            if ipaddress.ip_address(cand).is_global:
                return True
        except ValueError:
            continue
    return False


SECRETS = [
    re.compile(r"(?<![A-Za-z0-9_])ds_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"),  # DriftShield workspace key
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"execute-api\.[a-z0-9-]+\.amazonaws\.com", re.I),
]


def deny_terms() -> list[str]:
    """Private terms, from the cloud environment only (DS_DENY_TERMS, comma or newline separated)."""
    raw = os.environ.get("DS_DENY_TERMS", "")
    return sorted({t.strip().lower() for t in re.split(r"[,\n]", raw) if t.strip()})


def term_hits(text: str, terms: list[str]) -> list[str]:
    low = (text or "").lower()
    return [t for t in terms if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)]


def unsafe(text: str, terms: list[str] | None = None) -> list[str]:
    """Why a text must not go public, as categories only. Never echoes a term."""
    found = []
    if term_hits(text, deny_terms() if terms is None else terms):
        found.append("an internal name")
    if ipv4_public(text or ""):
        found.append("a public IP address")
    if any(p.search(text or "") for p in SECRETS):
        found.append("a key or internal address")
    return found


# ---------- shell command parsing, shared by the guard and the observer ----------

SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", "|&", ";;", "$"}
REDIRECTS = {">", ">>", "&>", ">|", "&>>"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
WRAPPERS = {"command": set(), "nohup": set(), "time": {"-f", "-o"}, "exec": {"-a"}, "nice": {"-n"},
            "builtin": set(), "sudo": {"-u", "-g"}, "stdbuf": set(), "timeout": {"-s", "-k"},
            "xargs": {"-I", "-n", "-P", "-L", "-d", "-s", "-E", "-a"}}


def unwrap(words: list[str]) -> list[list[str]]:
    """Strip env, command, nohup, time, sh -c and friends, so the guard sees the real command."""
    while words:
        name = Path(words[0]).name
        if name == "env":
            words = words[1:]
            while words and (words[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])):
                if words[0] in ("-S", "--split-string") and len(words) > 1:
                    return parse_command(" ".join(words[1:]))[0]
                words = words[2:] if words[0] in ("-u", "--unset", "-C", "--chdir") else words[1:]
            continue
        if name in WRAPPERS:
            takes = WRAPPERS[name]
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in takes else words[1:]
            if name == "timeout" and words:
                words = words[1:]  # the duration
            if name == "xargs" and words:
                return [words + ["<args from stdin>"]]  # arguments the guard cannot see
            continue
        if name in SHELLS:
            for i, w in enumerate(words[1:], start=1):
                if re.fullmatch(r"-[a-z]*c[a-z]*", w) and i + 1 < len(words):
                    return parse_command(words[i + 1])[0]
            return [words]
        if name == "eval":
            return parse_command(" ".join(words[1:]))[0]
        break
    return [words] if words else []


def parse_command(command: str) -> tuple[list[list[str]], list[str]]:
    """Simple commands (argv words, wrappers removed) and output redirect targets.
    Quotes are respected; newlines count as `;`. Best effort: a heredoc body is
    read as commands too, so it can only make the guard stricter."""
    text = (command or "").replace("\n", " ; ")
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        tokens = re.findall(r"&&|\|\||[;|&()]|>>|>|[^\s;|&()<>]+", text)
    segs, targets, words = [], [], []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in SEPARATORS:
            if words:
                segs.append(words)
            words = []
        elif t in REDIRECTS or t in (">&", "<", "<<", "<<<"):
            if words and words[-1].isdigit():
                words.pop()  # the fd in `2>`
            if t in REDIRECTS and i + 1 < len(tokens) and tokens[i + 1] != "/dev/null":
                targets.append(tokens[i + 1])
            i += 1
        elif not words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            pass  # leading VAR=value
        else:
            words.append(t)
        i += 1
    if words:
        segs.append(words)
    out = []
    for s in segs:
        out.extend(unwrap(s))
    for inner in re.findall(r"`([^`]*)`|\$\(([^()]*)\)", command or ""):
        out.extend(parse_command(inner[0] or inner[1])[0])  # command substitutions are commands too
    return out, targets


def segments(command: str) -> list[list[str]]:
    return parse_command(command)[0]


GH_VALUE_FLAGS = {"-X", "--method", "-f", "--raw-field", "-F", "--field", "--input", "-H", "--header", "-q",
                  "--jq", "-t", "--template", "--cache", "--hostname", "-p", "--preview"}


def normalise(words: list[str], short_with_value: str = "XfFHqtp") -> list[str]:
    """`--k=v` to `--k v` and `-Xv` to `-X v`, so every spelling parses one way."""
    out = []
    for w in words:
        if w.startswith("--") and "=" in w:
            out += w.split("=", 1)
        elif re.fullmatch(rf"-[{short_with_value}].+", w):
            out += [w[:2], w[2:]]
        else:
            out.append(w)
    return out


def gh_api_call(words: list[str]) -> dict | None:
    """Method, endpoint, query, fields (key to list of values) and input file of a `gh api` call."""
    if len(words) < 2 or Path(words[0]).name != "gh" or words[1] != "api":
        return None
    words = normalise(words[2:])
    method, endpoint, fields, input_file, flags = None, None, {}, None, []
    i = 0
    while i < len(words):
        w = words[i]
        if w in GH_VALUE_FLAGS and i + 1 < len(words):
            v = words[i + 1]
            if w in ("-X", "--method"):
                method = v.upper()
            elif w in ("-f", "--raw-field", "-F", "--field"):
                k, _, val = v.partition("=")
                fields.setdefault(k, []).append(val)
            elif w == "--input":
                input_file = v
            flags.append(w)
            i += 2
            continue
        if w.startswith("-"):
            flags.append(w)
        elif endpoint is None:
            endpoint = w.lstrip("/")
        i += 1
    if method is None:
        method = "POST" if fields or input_file else "GET"
    endpoint = endpoint or ""
    path, _, query = endpoint.partition("?")
    return {"method": method, "endpoint": endpoint, "path": path, "query": query, "fields": fields,
            "input": input_file, "flags": flags}


def input_body(path: str | None) -> dict | None:
    """The JSON object a `--input` file holds. None for stdin or anything unreadable."""
    if not path or path == "-":
        return None
    data = read_json(root() / path, None)
    if data is None:
        data = read_json(Path(path), None)
    return data if isinstance(data, dict) else None


def label_of(path: str) -> str:
    return unquote(path.rsplit("/", 1)[-1])
