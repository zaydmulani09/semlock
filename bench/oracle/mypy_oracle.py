"""mypy-backed oracle for Python cases (ADR-0009).

Runs mypy over a materialized state directory with a hermetic, deterministic
configuration (no cache reuse, no config inheritance, stable flags), parses its
stdout into SiteErrors, and attributes diagnostics to conflict classes by error
code + message pattern. Attribution lists are deliberately conservative; anything
not confidently attributable yields INCONCLUSIVE upstream, never a forced verdict.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from bench.oracle.base import CheckerUnavailable, Oracle, SiteError

_MYPY_LINE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):(?: (?P<col>\d+):)?"
    r" (?P<kind>error|note): (?P<msg>.*?)(?:  \[(?P<code>[\w-]+)\])?$"
)

# mypy error codes compatible with each conflict class. Kept narrow on purpose.
_CLASS_CODES: dict[str, frozenset[str]] = {
    "signature_changed": frozenset(
        {
            "call-arg",  # missing/unexpected keyword or positional args
            "arg-type",
            "no-untyped-call",
        }
    ),
    "removed_export": frozenset(
        {"attr-defined", "name-defined", "import", "import-untyped"}
    ),
    "field_removed": frozenset({"attr-defined"}),
    "return_changed": frozenset(
        {
            "attr-defined",  # consumer calls a member on the old return type
            "union-attr",
            "arg-type",  # old return value passed where the new type fails
            "assignment",
            "return-value",
            "index",
            "operator",
        }
    ),
}

# Message fallbacks for codes that are too generic alone ("misc").
_CLASS_MESSAGE_PATTERNS: dict[str, tuple[str, ...]] = {
    "signature_changed": (
        r"too many arguments",
        r"missing positional argument",
        r"unexpected keyword argument",
        r"missing a required argument",
        r"multiple values for argument",
        r"no overload variant of .* matches argument types",
    ),
    "removed_export": (
        r"module .* has no attribute",
        r"name .+ is not defined",
        r"cannot import name",
    ),
    "field_removed": (
        r"has no attribute",
    ),
    "return_changed": (),
}


class MypyOracle(Oracle):
    tool_name = "mypy"

    def __init__(self, mypy_bin: str | None = None) -> None:
        # Default: current interpreter's mypy module (works inside venvs where
        # the Scripts dir is not on PATH). Override with explicit bin or
        # SEMLOCK_MYPY for out-of-environment checkers.
        if mypy_bin or os.environ.get("SEMLOCK_MYPY"):
            self._argv0 = [mypy_bin or os.environ["SEMLOCK_MYPY"]]
        else:
            self._argv0 = [sys.executable, "-m", "mypy"]

    def check_state(self, state_dir: Path) -> tuple[SiteError, ...]:
        cmd = [
            *self._argv0,
            "--no-error-summary",
            "--hide-error-context",
            "--no-pretty",
            "--show-error-codes",
            "--no-incremental",
            "--cache-dir",
            str(state_dir / ".mypy_bench_cache"),
            "--follow-imports",
            "normal",
            "--explicit-package-bases",
            "--namespace-packages",
            str(state_dir),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_hermetic_env(),
            cwd=str(state_dir),
            check=False,
            timeout=600,
        )
        if proc.returncode not in (0, 1):
            raise CheckerUnavailable(
                f"mypy exited {proc.returncode}: {proc.stderr[:2000]}"
            )
        errors: list[SiteError] = []
        root = state_dir.resolve()
        for raw_line in proc.stdout.splitlines():
            m = _MYPY_LINE.match(raw_line.strip())
            if m is None or m.group("kind") != "error":
                continue
            raw_path = Path(m.group("path"))
            # mypy prints paths relative to its cwd (== state_dir); never let
            # them resolve against this process's cwd.
            path = raw_path if raw_path.is_absolute() else root / raw_path
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                rel = path.as_posix()
            errors.append(
                SiteError(
                    path=rel,
                    line=int(m.group("line")),
                    column=int(m.group("col") or 0),
                    code=m.group("code") or "",
                    message=re.sub(r"\s+", " ", m.group("msg")).strip(),
                )
            )
        return tuple(errors)

    def error_matches_class(self, error: SiteError, conflict_class: str) -> bool:
        codes = _CLASS_CODES.get(conflict_class, frozenset())
        if error.code and error.code in codes:
            return True
        if error.code in ("misc", ""):
            patterns = _CLASS_MESSAGE_PATTERNS.get(conflict_class, ())
            return any(re.search(p, error.message) for p in patterns)
        return False


def _hermetic_env() -> dict[str, str]:
    """Neutralize machine config so grading cannot drift between environments."""
    import os

    env = dict(os.environ)
    for var in ("MYPY_CONFIG_FILE", "MYPYPATH", "PYTHONPATH", "PYTHONSTARTUP"):
        env.pop(var, None)
    return env
