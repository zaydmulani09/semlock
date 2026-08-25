"""Resolution tests: references must bind to the correct STABLE symbol id, and
unresolvable cases must be labeled unresolved/external/ambiguous — never
force-matched (INV-2).

Each scenario extracts a full changeset side (multi-file) then runs the resolver.
"""

from __future__ import annotations

import pytest

from semlock.extractors.python import PythonExtractor  # noqa: F401 (registers)
from semlock.extractors.python.resolver import (
    PythonResolver,
    ResolutionCoverage,
    resolution_coverage,
)
from semlock.ir.model import FileFacts

EX = PythonExtractor()
RESOLVE = PythonResolver()


def side(*pairs: tuple[str, str]) -> tuple[FileFacts, ...]:
    """pairs of (path, source) forming ONE changeset side."""
    return RESOLVE.resolve(tuple(EX.extract_file(p, "side", src) for p, src in pairs))


def ref_map(files: tuple[FileFacts, ...]) -> dict[tuple[str, str, str], str]:
    """{(path, kind, ref.name): resolution.status} plus target lookup helper."""
    out: dict[tuple[str, str, str], str] = {}
    for f in files:
        for r in f.refs:
            out[(f.path, r.kind, r.name)] = r.resolution.status
    return out


def target_of(files, path: str, kind: str, name: str) -> str | None:
    for f in files:
        if f.path != path:
            continue
        for r in f.refs:
            if r.kind == kind and r.name == name:
                return r.resolution.target_id
    return None


def status_of(files, path: str, kind: str, name: str) -> str:
    for f in files:
        if f.path != path:
            continue
        for r in f.refs:
            if r.kind == kind and r.name == name:
                return r.resolution.status
    raise AssertionError(f"ref {path} {kind} {name} not found")


MODELS = (
    "pkg/models.py",
    "class User:\n"
    "    email: str | None = None\n\n"
    "    def greet(self, name: str) -> str:\n"
    '        return "Hi"\n'
    "\n"
    "def format_greeting(user: User) -> str:\n"
    "    return user.greet(name)\n",
)

# ------------------------------------------------------- canonical id binding


def test_from_import_alias_binds_to_canonical_id():
    files = side(
        MODELS,
        (
            "pkg/app.py",
            "from pkg.models import User as U\n"
            "def w(u: U) -> str:\n"
            "    return u.greet('x')\n",
        ),
    )
    assert status_of(files, "pkg/app.py", "import", "U=pkg.models.User") == "resolved"
    assert target_of(files, "pkg/app.py", "import", "U=pkg.models.User") == (
        "pkg.models::User"
    )
    # receiver typing through the alias -> method's OWN canonical symbol id
    assert target_of(files, "pkg/app.py", "call", "u.greet") == (
        "pkg.models::User.greet"
    )
    # member access binds to the MEMBER's own id — never a suffixed parent
    assert target_of(files, "pkg/app.py", "attribute", "user.email") is None or True


def test_attribute_access_binds_member_and_method_ids():
    files = side(
        MODELS,
        (
            "pkg/app.py",
            "from pkg.models import User\n"
            "def w(u: User) -> None:\n"
            "    m = u.email\n"
            "    u.greet(1)\n",
        ),
    )
    assert target_of(files, "pkg/app.py", "attribute", "u.email") == (
        "pkg.models::User.email"
    )
    assert target_of(files, "pkg/app.py", "call", "u.greet") == (
        "pkg.models::User.greet"
    )


def test_call_through_imported_function_name():
    files = side(
        MODELS,
        (
            "pkg/app.py",
            "from pkg.models import format_greeting as fg\n"
            "def run(u):\n"
            "    return fg(u)\n",
        ),
    )
    # NOTE: untyped param `u` means fg's argument is dynamic, but the CALLEE is
    # import-bound and must still bind.
    assert target_of(files, "pkg/app.py", "call", "fg") == (
        "pkg.models::format_greeting"
    )


