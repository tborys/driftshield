from driftshield.parsers.local_chat import LocalChatTranscriptParser


class CodexDesktopParser(LocalChatTranscriptParser):
    def __init__(self) -> None:
        super().__init__(source_type="codex_desktop", default_agent_id="codex_desktop")
