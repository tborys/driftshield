"""Optional run bundle upload to a private S3 bucket. Standard library only.

Off unless DS_RUNS_BUCKET, DS_RUNS_AWS_ACCESS_KEY_ID and DS_RUNS_AWS_SECRET_ACCESS_KEY are all
set in the cloud environment (DS_RUNS_AWS_REGION defaults to eu-west-2). The Stop hook calls
upload_run() after the DriftShield upload. One run is one folder of objects:

  runs/<owner>-<repo>/issue-<n>/<YYYYMMDDTHHMMSSZ of the run start>-<nonce>/
    record.json  links.json  notes.md  spec.json  claims.json
    verdicts/round-<k>.json
    checks/<check>-<time>.log  checks/junit-<check>-<time>.xml
    transcripts/lead.jsonl  transcripts/<role>-<agent id>.jsonl   raw, as Claude Code wrote them
    manifest.json                                                  written last, only if all else arrived

DS_RUNS_S3_ENDPOINT (path style addressing) exists for tests and is unset in the cloud.

Before an object leaves the VM, the run's secret values and key shaped strings are replaced
with <scrubbed>, in memory; the files on disk are not touched. Requests are signed here (AWS
Signature Version 4), so the hook needs no SDK and no pip install. Nothing in this file runs
code from the repository under change.

upload_run() never raises for a bad network or a bad key: that is a status, and it must not
block the end of the run.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

sys.dont_write_bytecode = True  # keep the kit folder clean
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dslib  # noqa: E402

MASK = "<scrubbed>"
DEFAULT_REGION = "eu-west-2"
MAX_OBJECT_BYTES = 256 * 1024 * 1024  # one PUT each; a bigger file is skipped and says so
REQUIRED = ("DS_RUNS_BUCKET", "DS_RUNS_AWS_ACCESS_KEY_ID", "DS_RUNS_AWS_SECRET_ACCESS_KEY")
SECRET_WORDS = {"KEY", "KEYS", "SECRET", "SECRETS", "TOKEN", "TOKENS", "PASSWORD", "PASSWD", "PASSPHRASE",
                "CREDENTIAL", "CREDENTIALS", "APIKEY"}
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
TYPES = {".json": "application/json", ".jsonl": "application/x-ndjson", ".md": "text/markdown", ".xml": "application/xml"}


# ---------- configuration ----------

def config(env: dict | None = None) -> tuple[dict | None, str | None]:
    """(settings, None) when the bundle is on, (None, None) when nothing is set, and
    (None, reason) when it is set up wrongly. The reason names variables, never values."""
    env = os.environ if env is None else env
    if not any(env.get(n) for n in REQUIRED):
        return None, None
    missing = [n for n in REQUIRED if not env.get(n)]
    if missing:
        return None, f"missing {', '.join(missing)}"
    cfg = {"bucket": env["DS_RUNS_BUCKET"], "region": env.get("DS_RUNS_AWS_REGION") or DEFAULT_REGION,
           "key_id": env["DS_RUNS_AWS_ACCESS_KEY_ID"], "secret": env["DS_RUNS_AWS_SECRET_ACCESS_KEY"],
           "endpoint": env.get("DS_RUNS_S3_ENDPOINT") or None}
    if not BUCKET.match(cfg["bucket"]):
        return None, "DS_RUNS_BUCKET is not a valid bucket name"
    if not REGION.match(cfg["region"]):
        return None, "DS_RUNS_AWS_REGION is not a valid region"
    return cfg, None


# ---------- AWS Signature Version 4, just enough for S3 ----------

def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def authorization(method: str, path: str, query: str, headers: dict, payload_hash: str, region: str,
                  key_id: str, secret: str, amz_date: str, service: str = "s3") -> str:
    """The Authorization header for one request. `headers` holds every header to sign,
    including host, x-amz-date and x-amz-content-sha256."""
    lowered = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    names = sorted(lowered)
    canonical = "\n".join([method, path, query, "".join(f"{n}:{lowered[n]}\n" for n in names),
                           ";".join(names), payload_hash])
    day = amz_date[:8]
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signing = _hmac(("AWS4" + secret).encode(), day)
    for part in (region, service, "aws4_request"):
        signing = _hmac(signing, part)
    signature = hmac.new(signing, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"


def target(cfg: dict, key: str) -> tuple[str, str, str]:
    """(base URL, host header, canonical path). Path style only when an endpoint is set (tests)."""
    quoted = quote(key, safe="/")
    if cfg.get("endpoint"):
        netloc = urlsplit(cfg["endpoint"]).netloc
        return f"{urlsplit(cfg['endpoint']).scheme}://{netloc}", netloc, f"/{cfg['bucket']}" + (f"/{quoted}" if key else "")
    host = f"{cfg['bucket']}.s3.{cfg['region']}.amazonaws.com"
    return f"https://{host}", host, f"/{quoted}"


def signed_request(cfg: dict, method: str, key: str, body: bytes = b"", query: dict | None = None,
                   content_type: str | None = None, timeout: float = 30, when: datetime | None = None
                   ) -> tuple[int, dict, bytes]:
    """One signed request: (status, headers, body). An HTTP error status is returned, not raised;
    a network failure raises URLError or OSError."""
    base, host, path = target(cfg, key)
    amz_date = (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    payload_hash = hashlib.sha256(body).hexdigest()
    qs = "&".join(f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in sorted((query or {}).items()))
    signed = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
    headers = {"x-amz-content-sha256": payload_hash, "x-amz-date": amz_date,
               "Authorization": authorization(method, path, qs, signed, payload_hash, cfg["region"],
                                              cfg["key_id"], cfg["secret"], amz_date)}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(base + path + (f"?{qs}" if qs else ""), method=method, headers=headers,
                                 data=body if method == "PUT" else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, dict(exc.headers), exc.read()
        finally:
            exc.close()


def s3_code(body: bytes) -> str:
    m = re.search(rb"<Code>([A-Za-z0-9]{1,40})</Code>", body or b"")
    return m.group(1).decode() if m else ""


def put_object(cfg: dict, key: str, body: bytes, deadline: float, content_type: str | None = None) -> tuple[bool, str]:
    """(stored, detail). Retries a server error, throttling or a dropped connection; a refused key
    or signature fails at once."""
    pause = float(os.environ.get("DS_RETRY_WAIT", "2"))
    detail = "deadline reached"
    for wait in (0, pause, 3 * pause):
        if time.time() + wait + 5 > deadline:
            break
        time.sleep(wait)
        try:
            status, _, data = signed_request(cfg, "PUT", key, body, content_type=content_type,
                                             timeout=min(60, max(5, deadline - time.time())))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            detail = f"network: {type(exc).__name__}"
            continue
        if 200 <= status < 300:
            return True, "stored"
        detail = f"http {status} {s3_code(data)}".strip()
        if status != 429 and status < 500:
            break
    return False, detail


# ---------- scrubbing ----------

def secret_values(env: dict | None = None) -> list[str]:
    """Every secret value in the environment, longest first: the named keys, and any variable whose
    name has a word like KEY, SECRET or TOKEN and whose value looks like a credential (16 or more
    characters with a letter and a digit, no spaces, not a path)."""
    env = os.environ if env is None else env
    found = {env[n] for n in dslib.SECRET_ENV if len(env.get(n, "")) >= 4}
    try:  # the App key is also hidden as the PEM it decodes to, and as each of its lines
        pem = dslib.decode_app_key(env.get("DS_REVIEWER_APP_KEY") or "")
        found |= {pem.strip(), *(l for l in pem.splitlines() if len(l) >= 16)}
    except dslib.ReviewerAppError:
        pass
    for name, value in env.items():
        if SECRET_WORDS & set(name.upper().split("_")) and len(value) >= 16 and not re.search(r"\s", value) \
                and re.search(r"\d", value) and re.search(r"[A-Za-z]", value) and not value.startswith(("/", ".", "~")):
            found.add(value)
    return sorted(found, key=len, reverse=True)


def scrub_bytes(data: bytes, values: list[str]) -> tuple[bytes, int]:
    """(data with every secret replaced, how many replacements). A value is also matched as JSON
    escaped text, because that is how it sits inside a transcript line."""
    text, hits = data.decode("utf-8", "surrogateescape"), 0
    for value in values:
        for form in {value, json.dumps(value)[1:-1]}:
            hits += text.count(form)
            text = text.replace(form, MASK)
    for pattern in dslib.SECRETS:
        text, n = pattern.subn(MASK, text)
        hits += n
    return text.encode("utf-8", "surrogateescape"), hits


# ---------- the bundle ----------

def bundle_prefix(run: dict, ctx: dict) -> str:
    started = re.sub(r"[-:]", "", run.get("started_at") or "") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = dslib.branch_slug(ctx["repo"]) if ctx.get("repo") else "unknown"
    return f"runs/{slug}/issue-{ctx['issue']}/{started}-{run.get('nonce') or 'run'}"


def transcript_name(t: dict) -> str:
    if not t.get("agent_id"):
        return "transcripts/lead.jsonl"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", f"{t.get('role') or 'agent'}-{t['agent_id']}")
    return f"transcripts/{safe}.jsonl"


def links(found: list[dict], run: dict, ctx: dict, events: list[dict]) -> dict:
    heads = []
    for e in events:
        sha = e.get("head_sha")
        if sha and sha not in heads:
            heads.append(sha)
    slug, issue, pr = ctx["repo"], ctx["issue"], ctx.get("pr")
    return {
        "repository": slug, "issue": issue, "issue_url": f"https://github.com/{slug}/issues/{issue}",
        "pr": pr, "pr_url": f"https://github.com/{slug}/pull/{pr}" if pr else None,
        "branch": ctx.get("branch"), "base_sha": run.get("base_sha"), "head_sha": dslib.git("rev-parse", "HEAD") or None,
        "head_shas": heads, "routine": run.get("routine"), "nonce": run.get("nonce"), "kit_tree": run.get("kit_tree"),
        "session_id": run.get("session_id"), "remote_session_id": run.get("remote_session_id"),
        "started_at": run.get("started_at"), "end_state": ctx.get("end_state"), "stop_reason": ctx.get("stop_reason"),
        "agents": [{"role": t["role"], "agent_id": t.get("agent_id"), "agent_type": t.get("agent_type"),
                    "file": transcript_name(t)} for t in found],
    }


def plan(found: list[dict], run: dict, ctx: dict, events: list[dict]) -> tuple[list[dict], list[str]]:
    """(objects to send, optional files that were not there). Small files first, so a short deadline
    still gets the record and the links across."""
    work, out, missing = dslib.work(), [], []

    def add(name: str, path: Path | None = None, data: bytes | None = None, optional: bool = False) -> None:
        if path is not None and not path.is_file():
            if optional:
                missing.append(name)
            else:
                out.append({"name": name, "error": "file not found"})
            return
        out.append({"name": name, "path": path, "data": data})

    add("record.json", work / "out" / "record.json")
    add("links.json", data=json.dumps(links(found, run, ctx, events), indent=2, sort_keys=True).encode())
    for name in ("notes.md", "spec.json", "claims.json"):
        add(name, work / name, optional=True)
    for folder in ("verdicts", "checks"):
        for p in sorted((work / folder).glob("*")) if (work / folder).is_dir() else []:
            add(f"{folder}/{p.name}", p)
    for t in found:
        add(transcript_name(t), t["path"])
    return out, missing


def upload_run(found: list[dict], run: dict, ctx: dict, events: list[dict], deadline: float,
               env: dict | None = None) -> dict:
    """Send the bundle if it is on, record the outcome in the ledger, return it:
    {status: ok | partial | failed | not_sent | off, prefix, objects, bytes, unchanged, failed, scrubbed, errors}.
    `objects` and `bytes` count what was sent now (the manifest included)."""
    cfg, why = config(env)
    if cfg is None:
        result = {"status": "not_sent" if why else "off", "errors": [why] if why else None}
    else:
        result = _upload(cfg, found, run, ctx, events, deadline, env)
    dslib.append_event("bundle.uploaded", status=result["status"], data={k: v for k, v in result.items() if k != "status"})
    return result


# ---------- the reviewer's verdict comment ----------

POST_SUFFIX = ".post.json"  # the bucket sends objects ending in this to the reviewer poster in AWS
POST_SCHEMA = "driftshield-reviewer-post.v1"


def post_key(run: dict, ctx: dict, round_no: int) -> str:
    return f"{bundle_prefix(run, ctx)}/reviewer/round-{round_no}{POST_SUFFIX}"


def queue_reviewer_post(run: dict, ctx: dict, round_no: int, head_sha: str | None, body: str,
                        env: dict | None = None, budget_s: float = 30) -> tuple[str | None, str | None]:
    """(key, None) once the verdict comment is in the run store for the reviewer poster to put on the PR
    as the reviewer's GitHub App, else (None, why not). Only when DS_REVIEWER_POST_VIA_STORE is 1, which is
    set once the poster is live: before that a queued comment would never reach GitHub. Never raises."""
    env = os.environ if env is None else env
    if env.get("DS_REVIEWER_POST_VIA_STORE") != "1":
        return None, "DS_REVIEWER_POST_VIA_STORE is not 1"
    cfg, why = config(env)
    if cfg is None:
        return None, why or "the run store is off"
    try:
        key = post_key(run, ctx, round_no)
        doc = {"schema": POST_SCHEMA, "repository": ctx["repo"], "issue": ctx["issue"], "pr": ctx["pr"],
               "branch": ctx["branch"], "round": round_no, "head_sha": head_sha, "body": body}
        data, _ = scrub_bytes(json.dumps(doc, indent=2).encode(), secret_values(env))
        stored, detail = put_object(cfg, key, data, time.time() + budget_s, TYPES[".json"])
    except Exception as exc:  # the hook must never fail on this
        return None, f"unexpected {type(exc).__name__}"
    return (key, None) if stored else (None, detail[:200])


def _upload(cfg: dict, found: list[dict], run: dict, ctx: dict, events: list[dict], deadline: float,
            env: dict | None) -> dict:
    values, prefix = secret_values(env), bundle_prefix(run, ctx)
    with dslib.state("state.json") as st:
        sent = dict(st.get("bundle_sent") or {})
    objects, missing = plan(found, run, ctx, events)
    totals = {"objects": 0, "bytes": 0, "unchanged": 0, "failed": 0, "scrubbed": 0}
    errors, manifest = [], []

    def send(name: str, data: bytes) -> None:
        digest = dslib.sha256(data)
        manifest.append({"name": name, "bytes": len(data), "sha256": digest})
        key = f"{prefix}/{name}"
        if sent.get(key) == digest:
            totals["unchanged"] += 1
            return
        stored, detail = put_object(cfg, key, data, deadline, TYPES.get(Path(name).suffix, "text/plain"))
        if stored:
            sent[key] = digest
            totals["objects"] += 1
            totals["bytes"] += len(data)
        else:
            totals["failed"] += 1
            errors.append(f"{name}: {detail}")

    for item in objects:
        if item.get("error"):
            totals["failed"] += 1
            errors.append(f"{item['name']}: {item['error']}")
            continue
        try:
            size = item["path"].stat().st_size if item.get("path") else 0
            if size > MAX_OBJECT_BYTES:
                raise ValueError("too large for one upload")
            raw = item["path"].read_bytes() if item.get("path") else item["data"]
        except (OSError, ValueError) as exc:
            totals["failed"] += 1
            errors.append(f"{item['name']}: {type(exc).__name__}")
            continue
        data, hits = scrub_bytes(raw, values)
        totals["scrubbed"] += hits
        send(item["name"], data)
    if not totals["failed"]:
        body = {"schema": "driftshield-delivery-run-bundle.v1", "prefix": prefix, "objects": manifest, "missing": missing}
        send("manifest.json", json.dumps(body, indent=2, sort_keys=True).encode())
    with dslib.state("state.json") as st:
        st["bundle_sent"] = sent
    arrived = totals["objects"] + totals["unchanged"]
    status = "ok" if not totals["failed"] else "partial" if arrived else "failed"
    return {"status": status, "prefix": prefix, **totals, "errors": sorted(set(errors))[:5] or None}
