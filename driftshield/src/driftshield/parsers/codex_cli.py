from driftshield.parsers.local_chat import LocalChatTranscriptParser


class CodexCliParser(LocalChatTranscriptParser):
    def __init__(self) -> None:
        super().__init__(source_type="codex_cli", default_agent_id="codex_cli")
