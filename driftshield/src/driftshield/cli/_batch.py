"""Discovery and execution logic behind the ``driftshield batch`` command.

Given a directory or a ``.zip``/``.tar.gz``/``.tgz`` archive of transcripts,
walk it, analyse each file through :func:`driftshield.public.analyse_run`,
and optionally submit every analysed file through
:func:`driftshield.public.submit`, the same door ``driftshield submit`` uses.

Per-file isolation is the point of this module: a file with no parseable
events is recorded ``skipped``; a file that raises during analysis or
submission is recorded ``failed`` with the exception message as the reason.
Neither aborts the rest of the batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Any
import zipfile

from driftshield.cli._submit import resolve_workspace_key
from driftshield.intake_contract import DEFAULT_WORKFLOW_REFERENCE
from driftshield.public import NoParseableEventsError, SubmitError, analyse_run, submit

_ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz")

# Characters the workflow_reference field is treated as accepting for a
# derived (not explicitly-flagged) value. A directory name is free-form user
# content, so any run of characters outside this set collapses to a single
# '-' rather than riding through unchecked.
_WORKFLOW_REFERENCE_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _derive_workflow_reference(file_path: Path) -> str:
    """Derive a stable, per-directory workflow reference for one discovered file.

    The file's immediate parent directory is the unit (driftshield#182): a
    tree of per-project session directories yields one workflow reference
    per project. Sanitised by collapsing any run of characters outside
    ``[A-Za-z0-9._-]`` into a single ``-`` and trimming leading/trailing
    ``-``; falls back to the module default when nothing usable survives.
    """
    sanitized = _WORKFLOW_REFERENCE_UNSAFE_RE.sub("-", file_path.parent.name).strip("-")
    return sanitized or DEFAULT_WORKFLOW_REFERENCE


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
    return path.name.lower().endswith(_ARCHIVE_SUFFIXES)


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
    submit_files: bool,
    tier: str,
    include_analysis: bool,
    backfill: bool = False,
    workflow_reference: str | None = None,
) -> None:
    for file_path in _discover_files(root):
        relative = _relative_label(file_path, root)

        try:
            run = analyse_run(file_path.read_bytes(), source=str(file_path))
        except NoParseableEventsError as exc:
            # Nothing to analyse is a skip; a parser that blew up on the
            # content is a failure the exit code must reflect.
            outcome = "failed" if exc.reason == "parse_failed" else "skipped"
            report.files.append(BatchFileOutcome(path=relative, outcome=outcome, reason=str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - per-file isolation
            report.files.append(BatchFileOutcome(path=relative, outcome="failed", reason=str(exc)))
            continue

        if not submit_files:
            report.files.append(BatchFileOutcome(path=relative, outcome="analysed-only"))
            continue

        # Resolution order: the explicit --workflow-reference flag (same
        # value for every file), then a value derived per file from its
        # immediate parent directory rather than falling straight through
        # to the module default (driftshield#182).
        try:
            receipt = submit(
                run,
                tier,
                resolve_workspace_key(tier),
                workflow_reference=(
                    workflow_reference
                    if workflow_reference is not None
                    else _derive_workflow_reference(file_path)
                ),
                backfill=backfill,
                include_analysis=include_analysis,
            )
        except (SubmitError, ValueError) as exc:  # per-file isolation
            report.files.append(BatchFileOutcome(path=relative, outcome="failed", reason=str(exc)))
            continue

        report.files.append(
            BatchFileOutcome(path=relative, outcome="submitted", submission_id=receipt.submission_id)
        )


def run_batch(
    source: Path,
    *,
    submit: bool = False,
    tier: str = "oss",
    include_analysis: bool = False,
    backfill: bool = False,
    workflow_reference: str | None = None,
) -> BatchReport:
    """Discover and analyse every transcript under ``source``.

    ``source`` is either a directory (walked recursively) or a
    ``.zip``/``.tar.gz``/``.tgz`` archive, which is extracted to a temporary
    directory that is cleaned up before this function returns. Raises
    ``ValueError`` if ``source`` is neither.

    ``backfill=True`` stamps top-level ``backfill: true`` on every
    submitted envelope (only meaningful together with ``submit=True`` and
    ``tier="teams"``; :func:`driftshield.public.submit` enforces this).

    ``workflow_reference``, when given, is stamped on every submitted
    envelope (matching ``driftshield submit --workflow-reference``). When
    omitted, each file's own value is derived from its immediate parent
    directory instead of falling back to the module default -- see
    :func:`_derive_workflow_reference`. Only meaningful together with
    ``submit=True``.
    """
    report = BatchReport()
    options = dict(
        report=report,
        submit_files=submit,
        tier=tier,
        include_analysis=include_analysis,
        backfill=backfill,
        workflow_reference=workflow_reference,
    )

    if source.is_dir():
        _process_directory(source, **options)
        return report

    if source.is_file() and _is_archive(source):
        with tempfile.TemporaryDirectory(prefix="driftshield-batch-") as tmp_name:
            extract_root = Path(tmp_name)
            _extract_archive(source, extract_root)
            _process_directory(extract_root, **options)
        return report

    raise ValueError(
        f"'{source}' is not a directory or a supported archive (.zip, .tar.gz, .tgz)"
    )


__all__ = ["BatchFileOutcome", "BatchReport", "run_batch"]
