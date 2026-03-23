from driftshield.parsers.local_chat import LocalChatTranscriptParser


class ClaudeDesktopParser(LocalChatTranscriptParser):
    def __init__(self) -> None:
        super().__init__(source_type="claude_desktop", default_agent_id="claude_desktop")
