"""Discovery and execution logic behind the ``driftshield batch`` command.

Given a directory or a ``.zip``/``.tar.gz``/``.tgz`` archive of transcripts,
walk it, auto-detect a parser per file, analyse each file independently, and
optionally submit every successfully analysed file through the same
build-payload -> redact -> submit path as ``driftshield submit``
(:func:`driftshield.cli._submit.submit_session_core`).

Per-file isolation is the point of this module: a file that cannot be
detected is recorded ``skipped``; a file that raises during parse, analysis,
or submission is recorded ``failed`` with the exception message as the
reason. Neither aborts the rest of the batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import tarfile
import tempfile
from pathlib import Path
from typing import Any
import zipfile

from driftshield.cli._session_payload import load_session_payload
from driftshield.cli._submit import (
    IncludeAnalysisError,
    SubmitCoreError,
    submit_session_core,
)
from driftshield.cli.parsers import detect_parser, get_parser
from driftshield.core.analysis.session import analyze_session
from driftshield.public import detect_source
from driftshield.remote_submission import RemoteSubmissionError, UnknownTranscriptShapeError


_ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz")

# Any exception raised by submit_session_core() (or by load_session_payload())
# on a legitimate, well-formed but unsubmittable transcript. Kept as one tuple
# so batch only needs a single except clause to record a "failed" outcome
# without ever letting one file's submission error abort the run.
_SUBMISSION_ERRORS = (
    OSError,
    ValueError,
    RemoteSubmissionError,
    UnknownTranscriptShapeError,
    IncludeAnalysisError,
    SubmitCoreError,
)


@dataclass(slots=True)
class BatchFileOutcome:
    """Result recorded for one discovered file in a batch run.

    ``outcome`` is one of ``"submitted"``, ``"analysed-only"``, ``"failed"``,
    or ``"skipped"``. This is the stable, documented shape behind both the
    human-readable report and ``--json`` output.
    """

    path: str
    outcome: str
    reason: str | None = None
    submission_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "outcome": self.outcome,
            "reason": self.reason,
            "submission_id": self.submission_id,
        }


@dataclass(slots=True)
class BatchReport:
    """Aggregate result of one ``run_batch`` call."""

    files: list[BatchFileOutcome] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, int]:
        totals = {"submitted": 0, "analysed-only": 0, "failed": 0, "skipped": 0}
        for entry in self.files:
            totals[entry.outcome] = totals.get(entry.outcome, 0) + 1
        return totals

    @property
    def has_failures(self) -> bool:
        return any(entry.outcome == "failed" for entry in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {"totals": self.totals, "files": [entry.to_dict() for entry in self.files]}


def _is_archive(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(_ARCHIVE_SUFFIXES)


def _safe_extract_zip(archive: zipfile.ZipFile, dest: Path) -> None:
    """Extract ``archive`` into ``dest``, refusing any member that would
    escape ``dest`` (a "zip slip" path-traversal attempt via ``../`` or an
    absolute path in the member name)."""
    dest_resolved = dest.resolve()
    for member in archive.infolist():
        member_path = (dest / member.filename).resolve()
        if member_path != dest_resolved and dest_resolved not in member_path.parents:
            raise ValueError(
                f"refusing to extract archive member outside the target directory: "
                f"{member.filename!r}"
            )
    archive.extractall(dest)


def _extract_archive(archive_path: Path, dest: Path) -> None:
    if archive_path.name.lower().endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            _safe_extract_zip(zf, dest)
    else:
        # .tar.gz / .tgz. filter="data" (Python 3.12+) rejects path
        # traversal, device files, and other unsafe members during
        # extraction -- the tarfile equivalent of the zip-slip guard above.
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(dest, filter="data")


def _discover_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _relative_label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _process_directory(
    root: Path,
    *,
    report: BatchReport,
    submit: bool,
    tier: str,
    include_analysis: bool,
) -> None:
    for file_path in _discover_files(root):
        relative = _relative_label(file_path, root)

        try:
            parser_name = detect_parser(file_path)
        except Exception as exc:  # noqa: BLE001 - per-file isolation
            report.files.append(
                BatchFileOutcome(
                    path=relative,
                    outcome="skipped",
                    reason=f"parser detection failed: {exc}",
                )
            )
            continue

        if parser_name is None:
            # detect_parser() keys on path conventions (e.g. `.codex-desktop/
            # sessions/`) that a batch source rarely preserves: files are
            # walked from an arbitrary directory or extracted from an archive
            # into a flat temp dir. Fall back to content sniffing so a
            # supported non-.jsonl transcript (claude_desktop, codex_desktop,
            # crewai, langchain, ...) is still recognised by its shape.
            try:
                content = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                content = None
            if content is not None:
                parser_name = detect_source(content)

        if parser_name is None:
            report.files.append(
                BatchFileOutcome(
                    path=relative,
                    outcome="skipped",
                    reason="no known parser detected for this file",
                )
            )
            continue

        try:
            parser_instance = get_parser(parser_name)
            events = parser_instance.parse_file(str(file_path))
            analyze_session(events)
        except Exception as exc:  # noqa: BLE001 - per-file isolation
            report.files.append(
                BatchFileOutcome(path=relative, outcome="failed", reason=str(exc))
            )
            continue

        if not submit:
            report.files.append(BatchFileOutcome(path=relative, outcome="analysed-only"))
            continue

        try:
            payload = load_session_payload(file_path)
            outcome = submit_session_core(
                payload=payload,
                path=file_path,
                tier=tier,
                include_analysis=include_analysis,
            )
        except _SUBMISSION_ERRORS as exc:  # noqa: BLE001 - per-file isolation
            report.files.append(
                BatchFileOutcome(path=relative, outcome="failed", reason=str(exc))
            )
            continue

        report.files.append(
            BatchFileOutcome(
                path=relative, outcome="submitted", submission_id=outcome.submission_id
            )
        )


def run_batch(
    source: Path,
    *,
    submit: bool = False,
    tier: str = "oss",
    include_analysis: bool = False,
) -> BatchReport:
    """Discover and analyse every transcript under ``source``.

    ``source`` is either a directory (walked recursively) or a
    ``.zip``/``.tar.gz``/``.tgz`` archive, which is extracted to a temporary
    directory that is cleaned up before this function returns. Raises
    ``ValueError`` if ``source`` is neither.
    """
    report = BatchReport()

    if source.is_dir():
        _process_directory(
            source, report=report, submit=submit, tier=tier, include_analysis=include_analysis
        )
        return report

    if source.is_file() and _is_archive(source):
        with tempfile.TemporaryDirectory(prefix="driftshield-batch-") as tmp_name:
            extract_root = Path(tmp_name)
            _extract_archive(source, extract_root)
            _process_directory(
                extract_root,
                report=report,
                submit=submit,
                tier=tier,
                include_analysis=include_analysis,
            )
        return report

    raise ValueError(
        f"'{source}' is not a directory or a supported archive (.zip, .tar.gz, .tgz)"
    )


__all__ = ["BatchFileOutcome", "BatchReport", "run_batch"]
