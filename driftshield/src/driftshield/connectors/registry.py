from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from driftshield.cli.discovery import SessionInfo, discover_sessions_in_path, get_claude_projects_dir, path_to_project_key


@dataclass(frozen=True)
class DiscoveryContext:
    project_dir: Path
    claude_home: Path | None = None
    codex_home: Path | None = None


@dataclass(frozen=True)
class ConnectorCandidate:
    source_type: str
    display_name: str
    root_path: Path
    parser_name: str
    watchable: bool
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def connector_key(self) -> str:
        return f"{self.source_type}:{self.root_path}"


@dataclass(frozen=True)
class ConnectorScanResult:
    connector_id: str
    session_count: int
    newest_session_id: str | None
    newest_session_path: str | None
    newest_modified_at: datetime | None
    sessions: list[SessionInfo] = field(default_factory=list)


class ConnectorAdapter:
    source_type: str
    display_name: str
    parser_name: str
    watchable: bool

    def build_candidate(self, context: DiscoveryContext) -> ConnectorCandidate | None:
        raise NotImplementedError

    def scan(self, root_path: Path) -> list[SessionInfo]:
        raise NotImplementedError


class ClaudeCodeConnectorAdapter(ConnectorAdapter):
    source_type = "claude_code"
    display_name = "Claude Code"
    parser_name = "claude_code"
    watchable = True

    def build_candidate(self, context: DiscoveryContext) -> ConnectorCandidate:
        claude_home = context.claude_home or Path.home() / ".claude"
        root_path = get_claude_projects_dir(claude_home) / path_to_project_key(context.project_dir)
        return ConnectorCandidate(
            source_type=self.source_type,
            display_name=self.display_name,
            root_path=root_path,
            parser_name=self.parser_name,
            watchable=self.watchable,
            metadata={"project_dir": str(context.project_dir)},
        )

    def scan(self, root_path: Path) -> list[SessionInfo]:
        return discover_sessions_in_path(root_path, patterns=("*.jsonl",))


class FixedPathConnectorAdapter(ConnectorAdapter):
    watchable = True

    def __init__(self, *, source_type: str, display_name: str, parser_name: str, root_dir_name: str):
        self.source_type = source_type
        self.display_name = display_name
        self.parser_name = parser_name
        self.root_dir_name = root_dir_name

    def build_candidate(self, context: DiscoveryContext) -> ConnectorCandidate:
        if self.source_type.startswith("codex"):
            configured_home = context.codex_home or Path.home() / ".codex"
        else:
            configured_home = context.claude_home or Path.home() / ".claude"

        configured_home = configured_home.expanduser()
        if configured_home.name.startswith("."):
            sessions_root = configured_home.parent
        else:
            sessions_root = configured_home

        root_path = sessions_root / self.root_dir_name / "sessions"
        return ConnectorCandidate(
            source_type=self.source_type,
            display_name=self.display_name,
            root_path=root_path,
            parser_name=self.parser_name,
            watchable=self.watchable,
            metadata={},
        )

    def scan(self, root_path: Path) -> list[SessionInfo]:
        return discover_sessions_in_path(root_path)


class OpenClawAgentConnectorAdapter(ConnectorAdapter):
    parser_name = "openclaw"
    watchable = True

    def __init__(self, *, source_type: str, agent_name: str, display_name: str):
        self.source_type = source_type
        self.agent_name = agent_name
        self.display_name = display_name

    def build_candidate(self, context: DiscoveryContext) -> ConnectorCandidate | None:
        openclaw_home = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser()
        root_path = openclaw_home / "agents" / self.agent_name / "sessions"
        if not root_path.exists():
            return None

        return ConnectorCandidate(
            source_type=self.source_type,
            display_name=self.display_name,
            root_path=root_path,
            parser_name=self.parser_name,
            watchable=self.watchable,
            metadata={
                "agent_name": self.agent_name,
                "openclaw_home": str(openclaw_home),
            },
        )

    def scan(self, root_path: Path) -> list[SessionInfo]:
        return discover_sessions_in_path(root_path)


CONNECTOR_ADAPTERS: dict[str, ConnectorAdapter] = {
    "claude_code": ClaudeCodeConnectorAdapter(),
    "claude_desktop": FixedPathConnectorAdapter(
        source_type="claude_desktop",
        display_name="Claude Desktop",
        parser_name="claude_desktop",
        root_dir_name=".claude-desktop",
    ),
    "codex_cli": FixedPathConnectorAdapter(
        source_type="codex_cli",
        display_name="Codex CLI",
        parser_name="codex_cli",
        root_dir_name=".codex",
    ),
    "codex_desktop": FixedPathConnectorAdapter(
        source_type="codex_desktop",
        display_name="Codex Desktop",
        parser_name="codex_desktop",
        root_dir_name=".codex-desktop",
    ),
    "openclaw_main": OpenClawAgentConnectorAdapter(
        source_type="openclaw_main",
        agent_name="main",
        display_name="OpenClaw Main",
    ),
    "openclaw_business": OpenClawAgentConnectorAdapter(
        source_type="openclaw_business",
        agent_name="business",
        display_name="OpenClaw Business",
    ),
    "openclaw_engineering": OpenClawAgentConnectorAdapter(
        source_type="openclaw_engineering",
        agent_name="engineering",
        display_name="OpenClaw Engineering",
    ),
}


def discover_connector_candidates(context: DiscoveryContext) -> list[ConnectorCandidate]:
    return [
        candidate
        for adapter in CONNECTOR_ADAPTERS.values()
        if (candidate := adapter.build_candidate(context)) is not None
    ]


def get_connector_adapter(source_type: str) -> ConnectorAdapter:
    try:
        return CONNECTOR_ADAPTERS[source_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported connector source: {source_type}") from exc
