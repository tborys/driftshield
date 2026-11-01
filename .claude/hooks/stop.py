#!/usr/bin/env python3
"""Stop and StopFailure (cloud routine only): end the run, build the record,
send it to DriftShield.

The end state comes from this run's own label writes, never from labels an
earlier run left; agent:stop wins. A run that ends interrupted or unknown
swaps agent:running for agent:interrupted and leaves one end comment, so the
issue is not stuck. The record carries integrity facts for an after the fact
check: remote branches before and after, kit and .github changes since the
base, and the kit's digest at both ends.

Then, inside one deadline under the hook's 600 s limit:
  1. every transcript through the public SDK (receipts kept as they arrive)
  2. session links that tie those uploads to the issue and PR
  3. the record, only if DRIFTSHIELD_RECORD_URL is set (no door yet)
Prints nothing, never blocks, always exits 0.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True  # keep the kit folder clean
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dslib  # noqa: E402

BUDGET_S = int(os.environ.get("DS_STOP_BUDGET_S", "540"))  # under the 600 s hook timeout
END_LABELS = {"agent:pr-ready": ("pr_ready", None), "agent:needs-info": ("needs_info", "needs_info"),
              "agent:awaiting-approval": ("awaiting_approval", "awaiting_approval"),
              "agent:blocked-env": ("blocked_env", "env"), "agent:escalated": ("escalated", "escalated")}


def own_writes(events: list[dict]) -> list[dict]:
    return [e.get("data") or {} for e in events if e["type"] == "github.write"]


def end_state(hook_input: dict, issue_labels: set[str], events: list[dict]) -> tuple[str, str | None]:
    if hook_input.get("hook_event_name") == "StopFailure":
        return "interrupted", "usage_limit" if hook_input.get("error") == "rate_limit" else "api_error"
    if "agent:stop" in issue_labels:
        return "stopped", "stop_requested"
    writes = own_writes(events)
    if any(w.get("marker") == dslib.BLOCKED_MARKER for w in writes):
        return "blocked", "blocked_by"
    added = [l for w in writes if w.get("method") == "POST" and w.get("endpoint", "").endswith("/labels")
             for l in (w.get("labels") or [])]
    for label in reversed(added):
        if label in END_LABELS:
            state, reason = END_LABELS[label]
            if state == "escalated" and any((e.get("data") or {}).get("kind") == "round_cap" for e in events):
                reason = "round_cap"
            return state, reason
    return "unknown", "unknown"


def leave_cleanly(run: dict, state: str, issue_labels: set[str], events: list[dict]) -> None:
    """An interrupted or unknown end must not leave agent:running, or the issue sticks."""
    slug, number = run["repository"], run["issue"]
    if "agent:running" in issue_labels:
        dslib.gh(f"repos/{slug}/issues/{number}/labels/agent:running", "--method", "DELETE")
        dslib.gh_json(f"repos/{slug}/issues/{number}/labels", body={"labels": ["agent:interrupted"]})
    ended = any(str(w.get("marker") or "").removeprefix("driftshield-delivery-").removesuffix(":v1") in dslib.END_MARKERS
                for w in own_writes(events))
    if not ended:
        body = (f"This run stopped before it finished ({state}). It can be started again.\n"
                f"<!-- driftshield-delivery-ended:v1 run={run.get('nonce')} state={state} -->")
        dslib.gh_json(f"repos/{slug}/issues/{number}/comments", body={"body": body})


def integrity(run: dict) -> dict:
    before, after = run.get("refs_before") or {}, dslib.remote_heads()
    changed = [{"ref": r, "before": before.get(r), "after": after.get(r)}
               for r in sorted(set(before) | set(after)) if before.get(r) != after.get(r)]
    base = run.get("base_sha") or "HEAD"
    paths = set(dslib.git("diff", "--name-only", base, "HEAD", "--", ".claude", ".github").splitlines())
    paths |= {l[3:] for l in dslib.git("status", "--porcelain", "--", ".claude", ".github").splitlines()}
    return {"refs_changed": changed, "kit_paths_changed": sorted(p for p in paths if p and "__pycache__" not in p),
            "kit_tree_start": run.get("kit_tree"), "kit_tree_end": dslib.git("rev-parse", "HEAD:.claude") or None,
            "kit_disk_sha256_start": run.get("kit_disk_sha256"), "kit_disk_sha256_end": dslib.kit_disk_digest()}


def usage(path: Path) -> dict:
    """Token totals from a transcript, one count per API message."""
    totals, seen, model = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}, set(), None
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return {**totals, "model": None}
    for line in lines:
        try:
            msg = json.loads(line).get("message") or {}
        except (ValueError, AttributeError):
            continue
        u = msg.get("usage") if isinstance(msg, dict) else None
        if not u or msg.get("id") in seen:
            continue
        seen.add(msg.get("id"))
        model = msg.get("model") or model
        totals["input"] += u.get("input_tokens", 0)
        totals["output"] += u.get("output_tokens", 0)
        totals["cache_read"] += u.get("cache_read_input_tokens", 0)
        totals["cache_creation"] += u.get("cache_creation_input_tokens", 0)
    return {**totals, "model": model}


def transcripts(hook_input: dict, agents: dict) -> list[dict]:
    main_path = Path(hook_input.get("transcript_path") or "")
    found = [{"role": "lead", "agent_id": None, "agent_type": None, "path": main_path}] if main_path.is_file() else []
    folder = main_path.with_suffix("") / "subagents"
    paths = {Path(a["transcript"]) for a in agents.values() if a.get("transcript")}
    paths |= set(folder.glob("agent-*.jsonl")) if folder.is_dir() else set()
    for p in sorted(paths):
        if p.is_file():
            agent_id = p.stem.removeprefix("agent-")
            a = agents.get(agent_id, {})
            kind = a.get("agent_type") or a.get("subagent_type") or ""
            found.append({"role": dslib.role_of(kind), "agent_id": agent_id, "agent_type": kind, "path": p})
    return found


def settle(paths: list[Path], max_wait: float = 10.0) -> None:
    """Transcripts are written asynchronously; wait until sizes stop moving."""
    deadline, last = time.time() + max_wait, None
    while time.time() < deadline:
        sizes = [p.stat().st_size if p.exists() else 0 for p in paths]
        if sizes == last:
            return
        last = sizes
        time.sleep(1)


def post_json(url: str, body: dict, deadline: float) -> tuple[int, dict | None]:
    data, status = json.dumps(body).encode(), 0
    for wait in (0, 3, 10, 30):
        if time.time() + wait + 5 > deadline:
            break
        time.sleep(wait)
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json", "X-API-Key": os.environ.get("DRIFTSHIELD_API_KEY", "")})
        try:
            with urllib.request.urlopen(req, timeout=min(30, max(5, deadline - time.time()))) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status in (400, 401, 403, 404, 413, 422):
                return status, None
        except (urllib.error.URLError, OSError, ValueError):
            status = 0
    return status, None


def api_base() -> str | None:
    if os.environ.get("DRIFTSHIELD_API_URL"):
        return os.environ["DRIFTSHIELD_API_URL"].rstrip("/")
    m = re.match(r"^(https?://[^/]+)", os.environ.get("DRIFTSHIELD_INTAKE_URL", ""))
    return m.group(1) if m else None


def upload(found: list[dict], run: dict, ctx: dict, deadline: float) -> list[dict]:
    sdk = os.environ.get("DS_SDK_PYTHON", "/opt/ds-sdk/bin/python")
    missing = [n for n in ("DRIFTSHIELD_API_KEY", "DRIFTSHIELD_INTAKE_URL") if not os.environ.get(n)]
    if missing or not Path(sdk).exists():
        why = f"missing {', '.join(missing)}" if missing else "SDK interpreter not found"
        return [{"role": t["role"], "agent_id": t["agent_id"], "status": "not_sent", "error": why} for t in found]
    with dslib.state("state.json") as st:
        sent = dict(st.get("sent") or {})
    items, out = [], []
    for t in found:
        digest = dslib.sha256(t["path"].read_bytes())
        if sent.get(str(t["path"])) == digest:
            out.append({"role": t["role"], "agent_id": t["agent_id"], "status": "unchanged"})
            continue
        key = f"{run.get('session_id')}:{run.get('nonce')}:{t['agent_id'] or 'lead'}"
        items.append({"path": str(t["path"]), "run_key": key, "source_session_id": key,
                      "agent_id": f"delivery-{t['role']}", "model_name": ctx["models"].get(t["agent_id"] or "lead"),
                      "workflow_reference": "driftshield-delivery", "project_reference": f"{ctx['repo']}#{ctx['issue']}",
                      "source_report_id": f"{key}@{digest[:16]}", "_meta": t, "_digest": digest})
    if not items:
        return out
    job = {"intake_url": os.environ["DRIFTSHIELD_INTAKE_URL"], "deadline": deadline - 60,
           "items": [{k: v for k, v in i.items() if not k.startswith("_")} for i in items]}
    try:
        proc = subprocess.run([sdk, str(Path(__file__).with_name("ds_submit.py"))], input=json.dumps(job),
                              capture_output=True, text=True, timeout=max(10, deadline - 30 - time.time()))
        lines = proc.stdout
    except subprocess.TimeoutExpired as exc:  # keep the receipts that arrived
        lines = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    except OSError:
        lines = ""
    receipts = {}
    for line in lines.splitlines():
        try:
            r = json.loads(line)
            receipts[r.get("path")] = r
        except ValueError:
            continue
    for i in items:
        r = receipts.get(i["path"], {"status": "error", "error": "no receipt before the deadline"})
        if r.get("status") == "submitted":
            sent[i["path"]] = i["_digest"]
        out.append({"role": i["_meta"]["role"], "agent_id": i["_meta"]["agent_id"], "agent_type": i["_meta"]["agent_type"],
                    "file": Path(i["path"]).name, **{k: v for k, v in r.items() if k != "path"}})
    with dslib.state("state.json") as st:
        st["sent"] = sent
    return out


def link_sessions(uploads: list[dict], ctx: dict, run: dict, events: list[dict], deadline: float) -> None:
    base = api_base()
    if not base:
        return
    lineage = dslib.branch_ok(ctx["branch"] or "", ctx["repo"], ctx["issue"])
    verdicts = {(e.get("actor") or {}).get("agent_id"): e for e in events if e["type"] == "review.verdict"}
    entries = []
    for u in uploads:
        if u.get("status") != "submitted":
            continue
        identity = {"repository": ctx["repo"], "issue_number": ctx["issue"], "pull_request": None, "head_sha": None,
                    "review_round": None, "dispatch_key": None, "branch": None}
        verdict = verdicts.get(u.get("agent_id"))
        if u["role"] == "checker" and verdict and ctx["pr"] and verdict.get("head_sha"):
            role = "review"
            identity.update(pull_request=ctx["pr"], head_sha=verdict["head_sha"], review_round=verdict.get("round"))
        elif u["role"] != "checker" and lineage:
            role = "implementation"
            identity["branch"] = ctx["branch"]
        else:
            u["link"] = "not_linked: no identity intel accepts (see docs/intel-door.md)"
            continue
        entries.append((u, {"submission_id": u["submission_id"], "role": role, "captured_at": dslib.now(),
                            "capture_run_key": f"delivery:{run.get('session_id')}:{run.get('nonce')}:{u.get('agent_id') or 'lead'}",
                            "identity": identity}))
    for _ in range(3):
        if not entries or time.time() > deadline - 30:
            return
        body = {"schema": "driftshield-work-session-links.v1", "observed_at": dslib.now(), "sessions": [e for _, e in entries]}
        status, payload = post_json(f"{base}/v1/teams/work/evidence", body, deadline - 20)
        results = {r.get("submission_id"): r for r in (payload or {}).get("sessions", [])} if isinstance(payload, dict) else {}
        for u, e in entries:
            r = results.get(e["submission_id"])
            u["link"] = r.get("status") if r else f"http {status}"
        entries = [(u, e) for u, e in entries if results.get(e["submission_id"], {}).get("retryable")]
        time.sleep(5)


def build_record(ctx: dict, run: dict, events: list[dict], uploads: list[dict], issue_data: dict, facts: dict) -> dict:
    spec = dslib.read_json(dslib.work() / "spec.json", None)
    parsed = dslib.parse_issue(issue_data.get("body") or "")
    if not isinstance(spec, dict):
        spec = {"source": "issue", "acceptance_criteria": parsed["acceptance_criteria"],
                "must_not_change": parsed["must_not_change"], "assumptions": [], "tasks": []}
    spec["decisions"] = parsed["decisions"]
    notes = []
    notes_path = dslib.work() / "notes.md"
    for line in (notes_path.read_text()[:6000].splitlines() if notes_path.exists() else []):
        m = re.match(r"^\s*[-*]\s*(?:(lead|builder|checker)\s*:\s*)?(.+)$", line, re.I)
        if m:
            notes.append({"by": (m.group(1) or "lead").lower(), "text": m.group(2).strip()[:500]})
    drill = dslib.read_json(dslib.work() / "drill.json", None)
    seqs, tokens = [e["seq"] for e in events], ctx["tokens"]
    total = sum(sum(v.values()) for v in tokens.values()) or 1
    return {
        "schema": "driftshield-delivery-record.v1",
        "work": {"repository": ctx["repo"], "issue_number": ctx["issue"], "pr": ctx["pr"], "branch": ctx["branch"]},
        "run": {
            "session_id": run.get("session_id"), "remote_session_id": run.get("remote_session_id"),
            "nonce": run.get("nonce"), "routine": run.get("routine"), "kit_tree": run.get("kit_tree"),
            "size": spec.get("size") or parsed["size"], "profile": spec.get("profile") or parsed["profile"],
            "started_at": run.get("started_at"), "ended_at": dslib.now(),
            "end_state": ctx["end_state"], "stop_reason": ctx["stop_reason"],
            "practice_run": bool(drill), "seeded_fault": drill if isinstance(drill, dict) else None,
            "models": ctx["models"],
            "tokens": {k: sum(v[k] for v in tokens.values()) for k in ("input", "output", "cache_read", "cache_creation")}
            | {"by_role": {r: round(sum(v.values()) / total, 3) for r, v in tokens.items()}},
            "last_seq": max(seqs) if seqs else 0,
            "sequence_complete": seqs == list(range(1, len(seqs) + 1)) and bool(events) and events[-1]["type"] == "run.ended",
        },
        "spec": spec,
        "integrity": facts,
        "transcripts": uploads,
        "notes": notes,
        "events": events,
    }


def main() -> int:
    dslib.exit_unless_active()
    hook_input = json.load(sys.stdin)
    run = dslib.run_info()
    if not run or not run.get("issue") or hook_input.get("background_tasks"):
        return 0  # nothing claimed (an idle safety run), or still waiting on background work
    deadline = time.time() + BUDGET_S
    issue_data = dslib.gh_json(f"repos/{run['repository']}/issues/{run['issue']}", retry=True) or {}
    issue_labels = {l.get("name") for l in issue_data.get("labels", [])}
    events = dslib.ledger()
    state, reason = end_state(hook_input, issue_labels, events)
    if state in ("interrupted", "unknown"):
        leave_cleanly(run, state, issue_labels, events)
    dslib.append_event("run.ended", status=state, data={
        "end_state": state, "stop_reason": reason, "error": hook_input.get("error"),
        "error_details": str(hook_input.get("error_details") or "")[:300] or None})
    events = dslib.ledger()
    facts = integrity(run)
    agents = dslib.read_json(dslib.work() / "agents.json", {}) or {}
    found = transcripts(hook_input, agents)
    settle([t["path"] for t in found])
    tokens, models = {}, {"lead": run.get("model")}
    for t in found:
        u = usage(t["path"])
        model = u.pop("model")
        models[t["agent_id"] or "lead"] = agents.get(t["agent_id"] or "", {}).get("model") or model or models.get("lead")
        role = tokens.setdefault(t["role"], {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0})
        for k in role:
            role[k] += u[k]
    run = dslib.run_info()
    ctx = {"repo": run["repository"], "issue": run["issue"], "pr": dslib.run_pr(), "branch": dslib.branch(),
           "end_state": state, "stop_reason": reason, "tokens": tokens, "models": models}
    out = dslib.work() / "out"
    pending = [{"role": t["role"], "agent_id": t["agent_id"], "status": "not_sent", "error": "upload pending"} for t in found]
    dslib.write_json(out / "record.json", build_record(ctx, run, events, pending, issue_data, facts))  # survives a timeout
    uploads = upload(found, run, ctx, deadline)
    link_sessions(uploads, ctx, run, events, deadline)
    record = build_record(ctx, run, events, uploads, issue_data, facts)
    dslib.write_json(out / "record.json", record)
    sent = {"status": "no_door", "detail": "DRIFTSHIELD_RECORD_URL is not set; intel has no route for the record yet"}
    if os.environ.get("DRIFTSHIELD_RECORD_URL"):
        status, _ = post_json(os.environ["DRIFTSHIELD_RECORD_URL"], record, deadline)
        sent = {"status": "sent" if 200 <= status < 300 else "error", "http": status}
    dslib.write_json(out / "uploads.json", {"transcripts": uploads, "record": sent, "at": dslib.now()})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        dslib.hook_error("stop", exc)
        sys.exit(0)
