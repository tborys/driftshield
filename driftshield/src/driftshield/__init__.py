"""DriftShield - AI Decision Forensics.

The public API is exactly two operations, ``analyse_run`` and ``submit``, with
their result and error types. Everything else in the package is internal.
"""

from driftshield.public import (
    AnalysedRun,
    Finding,
    NoParseableEventsError,
    SignatureHit,
    SubmitError,
    SubmitReceipt,
    UnsupportedFormatError,
    analyse_run,
    submit,
)

__version__ = "0.2.0"

__all__ = [
    "AnalysedRun",
    "Finding",
    "NoParseableEventsError",
    "SignatureHit",
    "SubmitError",
    "SubmitReceipt",
    "UnsupportedFormatError",
    "analyse_run",
    "submit",
]
