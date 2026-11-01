#!/usr/bin/env python3
"""SessionStart (cloud routine only): open the run.

Sets the commit identity and the git hooks path for this session only, as
GIT_CONFIG_* variables in CLAUDE_ENV_FILE. Nothing is written to .git/config.
The identity comes from DS_GIT_AUTHOR_NAME and DS_GIT_AUTHOR_EMAIL in the
cloud environment. Records the run's identity in .driftshield/run.json and
the remote branches and kit digest the Stop hook compares against.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import uuid
from pathlib import Path

sys.dont_write_bytecode = True  # keep the kit folder clean
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dslib  # noqa: E402

ENV_NAMES = ("DS_GIT_AUTHOR_NAME", "DS_GIT_AUTHOR_EMAIL", "DS_DENY_TERMS", "DS_REPO", "DRIFTSHIELD_API_KEY",
             "DRIFTSHIELD_INTAKE_URL", "DRIFTSHIELD_API_URL", "DRIFTSHIELD_RECORD_URL")


def session_env() -> list[str]:
    """Exports for every later Bash command in this session, git hooks included."""
    pairs = [("core.hooksPath", str(dslib.KIT / "git-hooks"))]
    name, email = os.environ.get("DS_GIT_AUTHOR_NAME"), os.environ.get("DS_GIT_AUTHOR_EMAIL")
    if name and email:
        pairs += [("user.name", name), ("user.email", email)]
    lines = [f"export GIT_CONFIG_COUNT={len(pairs)}"]
    for i, (k, v) in enumerate(pairs):
        lines += [f"export GIT_CONFIG_KEY_{i}={shlex.quote(k)}", f"export GIT_CONFIG_VALUE_{i}={shlex.quote(v)}"]
    lines.append(f'export PATH={shlex.quote(str(dslib.KIT / "bin"))}:"$PATH"')
    return lines


def main() -> int:
    dslib.exit_unless_active()
    try:
        hook_input = json.load(sys.stdin)
    except ValueError:
        hook_input = {}
    if hook_input.get("source", "startup") != "startup" and (dslib.work() / "run.json").exists():
        return 0
    problems = []
    if not (os.environ.get("DS_GIT_AUTHOR_NAME") and os.environ.get("DS_GIT_AUTHOR_EMAIL")):
        problems.append("DS_GIT_AUTHOR_NAME or DS_GIT_AUTHOR_EMAIL is not set, so every commit will be refused.")
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        with open(env_file, "a") as fh:
            fh.write("\n".join(session_env()) + "\n")
    else:
        problems.append("CLAUDE_ENV_FILE is not set, so the git hooks and the commit identity are not active.")
    exclude = dslib.root() / ".git" / "info" / "exclude"
    if exclude.parent.exists():
        text = exclude.read_text() if exclude.exists() else ""
        if ".driftshield/" not in text:
            exclude.write_text(text + ("\n" if text and not text.endswith("\n") else "") + ".driftshield/\n")
    origin = dslib.repo_slug()
    user = dslib.gh_json("user", retry=True)
    run = {
        "session_id": hook_input.get("session_id"),
        "remote_session_id": os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID"),
        "nonce": uuid.uuid4().hex[:8],
        "routine": os.environ.get("DS_ROUTINE_NAME"),
        "repository": origin,
        "login": user.get("login") if isinstance(user, dict) else None,
        "issue": None, "pr": None,
        "model": hook_input.get("model"),
        "started_at": dslib.now(),
        "base_sha": dslib.git("rev-parse", "HEAD"),
        "kit_tree": dslib.git("rev-parse", "HEAD:.claude"),
        "kit_disk_sha256": dslib.kit_disk_digest(),
        "refs_before": dslib.remote_heads(),
    }
    if not run["repository"]:
        problems.append("could not tell the repository from origin or DS_REPO.")
    if not run["login"]:
        problems.append("could not read the GitHub login, so markers are trusted from the repo owner only.")
    with dslib.lock():
        dslib.write_json(dslib.work() / "run.json", run)
        dslib.write_json(dslib.work() / "state.json", {"last_head": run["base_sha"]})
    sdk = Path(os.environ.get("DS_SDK_PYTHON", "/opt/ds-sdk/bin/python"))
    dslib.append_event("run.started", data={
        "kit_tree": run["kit_tree"], "model": run["model"], "base_sha": run["base_sha"],
        "repository": run["repository"], "repository_env": os.environ.get("DS_REPO"),
        "sdk_present": sdk.exists(), "gh_present": shutil.which(os.environ.get("DS_GH", "gh")) is not None,
        "env_present": {n: bool(os.environ.get(n)) for n in ENV_NAMES}, "problems": problems})
    print(f"Delivery kit ready, run {run['nonce']}. {' '.join(problems) or 'Commit identity and git hooks are set.'} "
          "Follow .claude/delivery/lead.md.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # never block a session on bookkeeping
        dslib.hook_error("session_start", exc)
        sys.exit(0)
