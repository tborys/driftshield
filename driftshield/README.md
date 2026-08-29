# driftshield

Find where an AI agent first went wrong.

DriftShield reconstructs a failed agent run as a decision graph, shows where
reasoning first drifted and matches the failure against known community
signatures. It reads Claude Code, Codex CLI, Claude Desktop, Codex Desktop,
OpenClaw, CrewAI and LangChain transcripts.

```bash
pip install driftshield-sdk
driftshield analyze session.jsonl
```

The distribution is called `driftshield-sdk` on PyPI because the name
`driftshield` was already too close to an unrelated project. The import
package and the command are still `driftshield`.

The library surface is two calls:

```python
from driftshield import analyse_run, submit

run = analyse_run(open("session.jsonl", "rb").read(), source="session.jsonl")
print(run.qualification_state, run.findings)

receipt = submit(run)  # community lane: redacted, no key needed
```

`analyse_run` works offline and touches nothing outside the process. `submit`
is the only call that sends anything off the machine, and it only ever sends
`run.redacted_transcript`.

Documentation, the self hosted web UI and the full CLI reference live in the
repository: https://github.com/tborys/driftshield

Licensed under AGPL-3.0-or-later.
