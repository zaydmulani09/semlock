"""Verify one mined-pair fn_candidate against the two falsification tests
used throughout tests/fixtures/real/candidates.md:

1. A-alone: does the error already exist in `base + side_a` alone (no B)?
   If yes, it's the provider's own pre-existing/self-inconsistent issue
   (ADR-0009 fp_a_self_inconsistent territory), not a break caused by B
   depending on the old surface — reject.
2. Real-merge: bench.synth.materialize_case()'s "merged" state overlays
   side_a then side_b as whole-file copies onto base. When BOTH sides touch
   the same file, whichever side was copied last wins entirely for that
   file — not a real 3-way text merge, and can fabricate or hide errors a
   real `git merge` would not produce. This test rebuilds the TRUE merged
   tree via `git merge-tree --write-tree --merge-base=<mb> <a-head> <b-head>`
   against the real clone and re-checks the error there.

Usage:
    python -m bench.real_recall.verify_candidate \\
        --case-dir <mined case dir, e.g. .../cases/pydantic-pydantic-12147x12333> \\
        --language python \\
        --grep "json_schema.py:426"

    # Real-merge test additionally needs the clone + raw SHAs (from meta.json):
    python -m bench.real_recall.verify_candidate \\
        --case-dir <case dir> --language python --grep "_client.py" \\
        --clone <path to the repo's local clone> --real-merge

Prints PASS (error not found — real, not an A-alone artifact) or FAIL
(error found — reject as A-alone) for the A-alone test; and for --real-merge,
prints the true merged tree's matching lines (empty = the naive overlay's
finding does not survive a real merge).
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

_TSCONFIG = {
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


def _run_checker(state_dir: Path, language: str, tsc_bin: str | None) -> str:
    if language == "python":
        proc = subprocess.run(
            [
                sys.executable, "-m", "mypy",
                "--no-error-summary", "--hide-error-context", "--no-pretty",
                "--show-error-codes", "--no-incremental",
                "--follow-imports", "normal", "--explicit-package-bases",
                "--namespace-packages", str(state_dir),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(state_dir), check=False, timeout=600,
        )
        return proc.stdout + proc.stderr
    if language == "typescript":
        (state_dir / "tsconfig.semlock_bench.json").write_text(
            json.dumps(_TSCONFIG, indent=2) + "\n", encoding="utf-8"
        )
        argv = [tsc_bin] if tsc_bin else ["tsc"]
        proc = subprocess.run(
            [*argv, "--noEmit", "--pretty", "false",
             "--project", "tsconfig.semlock_bench.json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(state_dir), check=False, timeout=600,
        )
        return proc.stdout + proc.stderr
    raise ValueError(f"unsupported language {language!r}")


def a_alone_test(case_dir: Path, language: str, grep: str, tsc_bin: str | None) -> bool:
    """True (PASS) if `grep` does NOT appear when checking base+side_a alone."""
    states = case_dir / "states"
    with tempfile.TemporaryDirectory(prefix="a-alone-") as tmp:
        dest = Path(tmp)
        shutil.copytree(states / "base", dest, dirs_exist_ok=True)
        shutil.copytree(states / "side_a", dest, dirs_exist_ok=True)
        output = _run_checker(dest, language, tsc_bin)
    found = grep in output
    return not found


def _archive(clone: Path, sha: str, module_dirs: list[str], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    args = ["archive", sha, *module_dirs] if module_dirs else ["archive", sha]
    proc = subprocess.run(["git", *args], cwd=clone, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            tar.extractall(dest)


def real_merge_test(
    clone: Path, merge_base: str, a_head: str, b_head: str,
    module_dirs: list[str], language: str, grep: str, tsc_bin: str | None,
) -> str:
    """Rebuild the TRUE merged tree via git merge-tree and check it for `grep`.
    Returns the matching output lines (empty string = grep not found)."""
    proc = subprocess.run(
        ["git", "merge-tree", "--write-tree", f"--merge-base={merge_base}",
         a_head, b_head],
        cwd=clone, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"merge-tree failed/conflicted:\n{proc.stdout}\n{proc.stderr}"
        )
    tree = proc.stdout.splitlines()[0].strip()
    with tempfile.TemporaryDirectory(prefix="real-merge-") as tmp:
        dest = Path(tmp)
        _archive(clone, tree, module_dirs, dest)
        output = _run_checker(dest, language, tsc_bin)
    return "\n".join(line for line in output.splitlines() if grep in line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--language", required=True, choices=("python", "typescript"))
    parser.add_argument("--grep", required=True, help="substring identifying the error")
    parser.add_argument("--tsc-bin", default=None)
    parser.add_argument("--real-merge", action="store_true")
    parser.add_argument("--clone", default=None, help="repo clone (for --real-merge)")
    parser.add_argument("--merge-base", default=None)
    parser.add_argument("--a-head", default=None)
    parser.add_argument("--b-head", default=None)
    parser.add_argument("--module-dirs", nargs="*", default=[])
    args = parser.parse_args()

    case_dir = Path(args.case_dir)
    passed = a_alone_test(case_dir, args.language, args.grep, args.tsc_bin)
    verdict = (
        "PASS (not a self-inconsistency artifact)"
        if passed
        else "FAIL (reject: reproduces with no B present)"
    )
    print(f"A-alone test: {verdict}")

    if args.real_merge:
        if not (args.clone and args.merge_base and args.a_head and args.b_head):
            parser.error("--real-merge requires --clone --merge-base --a-head --b-head")
        matches = real_merge_test(
            Path(args.clone), args.merge_base, args.a_head, args.b_head,
            args.module_dirs, args.language, args.grep, args.tsc_bin,
        )
        if matches:
            print("Real-merge test: FOUND in true merged tree:")
            print(matches)
        else:
            print("Real-merge test: NOT FOUND (reject: naive overlay artifact)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
