"""Recursive redactor v2 for OSS submission payloads.

driftshield#109 hard-gate scope. Extends the v1 redactor (driftshield#107,
remote_submission.redact_payload) which only drops the top-level
REQUIRED_REDACTION_FIELDS plus nested ``content`` / ``text`` keys.

What v2 adds:

* tool-IO key-value redaction at any depth (``arguments``, ``input``,
  ``parameters``, ``result``, ``output``, ``file_content``, ``tool_input``,
  ``tool_output``, ``function_args``, ``function_result``)
* regex-based secret patterns in any string value (AWS access key, GitHub PAT,
  OpenAI key, JWT, SSN, Luhn-validated credit card)
* path-shape detection (``/Users/...``, ``/home/...``, ``C:\\Users\\...``)
* free-text email replacement

The public envelope contract continues to advertise the v1 manifest claim
(``REQUIRED_REDACTION_FIELDS``). The internal rule set is implementation-only
and intentionally not surfaced on the manifest. A future contract bump
will add ``redactor_version`` and ``redaction_ruleset_version`` provenance
fields; this module pins both values as constants in anticipation.

Tool-IO values are replaced (not deleted) with a stable hash placeholder so
downstream analysers can keep their structural assumptions about tool-call
shapes. Pure prompt/response keys (``content``, ``text``) still delete to
match v1 behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import re
from typing import Any

from driftshield.intake_contract import REQUIRED_REDACTION_FIELDS


REDACTOR_VERSION = "recursive-redactor.v2.0.0"
REDACTION_RULESET_VERSION = "ruleset.v2"

_TOOL_IO_KEYS: frozenset[str] = frozenset(
    {
        "arguments",
        "input",
        "parameters",
        "result",
        "output",
        "file_content",
        "tool_input",
        "tool_output",
        "function_args",
        "function_result",
    }
)

_PROMPT_RESPONSE_KEYS: frozenset[str] = frozenset({"content", "text"})

# Failure / diagnostic body keys.
#
# Native transcripts append failure and tool-result records verbatim into
# ``payload['events']`` with no field mapping, so a key carrying a raw
# failure body (an API-error message with bearer tokens and response
# headers, a command's stdout/stderr, a traceback, a tool-argument blob)
# survives unless dropped by name. None of these keys are read by the
# deterministic matcher: failure mechanism is keyed off the locally derived
# structured fields (``result_status``, ``failure_context.error``,
# ``error_code``, the ``is_error`` flag), which are computed before
# redaction from the parsed events, not from these verbatim keys. So
# dropping them has zero matcher-quality cost.
#
# Scope is the named free-text keys only. Bare codes / enums / flags are
# deliberately NOT dropped, so the matcher keeps its failure signal and
# the retained non-sensitive HTTP status code stays available:
#
#  * ``status`` / ``error_code`` / ``result_status`` / ``is_error`` are
#    matcher mechanism signals (enums / flags), retained.
#  * ``api_error_status`` is a bare HTTP status code (401/429/500). It is
#    non-sensitive and is retained on purpose; only the ``error`` body that
#    accompanies it carries tokens/headers/tracebacks and must be dropped.
#
# Dropped keys:
#  * ``error``          free-text failure body (Claude Code API-error
#                       records; crewai ``outputs.error``; langchain
#                       ``outputs.error`` + ``metadata.error``)
#  * ``stdout`` /       native ``toolUseResult`` command-output streams
#    ``stderr``         (tracebacks, hostnames, file dumps)
#  * ``toolUseResult``  the native root-level key itself, which arrives as a
#                       bare string ("Error: ...") or a dict wrapping
#                       stdout/stderr
#  * ``details``        openclaw ``outputs.details`` diagnostic dict
#  * ``raw``            openclaw fallback for unparseable tool arguments
_FAILURE_BODY_KEYS: frozenset[str] = frozenset(
    {
        "error",
        "stdout",
        "stderr",
        "toolUseResult",
        "details",
        "raw",
    }
)

# OpenClaw trajectory content keys (ruleset.v2).
#
# OpenClaw runtime trajectories carry the conversation and tool surface
# under their own key names, which the v1 ruleset did not cover: the
# generic rules redacted path-shaped strings and ``_TOOL_IO_KEYS`` values
# inside them, but the free-text prompt/response bodies survived. None of
# these keys feed the deterministic matcher, so dropping them costs no
# matcher signal:
#  * ``prompt`` / ``systemPrompt`` / ``finalPromptText``  submitted prompt
#    text and the compiled system prompt (tool inventories, agent config)
#  * ``assistantTexts``       model response bodies
#  * ``messagesSnapshot``     full message-history snapshot
#  * ``messagingToolSentTexts``  outbound messages sent via messaging tools
#  * ``toolMetas``            per-tool-call free-text meta (command lines)
_OPENCLAW_CONTENT_KEYS: frozenset[str] = frozenset(
    {
        "prompt",
        "systemPrompt",
        "finalPromptText",
        "assistantTexts",
        "messagesSnapshot",
        "messagingToolSentTexts",
        "toolMetas",
    }
)

_DROPPED_KEYS: frozenset[str] = (
    REQUIRED_REDACTION_FIELDS
    | _PROMPT_RESPONSE_KEYS
    | _FAILURE_BODY_KEYS
    | _OPENCLAW_CONTENT_KEYS
)


_AWS_ACCESS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")
_GITHUB_PAT = re.compile(r"ghp_[A-Za-z0-9]{36}")
_OPENAI_KEY = re.compile(r"sk-[A-Za-z0-9]{20,}")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_CANDIDATE = re.compile(r"\b\d{13,19}\b")
_HOME_PATH_UNIX = re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+")
_HOME_PATH_WIN = re.compile(r"C:\\Users\\[A-Za-z0-9_.-]+", re.IGNORECASE)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@dataclass(slots=True)
class RedactionEntry:
    path: str
    category: str
    sample_hash: str


@dataclass(slots=True)
class RedactionResult:
    payload: Any
    entries: list[RedactionEntry] = field(default_factory=list)


def _stable_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:16]


def _placeholder(category: str, value: str) -> str:
    return f"<REDACTED:{category}:{_stable_hash(value)}>"


def _luhn_valid(digits: str) -> bool:
    total = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _redact_string(value: str, path: str, entries: list[RedactionEntry]) -> str:
    def record(category: str, matched: str) -> str:
        entries.append(
            RedactionEntry(path=path, category=category, sample_hash=_stable_hash(matched))
        )
        return _placeholder(category, matched)

    def _sub_card(match: re.Match[str]) -> str:
        raw = match.group(0)
        if _luhn_valid(raw):
            return record("credit_card", raw)
        return raw

    value = _AWS_ACCESS_KEY.sub(lambda m: record("aws_access_key", m.group(0)), value)
    value = _GITHUB_PAT.sub(lambda m: record("github_pat", m.group(0)), value)
    value = _OPENAI_KEY.sub(lambda m: record("openai_key", m.group(0)), value)
    value = _JWT.sub(lambda m: record("jwt", m.group(0)), value)
    value = _SSN.sub(lambda m: record("ssn", m.group(0)), value)
    value = _CARD_CANDIDATE.sub(_sub_card, value)
    value = _HOME_PATH_UNIX.sub(lambda m: record("home_path", m.group(0)), value)
    value = _HOME_PATH_WIN.sub(lambda m: record("home_path", m.group(0)), value)
    value = _EMAIL.sub(lambda m: record("email", m.group(0)), value)
    return value


def _redact_value(value: Any, path: str, entries: list[RedactionEntry]) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in _DROPPED_KEYS:
                entries.append(
                    RedactionEntry(
                        path=child_path,
                        category="dropped_key",
                        sample_hash=_stable_hash(repr(item)),
                    )
                )
                continue
            if key in _TOOL_IO_KEYS:
                serialised = repr(item)
                entries.append(
                    RedactionEntry(
                        path=child_path,
                        category="tool_io",
                        sample_hash=_stable_hash(serialised),
                    )
                )
                result[key] = _placeholder("tool_io", serialised)
                continue
            result[key] = _redact_value(item, child_path, entries)
        return result
    if isinstance(value, list):
        return [
            _redact_value(item, f"{path}[{index}]", entries)
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        return _redact_string(value, path, entries)
    return value


def redact(payload: dict[str, Any]) -> RedactionResult:
    """Recursively redact ``payload`` and return the rewritten copy plus entries.

    The public manifest claim (REQUIRED_REDACTION_FIELDS) stays accurate: the
    top-level redacted field set always advertises those three. The detailed
    entries list captures every match the recursive ruleset made and is
    intended for ``--show-manifest`` / ``--dry-run-redaction`` output and for
    audit-trail consumers.
    """
    entries: list[RedactionEntry] = []
    redacted_payload = _redact_value(payload, "", entries)
    return RedactionResult(payload=redacted_payload, entries=entries)
