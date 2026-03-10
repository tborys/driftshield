from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from driftshield.cli.discovery import (
    SessionInfo,
    discover_sessions_in_path,
    get_claude_projects_dir,
    path_to_project_key,
)


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
        return discover_sessions_in_path(root_path)


CONNECTOR_ADAPTERS: dict[str, ConnectorAdapter] = {
    "claude_code": ClaudeCodeConnectorAdapter(),
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
