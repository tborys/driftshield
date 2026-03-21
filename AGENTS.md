# Project Agent Guidance

## Implementation Workflow

- For issue or PR driven work, read the linked issue or PR and the relevant code paths before making changes.
- Before implementing, write a short spec and plan in your working notes or user update, then continue into implementation without waiting for extra human approval unless there is a real blocker or a risky irreversible decision.
- Prefer end to end execution. Do not stop at analysis, planning or partial scaffolding when the task can reasonably be completed in one pass.
- If a change touches frontend or UI behaviour, include browser based verification as part of completion, not just static or unit checks.
- When browser testing is needed, use the real browser tooling available in the environment and report what flow was exercised.

## Handoffs

- When preparing a prompt for another agent, make it autonomous by default.
- Tell the agent to inspect the issue and codebase first, produce a concrete spec and plan, then implement, verify and summarise the result without waiting for a human in the loop.
