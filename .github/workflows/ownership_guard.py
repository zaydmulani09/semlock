#!/usr/bin/env python3
"""Ownership guard: fails a PR that edits paths outside the source branch's row.

Usage (CI): python ownership_guard.py --base <ref> --head <ref>
Reads ownership.yaml at repo root. Branches named session/N-* may only touch rows
with matching branch_prefix, plus common paths. Violations exit 1 with a report.
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

# stdlib-only YAML subset parser: ownership.yaml uses only nested maps/lists/strings.
try:
    import yaml  # type: ignore[import-untyped]
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def load_rows(repo: Path) -> tuple[list[dict], list[str]]:
    text = (repo / "ownership.yaml").read_text(encoding="utf-8")
    if _HAS_YAML:
        data = yaml.safe_load(text)
        return data["rows"], [str(p) for p in data.get("common", [])]
    return _parse_minimal(text)


def _parse_minimal(text: str) -> tuple[list[dict], list[str]]:
    """Indentation-light parser: keys are unique so content patterns suffice."""
    rows: list[dict] = []
    common: list[str] = []
    current_row: dict | None = None
    in_common = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        line = raw.strip()
        if line.startswith("- session:"):
            current_row = {"session": _unquote(line.split(":", 1)[1]), "paths": []}
            rows.append(current_row)
            in_common = False
        elif line == "common:":
            in_common = True
            current_row = None
        elif line.startswith("branch_prefix:") and current_row is not None:
            current_row["branch_prefix"] = _unquote(line.split(":", 1)[1])
        elif line.startswith("- "):
            val = _unquote(line[2:])
            if in_common:
                common.append(val)
            elif current_row is not None:
                current_row["paths"].append(val)
    return rows, common


def _unquote(s: str) -> str:
    s = s.strip()
    return s.strip('"').strip("'")


def changed_files(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def matches(path: str, pattern: str) -> bool:
    pat = pattern.rstrip("/")
    return (
        fnmatch.fnmatch(path, pat + "/*")
        or path == pattern
        or path.startswith(pattern)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[2]
    rows, common = load_rows(repo)
    head_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", args.head],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if not head_branch.startswith("session/"):
        print(
            f"[ownership] branch {head_branch!r} is not a session branch; "
            "allowing (main/admin)."
        )
        return 0
    prefix = head_branch.split("-", 1)[0] + "-"  # e.g. "session/1-"

    owned: list[str] = []
    for row in rows:
        if row["branch_prefix"] == prefix:
            owned = row["paths"]
            break
    if not owned:
        print(f"[ownership] no ownership row for {head_branch!r}; FAIL.")
        return 1

    violations = [
        p for p in changed_files(args.base, args.head)
        if not any(matches(p, pat) for pat in owned)
        and not any(matches(p, pat) for pat in common)
    ]
    if violations:
        print(f"[ownership] {head_branch} may only edit {owned} (+common). Violations:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"[ownership] OK: {head_branch} within its row.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
