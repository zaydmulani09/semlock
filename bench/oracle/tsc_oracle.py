"""tsc-backed oracle for TypeScript cases (ADR-0009).

Discovers tsc (env override > repo-local node_modules > PATH), runs it with
--noEmit --pretty false over a generated tsconfig rooted at the materialized state,
and attributes diagnostics to conflict classes by TS diagnostic code. S3 flagged TS
resolution as weaker than Python's; this oracle quantifies that independently.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from bench.oracle.base import CheckerUnavailable, Oracle, SiteError

REPO_ROOT = Path(__file__).resolve().parents[2]

_TSC_LINE = re.compile(
    r"^(?P<path>[^\(]+)\((?P<line>\d+),(?P<col>\d+)\):"
    r" (?P<kind>error|warning) (?P<code>TS\d+): (?P<msg>.*)$"
)

# tsc diagnostic codes compatible with each conflict class. Conservative sets:
# anything not listed must fall through to INCONCLUSIVE, never a forced verdict.
_CLASS_CODES: dict[str, frozenset[str]] = {
    "signature_changed": frozenset(
        {
            "TS2554",  # expected N arguments, but got M
            "TS2345",  # argument of type X not assignable to parameter
            "TS2339",  # property does not exist (renamed parameter object shape)
        }
    ),
    "removed_export": frozenset(
        {"TS2305", "TS2724", "TS2304", "TS2307"}
    ),
    "field_removed": frozenset({"TS2339"}),
    "return_changed": frozenset(
        {
            "TS2339",  # member access on old return type
            "TS2345",
            "TS2322",  # old-return value assigned to narrower typed target
            "TS2531",  # object is possibly null after narrowing change
            "TS2532",
            "TS7053",  # element implicitly any / index signature mismatch
        }
    ),
}


def discover_tsc(explicit: str | None = None) -> list[str]:
    """Resolution order: explicit arg > SEMLOCK_TSC env > repo-local
    node_modules > PATH. Returns an argv prefix (node/cmd wrappers included).
    Raises CheckerUnavailable when nothing usable is found."""
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    env_bin = os.environ.get("SEMLOCK_TSC")
    if env_bin:
        candidates.append(env_bin)
    for cwd in (Path.cwd(), REPO_ROOT):
        local = cwd / "node_modules" / "typescript" / "bin" / "tsc"
        if local.is_file():
            candidates.append(str(local))
    which = shutil.which("tsc")
    if which:
        candidates.append(which)
    node = shutil.which("node")
    for cand in candidates:
        path = Path(cand)
        if not (path.is_file() or shutil.which(cand)):
            continue
        suffix = path.suffix.lower()
        if suffix == ".js":
            if node:
                return [node, cand]
            continue
        # Extensionless "bin/tsc" is a `#!/usr/bin/env node` shim whose real
        # entrypoint lives beside it (lib/tsc.js); prefer the JS directly.
        js = path.parent.parent / "lib" / "tsc.js"
        if suffix == "" and js.is_file() and node:
            return [node, str(js)]
        if suffix in (".cmd", ".bat"):
            return ["cmd", "/c", cand]
        return [cand]
    raise CheckerUnavailable(
        "tsc not found; install typescript locally or set SEMLOCK_TSC "
        "(a node wrapper is used automatically when only bin/tsc exists)"
    )


def _parse_diagnostics(output: str) -> list[SiteError]:
    """Parse tsc's `path(line,col): error TSxxxx: message` lines.

    Paths are anchored to the checker cwd by the caller via SiteError.path
    normalization here: tsc prints paths relative to --project root.
    """
    errors: list[SiteError] = []
    for raw_line in output.splitlines():
        m = _TSC_LINE.match(raw_line.strip())
        if m is None or m.group("kind") != "error":
            continue
        rel = m.group("path").strip().replace("\\", "/")
        if rel.startswith("./"):
            rel = rel[2:]
        errors.append(
            SiteError(
                path=rel,
                line=int(m.group("line")),
                column=int(m.group("col")),
                code=m.group("code"),
                message=re.sub(r"\s+", " ", m.group("msg")).strip(),
            )
        )
    return errors


class TscOracle(Oracle):
    tool_name = "tsc"

    def __init__(self, tsc_bin: str | None = None) -> None:
        self._argv0 = discover_tsc(tsc_bin)

    def version_argv(self) -> list[str]:
        """argv prefix that runs the discovered checker (for --version)."""
        return list(self._argv0)

    def check_state(self, state_dir: Path) -> tuple[SiteError, ...]:
        tsconfig = _write_tsconfig(state_dir)
        proc = subprocess.run(
            [
                *self._argv0,
                "--noEmit",
                "--pretty",
                "false",
                "--project",
                str(tsconfig),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(state_dir),
            check=False,
            timeout=600,
        )
        # Exit-code conventions differ across tsc majors (2 vs 1 for
        # diagnostics). Trust parseable file-anchored output instead: if any
        # diagnostic line parses, the run succeeded regardless of rc; a run
        # with NO parseable diagnostics and nonzero rc is fatal/config error.
        parsed = _parse_diagnostics(proc.stdout + "\n" + proc.stderr)
        if proc.returncode == 0:
            return tuple(parsed)
        if parsed:
            return tuple(parsed)
        raise CheckerUnavailable(
            f"tsc exited {proc.returncode} with no parsable diagnostics: "
            f"{(proc.stdout + proc.stderr)[:2000]}"
        )

    def error_matches_class(self, error: SiteError, conflict_class: str) -> bool:
        codes = _CLASS_CODES.get(conflict_class, frozenset())
        return error.code in codes


def _write_tsconfig(state_dir: Path) -> Path:
    """Deterministic strict-project tsconfig; written fresh per run (no drift).

    Deliberately does NOT pin moduleResolution: TS5 defaults it sensibly for
    module=commonjs and TS6 removed the old name outright. Fixture specifiers
    are extensionless relative paths, valid under both.
    """
    config = {
        "compilerOptions": {
            "strict": True,
            "noEmit": True,
            "module": "commonjs",
            "target": "es2020",
            "skipLibCheck": True,
            "types": [],
            "rootDir": ".",
        },
        "include": ["**/*.ts", "**/*.tsx"],
        "exclude": ["node_modules", ".mypy_bench_cache"],
    }
    out = state_dir / "tsconfig.semlock_bench.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return out
