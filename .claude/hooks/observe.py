#!/usr/bin/env python3
"""PostToolUse and PostToolUseFailure (cloud routine only): write what just
happened into the run ledger.

  - new commits on HEAD                    -> commit.created
  - successful gh api writes and reads     -> github.write, pr.created, pr.body_updated, github.read
  - the claim or blocked comment           -> run.json issue; the draft PR -> run.json pr
  - .driftshield/spec.json or claims.json  -> spec.posted, dod.claimed
  - SubagentHandback and Agent results     -> kept for the SubagentStop and Stop hooks

ds-check writes its own events. Prints nothing, always exits 0.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the kit folder clean
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dslib  # noqa: E402


def stdout_of(response) -> str:
    if isinstance(response, dict):
        return str(response.get("stdout") or response.get("output") or "")
    return str(response or "")


def record_commits(actor: dict) -> None:
    with dslib.state("state.json") as st:
        head = dslib.git("rev-parse", "HEAD")
        last = st.get("last_head")
        if not head or head == last:
            return
        span = f"{last}..{head}" if last else head
        for line in dslib.git("log", "--reverse", "--format=%H%x09%s", span).splitlines():
            sha, _, subject = line.partition("\t")
            dslib.append_event("commit.created", actor=actor, head_sha=sha,
                               ac_refs=dslib.items_in(subject) or None, data={"subject": subject[:200]})
        st["last_head"] = head


def record_github(command: str, response, actor: dict) -> None:
    out = stdout_of(response).strip()
    try:
        payload = json.loads(out) if out.startswith(("{", "[")) else None
    except ValueError:
        payload = None
    for words in dslib.segments(command):
        call = dslib.gh_api_call(words)
        if call is None:
            continue
        path, method = call["path"], call["method"]
        if method == "GET":
            m = re.match(r"^repos/[^/]+/[^/]+/issues/(\d+)(/comments)?$", path)
            if m and payload is not None:
                data = {"issue": int(m.group(1))}
                if m.group(2) and isinstance(payload, list):
                    data["comment_ids"] = [c.get("id") for c in payload if isinstance(c, dict)]
                elif isinstance(payload, dict):
                    data["issue_body_sha256"] = dslib.sha256(payload.get("body") or "")
                    data["issue_updated_at"] = payload.get("updated_at")
                dslib.append_event("github.read", actor=actor, data=data)
            continue
        body = dict(dslib.input_body(call["input"]) or {})
        text = str(body.get("body") or "".join(call["fields"].get("body", [])))
        marker = re.search(r"driftshield-[a-z-]+:v\d", text)
        labels = call["fields"].get("labels[]") or body.get("labels")
        if method == "DELETE" and "/labels/" in path:
            labels = [dslib.label_of(path)]
        data = {"method": method, "endpoint": path, "marker": marker.group(0) if marker else None,
                "labels": labels or None, "id": payload.get("id") if isinstance(payload, dict) else None}
        dslib.append_event("github.write", actor=actor, data=data)
        with dslib.state("run.json") as run:
            m = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\d+)/comments", path)
            if m and run.get("issue") is None and marker and marker.group(0) in (dslib.CLAIM_MARKER, dslib.BLOCKED_MARKER):
                run["issue"] = int(m.group(1))
            if re.fullmatch(r"repos/[^/]+/[^/]+/pulls", path) and method == "POST":
                if not isinstance(payload, dict):  # tool_response shape is undocumented: ask GitHub instead
                    payload = dslib.open_pr()[1] or {}
                run["pr"] = payload.get("number")
                dslib.append_event("pr.created", actor=actor, pr=payload.get("number"),
                                   head_sha=(payload.get("head") or {}).get("sha"), data={"draft": payload.get("draft")})
        if re.fullmatch(r"repos/[^/]+/[^/]+/pulls/\d+", path) and method == "PATCH" and text:
            dslib.append_event("pr.body_updated", actor=actor, pr=int(path.rsplit("/", 1)[1]),
                               ac_refs=dslib.items_in(text) or None, data={"body_sha256": dslib.sha256(text)})


def record_files(actor: dict) -> None:
    with dslib.state("state.json") as st:
        for name, event in (("spec.json", "spec.posted"), ("claims.json", "dod.claimed")):
            path = dslib.work() / name
            if not path.exists():
                continue
            digest = dslib.sha256(path.read_bytes())
            if st.get(name) == digest:
                continue
            st[name] = digest
            data = dslib.read_json(path, None)
            if not isinstance(data, dict):
                dslib.append_event(event, actor=actor, tier="C", status="invalid", data={"why": "not a JSON object"})
                continue
            refs = [i.get("id") for i in data.get("acceptance_criteria", [])] or [a.get("ac") for a in data.get("acs", [])]
            dslib.append_event(event, actor=actor, tier="C", ac_refs=[r for r in refs if r] or None, data=data)


def keep_agent_facts(hook_input: dict) -> None:
    tool = hook_input.get("tool_name")
    if tool == "SubagentHandback" and hook_input.get("agent_id"):
        folder = dslib.work() / "handback"
        folder.mkdir(exist_ok=True)
        message = str((hook_input.get("tool_input") or {}).get("message") or "")
        (folder / f"{dslib.norm_agent(hook_input['agent_id'])}.txt").write_text(message)
    if tool == "Agent":
        resp = hook_input.get("tool_response") or {}
        if isinstance(resp, dict) and resp.get("agentId"):
            with dslib.state("agents.json") as agents:
                agents.setdefault(dslib.norm_agent(resp["agentId"]), {}).update({
                    "subagent_type": (hook_input.get("tool_input") or {}).get("subagent_type"),
                    "model": resp.get("resolvedModel"), "models_used": resp.get("modelsUsed"),
                    "tool_uses": resp.get("totalToolUseCount"), "duration_ms": resp.get("totalDurationMs"),
                    "status": resp.get("status")})


def main() -> int:
    dslib.exit_unless_active()
    try:
        hook_input = json.load(sys.stdin)
    except ValueError:
        return 0
    if not (dslib.work() / "run.json").exists():
        return 0
    actor = dslib.actor_from(hook_input)
    keep_agent_facts(hook_input)
    if hook_input.get("tool_name") == "Bash":
        record_commits(actor)
        command = (hook_input.get("tool_input") or {}).get("command") or ""
        if hook_input.get("hook_event_name") != "PostToolUseFailure" and "gh" in command:
            record_github(command, hook_input.get("tool_response"), actor)
    record_files(actor)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        dslib.hook_error("observe", exc)
        sys.exit(0)
