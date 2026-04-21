# DriftShield

Find where an AI agent first went wrong.

DriftShield is an open source failed-run investigation tool for AI workflows. When a run
breaks, teams often fall back on logs, traces, and guesswork. DriftShield reconstructs the run
as a decision graph, highlights where reasoning first drifted, and turns the failure into a
report a human can inspect.

As teams move from single prompts to multi-step and agentic workflows, failures become harder to
explain. A workflow can follow the right steps but still produce the wrong outcome, acknowledge a
constraint and then ignore it, or behave inconsistently across runs. Similar failures can recur,
but teams still end up treating each broken run like a one-off debugging exercise.

The OSS core focuses on one failed run at a time. It helps teams explain what happened, inspect
where the run broke, and produce an investigation-grade artifact for debugging, review, and
follow-up.

## Why DriftShield

- Move from raw logs and traces to an inspectable failure investigation
- See where a workflow broke and how the run drifted off course
- Give engineers and product teams a shared artifact for debugging and review

## Built For

- AI engineers building multi-step or agentic workflows
- Product teams shipping AI-powered features
- Teams where reliability and correctness matter

## Demo

<video src="https://github.com/user-attachments/assets/bc103601-aa85-4106-81a3-cf352d4e10a8" controls width="100%"></video>

## Supported Sources

| Source | Format | Status |
|--------|--------|--------|
| Claude Code | JSONL | Stable |
| Claude Desktop | JSON | Experimental |
| Codex CLI | JSONL | Experimental |
| Codex Desktop | JSON | Experimental |
| OpenClaw | JSONL | Experimental |

DriftShield uses a parser protocol. New sources can be added by implementing a single interface.

## Community signature packs

Phase 2a uses a deliberately simple pull flow for community-safe signature packs. Packs are versioned JSON manifests that follow the Phase 2a contract and can be fetched directly from a Git ref or tag.

Example:

```bash
source .venv/bin/activate
driftshield signatures pull community-general --ref <git-tag-or-commit>
```

By default this pulls from `tborys/driftshield` and stores the validated manifest under `~/.local/share/driftshield/signatures/<pack-name>/<pack-version>/`.

If you need to test or mirror a pack source, override the source URL directly:

```bash
driftshield signatures pull community-general \
  --ref local-smoke \
  --url http://127.0.0.1:8000/community-general.json
```

Compatibility rules for the first rollout:

- `schema_version` is the compatibility gate and is validated before installation
- `pack_metadata.version` is the pack release version and determines the install path
- only `pack_kind: community` is accepted by the OSS pull path
- the pull flow is intentionally replaceable later without committing DriftShield to a marketplace design

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker (optional, but needed for the local API/dashboard Postgres path)

### 1. Setup from a clean clone

```bash
git clone https://github.com/tborys/driftshield.git
cd driftshield
./scripts/dev-setup.sh
```

This creates local env files, installs backend and frontend dependencies, and starts local
Postgres if Docker is available. No private credentials or proprietary setup steps are
required for the OSS path.

### 2. Get a first useful result

```bash
cd driftshield
source .venv/bin/activate
driftshield report tests/fixtures/transcripts/sample_claude_code_session.jsonl --type summary
```

This generates a forensic report from the bundled sample transcript, which is the shortest
supported path from a clean clone to a meaningful DriftShield investigation artifact.

### 3. Verify the repo

```bash
cd ..
./scripts/dev-verify.sh
```

### 4. Run the full local stack

The API ingest flow and web dashboard expect a local Postgres instance. The supported dev path
is `docker-compose.dev.yml`; the production `docker-compose.yml` is not the primary quickstart.

Start the backend:

```bash
cd driftshield
source .venv/bin/activate
set -a
source .env
set +a
driftshield-api
```

The backend reads `API_KEY` and `DATABASE_URL` from process env, so source `driftshield/.env`
before starting it.

Start the frontend (in a separate terminal):

```bash
cd driftshield/frontend
npm run dev
```

Open http://localhost:5173 to view ingested sessions.

### 5. Ingest a transcript into the local API

```bash
cd driftshield
source .venv/bin/activate
set -a
source .env
set +a
DRIFTSHIELD_API_URL=http://localhost:8080 \
driftshield ingest --path tests/fixtures/transcripts/sample_claude_code_session.jsonl
```

Or ingest the latest Claude Code session for the current project:

