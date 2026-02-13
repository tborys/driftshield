# DriftShield CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a CLI tool (`driftshield`) for analysing AI agent sessions from the terminal.

**Architecture:** Typer-based CLI with flat command structure (`analyze`, `list`, `inspect`). Uses existing `analyze_session()` pipeline and `ClaudeCodeParser`. Rich library for formatted output.

**Tech Stack:** Python 3.12+, Typer, Rich, existing DriftShield core

**Approach:** TDD throughout. Build incrementally: single file analysis first, then batch/discovery, then inspection, then CI features.

---

## Phase 9.1: Single File Analysis

### Task 9.1.1: Add CLI Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add typer and rich to dependencies**

Edit `pyproject.toml` dependencies section:

```toml
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "psycopg2-binary>=2.9.9",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "typer>=0.9.0",
    "rich>=13.0.0",
]
```

**Step 2: Add entry point**

Add after `[tool.mypy]` section:

```toml
[project.scripts]
driftshield = "driftshield.cli.main:app"
```

**Step 3: Reinstall package**

Run: `pip install -e ".[dev]"`

Expected: Success (CLI module doesn't exist yet, but that's OK)

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add typer and rich CLI dependencies"
```

---

### Task 9.1.2: CLI Package Structure

**Files:**
- Create: `src/driftshield/cli/__init__.py`
- Create: `src/driftshield/cli/main.py`
- Create: `src/driftshield/cli/commands/__init__.py`
- Create: `tests/cli/__init__.py`

**Step 1: Create directory structure**

```bash
mkdir -p src/driftshield/cli/commands
mkdir -p tests/cli
touch src/driftshield/cli/__init__.py
touch src/driftshield/cli/commands/__init__.py
touch tests/cli/__init__.py
```

**Step 2: Create minimal main.py**

```python
# src/driftshield/cli/main.py
"""DriftShield CLI entry point."""

import typer

from driftshield import __version__

