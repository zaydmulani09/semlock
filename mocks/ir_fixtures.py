"""RESOLVED, schema-valid FileFacts fixtures (S1-owned mocks; build against these
until real extractors/resolvers land).

Seeded from the canonical `pkg.models::User.greet` example in docs/IR_CONTRACT.md §3.
All refs arrive PRE-resolved — these are post-Resolver artifacts. Ids use the ratified
0.2.0 grammar `<module_path>::<qualified_name>`; member access binds to the member's
own id `<module_path>::<Owner>.<member>` (ADR-0008).
"""
from __future__ import annotations

from semlock.ir.model import (
    FileFacts,
    Member,
    Param,
    Ref,
    Resolution,
    Signature,
    Span,
    Symbol,
)
from semlock.ir.version import FORMAT_VERSION

MAIN = "main"
SIDE_A = "feat/greeting-surface"
SIDE_B = "feat/app"


def _span(sl: int, sc: int, el: int, ec: int) -> Span:
    return Span(start_line=sl, start_col=sc, end_line=el, end_col=ec)


def _resolved(target: str) -> Resolution:
    return Resolution(status="resolved", target_id=target)


def canonical_example() -> FileFacts:
    """Exactly the JSON shown in docs/IR_CONTRACT.md §3."""
    return FileFacts(
        format_version=FORMAT_VERSION,
        path="pkg/models.py",
        language="python",
        ref="main",
        symbols=(
            Symbol(
                id="pkg.models::User.greet",
                name="greet",
                kind="method",
                span=_span(2, 4, 3, 30),
                exports=False,
                signature=Signature(
                    params=(
                        Param("self", 0, "positional", None, False),
                        Param("name", 1, "positional", "str", False),
                    ),
                    return_type="str",
                ),
            ),
        ),
        refs=(
            Ref(
                name="print",
                kind="call",
                span=_span(9, 4, 9, 15),
                resolution=Resolution(status="external"),
            ),
        ),
    )


def models_main(ref: str = MAIN) -> FileFacts:
    """pkg/models.py on main:

        3: class User:
        6:     email: str | None = None
        8:     def greet(self, name: str) -> str:
       11: def format_greeting(user: User) -> str:
    """
    return FileFacts(
        format_version=FORMAT_VERSION,
        path="pkg/models.py",
        language="python",
        ref=ref,
        symbols=(
            Symbol(
                id="pkg.models::User",
                name="User",
                kind="class",
                span=_span(3, 0, 12, 34),
                exports=True,
                members=(
                    Member("email", "str | None", _span(6, 4, 6, 27)),
                ),
            ),
            Symbol(
                id="pkg.models::User.greet",
                name="greet",
                kind="method",
                span=_span(8, 4, 9, 34),
                exports=False,
                signature=Signature(
                    params=(
                        Param("self", 0, "positional", None, False),
                        Param("name", 1, "positional", "str", False),
                    ),
                    return_type="str",
                ),
            ),
            Symbol(
                id="pkg.models::format_greeting",
                name="format_greeting",
                kind="function",
                span=_span(11, 0, 12, 34),
                exports=True,
                signature=Signature(
                    params=(Param("user", 0, "positional", "User", False),),
                    return_type="str",
                ),
            ),
        ),
        refs=(
            Ref(
                name="greet",
                kind="call",
                span=_span(12, 11, 12, 29),
                resolution=_resolved("pkg.models::User.greet"),
            ),
        ),
    )


def app_consumer(ref: str = SIDE_B) -> FileFacts:
    """pkg/app.py on side B — consumes the OLD surface of pkg.models.

        1: from pkg.models import User, format_greeting
        3: def welcome(user: User) -> str:
        4:     message = user.greet(name="Ada")
        5:     footer = format_greeting(user)
        6:     email_ref = user.email
    """
    return FileFacts(
        format_version=FORMAT_VERSION,
        path="pkg/app.py",
        language="python",
        ref=ref,
        symbols=(
            Symbol(
                id="pkg.app::welcome",
                name="welcome",
                kind="function",
                span=_span(3, 0, 6, 41),
                exports=True,
                signature=Signature(
                    params=(Param("user", 0, "positional", "User", False),),
                    return_type="str",
                ),
            ),
        ),
        refs=(
            Ref(
                name="User",
                kind="import",
                span=_span(1, 20, 1, 24),
                resolution=_resolved("pkg.models::User"),
                module_specifier="pkg.models",
            ),
            Ref(
                name="format_greeting",
                kind="import",
                span=_span(1, 26, 1, 41),
                resolution=_resolved("pkg.models::format_greeting"),
                module_specifier="pkg.models",
            ),
            Ref(
                name="greet",
                kind="call",
                span=_span(4, 14, 4, 33),
                resolution=_resolved("pkg.models::User.greet"),
            ),
            Ref(
                name="format_greeting",
                kind="call",
                span=_span(5, 13, 5, 32),
                resolution=_resolved("pkg.models::format_greeting"),
            ),
            # Ratified in 0.2.0: member access resolves to the member's OWN id
            # <module_path>::<Owner>.<member> (ADR-0008).
            Ref(
                name="email",
                kind="attribute",
                span=_span(6, 15, 6, 25),
                resolution=_resolved("pkg.models::User.email"),
            ),
        ),
    )