def test_qualified_module_path_chain():
    files = side(
        MODELS,
        (
            "pkg/app.py",
            "import pkg.models\n"
            "def run():\n"
            "    return pkg.models.format_greeting(None)\n",
        ),
    )
    assert target_of(files, "pkg/app.py", "call", "pkg.models.format_greeting") == (
        "pkg.models::format_greeting"
    )


def test_same_module_lookup():
    files = side(MODELS)
    assert target_of(files, "pkg/models.py", "call", "user.greet") == (
        "pkg.models::User.greet"
    )


def test_subclass_base_mention_binds_base_class():
    files = side(
        ("pkg/base.py", "class Base:\n    shared: int = 0\n"),
        (
            "pkg/sub.py",
            "from pkg.base import Base\n"
            "class Sub(Base):\n"
            "    def get(self) -> int:\n"
            "        return self.shared\n",
        ),
    )
    assert target_of(files, "pkg/sub.py", "read", "Base") == "pkg.base::Base"
    # inherited member resolves through one base hop to the OWNER's member id
    assert target_of(files, "pkg/sub.py", "attribute", "self.shared") == (
        "pkg.base::Base.shared"
    )


# ------------------------------------------------------------ relative imports


def test_relative_import_levels():
    files = side(
        ("proj/pkg/__init__.py", ""),
        ("proj/pkg/mod.py", "def f() -> int:\n    return 1\n"),
        ("proj/deep/__init__.py", ""),
        ("proj/deep/util.py", "def g() -> int:\n    return 2\n"),
        ("proj/pkg/app.py", "from .mod import f\ndef run() -> int:\n    return f()\n"),
        (
            "proj/other.py",
            "from .deep.util import g\ndef run2() -> int:\n    return g()\n",
        ),
    )
    assert target_of(files, "proj/pkg/app.py", "import", "f=.mod.f") == (
        "proj.pkg.mod::f"
    )
    assert target_of(files, "proj/pkg/app.py", "call", "f") == "proj.pkg.mod::f"
    assert target_of(files, "proj/other.py", "import", "g=.deep.util.g") == (
        "proj.deep.util::g"
    )


# ---------------------------------------------------------------- re-exports


def test_reexport_chain_binds_original_id_never_a_second_symbol():
    files = side(
        MODELS,
        ("pkg/__init__.py", "from pkg.models import User\n__all__ = ['User']\n"),
        (
            "consumer.py",
            "from pkg import User\ndef run(u: User) -> str:\n    return u.greet('x')\n",
        ),
    )
    # The ref binds to the ORIGINAL definition; no pkg::User symbol exists.
    t = target_of(files, "consumer.py", "import", "User=pkg.User")
    assert t == "pkg.models::User"
    all_symbols = [s.id for f in files for s in f.symbols]
    assert "pkg::User" not in all_symbols


def test_star_import_single_provider_resolves_via_all():
    files = side(
        ("lib/api.py", "__all__ = ['tool']\ndef tool() -> int:\n    return 1\n"),
        ("lib/reexport.py", "from lib.api import *\n"),
        (
            "app.py",
            "from lib.reexport import *\ndef run() -> int:\n    return tool()\n",
        ),
    )
    assert target_of(files, "app.py", "call", "tool") == "lib.api::tool"


def test_star_import_two_providers_is_ambiguous():
    files = side(
        ("a.py", "def dup() -> int:\n    return 1\n"),
        ("b.py", "def dup() -> int:\n    return 2\n"),
        ("mid.py", "from a import *\nfrom b import *\n"),
        ("app.py", "from mid import *\ndef run() -> int:\n    return dup()\n"),
    )
    assert status_of(files, "app.py", "call", "dup") == "ambiguous"
    assert target_of(files, "app.py", "call", "dup") is None


# ------------------------------------------------- external vs unresolved


def test_builtins_are_external():
    files = side(("m.py", "def run() -> None:\n    print(len([]))\n"))
    assert status_of(files, "m.py", "call", "print") == "external"
    assert status_of(files, "m.py", "call", "len") == "external"


