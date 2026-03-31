---
name: pickup-driftshield-issue
description: Pick up a DriftShield GitHub issue from a URL or issue number, gather the parent and strategy context from driftshield-meta, inspect the relevant code and tests, write a short spec and plan, and then continue into implementation, verification, and a draft PR with minimal prompting.
---

# Pick Up DriftShield Issue

Use this skill when a fresh thread should start from a DriftShield GitHub issue URL or issue number with as little prompting as possible.

## Workflow

1. Resolve the issue cleanly.
- Read the issue with `gh issue view <issue> --json number,title,body,url,labels,state`.
- If the user passed a full GitHub URL, extract the repo and issue number first.
- Confirm which local repo the work belongs to before editing files.

2. Pull the planning context.
- If the issue body links a parent issue, read that parent issue before designing the change.
- If the target repo is part of the DriftShield split, treat `driftshield-meta` as the planning source of truth.
- Prefer local planning docs when a sibling repo exists at `../driftshield-meta`.
- If the meta repo is not checked out locally, read the same docs from GitHub:
  - `https://github.com/demouser/driftshield-meta/blob/main/strategy/2026-03-29-oss-commercial-strategy-design.md`
  - `https://github.com/demouser/driftshield-meta/blob/main/plans/2026-03-29-phase1-split-and-ship.md`
- Treat the parent issue and strategy doc as the source of truth for phase, sequencing, and manual-only boundaries.

3. Read repo rules and map the affected system.
- Read `AGENTS.md` and `CLAUDE.md` in the target repo if they exist.
- Read [../driftshield-issue-implementation/references/repo-map.md](../driftshield-issue-implementation/references/repo-map.md) to find the relevant backend, DB, CLI, or frontend surfaces.
- Read nearby tests before changing anything.
- If the issue crosses layers, trace the full chain before planning.

4. Write the short spec and plan first.
- Keep it concise but concrete.
- Cover the intended behavior, affected layers, verification plan, and any likely blocker or follow-up.
- If the issue is implementation work, continue immediately after the plan unless a real blocker appears.

5. Keep workflow state accurate.
- If coding work is starting, move the project item to `In Progress` or confirm that it is already there.
- Keep the linked issue and project item `In Progress` while implementation or PR follow-up is active.
- If the issue is labeled `manual-only`, stop after clarifying the safe next step instead of implementing.
- If the issue is under-scoped or blocked, leave a precise comment and stop instead of guessing.

6. Continue into execution by default.
- Follow the same end-to-end expectations as `$driftshield-issue-implementation`.
- Read [../driftshield-issue-implementation/references/implementation-checklist.md](../driftshield-issue-implementation/references/implementation-checklist.md) for verification depth.
- Add or update focused tests first where practical.
- Run the targeted verification needed for the touched area.
- If UI behavior changes, include real browser verification.
- After local verification, push the branch to the private working repo and open or update a draft PR linked to the issue.

7. Close out clearly.
- Summarize what changed, what was verified, and any residual risk.
- Do not close the issue or move the project item to `Done` until the PR is merged.

## Guardrails

- Do not merge the PR.
- Do not perform public OSS publication, repo creation, visibility changes, archive actions, or external service changes unless the task explicitly requires them and the repo rules allow them.
- Prefer a small concrete plan over a long restatement of the issue.
- If the issue is analysis-only, stop after the spec and plan instead of implementing.

## Good Starting Prompt

Use $pickup-driftshield-issue for issue <url> and take it from issue context through spec, plan, implementation, verification, and a draft PR without extra prompting.