def ts_consumer_aliased(ref: str = SIDE_B) -> FileFacts:
    """src/app.ts on side B — aliased import + receiver-typed member call:

        1: import { User as U } from "./models/user";
        3: export function welcome(u: U): string {
        4:     return u.greet(name="Ada");
    """
    return FileFacts(
        format_version=FORMAT_VERSION,
        path="src/app.ts",
        language="typescript",
        ref=ref,
        symbols=(
            Symbol(
                id="src/app::welcome",
                name="welcome",
                kind="function",
                span=_span(3, 0, 4, 33),
                exports=True,
                signature=Signature(
                    params=(Param("u", 0, "positional", "U", False),),
                    return_type="string",
                ),
            ),
        ),
        refs=(
            Ref(
                name="U",
                kind="import",
                span=_span(1, 7, 1, 40),
                resolution=_resolved("src/models::User"),
                module_specifier="./models/user",
                imported_name="User",
            ),
            Ref(
                name="greet",
                kind="call",
                span=_span(4, 11, 4, 28),
                resolution=_resolved("src/models::User.greet"),
            ),
        ),
    )


def models_signature_changed(ref: str = SIDE_A) -> FileFacts:
    """Side A renames greet's parameter `name` -> `greeting` (kw-caller breaks)."""
    base = models_main(ref)
    greet = next(s for s in base.symbols if s.id == "pkg.models::User.greet")
    new_greet = Symbol(
        id=greet.id,
        name=greet.name,
        kind=greet.kind,
        span=greet.span,
        exports=greet.exports,
        signature=Signature(
            params=(
                Param("self", 0, "positional", None, False),
                Param("greeting", 1, "positional", "str", False),
            ),
            return_type="str",
        ),
    )
    return FileFacts(
        format_version=base.format_version,
        path=base.path,
        language=base.language,
        ref=base.ref,
        symbols=tuple(new_greet if s.id == greet.id else s for s in base.symbols),
        refs=(),
    )


def models_field_removed(ref: str = SIDE_A) -> FileFacts:
    """Side A removes the `email` member from User."""
    base = models_main(ref)
    user = next(s for s in base.symbols if s.id == "pkg.models::User")
    no_email = Symbol(
        id=user.id,
        name=user.name,
        kind=user.kind,
        span=user.span,
        exports=user.exports,
        members=(),
        bases=user.bases,
        signature=user.signature,
    )
    return FileFacts(
        format_version=base.format_version,
        path=base.path,
        language=base.language,
        ref=base.ref,
        symbols=tuple(no_email if s.id == user.id else s for s in base.symbols),
        refs=(),
    )


def models_return_changed(ref: str = SIDE_A) -> FileFacts:
    """Side A changes greet's declared return type str -> GreetingResult."""
    base = models_main(ref)
    greet = next(s for s in base.symbols if s.id == "pkg.models::User.greet")
    changed = Symbol(
        id=greet.id,
        name=greet.name,
        kind=greet.kind,
        span=greet.span,
        exports=greet.exports,
        signature=Signature(
            params=greet.signature.params if greet.signature else (),
            return_type="GreetingResult",
        ),
        members=greet.members,
        bases=greet.bases,
    )
    return FileFacts(
        format_version=base.format_version,
        path=base.path,
        language=base.language,
        ref=base.ref,
        symbols=tuple(changed if s.id == greet.id else s for s in base.symbols),
        refs=(),
    )


def models_export_removed(ref: str = SIDE_A) -> FileFacts:
    """Side A deletes the exported function format_greeting entirely."""
    base = models_main(ref)
    return FileFacts(
        format_version=base.format_version,
        path=base.path,
        language=base.language,
        ref=base.ref,
        symbols=tuple(s for s in base.symbols if s.id != "pkg.models::format_greeting"),
        refs=(),
    )


def models_new_method_added(ref: str = SIDE_A) -> FileFacts:
    """Side A adds a brand-new method; old surface untouched (true-negative seed)."""
    base = models_main(ref)
    added = Symbol(
        id="pkg.models::User.shout",
        name="shout",
        kind="method",
        span=_span(10, 4, 11, 34),
        exports=False,
        signature=Signature(
            params=(
                Param("self", 0, "positional", None, False),
                Param("text", 1, "positional", "str", False),
            ),
            return_type="str",
        ),
    )
    return FileFacts(
        format_version=base.format_version,
        path=base.path,
        language=base.language,
        ref=base.ref,
        symbols=tuple(sorted((*base.symbols, added), key=lambda s: s.id)),
        refs=base.refs,
    )
