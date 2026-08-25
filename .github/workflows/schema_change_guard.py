#!/usr/bin/env python3
"""Schema-change guard: edits to schema/** or semlock/ir/model.py require an
`IR-CHANGE-ADR:` line in the PR body referencing the ADR (docs/adr/NNNN-*.md).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

GUARDED = ("schema/", "semlock/ir/model.py")


def changed(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def main() -> int:
    base = os.environ.get("BASE", "HEAD~1")
    head = os.environ.get("HEAD", "HEAD")
    body = os.environ.get("PR_BODY", "")
    touched = [p for p in changed(base, head) if p.startswith(GUARDED)]
    if not touched:
        print("[schema-guard] no guarded paths touched.")
        return 0
    match = re.search(r"IR-CHANGE-ADR:\s*(docs/adr/\d[^ \t\n]*)", body)
    if match is None:
        print(
            "[schema-guard] FAIL: PR touches IR surface but PR body has no "
            "'IR-CHANGE-ADR: docs/adr/NNNN-...' line. Files:"
        )
        for p in touched:
            print(f"  - {p}")
        return 1
    adr = match.group(1).rstrip(".,);")
    listed = subprocess.run(
        ["git", "cat-file", "-e", f"{head}:{adr}"], capture_output=True
    ).returncode == 0
    if not listed:
        print(f"[schema-guard] FAIL: referenced ADR {adr!r} not found in tree.")
        return 1
    print(f"[schema-guard] OK: {adr} covers {len(touched)} guarded file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
