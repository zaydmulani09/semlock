"""Deterministic synthetic two-branch cases (S6-owned).

Builds materialized case directories WITHOUT network, git history, or wall-clock
input, so oracle validation and determinism tests are reproducible byte-for-byte.

Case directory contract (generated into a workdir, not committed):

    <workdir>/cases/<case_id>/meta.json
    <workdir>/cases/<case_id>/states/base/...      # common ancestor
    <workdir>/cases/<case_id>/states/side_a/...    # delta: changed symbol surface
    <workdir>/cases/<case_id>/states/side_b/...    # delta: depends on OLD surface

Merged state      = overlay(base, side_a, side_b)
Counterfactual    = overlay(base, side_b)          # side B without A's change

`expectation` blocks exist ONLY in synthetic metas, to validate that checkers flag
the planted breaks at the predicted sites. They are never used to grade mined
corpus cases and never substitute for SEMLock labels.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADVERSARIAL_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "adversarial"


@dataclass(frozen=True, slots=True)
class PlantedRef:
    """The use-site SEMLock would (or should) flag; plumbing-only until S5."""

    conflict_class: str
    symbol_id: str
    ref_path: str
    anchor: str  # unique token identifying the ref line in side_b content


@dataclass(frozen=True, slots=True)
class SyntheticCase:
    case_id: str
    language: str  # python | typescript
    description: str
    base: dict[str, str]  # relpath ("/") -> content
    side_a: dict[str, str]
    side_b: dict[str, str]
    planted: tuple[PlantedRef, ...]
    expectation: dict[str, str]  # prediction_id -> Verdict value
    notes: str = ""


PY_MODELS_BASE = '''\
class GreetingResult:
    def __init__(self, text: str) -> None:
        self.text = text


class User:
    def __init__(self, email: str | None = None) -> None:
        self.email = email

    def greet(self, name: str) -> str:
        return f"Hello, {name}"

    def shout(self, text: str) -> str:
        return text.upper()


def format_greeting(user: User) -> str:
    return user.greet(name=user.email or "user")
'''

PY_APP_SIGNATURE = '''\
from pkg.models import User


def welcome(user: User) -> str:
    message = user.greet(name="Ada")
    return message.upper()
'''

PY_APP_FIELD = '''\
from pkg.models import User


def profile(user: User) -> str:
    email_ref = user.email
    return f"{user.greet(name='Ada')} <{email_ref}>"
'''

PY_APP_RETURN = '''\
from pkg.models import User


def banner(user: User) -> int:
    shout = user.greet(name="Ada").upper()
    return len(shout)
'''

PY_APP_IMPORT = '''\
from pkg.models import format_greeting, User


def welcome(user: User) -> str:
    return format_greeting(user)
'''

# Side-A deltas (each replaces pkg/models.py wholesale). Explicit literals —
# never string surgery, so every state is valid Python on inspection.
PY_MODELS_PARAM_RENAMED = '''\
class GreetingResult:
    def __init__(self, text: str) -> None:
        self.text = text


class User:
    def __init__(self, email: str | None = None) -> None:
        self.email = email

    def greet(self, greeting: str) -> str:
        return f"Hello, {greeting}"

    def shout(self, text: str) -> str:
        return text.upper()


def format_greeting(user: User) -> str:
    return user.greet(name=user.email or "user")
'''

PY_MODELS_FIELD_REMOVED = '''\
class GreetingResult:
    def __init__(self, text: str) -> None:
        self.text = text


class User:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"

    def shout(self, text: str) -> str:
        return text.upper()


def format_greeting(user: User) -> str:
    return user.greet(name="user")
'''

PY_MODELS_RETURN_CHANGED = '''\
class GreetingResult:
    def __init__(self, text: str) -> None:
        self.text = text


class User:
    def __init__(self, email: str | None = None) -> None:
        self.email = email

    def greet(self, name: str) -> "GreetingResult":
        return GreetingResult(f"Hello, {name}")

    def shout(self, text: str) -> str:
        return text.upper()


def format_greeting(user: User) -> str:
    return user.greet(name=user.email or "user").text
'''

PY_MODELS_EXPORT_REMOVED = '''\
class GreetingResult:
    def __init__(self, text: str) -> None:
        self.text = text


class User:
    def __init__(self, email: str | None = None) -> None:
        self.email = email

    def greet(self, name: str) -> str:
        return f"Hello, {name}"

    def shout(self, text: str) -> str:
        return text.upper()
'''

PY_MODELS_METHOD_ADDED = '''\
class GreetingResult:
    def __init__(self, text: str) -> None:
        self.text = text


class User:
    def __init__(self, email: str | None = None) -> None:
        self.email = email

    def greet(self, name: str) -> str:
        return f"Hello, {name}"

    def shout(self, text: str) -> str:
        return text.upper()

    def wave(self) -> str:
        return "o/"


def format_greeting(user: User) -> str:
    return user.greet(name=user.email or "user")
'''


def _line_of(text: str, needle: str) -> int:
    for idx, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return idx
    raise ValueError(f"anchor {needle!r} not found")


def _build_case_meta(case: SyntheticCase, out_dir: Path) -> None:
    predictions: list[dict[str, object]] = []
    expectation: dict[str, str] = {}
    for idx, planted in enumerate(case.planted):
        content = case.side_b[planted.ref_path]
        line = _line_of(content, planted.anchor)
        pred_id = f"{case.case_id}-p{idx}"
        predictions.append(
            {
                "prediction_id": pred_id,
                "conflict_class": planted.conflict_class,
                "symbol_id": planted.symbol_id,
                "ref_path": planted.ref_path,
                "ref_start_line": line,
                "ref_end_line": line,
                "resolution_status": "resolved",
            }
        )
        verdict = case.expectation.get(str(idx))
        if verdict is not None:
            expectation[pred_id] = verdict
    document = {
        "case_id": case.case_id,
        "language": case.language,
        "source": "synthetic",
        "description": case.description,
        "classes": sorted({p.conflict_class for p in case.planted}),
        "predictions": predictions,
        "expectation": expectation,
        "notes": case.notes,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def materialize_case(case_dir: Path) -> tuple[Path, Path]:
    """Return (merged_dir, counterfactual_dir), materialized under case_dir.

    Deterministic: fixed copy order, fresh directories each call.
    """
    states = case_dir / "states"
    merged = case_dir / "merged"
    counterfactual = case_dir / "counterfactual"
    for out in (merged, counterfactual):
        if out.exists():
            shutil.rmtree(out)
    shutil.copytree(states / "base", merged)
    for layer in ("side_a", "side_b"):
        shutil.copytree(states / layer, merged, dirs_exist_ok=True)
    shutil.copytree(states / "base", counterfactual)
    shutil.copytree(states / "side_b", counterfactual, dirs_exist_ok=True)
    return merged, counterfactual


def write_case(workdir: Path, case: SyntheticCase) -> Path:
    case_dir = workdir / "cases" / case.case_id
    states = case_dir / "states"
    for name, layer in (
        ("base", case.base),
        ("side_a", case.side_a),
        ("side_b", case.side_b),
    ):
        layer_dir = states / name
        for rel, content in layer.items():
            path = layer_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    _build_case_meta(case, case_dir)
    return case_dir


def builtin_cases() -> tuple[SyntheticCase, ...]:
    """All four classes x both languages, plus clean-merge true negatives."""
    py_pkg = "pkg/models.py"
    cases: list[SyntheticCase] = []

    def py_case(
        case_id: str,
        description: str,
        models_delta: str,
        app: str,
        anchor: str,
        conflict_class: str,
        symbol_id: str,
        verdict: str,
        notes: str = "",
    ) -> SyntheticCase:
        side_b = {"pkg/app.py": app}
        return SyntheticCase(
            case_id=case_id,
            language="python",
            description=description,
            base={"pkg/models.py": PY_MODELS_BASE},
            side_a={py_pkg: models_delta},
            side_b=side_b,
            planted=(
                PlantedRef(
                    conflict_class=conflict_class,
                    symbol_id=symbol_id,
                    ref_path="pkg/app.py",
                    anchor=anchor,
                ),
            ),
            expectation={"0": verdict},
            notes=notes,
        )

    cases.append(
        py_case(
            "py-signature-changed",
            "callee renames greet parameter; keyword caller breaks.",
            PY_MODELS_PARAM_RENAMED,
            PY_APP_SIGNATURE,
            'user.greet(name="Ada")',
            "signature_changed",
            "pkg.models::User.greet",
            "true_positive",
        )
    )
    cases.append(
        py_case(
            "py-field-removed",
            "User.email attribute removed; reader breaks.",
            PY_MODELS_FIELD_REMOVED,
            PY_APP_FIELD,
            "user.email",
            "field_removed",
            "pkg.models::User.email",
            "true_positive",
        )
    )
    cases.append(
        py_case(
            "py-return-changed",
            "greet declared return becomes GreetingResult; member chain breaks.",
            PY_MODELS_RETURN_CHANGED,
            PY_APP_RETURN,
            'user.greet(name="Ada").upper()',
            "return_changed",
            "pkg.models::User.greet",
            "true_positive",
        )
    )
    cases.append(
        py_case(
            "py-removed-export",
            "format_greeting deleted; importer breaks at import line.",
            PY_MODELS_EXPORT_REMOVED,
            PY_APP_IMPORT,
            "from pkg.models import format_greeting",
            "removed_export",
            "pkg.models::format_greeting",
            "true_positive",
        )
    )
    cases.append(
        SyntheticCase(
            case_id="py-clean-merge",
            language="python",
            description=(
                "Side A adds a new method only; side B untouched old surface."
            ),
            base={"pkg/models.py": PY_MODELS_BASE},
            side_a={py_pkg: PY_MODELS_METHOD_ADDED},
            side_b={"pkg/app.py": PY_APP_SIGNATURE},
            planted=(),
            expectation={},
            notes="true-negative seed: scan_breaks must stay empty",
        )
    )
    cases.extend(_ts_cases())
    return tuple(cases)


TS_USER_BASE = '''\
export interface GreetingResult {
    text: string;
}

export class User {
    email: string | null = null;

    greet(name: string): string {
        return `Hello, ${name}`;
    }

    shout(text: string): string {
        return text.toUpperCase();
    }
}

export function formatGreeting(user: User): string {
    return user.greet(user.email ?? "user");
}
'''

TS_APP_SIGNATURE = '''\
import { User } from "./models/user";

export function welcome(u: User): string {
    const message = u.greet("Ada");
    return message.toUpperCase();
}
'''

TS_APP_FIELD = '''\
import { User } from "./models/user";

export function profile(u: User): string {
    const emailRef = u.email;
    return `${u.greet("Ada")} <${String(emailRef)}>`;
}
'''

TS_APP_RETURN = '''\
import { User } from "./models/user";

export function banner(u: User): number {
    const shout = u.greet("Ada").toUpperCase();
    return shout.length;
}
'''

TS_APP_IMPORT = '''\
import { formatGreeting, User } from "./models/user";

export function welcome(u: User): string {
    return formatGreeting(u);
}
'''

# Side-A deltas: explicit literals (string surgery silently no-ops on a
# mismatched anchor, which would turn a planted break into a false clean merge).
TS_MODELS_PARAM_WIDENED = '''\
export interface GreetingResult {
    text: string;
}

export class User {
    email: string | null = null;

    greet(greeting: string, punct: string): string {
        return `Hello, ${greeting}${punct}`;
    }

    shout(text: string): string {
        return text.toUpperCase();
    }
}

export function formatGreeting(user: User): string {
    return user.greet(user.email ?? "user", "!");
}
'''

TS_MODELS_FIELD_REMOVED = '''\
export interface GreetingResult {
    text: string;
}

export class User {
    greet(name: string): string {
        return `Hello, ${name}`;
    }

    shout(text: string): string {
        return text.toUpperCase();
    }
}

export function formatGreeting(user: User): string {
    return user.greet("user");
}
'''

TS_MODELS_RETURN_CHANGED = '''\
export interface GreetingResult {
    text: string;
}

export class User {
    email: string | null = null;

    greet(name: string): GreetingResult {
        return { text: `Hello, ${name}` };
    }

    shout(text: string): string {
        return text.toUpperCase();
    }
}

export function formatGreeting(user: User): string {
    return user.greet(user.email ?? "user").text;
}
'''

TS_MODELS_EXPORT_REMOVED = '''\
export interface GreetingResult {
    text: string;
}

export class User {
    email: string | null = null;

    greet(name: string): string {
        return `Hello, ${name}`;
    }

    shout(text: string): string {
        return text.toUpperCase();
    }
}
'''

TS_MODELS_FN_ADDED = '''\
export interface GreetingResult {
    text: string;
}

export class User {
    email: string | null = null;

    greet(name: string): string {
        return `Hello, ${name}`;
    }

    shout(text: string): string {
        return text.toUpperCase();
    }
}

export function wave(): string {
    return 'o/';
}

export function formatGreeting(user: User): string {
    return user.greet(user.email ?? "user");
}
'''


def _ts_cases() -> tuple[SyntheticCase, ...]:
    def ts_case(
        case_id: str,
        description: str,
        models_delta: str,
        app: str,
        anchor: str,
        conflict_class: str,
        symbol_id: str,
        verdict: str,
    ) -> SyntheticCase:
        return SyntheticCase(
            case_id=case_id,
            language="typescript",
            description=description,
            base={"src/models/user.ts": TS_USER_BASE},
            side_a={"src/models/user.ts": models_delta},
            side_b={"src/app.ts": app},
            planted=(
                PlantedRef(
                    conflict_class=conflict_class,
                    symbol_id=symbol_id,
                    ref_path="src/app.ts",
                    anchor=anchor,
                ),
            ),
            expectation={"0": verdict},
        )

    return (
        ts_case(
            "ts-signature-changed",
            "greet gains required second parameter; single-arg caller breaks.",
            TS_MODELS_PARAM_WIDENED,
            TS_APP_SIGNATURE,
            'u.greet("Ada")',
            "signature_changed",
            "src/models::User.greet",
            "true_positive",
        ),
        ts_case(
            "ts-field-removed",
            "User.email deleted; reader breaks.",
            TS_MODELS_FIELD_REMOVED,
            TS_APP_FIELD,
            "u.email",
            "field_removed",
            "src/models::User.email",
            "true_positive",
        ),
        ts_case(
            "ts-return-changed",
            "greet returns GreetingResult; toUpperCase chain breaks.",
            TS_MODELS_RETURN_CHANGED,
            TS_APP_RETURN,
            'u.greet("Ada").toUpperCase()',
            "return_changed",
            "src/models::User.greet",
            "true_positive",
        ),
        ts_case(
            "ts-removed-export",
            "formatGreeting export deleted; importer breaks.",
            TS_MODELS_EXPORT_REMOVED,
            TS_APP_IMPORT,
            "import { formatGreeting",
            "removed_export",
            "src/models::formatGreeting",
            "true_positive",
        ),
        SyntheticCase(
            case_id="ts-clean-merge",
            language="typescript",
            description="Side A adds a function only; side B unaffected.",
            base={"src/models/user.ts": TS_USER_BASE},
            side_a={"src/models/user.ts": TS_MODELS_FN_ADDED},
            side_b={"src/app.ts": TS_APP_SIGNATURE},
            planted=(),
            expectation={},
            notes="true-negative seed: scan_breaks must stay empty",
        ),
    )


def write_all_builtin(workdir: Path) -> list[Path]:
    return [write_case(workdir, c) for c in builtin_cases()]
