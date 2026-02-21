from pathlib import Path

from driftshield.fixtures.transcript_generator import (
    ScenarioTranscriptGenerator,
    default_scenario_registry,
)
from driftshield.parsers.claude_code import ClaudeCodeParser


def test_generator_creates_jsonl_files_parseable_by_claude_parser(tmp_path: Path) -> None:
    out_dir = tmp_path / "fixtures"
    generator = ScenarioTranscriptGenerator(default_scenario_registry())

    written = generator.generate(out_dir)

    assert written
    parser = ClaudeCodeParser()
    for file_path in written:
        content = file_path.read_text(encoding="utf-8")
        events = parser.parse(content)
        assert len(events) > 0


def test_generator_can_include_clean_fixture(tmp_path: Path) -> None:
    out_dir = tmp_path / "fixtures"
    generator = ScenarioTranscriptGenerator(default_scenario_registry())

    written = generator.generate(out_dir, include_clean=True)

    names = {p.name for p in written}
    assert "clean_session.jsonl" in names