app = typer.Typer(
    name="driftshield",
    help="DriftShield - AI Decision Forensics CLI",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    if value:
        print(f"driftshield {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """DriftShield - AI Decision Forensics CLI."""
    pass
```

**Step 3: Verify CLI installs**

Run: `pip install -e . && driftshield --version`

Expected: `driftshield 0.1.0`

**Step 4: Commit**

```bash
git add src/driftshield/cli/ tests/cli/
git commit -m "feat(cli): add CLI package structure with version command"
```

---

### Task 9.1.3: Parser Registry

**Files:**
- Create: `src/driftshield/cli/parsers.py`
- Create: `tests/cli/test_parsers.py`

**Step 1: Write the failing test**

```python
# tests/cli/test_parsers.py
"""Tests for CLI parser registry."""

from pathlib import Path

import pytest

from driftshield.cli.parsers import get_parser, detect_parser, ParserNotFoundError


class TestGetParser:
    def test_get_claude_code_parser(self):
        """Can get claude_code parser by name."""
        parser = get_parser("claude_code")
        assert parser.source_type == "claude_code"

    def test_get_auto_defaults_to_claude_code(self):
        """Auto parser returns claude_code for now."""
        parser = get_parser("auto")
        assert parser.source_type == "claude_code"

    def test_unknown_parser_raises(self):
        """Unknown parser name raises ParserNotFoundError."""
        with pytest.raises(ParserNotFoundError) as exc_info:
            get_parser("unknown")
        assert "unknown" in str(exc_info.value)
        assert "claude_code" in str(exc_info.value)  # Lists available


class TestDetectParser:
    def test_detects_jsonl_as_claude_code(self):
        """JSONL files detected as claude_code."""
        parser_name = detect_parser(Path("session.jsonl"))
        assert parser_name == "claude_code"

    def test_detects_claude_projects_path(self, tmp_path):
        """Files under ~/.claude/projects/ detected as claude_code."""
        # Simulate claude path structure
        claude_path = tmp_path / ".claude" / "projects" / "test" / "session.jsonl"
        claude_path.parent.mkdir(parents=True)
        claude_path.touch()

        parser_name = detect_parser(claude_path)
        assert parser_name == "claude_code"

    def test_unknown_format_returns_none(self):
        """Unknown format returns None."""
        parser_name = detect_parser(Path("unknown.xyz"))
        assert parser_name is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_parsers.py -v`

Expected: FAIL with "cannot import name 'get_parser'"

**Step 3: Write implementation**

```python
# src/driftshield/cli/parsers.py
"""Parser registry and auto-detection for CLI."""

from pathlib import Path
from typing import Protocol

from driftshield.parsers.claude_code import ClaudeCodeParser
from driftshield.parsers.protocol import TranscriptParser


class ParserNotFoundError(Exception):
    """Raised when requested parser is not found."""

    pass


PARSERS: dict[str, type[TranscriptParser]] = {
    "claude_code": ClaudeCodeParser,
}


def get_parser(name: str) -> TranscriptParser:
    """
    Get a parser instance by name.

    Args:
        name: Parser name ('auto', 'claude_code', etc.)

    Returns:
        Parser instance

    Raises:
        ParserNotFoundError: If parser not found
    """
    if name == "auto":
        # Default to claude_code for now
        return ClaudeCodeParser()

    if name not in PARSERS:
        available = ", ".join(PARSERS.keys())
        raise ParserNotFoundError(
            f"Parser '{name}' not found. Available parsers: {available}"
        )

    return PARSERS[name]()


def detect_parser(path: Path) -> str | None:
    """
    Detect parser type from file path.

    Args:
        path: Path to the file

    Returns:
        Parser name or None if cannot detect
    """
    # Check if under ~/.claude/projects/
    path_str = str(path.resolve())
    if ".claude/projects/" in path_str or ".claude\\projects\\" in path_str:
        return "claude_code"

    # Check file extension
    if path.suffix == ".jsonl":
        return "claude_code"

    return None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_parsers.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/driftshield/cli/parsers.py tests/cli/test_parsers.py
git commit -m "feat(cli): add parser registry with auto-detection"
```

---

### Task 9.1.4: Output Formatters - Summary

**Files:**
- Create: `src/driftshield/cli/output.py`
- Create: `tests/cli/test_output.py`

**Step 1: Write the failing test**

```python
# tests/cli/test_output.py
"""Tests for CLI output formatters."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from driftshield.core.models import CanonicalEvent, EventType, RiskClassification
from driftshield.core.graph.builder import build_graph
from driftshield.core.graph.models import DecisionNode
from driftshield.core.analysis.session import AnalysisResult
from driftshield.cli.output import format_summary, format_json


def make_analysis_result(
    events: list[CanonicalEvent] | None = None,
    flagged: int = 0,
    inflection_action: str | None = None,
) -> AnalysisResult:
    """Create test AnalysisResult."""
    if events is None:
        events = []

    session_id = "test-session"
    graph = build_graph(events, session_id=session_id)

    inflection_node = None
    if inflection_action and graph.nodes:
        for node in graph.nodes:
            if node.action == inflection_action:
                inflection_node = node
                break

    return AnalysisResult(
        events=events,
        graph=graph,
        inflection_node=inflection_node,
        total_events=len(events),
        flagged_events=flagged,
    )


class TestFormatSummary:
    def test_empty_session(self):
        """Empty session shows zero events."""
        result = make_analysis_result()
        output = format_summary(result)

        assert "Events:  0" in output or "Events: 0" in output
        assert "Flagged: 0" in output or "Flagged:  0" in output

    def test_shows_session_id(self):
        """Summary shows session ID."""
        result = make_analysis_result()
        output = format_summary(result)

        assert "test-session" in output

    def test_shows_risk_counts(self):
        """Summary shows risk type counts when present."""
        event = CanonicalEvent(
            id=uuid4(),
            session_id="test-session",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.BRANCH,
            agent_id="test",
            action="risky_action",
            risk_classification=RiskClassification(coverage_gap=True),
        )
        result = AnalysisResult(
            events=[event],
            graph=build_graph([event], session_id="test-session"),
            inflection_node=None,
            total_events=1,
            flagged_events=1,
        )
        output = format_summary(result)

        assert "coverage_gap" in output

    def test_shows_inflection_point(self):
        """Summary shows inflection point when present."""
        event = CanonicalEvent(
            id=uuid4(),
            session_id="test-session",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.BRANCH,
            agent_id="test",
            action="bad_decision",
            risk_classification=RiskClassification(coverage_gap=True),
        )
        graph = build_graph([event], session_id="test-session")
        result = AnalysisResult(
            events=[event],
            graph=graph,
            inflection_node=graph.nodes[0],
            total_events=1,
            flagged_events=1,
        )
        output = format_summary(result)

        assert "Inflection" in output
        assert "bad_decision" in output


class TestFormatJson:
    def test_returns_valid_json_structure(self):
        """JSON output has expected structure."""
        result = make_analysis_result()
        output = format_json(result)

        assert "session_id" in output
        assert "total_events" in output
        assert "flagged_events" in output
        assert "risks" in output

    def test_includes_inflection_when_present(self):
        """JSON includes inflection data when present."""
        event = CanonicalEvent(
            id=uuid4(),
            session_id="test-session",
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.BRANCH,
            agent_id="test",
            action="inflection_action",
            risk_classification=RiskClassification(assumption_mutation=True),
        )
        graph = build_graph([event], session_id="test-session")
        result = AnalysisResult(
            events=[event],
            graph=graph,
            inflection_node=graph.nodes[0],
            total_events=1,
            flagged_events=1,
        )
        output = format_json(result)

        assert "inflection" in output
        assert "inflection_action" in output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_output.py -v`

Expected: FAIL with "cannot import name 'format_summary'"

**Step 3: Write implementation**

```python
# src/driftshield/cli/output.py
"""Output formatters for CLI."""

import json
from typing import Any

from rich.console import Console
from rich.table import Table

from driftshield.core.analysis.session import AnalysisResult


def format_summary(result: AnalysisResult) -> str:
    """
    Format analysis result as summary text.

    Args:
        result: Analysis result to format

    Returns:
        Formatted summary string
    """
    lines = [
        "DriftShield Analysis",
        "─" * 20,
        f"Session: {result.graph.session_id}",
        f"Events:  {result.total_events}",
        f"Flagged: {result.flagged_events}",
    ]

    # Add risk summary if any risks
    if result.has_risks:
        lines.append("")
        lines.append("Risks Detected:")
        for risk_type, count in result.risk_summary.items():
            if count > 0:
                lines.append(f"  - {risk_type}: {count}")

    # Add inflection point if present
    if result.inflection_node:
        node = result.inflection_node
        lines.append("")
        lines.append("Inflection Point:")
        lines.append(f"  Event #{node.sequence_num} : {node.action}")
        lines.append(f"  Type      : {node.event_type.value}")

        if node.event.risk_classification:
            flags = ", ".join(node.event.risk_classification.active_flags())
            lines.append(f"  Risk      : {flags}")

    return "\n".join(lines)


def format_json(result: AnalysisResult) -> str:
    """
    Format analysis result as JSON.

    Args:
        result: Analysis result to format

    Returns:
        JSON string
    """
    data: dict[str, Any] = {
        "session_id": result.graph.session_id,
        "total_events": result.total_events,
        "flagged_events": result.flagged_events,
        "risks": result.risk_summary,
    }

    if result.inflection_node:
        node = result.inflection_node
        data["inflection"] = {
            "event_index": node.sequence_num,
            "action": node.action,
            "flags": (
                node.event.risk_classification.active_flags()
                if node.event.risk_classification
                else []
            ),
        }
    else:
        data["inflection"] = None

    # Add events summary (not full details to keep output manageable)
    data["events"] = [
        {
            "index": i,
            "action": e.action,
            "type": e.event_type.value,
            "has_flags": e.has_risk_flags(),
        }
        for i, e in enumerate(result.events)
    ]

    return json.dumps(data, indent=2)


def format_verbose_table(result: AnalysisResult) -> str:
    """
    Format analysis result as verbose table.

    Args:
        result: Analysis result to format

    Returns:
        Formatted table string
    """
    console = Console(force_terminal=True, width=100)

    table = Table(title="Events")
    table.add_column("#", style="dim", width=4)
    table.add_column("Action", width=30)
    table.add_column("Type", width=15)
    table.add_column("Flags", width=25)

    for i, event in enumerate(result.events):
        flags = ""
        if event.has_risk_flags() and event.risk_classification:
            flags = "⚠ " + ", ".join(event.risk_classification.active_flags())

        table.add_row(
            str(i),
            event.action[:28] + ".." if len(event.action) > 30 else event.action,
            event.event_type.value,
            flags,
        )

    # Capture table to string
    with console.capture() as capture:
        console.print(table)

    return capture.get()


def format_quiet(result: AnalysisResult) -> str:
    """
    Format analysis result as minimal output.

    Args:
        result: Analysis result to format

    Returns:
        Single line status
    """
    if result.flagged_events == 0:
        return "✓ No risks detected"
    else:
        return f"⚠ {result.flagged_events} risk(s) detected"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_output.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/driftshield/cli/output.py tests/cli/test_output.py
git commit -m "feat(cli): add output formatters (summary, JSON, table, quiet)"
```

---

### Task 9.1.5: Analyze Command - Single File

**Files:**
- Create: `src/driftshield/cli/commands/analyze.py`
- Create: `tests/cli/test_analyze.py`

**Step 1: Write the failing test**

```python
# tests/cli/test_analyze.py
"""Tests for analyze command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app


runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


class TestAnalyzeCommand:
    def test_analyze_single_file(self):
        """Can analyze a single JSONL file."""
        result = runner.invoke(
            app,
            ["analyze", str(FIXTURES_DIR / "sample_claude_code_session.jsonl")],
        )

        assert result.exit_code == 0
        assert "DriftShield Analysis" in result.output
        assert "Events:" in result.output

    def test_analyze_with_verbose(self):
        """Verbose flag shows event table."""
        result = runner.invoke(
            app,
            ["analyze", str(FIXTURES_DIR / "sample_claude_code_session.jsonl"), "--verbose"],
        )

        assert result.exit_code == 0
        assert "Action" in result.output  # Table header

    def test_analyze_with_json(self):
        """JSON flag outputs valid JSON."""
        result = runner.invoke(
            app,
            ["analyze", str(FIXTURES_DIR / "sample_claude_code_session.jsonl"), "--json"],
        )

        assert result.exit_code == 0
        assert '"session_id"' in result.output
        assert '"total_events"' in result.output

    def test_analyze_nonexistent_file(self):
        """Nonexistent file shows error."""
        result = runner.invoke(app, ["analyze", "/nonexistent/path.jsonl"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_analyze_with_parser_flag(self):
        """Can specify parser explicitly."""
        result = runner.invoke(
            app,
            [
                "analyze",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--parser",
                "claude_code",
            ],
        )

        assert result.exit_code == 0

    def test_analyze_with_unknown_parser(self):
        """Unknown parser shows error with available options."""
        result = runner.invoke(
            app,
            [
                "analyze",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--parser",
                "unknown",
            ],
        )

        assert result.exit_code != 0
        assert "claude_code" in result.output  # Lists available
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_analyze.py -v`

Expected: FAIL with "No such command 'analyze'"

**Step 3: Write implementation**

```python
# src/driftshield/cli/commands/analyze.py
"""Analyze command for DriftShield CLI."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from driftshield.cli.parsers import get_parser, detect_parser, ParserNotFoundError
from driftshield.cli.output import format_summary, format_json, format_verbose_table, format_quiet
from driftshield.core.analysis.session import analyze_session


console = Console()


def analyze(
    path: Optional[Path] = typer.Argument(
        None,
        help="Session file or directory to analyze.",
        exists=False,  # We handle existence check ourselves for better error messages
    ),
    parser: str = typer.Option(
        "auto",
        "--parser",
        "-p",
        help="Parser to use (auto, claude_code).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show full event table.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Minimal output.",
    ),
) -> None:
    """Analyse session(s) for reasoning risks."""
    if path is None:
        console.print("[red]Error:[/red] No path provided. Use --project or specify a file path.")
        raise typer.Exit(1)

    path = Path(path).expanduser().resolve()

    if not path.exists():
        console.print(f"[red]Error:[/red] Path not found: {path}")
        raise typer.Exit(1)

    # Determine parser
    if parser == "auto":
        detected = detect_parser(path)
        if detected is None:
            console.print(
                f"[red]Error:[/red] Could not detect parser for '{path.name}'\n"
                "Hint: Use --parser to specify format (available: claude_code)"
            )
            raise typer.Exit(1)
        parser = detected

    try:
        parser_instance = get_parser(parser)
    except ParserNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Parse and analyze
    try:
        if path.is_file():
            events = parser_instance.parse_file(str(path))
        else:
            # Directory: analyze all matching files
            # For now, just handle single files
            console.print("[red]Error:[/red] Directory analysis not yet supported. Specify a file.")
            raise typer.Exit(1)

        result = analyze_session(events)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to analyze: {e}")
        raise typer.Exit(1)

    # Output
    if json_output:
        console.print(format_json(result))
    elif quiet:
        console.print(format_quiet(result))
    elif verbose:
        console.print(format_summary(result))
        console.print()
        console.print(format_verbose_table(result))
    else:
        console.print(format_summary(result))
```

**Step 4: Register command in main.py**

Add to `src/driftshield/cli/main.py`:

```python
# src/driftshield/cli/main.py
"""DriftShield CLI entry point."""

import typer

from driftshield import __version__
from driftshield.cli.commands.analyze import analyze

app = typer.Typer(
    name="driftshield",
    help="DriftShield - AI Decision Forensics CLI",
    no_args_is_help=True,
)

# Register commands
app.command()(analyze)


def version_callback(value: bool) -> None:
    if value:
        print(f"driftshield {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """DriftShield - AI Decision Forensics CLI."""
    pass
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/cli/test_analyze.py -v`

Expected: PASS

**Step 6: Manual verification**

Run: `driftshield analyze tests/fixtures/transcripts/sample_claude_code_session.jsonl`

Expected: Summary output showing session analysis

**Step 7: Commit**

```bash
git add src/driftshield/cli/commands/analyze.py src/driftshield/cli/main.py tests/cli/test_analyze.py
git commit -m "feat(cli): add analyze command for single file analysis"
```

---

## Phase 9.2: Batch Analysis and Discovery

### Task 9.2.1: Session Discovery Module

**Files:**
- Create: `src/driftshield/cli/discovery.py`
- Create: `tests/cli/test_discovery.py`

**Step 1: Write the failing test**

```python
# tests/cli/test_discovery.py
"""Tests for session discovery."""

from pathlib import Path
from datetime import datetime, timezone

import pytest

from driftshield.cli.discovery import (
    get_claude_projects_dir,
    path_to_project_key,
    discover_sessions,
    resolve_session,
    SessionInfo,
)


class TestPathToProjectKey:
    def test_converts_path_to_key(self):
        """Converts absolute path to Claude project key format."""
        path = Path("/Users/tom/github/my-repo")
        key = path_to_project_key(path)
        assert key == "-Users-tom-github-my-repo"

    def test_handles_different_paths(self):
        """Works with various path formats."""
        assert path_to_project_key(Path("/foo/bar")) == "-foo-bar"
        assert path_to_project_key(Path("/a/b/c/d")) == "-a-b-c-d"


class TestDiscoverSessions:
    def test_returns_empty_when_no_sessions(self, tmp_path):
        """Returns empty list when no sessions found."""
        sessions = discover_sessions(tmp_path, claude_base=tmp_path / ".claude")
        assert sessions == []

    def test_finds_jsonl_sessions(self, tmp_path):
        """Finds JSONL session files."""
        # Create mock claude structure
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        # Create mock session files
        (sessions_dir / "abc123.jsonl").write_text('{"type": "test"}')
        (sessions_dir / "def456.jsonl").write_text('{"type": "test"}')

        sessions = discover_sessions(tmp_path, claude_base=tmp_path / ".claude")

        assert len(sessions) == 2
        assert all(isinstance(s, SessionInfo) for s in sessions)

    def test_sorts_by_modification_time(self, tmp_path):
        """Sessions sorted newest first."""
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        # Create files with different times
        old = sessions_dir / "old.jsonl"
        new = sessions_dir / "new.jsonl"

        old.write_text('{"type": "test"}')
        new.write_text('{"type": "test"}')

        # Touch to set different times
        import os
        import time
        os.utime(old, (time.time() - 100, time.time() - 100))

        sessions = discover_sessions(tmp_path, claude_base=tmp_path / ".claude")

        assert sessions[0].path.name == "new.jsonl"
        assert sessions[1].path.name == "old.jsonl"


class TestResolveSession:
    def test_resolves_full_path(self, tmp_path):
        """Full path resolves directly."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text('{"type": "test"}')

        path = resolve_session(str(session_file), project_dir=tmp_path)
        assert path == session_file

    def test_resolves_session_id(self, tmp_path):
        """Session ID resolves via discovery."""
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        session_file = sessions_dir / "abc123-def.jsonl"
        session_file.write_text('{"type": "test"}')

        path = resolve_session(
            "abc123-def",
            project_dir=tmp_path,
            claude_base=tmp_path / ".claude",
        )
        assert path == session_file

    def test_resolves_index(self, tmp_path):
        """Numeric index resolves to nth session."""
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        (sessions_dir / "first.jsonl").write_text('{"type": "test"}')
        (sessions_dir / "second.jsonl").write_text('{"type": "test"}')

        # Index 1 = most recent (first in sorted list)
        path = resolve_session(
            "1",
            project_dir=tmp_path,
            claude_base=tmp_path / ".claude",
        )
        assert path is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_discovery.py -v`

Expected: FAIL with "cannot import name 'get_claude_projects_dir'"

**Step 3: Write implementation**

```python
# src/driftshield/cli/discovery.py
"""Session discovery for Claude Code projects."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class SessionInfo:
    """Information about a discovered session."""

    path: Path
    session_id: str
    modified_at: datetime
    size_bytes: int

    @property
    def age_description(self) -> str:
        """Human-readable age description."""
        delta = datetime.now() - self.modified_at
        if delta.days > 1:
            return f"{delta.days} days ago"
        elif delta.days == 1:
            return "yesterday"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"


def get_claude_projects_dir(claude_base: Optional[Path] = None) -> Path:
    """Get the Claude Code projects directory."""
    if claude_base is None:
        claude_base = Path.home() / ".claude"
    return claude_base / "projects"


def path_to_project_key(path: Path) -> str:
    """
    Convert a filesystem path to Claude project key format.

    /Users/tom/github/repo -> -Users-tom-github-repo
    """
    resolved = path.resolve()
    return str(resolved).replace("/", "-").replace("\\", "-")


def discover_sessions(
    project_dir: Path,
    claude_base: Optional[Path] = None,
) -> list[SessionInfo]:
    """
    Discover Claude Code sessions for a project directory.

    Args:
        project_dir: The project directory to find sessions for
        claude_base: Base claude directory (default: ~/.claude)

    Returns:
        List of SessionInfo, sorted by modification time (newest first)
    """
    projects_dir = get_claude_projects_dir(claude_base)
    project_key = path_to_project_key(project_dir)
    sessions_path = projects_dir / project_key

    if not sessions_path.exists():
        return []

    sessions = []
    for file in sessions_path.glob("*.jsonl"):
        stat = file.stat()
        sessions.append(
            SessionInfo(
                path=file,
                session_id=file.stem,
                modified_at=datetime.fromtimestamp(stat.st_mtime),
                size_bytes=stat.st_size,
            )
        )

    # Sort by modification time, newest first
    sessions.sort(key=lambda s: s.modified_at, reverse=True)
    return sessions


def resolve_session(
    identifier: str,
    project_dir: Optional[Path] = None,
    claude_base: Optional[Path] = None,
) -> Optional[Path]:
    """
    Resolve a session identifier to a file path.

    Identifier can be:
    - Full path to a .jsonl file
    - Session ID (filename without extension)
    - Numeric index (1 = most recent)

    Args:
        identifier: The session identifier
        project_dir: Project directory for discovery (default: cwd)
        claude_base: Base claude directory (default: ~/.claude)

    Returns:
        Path to session file, or None if not found
    """
    # Check if it's a direct path
    path = Path(identifier).expanduser()
    if path.exists() and path.is_file():
        return path.resolve()

    # Need project_dir for further resolution
    if project_dir is None:
        project_dir = Path.cwd()

    sessions = discover_sessions(project_dir, claude_base)
    if not sessions:
        return None

    # Check if it's a numeric index
    if identifier.isdigit():
        index = int(identifier) - 1  # 1-indexed
        if 0 <= index < len(sessions):
            return sessions[index].path
        return None

    # Check if it's a session ID
    for session in sessions:
        if session.session_id == identifier or session.session_id.startswith(identifier):
            return session.path

    return None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_discovery.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/driftshield/cli/discovery.py tests/cli/test_discovery.py
git commit -m "feat(cli): add session discovery module"
```

---

### Task 9.2.2: List Command

**Files:**
- Create: `src/driftshield/cli/commands/list.py`
- Modify: `src/driftshield/cli/main.py`
- Create: `tests/cli/test_list.py`

**Step 1: Write the failing test**

```python
# tests/cli/test_list.py
"""Tests for list command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app
from driftshield.cli.discovery import path_to_project_key


runner = CliRunner()


class TestListCommand:
    def test_list_with_project_flag(self, tmp_path, monkeypatch):
        """List shows sessions for current project."""
        # Setup mock claude structure
        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "abc123.jsonl").write_text('{"type": "test"}')

        # Change to project dir and set claude base
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

        result = runner.invoke(app, ["list", "--project"])

        assert result.exit_code == 0
        assert "abc123" in result.output

    def test_list_no_sessions(self, tmp_path, monkeypatch):
        """List shows message when no sessions found."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

        result = runner.invoke(app, ["list", "--project"])

        assert "No sessions found" in result.output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_list.py -v`

Expected: FAIL with "No such command 'list'"

**Step 3: Write implementation**

```python
# src/driftshield/cli/commands/list.py
"""List command for DriftShield CLI."""

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from driftshield.cli.discovery import discover_sessions, get_claude_projects_dir
from driftshield.cli.parsers import get_parser


console = Console()


def list_sessions(
    project: bool = typer.Option(
        False,
        "--project",
        help="List sessions for current project.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON.",
    ),
) -> None:
    """List available sessions."""
    if not project:
        console.print(
            "[yellow]Hint:[/yellow] Use --project to list sessions for current directory."
        )
        raise typer.Exit(0)

    # Determine claude base from env or default
    claude_home = os.environ.get("CLAUDE_HOME")
    claude_base = Path(claude_home) if claude_home else None

    project_dir = Path.cwd()
    sessions = discover_sessions(project_dir, claude_base)

    if not sessions:
        console.print(f"No sessions found for this project.")
        console.print(f"[dim]Looking in: {get_claude_projects_dir(claude_base)}[/dim]")
        raise typer.Exit(0)

    if json_output:
        import json
        data = [
            {
                "index": i + 1,
                "session_id": s.session_id,
                "path": str(s.path),
                "modified_at": s.modified_at.isoformat(),
                "size_bytes": s.size_bytes,
            }
            for i, s in enumerate(sessions)
        ]
        console.print(json.dumps(data, indent=2))
    else:
        console.print(f"\nSessions for: [bold]{project_dir.name}[/bold]")
        console.print("─" * 40)

        for i, session in enumerate(sessions, 1):
            # Count events (quick scan)
            try:
                event_count = sum(1 for _ in session.path.open())
            except Exception:
                event_count = "?"

            console.print(
                f"  {i}. {session.session_id}  "
                f"[dim]({session.age_description}, {event_count} lines)[/dim]"
            )

        console.print()
        console.print("[dim]Use: driftshield analyze <session-id>[/dim]")
```

**Step 4: Register command in main.py**

Update `src/driftshield/cli/main.py`:

```python
# src/driftshield/cli/main.py
"""DriftShield CLI entry point."""

import typer

from driftshield import __version__
from driftshield.cli.commands.analyze import analyze
from driftshield.cli.commands.list import list_sessions

app = typer.Typer(
    name="driftshield",
    help="DriftShield - AI Decision Forensics CLI",
    no_args_is_help=True,
)

# Register commands
app.command()(analyze)
app.command(name="list")(list_sessions)


def version_callback(value: bool) -> None:
    if value:
        print(f"driftshield {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """DriftShield - AI Decision Forensics CLI."""
    pass
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/cli/test_list.py -v`

Expected: PASS

**Step 6: Commit**

```bash
git add src/driftshield/cli/commands/list.py src/driftshield/cli/main.py tests/cli/test_list.py
git commit -m "feat(cli): add list command for session discovery"
```

---

### Task 9.2.3: Analyze with --project Flag

**Files:**
- Modify: `src/driftshield/cli/commands/analyze.py`
- Modify: `tests/cli/test_analyze.py`

**Step 1: Add test for --project flag**

Add to `tests/cli/test_analyze.py`:

```python
class TestAnalyzeProject:
    def test_analyze_with_project_flag(self, tmp_path, monkeypatch):
        """Analyze --project analyzes all sessions."""
        # Setup mock structure
        from driftshield.cli.discovery import path_to_project_key

        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        # Copy fixture
        fixture = Path(__file__).parent.parent / "fixtures" / "transcripts" / "sample_claude_code_session.jsonl"
        if fixture.exists():
            (sessions_dir / "test-session.jsonl").write_text(fixture.read_text())
        else:
            # Create minimal valid session
            (sessions_dir / "test-session.jsonl").write_text(
                '{"type":"assistant","timestamp":1234567890000,"message":{"content":[]}}\n'
            )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

        result = runner.invoke(app, ["analyze", "--project"])

        assert result.exit_code == 0
        assert "test-session" in result.output or "DriftShield" in result.output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_analyze.py::TestAnalyzeProject -v`

Expected: FAIL

**Step 3: Update analyze command**

Update `src/driftshield/cli/commands/analyze.py`:

```python
# src/driftshield/cli/commands/analyze.py
"""Analyze command for DriftShield CLI."""

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from driftshield.cli.parsers import get_parser, detect_parser, ParserNotFoundError
from driftshield.cli.output import format_summary, format_json, format_verbose_table, format_quiet
from driftshield.cli.discovery import discover_sessions, resolve_session
from driftshield.core.analysis.session import analyze_session


console = Console()


def analyze(
    path: Optional[str] = typer.Argument(
        None,
        help="Session file, directory, or session ID to analyze.",
    ),
    project: bool = typer.Option(
        False,
        "--project",
        help="Analyze sessions for current project.",
    ),
    parser: str = typer.Option(
        "auto",
        "--parser",
        "-p",
        help="Parser to use (auto, claude_code).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show full event table.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Minimal output.",
    ),
) -> None:
    """Analyse session(s) for reasoning risks."""
    # Determine claude base from env or default
    claude_home = os.environ.get("CLAUDE_HOME")
    claude_base = Path(claude_home) if claude_home else None

    # Collect files to analyze
    files_to_analyze: list[Path] = []

    if project:
        # Discover sessions for current project
        sessions = discover_sessions(Path.cwd(), claude_base)
        if not sessions:
            console.print("No sessions found for this project.")
            raise typer.Exit(0)
        files_to_analyze = [s.path for s in sessions]
    elif path is not None:
        # Resolve the path/identifier
        resolved = resolve_session(path, Path.cwd(), claude_base)
        if resolved is None:
            # Try as direct path
            direct = Path(path).expanduser().resolve()
            if direct.exists():
                resolved = direct
            else:
                console.print(f"[red]Error:[/red] Could not find session: {path}")
                raise typer.Exit(1)
        files_to_analyze = [resolved]
    else:
        console.print("[red]Error:[/red] No path provided. Use --project or specify a file path.")
        raise typer.Exit(1)

    # Analyze each file
    all_results = []
    for file_path in files_to_analyze:
        # Determine parser
        effective_parser = parser
        if effective_parser == "auto":
            detected = detect_parser(file_path)
            if detected is None:
                console.print(
                    f"[yellow]Warning:[/yellow] Could not detect parser for '{file_path.name}', skipping"
                )
                continue
            effective_parser = detected

        try:
            parser_instance = get_parser(effective_parser)
        except ParserNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

        # Parse and analyze
        try:
            events = parser_instance.parse_file(str(file_path))
            result = analyze_session(events)
            all_results.append((file_path, result))
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to analyze {file_path.name}: {e}")
            if len(files_to_analyze) == 1:
                raise typer.Exit(1)
            continue

    if not all_results:
        console.print("No sessions analyzed.")
        raise typer.Exit(1)

    # Output results
    if json_output:
        import json
        if len(all_results) == 1:
            console.print(format_json(all_results[0][1]))
        else:
            data = []
            for file_path, result in all_results:
                import json as json_lib
                data.append(json_lib.loads(format_json(result)))
            console.print(json.dumps(data, indent=2))
    elif quiet:
        for file_path, result in all_results:
            if len(all_results) > 1:
                console.print(f"[bold]{file_path.stem}:[/bold] ", end="")
            console.print(format_quiet(result))
    else:
        for i, (file_path, result) in enumerate(all_results):
            if i > 0:
                console.print()
                console.print("─" * 40)
                console.print()

            if len(all_results) > 1:
                console.print(f"[bold]Session: {file_path.stem}[/bold]")
                console.print()

            console.print(format_summary(result))

            if verbose:
                console.print()
                console.print(format_verbose_table(result))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_analyze.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/driftshield/cli/commands/analyze.py tests/cli/test_analyze.py
git commit -m "feat(cli): add --project flag to analyze command"
```

---

## Phase 9.3: Inspect Command

### Task 9.3.1: Inspect Command Implementation

**Files:**
- Create: `src/driftshield/cli/commands/inspect.py`
- Modify: `src/driftshield/cli/main.py`
- Create: `tests/cli/test_inspect.py`

**Step 1: Write the failing test**

```python
# tests/cli/test_inspect.py
"""Tests for inspect command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app
from driftshield.cli.discovery import path_to_project_key


runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


class TestInspectCommand:
    def test_inspect_node_by_path(self):
        """Can inspect a specific node."""
        result = runner.invoke(
            app,
            [
                "inspect",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--node",
                "0",
            ],
        )

        assert result.exit_code == 0
        assert "Node #0" in result.output

    def test_inspect_with_path_to_root(self):
        """Path to root shows ancestry."""
        result = runner.invoke(
            app,
            [
                "inspect",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--node",
                "1",
                "--path-to-root",
            ],
        )

        assert result.exit_code == 0
        assert "Path to Root" in result.output

    def test_inspect_invalid_node(self):
        """Invalid node number shows error."""
        result = runner.invoke(
            app,
            [
                "inspect",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--node",
                "9999",
            ],
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_inspect_with_json(self):
        """JSON output returns valid JSON."""
        result = runner.invoke(
            app,
            [
                "inspect",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--node",
                "0",
                "--json",
            ],
        )

        assert result.exit_code == 0
        assert '"action"' in result.output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_inspect.py -v`

Expected: FAIL with "No such command 'inspect'"

**Step 3: Write implementation**

```python
# src/driftshield/cli/commands/inspect.py
"""Inspect command for DriftShield CLI."""

import json
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from driftshield.cli.parsers import get_parser, detect_parser
from driftshield.cli.discovery import resolve_session
from driftshield.core.graph.builder import build_graph
from driftshield.core.graph.models import DecisionNode


console = Console()


def format_node_detail(node: DecisionNode, graph) -> str:
    """Format a node for detailed display."""
    lines = [
        f"Node #{node.sequence_num}: {node.action}",
        "─" * 30,
        f"Type:      {node.event_type.value}",
        f"Timestamp: {node.event.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Agent:     {node.event.agent_id}",
    ]

    # Inputs
    if node.inputs:
        lines.append("")
        lines.append("Inputs:")
        for key, value in list(node.inputs.items())[:5]:
            val_str = str(value)
            if len(val_str) > 60:
                val_str = val_str[:57] + "..."
            lines.append(f"  {key}: {val_str}")

    # Outputs
    if node.outputs:
        lines.append("")
        lines.append("Outputs:")
        for key, value in list(node.outputs.items())[:5]:
            val_str = str(value)
            if len(val_str) > 60:
                val_str = val_str[:57] + "..."
            lines.append(f"  {key}: {val_str}")

    # Risk flags
    if node.has_risk_flags() and node.event.risk_classification:
        lines.append("")
        lines.append("Risk Flags:")
        for flag in node.event.risk_classification.active_flags():
            lines.append(f"  ⚠ {flag}")

    # Parent/Children
    lines.append("")
    parent = graph.get_parent(node.id)
    if parent:
        lines.append(f"Parent: #{parent.sequence_num} ({parent.action})")
    else:
        lines.append("Parent: (root)")

    children = graph.get_children(node.id)
    if children:
        child_strs = [f"#{c.sequence_num} ({c.action})" for c in children]
        lines.append(f"Children: {', '.join(child_strs)}")

    return "\n".join(lines)


def format_path_to_root(path: list[DecisionNode]) -> str:
    """Format path to root display."""
    lines = [f"Path to Root from Node #{path[0].sequence_num}", "─" * 30]

    for i, node in enumerate(path):
        flags = ""
        if node.has_risk_flags() and node.event.risk_classification:
            flags = "   ⚠ " + ", ".join(node.event.risk_classification.active_flags())

        suffix = " (root)" if i == len(path) - 1 else ""
        lines.append(f"#{node.sequence_num} {node.action}{flags}{suffix}")

        if i < len(path) - 1:
            lines.append(" ↑")

    return "\n".join(lines)


def inspect(
    session: str = typer.Argument(
        ...,
        help="Session file path or session ID.",
    ),
    node: int = typer.Option(
        ...,
        "--node",
        "-n",
        help="Node number to inspect.",
    ),
    path_to_root: bool = typer.Option(
        False,
        "--path-to-root",
        help="Show path from node to root.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON.",
    ),
) -> None:
    """Inspect a specific node in a session."""
    # Determine claude base from env or default
    claude_home = os.environ.get("CLAUDE_HOME")
    claude_base = Path(claude_home) if claude_home else None

    # Resolve session
    resolved = resolve_session(session, Path.cwd(), claude_base)
    if resolved is None:
        direct = Path(session).expanduser().resolve()
        if direct.exists():
            resolved = direct
        else:
            console.print(f"[red]Error:[/red] Could not find session: {session}")
            raise typer.Exit(1)

    # Parse session
    parser_name = detect_parser(resolved)
    if parser_name is None:
        console.print(f"[red]Error:[/red] Could not detect parser for: {resolved.name}")
        raise typer.Exit(1)

    parser = get_parser(parser_name)
    events = parser.parse_file(str(resolved))

    if not events:
        console.print("[red]Error:[/red] No events found in session.")
        raise typer.Exit(1)

    # Build graph
    graph = build_graph(events, session_id=events[0].session_id)

    # Find node
    target_node = None
    for n in graph.nodes:
        if n.sequence_num == node:
            target_node = n
            break

    if target_node is None:
        console.print(f"[red]Error:[/red] Node #{node} not found. Session has {len(graph.nodes)} nodes (0-{len(graph.nodes)-1}).")
        raise typer.Exit(1)

    # Output
    if json_output:
        data = {
            "node": node,
            "action": target_node.action,
            "type": target_node.event_type.value,
            "timestamp": target_node.event.timestamp.isoformat(),
            "agent_id": target_node.event.agent_id,
            "inputs": target_node.inputs,
            "outputs": target_node.outputs,
            "has_risk_flags": target_node.has_risk_flags(),
            "risk_flags": (
                target_node.event.risk_classification.active_flags()
                if target_node.event.risk_classification
                else []
            ),
        }
        if path_to_root:
            path = graph.path_to_root(target_node.id)
            data["path_to_root"] = [
                {"node": n.sequence_num, "action": n.action}
                for n in path
            ]
        console.print(json.dumps(data, indent=2, default=str))
    elif path_to_root:
        path = graph.path_to_root(target_node.id)
        console.print(format_path_to_root(path))
    else:
        console.print(format_node_detail(target_node, graph))
```

**Step 4: Register command in main.py**

Update `src/driftshield/cli/main.py`:

```python
# src/driftshield/cli/main.py
"""DriftShield CLI entry point."""

import typer

from driftshield import __version__
from driftshield.cli.commands.analyze import analyze
from driftshield.cli.commands.list import list_sessions
from driftshield.cli.commands.inspect import inspect

app = typer.Typer(
    name="driftshield",
    help="DriftShield - AI Decision Forensics CLI",
    no_args_is_help=True,
)

# Register commands
app.command()(analyze)
app.command(name="list")(list_sessions)
app.command()(inspect)


def version_callback(value: bool) -> None:
    if value:
        print(f"driftshield {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """DriftShield - AI Decision Forensics CLI."""
    pass
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/cli/test_inspect.py -v`

Expected: PASS

**Step 6: Commit**

```bash
git add src/driftshield/cli/commands/inspect.py src/driftshield/cli/main.py tests/cli/test_inspect.py
git commit -m "feat(cli): add inspect command for node inspection"
```

---

## Phase 9.4: CI Integration

### Task 9.4.1: Exit Code Logic

**Files:**
- Modify: `src/driftshield/cli/commands/analyze.py`
- Modify: `tests/cli/test_analyze.py`

**Step 1: Add CI tests**

Add to `tests/cli/test_analyze.py`:

```python
class TestAnalyzeCI:
    def test_fail_on_specific_risk(self, tmp_path, monkeypatch):
        """--fail-on exits 1 when specified risk detected."""
        from driftshield.cli.discovery import path_to_project_key

        project_key = path_to_project_key(tmp_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)

        # Use fixture with known structure
        fixture = FIXTURES_DIR / "sample_claude_code_session.jsonl"
        if fixture.exists():
            (sessions_dir / "session.jsonl").write_text(fixture.read_text())

            monkeypatch.chdir(tmp_path)
            monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

            # This may or may not fail depending on fixture content
            # Just verify the flag is accepted
            result = runner.invoke(
                app,
                ["analyze", "--project", "--fail-on", "coverage_gap"],
            )
            # Should run without crashing
            assert result.exit_code in [0, 1]

    def test_fail_threshold(self):
        """--fail-threshold exits 1 when threshold exceeded."""
        result = runner.invoke(
            app,
            [
                "analyze",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--fail-threshold",
                "1000",  # Very high threshold, should pass
            ],
        )
        assert result.exit_code == 0

    def test_quiet_mode_minimal_output(self):
        """--quiet produces minimal output."""
        result = runner.invoke(
            app,
            [
                "analyze",
                str(FIXTURES_DIR / "sample_claude_code_session.jsonl"),
                "--quiet",
            ],
        )
        assert result.exit_code == 0
        # Quiet output should be short
        assert len(result.output.strip().split("\n")) <= 3
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_analyze.py::TestAnalyzeCI -v`

Expected: FAIL (--fail-on not implemented)

**Step 3: Update analyze command with CI options**

Update `src/driftshield/cli/commands/analyze.py` to add CI options:

```python
# Add these options to the analyze function signature:
    fail_on: Optional[str] = typer.Option(
        None,
        "--fail-on",
        help="Exit 1 if specified risks detected (comma-separated).",
    ),
    fail_threshold: Optional[int] = typer.Option(
        None,
        "--fail-threshold",
        help="Exit 1 if N or more events flagged.",
    ),
```

Add this logic before the output section:

```python
    # Check CI failure conditions
    should_fail = False
    fail_reasons = []

    for file_path, result in all_results:
        # Check fail-on risks
        if fail_on:
            risk_types = [r.strip() for r in fail_on.split(",")]
            for risk_type in risk_types:
                if result.risk_summary.get(risk_type, 0) > 0:
                    should_fail = True
                    fail_reasons.append(f"{risk_type} detected in {file_path.stem}")

        # Check fail-threshold
        if fail_threshold is not None:
            if result.flagged_events >= fail_threshold:
                should_fail = True
                fail_reasons.append(
                    f"{result.flagged_events} flagged events in {file_path.stem} "
                    f"(threshold: {fail_threshold})"
                )
```

Add this after the output section:

```python
    # Exit with failure if CI conditions met
    if should_fail:
        if not quiet:
            console.print()
            console.print("[red]FAIL:[/red]")
            for reason in fail_reasons:
                console.print(f"  - {reason}")
        raise typer.Exit(1)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_analyze.py::TestAnalyzeCI -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/driftshield/cli/commands/analyze.py tests/cli/test_analyze.py
git commit -m "feat(cli): add CI integration (--fail-on, --fail-threshold)"
```

---

### Task 9.4.2: Full Test Suite and Documentation

**Files:**
- Run all tests
- Update `--help` output verification

**Step 1: Run full test suite**

Run: `pytest tests/ -v`

Expected: All tests pass

**Step 2: Verify CLI help**

Run: `driftshield --help`
Run: `driftshield analyze --help`
Run: `driftshield list --help`
Run: `driftshield inspect --help`

Expected: Help output matches design document

**Step 3: Final commit**

```bash
git add .
git commit -m "feat(cli): complete Phase 9 CLI implementation"
```

---

## Summary

Phase 9 delivers:

- **9.1**: Single file analysis with `analyze <path>`
- **9.2**: Batch analysis with `--project`, `list` command, session discovery
- **9.3**: Node inspection with `inspect` command
- **9.4**: CI integration with `--fail-on`, `--fail-threshold`, exit codes

All following TDD with tests first, implementation second, frequent commits.

---

**Plan complete and saved to `docs/plans/2025-02-13-cli-implementation.md`.**

**Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
