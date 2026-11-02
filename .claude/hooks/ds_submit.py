"""Upload transcripts to DriftShield with the public SDK.

Runs under the SDK's own interpreter (DS_SDK_PYTHON, default
/opt/ds-sdk/bin/python), never the repo's, so it never runs code the agent
is changing. Reads a job on stdin and prints one JSON receipt line per item
as soon as that item is done, so a caller that times out keeps what arrived.
Job: {"intake_url", "deadline": unix seconds, "items": [{"path", "run_key",
"source_session_id", "agent_id", "model_name", "workflow_reference",
"project_reference", "source_report_id"}]}. The key comes from
DRIFTSHIELD_API_KEY only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True  # keep the kit folder clean
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dslib import NAMESPACE  # noqa: E402  (standard library only)

WAITS = (0, 3, 10, 30)


def scrub(text: str, key: str) -> str:
    return text.replace(key, "<key>") if key else text


def submit_one(item: dict, key: str, deadline: float) -> dict:
    from driftshield.public import NoParseableEventsError, SubmitError, analyse_run, submit

    out = {"path": item["path"], "run_key": item["run_key"]}
    if time.time() > deadline:
        return {**out, "status": "error", "error": "deadline reached before upload"}
    try:
        with open(item["path"], "rb") as fh:
            run = analyse_run(fh.read(), source=item["path"], run_id=uuid.uuid5(NAMESPACE, item["run_key"]))
    except NoParseableEventsError as exc:
        return {**out, "status": "skipped", "error": str(exc)[:200]}
    for attempt, wait in enumerate(WAITS):
        if attempt and time.time() + wait > deadline:
            return {**out, "status": "error", "error": "retry budget used up", "attempts": attempt}
        time.sleep(wait)
        try:
            receipt = submit(run, visibility="workspace", key=key, source_session_id=item.get("source_session_id"),
                             workflow_reference=item.get("workflow_reference"),
                             project_reference=item.get("project_reference"),
                             source_report_id=item.get("source_report_id"),
                             agent_id=item.get("agent_id"), model_name=item.get("model_name"))
            return {**out, "status": "submitted", "submission_id": receipt.submission_id,
                    "processing_status": receipt.processing_status, "attempts": attempt + 1}
        except SubmitError as exc:
            message = scrub(str(exc), key)
            if attempt == len(WAITS) - 1 or any(code in message for code in ("401", "403", "413", "422")):
                return {**out, "status": "error", "error": message[:300], "attempts": attempt + 1}
    return {**out, "status": "error", "error": "no attempt made"}


def main() -> int:
    job = json.load(sys.stdin)
    key = os.environ.get("DRIFTSHIELD_API_KEY", "")
    os.environ["DRIFTSHIELD_HOME"] = tempfile.mkdtemp(prefix="ds-home-")
    from driftshield.telemetry.service import TelemetryService

    TelemetryService().remote_enable(intake_url=job["intake_url"])
    deadline = float(job.get("deadline") or time.time() + 150)
    for item in job["items"]:
        try:
            receipt = submit_one(item, key, deadline)
        except Exception as exc:  # one bad file must not cost the others their receipts
            receipt = {"path": item["path"], "run_key": item["run_key"], "status": "error",
                       "error": scrub(f"{type(exc).__name__}: {exc}", key)[:300]}
        print(json.dumps(receipt), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