```bash
set -a
source .env
set +a
source .venv/bin/activate
driftshield ingest --latest
```

## How It Works

```
Transcript → Parser → Canonical Events → Decision Graph → Risk Heuristics → Report
```

1. **Parsers** read raw transcripts and produce a sequence of canonical events (tool calls, outputs, branches, handoffs, assumptions, constraint checks)
2. **Graph builder** connects events into a decision tree with parent/child relationships
3. **Risk heuristics** scan every node for failure patterns
4. **Inflection detection** scores points in the session where the agent's trajectory changed
5. **Reports** present findings as Markdown, JSON, or through the web dashboard

## Built-in Risk Detectors

| Detector | What it catches |
|----------|----------------|
| Coverage Gap | Output references fewer items than the input provided |
| Assumption Mutation | An assumption changed between steps without acknowledgement |
| Policy Divergence | Agent behaviour contradicts an earlier stated constraint |
| Constraint Violation | An explicit constraint was checked and then ignored |
| Context Contamination | Information from one context leaks into an unrelated decision |

Risk detectors are additive. Each implements a `RiskHeuristic` interface and can be extended without modifying existing code.

## CLI Reference

All commands run from the `driftshield/` directory after `source .venv/bin/activate`.

```bash
# Ingest a transcript file
driftshield ingest --path <file.jsonl>

# Ingest the latest Claude Code session
driftshield ingest --latest

# List ingested sessions
driftshield list

# Analyse a session for risk signals
driftshield analyze <session-id-or-path>

# Inspect a specific node in the decision graph
driftshield inspect <file.jsonl> --node 0

# Generate a report
driftshield report <file.jsonl>

# Discover available transcript sources
driftshield connectors list
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic |
| CLI | Typer + Rich |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, TanStack Query |
| Graph visualisation | @xyflow/react |
| Database | PostgreSQL 16 (production), SQLite in-memory (tests) |
| Testing | pytest (backend), Playwright (e2e), Vitest (frontend unit) |
| Infrastructure | Docker, docker-compose, GitHub Actions |

## Project Structure

```
driftshield/
├── src/driftshield/
│   ├── api/            # FastAPI routes (ingest, sessions, reports, connectors)
│   ├── cli/            # Typer commands and session discovery
│   ├── connectors/     # Auto-discovery of transcript sources
│   ├── core/
│   │   ├── analysis/   # Risk heuristics, inflection detection, session analysis
│   │   ├── graph/      # Decision graph builder and models
│   │   └── models.py   # Domain models (CanonicalEvent, RiskClassification)
│   ├── db/             # SQLAlchemy models, persistence, Alembic migrations
│   ├── parsers/        # Transcript format parsers (protocol + implementations)
│   └── reports/        # Jinja2 report templates
├── frontend/           # React investigation dashboard
├── tests/              # Backend test suite
└── docker-compose.yml  # Production deployment
```

## Docker Deployment

```bash
cd driftshield

# Create .env with required values
cp .env.example .env
# Edit .env: set API_KEY and DB_PASSWORD

# Start the stack
docker compose up -d
```

The production compose file runs the app on port 8080 with PostgreSQL 16. Both `API_KEY` and `DB_PASSWORD` are required and will fail on startup if missing.

## Contributing

Contributions are welcome. DriftShield is founded and maintained by Tomasz Borys, and pull requests are reviewed with that founder-led OSS scope in mind. Please follow these steps:

1. **Fork** the repository to your own GitHub account
2. **Clone** your fork locally
3. **Create a branch** from `main` for your change
4. **Make your changes** with tests where applicable
5. **Run verification** before submitting:
   ```bash
   ./scripts/dev-verify.sh
   ```
6. **Open a pull request** from your fork's branch to `tborys/driftshield:main`

All pull requests are reviewed and merged by Tomasz Borys, DriftShield's founder and current maintainer. Direct pushes to `main` are not accepted.

### Code style

- Python: Ruff (line length 100), MyPy strict, conventional commits
- TypeScript: ESLint 9 flat config, strict mode, no `any` types
- Tailwind CSS for frontend styling

### Adding a parser

Implement the `ParserProtocol` interface in `src/driftshield/parsers/`. Each parser converts a raw transcript format into a list of `CanonicalEvent` objects. See `claude_code.py` for a reference implementation.

## Licence

AGPL-3.0-or-later. See [LICENSE](./LICENSE).