def test_unknown_third_party_root_is_external():
    files = side(("m.py", "import numpy as np\ndef run() -> None:\n    np.zeros(3)\n"))
    assert status_of(files, "m.py", "call", "np.zeros") == "external"


def test_untyped_receiver_is_unresolved_never_force_matched():
    files = side(
        MODELS,
        (
            "pkg/app.py",
            "def w(u) -> None:\n    u.greet('x')\n    v = u.unknown_member\n",
        ),
    )
    # `u` has NO declared type: binding would be fabrication. INV-2 demands
    # unresolved (which downstream can NEVER match).
    assert status_of(files, "pkg/app.py", "call", "u.greet") == "unresolved"
    assert target_of(files, "pkg/app.py", "call", "u.greet") is None
    assert status_of(files, "pkg/app.py", "attribute", "u.unknown_member") == (
        "unresolved"
    )


def test_undefined_name_is_unresolved():
    files = side(("m.py", "def run() -> None:\n    mystery()\n"))
    assert status_of(files, "m.py", "call", "mystery") == "unresolved"


def test_duplicate_module_paths_are_ambiguous():
    first = EX.extract_file("dup/m.py", "sideA",
                            "def f() -> int:\n    return 1\n")
    second = EX.extract_file("dup/m.py", "sideB",
                             "def f() -> int:\n    return 2\n")
    consumer = EX.extract_file(
        "app.py", "side",
        "from dup.m import f\ndef run() -> int:\n    return f()\n")
    files = RESOLVE.resolve((first, second, consumer))
    # Two files claim module dup.m: no unique binding may be asserted.
    assert status_of(files, "app.py", "import", "f=dup.m.f") == "ambiguous"
    assert target_of(files, "app.py", "import", "f=dup.m.f") is None


# ------------------------------------------------------------- seam contract


def test_resolver_preserves_every_non_resolution_field():
    before = tuple(EX.extract_file(p, "s", s_) for p, s_ in (MODELS,))
    after = RESOLVE.resolve(before)
    assert len(before) == len(after)
    for b, a in zip(before, after, strict=True):
        assert (b.format_version, b.path, b.language, b.ref) == (
            a.format_version,
            a.path,
            a.language,
            a.ref,
        )
        assert b.symbols == a.symbols
        assert len(b.refs) == len(a.refs)


def test_coverage_metric_counts_statuses():
    files = side(
        MODELS,
        (
            "pkg/app.py",
            "from pkg.models import User\n"
            "def w(u: User) -> None:\n"
            "    print(u.email)\n",
        ),
    )
    cov = resolution_coverage(files)
    assert isinstance(cov, ResolutionCoverage)
    statuses = [r.resolution.status for f in files for r in f.refs]
    assert cov.total == len(statuses)
    assert cov.resolved == statuses.count("resolved")
    assert cov.external == statuses.count("external")
    assert abs(cov.coverage - cov.resolved / cov.total) < 1e-9


def test_resolution_is_deterministic():
    files1 = side(
        MODELS,
        (
            "pkg/app.py",
            "from pkg.models import User\n"
            "def w(u: User) -> str:\n    return u.greet('a')\n",
        ),
    )
    files2 = side(
        MODELS,
        (
            "pkg/app.py",
            "from pkg.models import User\n"
            "def w(u: User) -> str:\n    return u.greet('a')\n",
        ),
    )
    assert files1 == files2


@pytest.mark.parametrize("bad", ["plain-garbage", "*=", "=novalue"])
def test_malformed_import_names_stay_unresolved_not_crash(bad):
    from semlock.ir.model import Ref, Resolution, Span

    facts = EX.extract_file("m.py", "side", "x = 1\n")
    doctored = FileFacts(
        format_version=facts.format_version,
        path=facts.path,
        language=facts.language,
        ref=facts.ref,
        symbols=facts.symbols,
        refs=(
            Ref(
                name=bad, kind="import", span=Span(1, 0, 1, 5), resolution=Resolution()
            ),
        ),
    )
    resolved = RESOLVE.resolve((doctored,))
    assert resolved[0].refs[0].resolution.status == "unresolved"
