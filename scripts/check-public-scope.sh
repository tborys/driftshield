#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[public-scope] Checking tracked files for public-OSS boundary leaks"

python3 - <<'PY'
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()

# Exact private boundary markers are stored as hashes so this public repo can
# enforce the boundary without spelling out private names in source.
FORBIDDEN_HASHES = {
    "3a26e7f9b31c8b0e319214a04f7d967e5cefb35a6f14e1514ba7e8d6f38a1fcf",
    "9a70e567af76c29e3aa02d5d80301b52bbd5471ad185d9d5c8fba6242cc4f89b",
    "b2556c2ab49345b87a84b45dbc5b46119a5f30a2144cc57cb6995cd08a6175b3",
    "de3462d28672fb71b8141792c7c9929af24c87d02e5182509784da9e2b1c6fbf",
    "d8862b2539e51b1366c2f037be75cdd861ac93491314f0d19b276dc15b622862",
    "2fad45d66945a9bc873cbfe965e25b353a666dce6a32d870a1d808bd1d11b071",
    "8bb60789953d112a8f1eadab1a47f6bdfdb13c3aade5fae6d4d3d06878cb37a9",
    "9624dd0b7270b612a084db7c5c71e8aa5fa29882dba5ad80baad9f8875dd187a",
    "ff088fe5a664240bef5b6a9f2677805090c0bc47f8794e92a4289e1574119091",
    "49f80436dd25131ab7d63287cbb11ba86dd0acd1b8917dcaf3cee8f5cd6cfbb1",
    "0a2887afea9dbc29b575c732a6ccb005da6a6d5a9b13e17d7ff131583423019e",
    "6ee47b4625f23fbffcff6d428846b4f3b0c5393c37cf2aaacae64ed0860816ad",
    "dcd833d938b15c60a45b26d983673200aaf8c75d892e0c15a8c412e9971f331f",
    "8ecc724ceadc844339e5fdcaa73aa1927fcea59ccd8f66a54f494ebde2bd5408",
    "086d0cdd70a747d37a6d145fbec5a051d06882663f7d98ca190bfa6536efaae8",
    "6a3df8cb9431a676c336c01966394610e62e3f6cbbddb55bbb7805cbd12ef4d2",
}

TOKEN_RE = re.compile(r"[A-Za-z0-9._:/-]+")
PUBLIC_REPO_BASES = (
    "tborys/driftshield",
    "github.com/tborys/driftshield",
    "https://github.com/tborys/driftshield",
    "http://github.com/tborys/driftshield",
    "git@github.com:tborys/driftshield",
    "ssh://git@github.com/tborys/driftshield",
)
SAME_OWNER_PREFIXES = (
    "tborys/",
    "github.com/tborys/",
    "https://github.com/tborys/",
    "http://github.com/tborys/",
    "git@github.com:tborys/",
    "ssh://git@github.com/tborys/",
)
EXCLUDED_FILES = {
    "scripts/check-public-scope.sh",
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_repo_reference(token: str, base: str) -> bool:
    if token == base or token.startswith(base + ".git"):
        return True

    return any(token.startswith(base + separator) for separator in ("/", ":", "?", "#"))


def is_public_repo_reference(token: str) -> bool:
    return any(is_repo_reference(token, base) for base in PUBLIC_REPO_BASES)


tracked_files = subprocess.run(
    ["git", "ls-files"],
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()

violations: list[tuple[str, int, str]] = []

for rel_path in tracked_files:
    if rel_path in EXCLUDED_FILES:
        continue

    path = ROOT / rel_path
    if not path.exists():
        continue

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue

    for lineno, line in enumerate(text.splitlines(), start=1):
        line_findings: set[str] = set()

        for token in TOKEN_RE.findall(line):
            if is_public_repo_reference(token):
                continue

            if sha256(token) in FORBIDDEN_HASHES:
                line_findings.add("private boundary marker")
                continue

            if token.startswith(SAME_OWNER_PREFIXES):
                line_findings.add("unexpected same-owner repo reference")

        for finding in sorted(line_findings):
            violations.append((rel_path, lineno, finding))

if violations:
    for rel_path, lineno, finding in violations:
        print(f"{rel_path}:{lineno}: {finding}")
    print()
    print("[public-scope] Found public-OSS boundary leaks.")
    print("[public-scope] Remove private sibling or planning references before merging.")
    sys.exit(1)

print("[public-scope] OK")
PY
