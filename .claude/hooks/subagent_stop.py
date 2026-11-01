#!/usr/bin/env python3
"""SubagentStop (cloud routine only): note every subagent that finished, and
post the checker's verdict on the PR word for word, so the lead cannot soften it.

The verdict is the checker's final report: the SubagentHandback message when
there is one (auto mode), else `last_assistant_message`. It must be valid
JSON, name the PR's current head, cover every AC and MNC in the issue, and
not approve with a blocking or major finding. If not, the checker is sent
back once (exit 2). Still invalid, it is posted as `changes` with one
synthetic blocking finding, which the lead escalates. If its text fails the
public safety scan, only the verdict and counts go on GitHub. The full
verdict is kept in .driftshield/verdicts/round-<k>.json either way.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the kit folder clean
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dslib  # noqa: E402


def extract_json(text: str) -> tuple[str, dict] | None:
    text = text or ""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text[text.find("{"):text.rfind("}") + 1]
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return (raw, data) if isinstance(data, dict) else None


def problems(v: dict, pr_head: str | None, items: list[str]) -> list[str]:
    errs = []
    if v.get("verdict") not in ("approve", "changes"):
        errs.append("verdict must be approve or changes")
    if not isinstance(v.get("findings"), list) or not isinstance(v.get("ac_assessment"), list):
        return errs + ["findings and ac_assessment must both be lists"]
    if not re.fullmatch(r"[0-9a-f]{40}", str(v.get("head_sha", ""))):
        errs.append("head_sha must be the full 40 character SHA you reviewed")
    elif pr_head and v["head_sha"] != pr_head:
        errs.append(f"head_sha {v['head_sha'][:7]} is not the PR head {pr_head[:7]}; review the current head")
    assessed = {a.get("ac") for a in v["ac_assessment"] if isinstance(a, dict)}
    missing = [i for i in items if i not in assessed]
    if missing:
        errs.append(f"ac_assessment has no entry for {', '.join(missing)}")
    serious = [f.get("id") for f in v["findings"] if isinstance(f, dict) and f.get("severity") in ("blocking", "major")]
    if v.get("verdict") == "approve" and serious:
        errs.append(f"approve is not allowed with blocking or major findings ({', '.join(map(str, serious))})")
    return errs


def issue_items(run: dict) -> list[str]:
    data = dslib.gh_json(f"repos/{run.get('repository')}/issues/{run.get('issue')}", retry=True) if run.get("issue") else None
    if isinstance(data, dict):
        parsed = dslib.parse_issue(data.get("body") or "")
    else:
        parsed = dslib.read_json(dslib.work() / "spec.json", {}) or {}
    return [i["id"] for i in parsed.get("acceptance_criteria", []) + parsed.get("must_not_change", []) if i.get("id")]


def comment_body(round_no: int, raw: str, v: dict, withheld: list[str]) -> str:
    findings = v.get("findings") or []
    serious = [f for f in findings if f.get("severity") in ("blocking", "major")]
    word = "approved" if v["verdict"] == "approve" else "changes requested"
    head = (f"<!-- {dslib.REVIEW_MARKER} round={round_no} head={v.get('head_sha')} verdict={v['verdict']} -->\n"
            f"**Checker, round {round_no}: {word}.** {len(findings)} findings, {len(serious)} blocking or major.\n\n")
    if withheld:
        return head + "The full verdict failed the public safety scan, so it is kept off GitHub.\n"
    return head + "```json\n" + raw + "\n```\n"


def main() -> int:
    dslib.exit_unless_active()
    hook_input = json.load(sys.stdin)
    if not (dslib.work() / "run.json").exists():
        return 0
    agent_id, agent_type = dslib.norm_agent(hook_input.get("agent_id")), hook_input.get("agent_type") or ""
    with dslib.state("agents.json") as agents:
        agents.setdefault(agent_id, {}).update({"agent_type": agent_type, "transcript": hook_input.get("agent_transcript_path")})
    actor = dslib.actor_from(hook_input)
    finished = {"transcript": Path(hook_input.get("agent_transcript_path") or "").name}
    if agent_type != "checker":
        dslib.append_event("agent.finished", actor=actor, data=finished)
        return 0

    run = dslib.run_info()
    handback = dslib.work() / "handback" / f"{agent_id}.txt"
    text = handback.read_text() if handback.exists() else hook_input.get("last_assistant_message") or ""
    _, pr = dslib.open_pr()
    pr_head = (pr or {}).get("head", {}).get("sha")
    parsed = extract_json(text)
    errors = ["no JSON object found"] if parsed is None else problems(parsed[1], pr_head, issue_items(run))
    if errors and not hook_input.get("stop_hook_active"):
        print("Your verdict is not valid: " + "; ".join(errors) +
              ". Reply again with only the JSON verdict described in your instructions.", file=sys.stderr)
        return 2

    round_no = max((dslib.review_markers(pr["number"]) or 0) if pr else 0,
                   sum(1 for e in dslib.ledger() if e["type"] == "review.verdict")) + 1
    if errors:
        verdict = {"verdict": "changes", "round": round_no, "head_sha": pr_head, "invalid": True, "ac_assessment": [],
                   "findings": [{"id": f"F-{round_no}-0", "axis": "spec", "severity": "blocking", "ac": None,
                                 "location": "", "finding": ("The checker gave no valid verdict after one retry: "
                                                             + "; ".join(errors))[:300]}]}
        raw = json.dumps(verdict, indent=2)
    else:
        raw, verdict = parsed
    dslib.write_json(dslib.work() / "verdicts" / f"round-{round_no}.json", verdict)
    withheld = dslib.unsafe(raw)
    comment_id = None
    if pr:
        posted = dslib.gh_json(f"repos/{run.get('repository')}/issues/{pr['number']}/comments",
                               body={"body": comment_body(round_no, raw, verdict, withheld)})
        comment_id = posted.get("id") if isinstance(posted, dict) else None
    findings = [{**f, "finding": str(f.get("finding", ""))[:300]} for f in verdict.get("findings") or [] if isinstance(f, dict)]
    dslib.append_event(
        "review.verdict", actor=actor, tier="C", round=round_no, pr=pr["number"] if pr else None,
        head_sha=verdict.get("head_sha"), status=verdict["verdict"],
        ac_refs=dslib.items_in(" ".join(str(a.get("ac")) for a in verdict.get("ac_assessment") or [] if isinstance(a, dict))) or None,
        data={"ac_assessment": verdict.get("ac_assessment"), "findings": findings, "resolved": verdict.get("resolved"),
              "comment_id": comment_id, "posted": comment_id is not None, "withheld": bool(withheld),
              "invalid": bool(errors), "checker_round": verdict.get("round")})
    dslib.append_event("agent.finished", actor=actor, data=finished)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        dslib.hook_error("subagent_stop", exc)
        sys.exit(0)
