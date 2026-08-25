"""Extractor unit tests: every fact kind the Python extractor emits.

All outputs MUST be UNRESOLVED (INV-2/seam), schema-valid under canonical
serialization, and byte-deterministic.
"""

from __future__ import annotations

import pytest

from semlock.extractors.base import assert_unresolved
from semlock.extractors.python.extractor import PythonExtractor
from semlock.ir.serialize import to_json

EX = PythonExtractor()


def _refs_by_name(source: str, path: str = "pkg/mod.py"):
    facts = EX.extract_file(path, "test", source)
    return facts, {(r.kind, r.name): r for r in facts.refs}


def _symbols_by_id(facts):
    return {s.id: s for s in facts.symbols}


# ------------------------------------------------------------------ symbols


def test_symbol_ids_follow_module_path_qualified_grammar():
    src = (
        "CONST = 1\n"
        "class Outer:\n"
        "    def method(self) -> None: ...\n"
        "    class Nested:\n"
        "        pass\n"
        "def top() -> None: ...\n"
    )
    facts = EX.extract_file("pkg/sub/mod.py", "main", src)
    syms = _symbols_by_id(facts)
    assert set(syms) == {
        "pkg.sub.mod::CONST",
        "pkg.sub.mod::Outer",
        "pkg.sub.mod::Outer.method",
        "pkg.sub.mod::Outer.Nested",
        "pkg.sub.mod::top",
    }
    assert syms["pkg.sub.mod::Outer"].kind == "class"
    assert syms["pkg.sub.mod::Outer.method"].kind == "method"
    assert syms["pkg.sub.mod::Outer.Nested"].kind == "class"
    assert syms["pkg.sub.mod::top"].kind == "function"
    assert syms["pkg.sub.mod::CONST"].kind == "variable"


def test_package_init_maps_to_package_module_path():
    facts = EX.extract_file("pkg/__init__.py", "main", "X = 1\n")
    assert [s.id for s in facts.symbols] == ["pkg::X"]


def test_signature_param_kinds_defaults_annotations():
    src = "def f(a, b: int = 2, *args, kw, kw2: str = 'x', **kw3) -> bool:\n    ...\n"
    facts = EX.extract_file("m.py", "main", src)
    sig = facts.symbols[0].signature
    assert sig is not None
    names = [(p.name, p.kind, p.has_default, p.type_annotation) for p in sig.params]
    assert names == [
        ("a", "positional", False, None),
        ("b", "positional", True, "int"),
        ("args", "varargs", False, None),
        ("kw", "keyword_only", False, None),
        ("kw2", "keyword_only", True, "str"),
        ("kw3", "kwargs", False, None),
    ]
    assert sig.return_type == "bool"


def test_forward_reference_annotation_quotes_stripped():
    src = 'def make() -> "Klass":\n    ...\n'
    facts = EX.extract_file("m.py", "main", src)
    assert facts.symbols[0].signature.return_type == "Klass"


# ------------------------------------------------------------------ members


def test_class_fields_property_twin_and_self_stores():
    src = (
        "class C:\n"
        "    annotated: str = 'x'\n"
        "    plain = 1\n"
        "\n"
        "    def __init__(self) -> None:\n"
        "        self.instance_fld: int = 0\n"
        "\n"
        "    @property\n"
        "    def prop(self) -> int:\n"
        "        return 1\n"
    )
    facts = EX.extract_file("m.py", "main", src)
    cls = _symbols_by_id(facts)["m::C"]
    members = {m.name: m.type_annotation for m in cls.members}
    assert members == {
        "annotated": "str",
        "plain": None,
        "instance_fld": "int",
        "prop": "int",  # property twin keeps declared return type
    }


def test_function_local_typed_members_channel():
    src = "def f() -> None:\n    x: int = 1\n    y = C()\n    z = 3\n"
    facts = EX.extract_file("m.py", "main", src)
    fn = _symbols_by_id(facts)["m::f"]
    locals_typed = {m.name: m.type_annotation for m in fn.members}
    # annotated always recorded; ctor-call inferred; bare literal not
    assert locals_typed == {"x": "int", "y": "C"}


# ------------------------------------------------------------------ exports


def test_exports_without_all_skip_underscore():
    src = "def pub(): ...\ndef _priv(): ...\nclass Pub: ...\n_PRIV = 1\nPUB = 2\n"
    facts = EX.extract_file("m.py", "main", src)
    exports = {s.name: s.exports for s in facts.symbols}
    assert exports == {
        "pub": True,
        "_priv": False,
        "Pub": True,
        "_PRIV": False,
        "PUB": True,
    }


def test_exports_with_all_is_exhaustive_and_merges_augmented():
    src = (
        "__all__ = ['a']\n__all__ += ['b']\ndef a(): ...\ndef b(): ...\ndef c(): ...\n"
    )
    facts = EX.extract_file("m.py", "main", src)
    exports = {s.name: s.exports for s in facts.symbols}
    assert exports == {"a": True, "b": True, "c": False}


# ------------------------------------------------------------- import encodings


def test_plain_and_aliased_plain_import_encoding():
    _, refs = _refs_by_name("import os\nimport os.path as osp\n")
    assert ("import", "os~os") in refs
    assert ("import", "osp~os.path") in refs


def test_from_import_encoding_including_alias_relative_wildcard():
    src = (
        "from pkg.models import User\n"
        "from pkg.models import User as U\n"
        "from .rel.mod import Thing\n"
        "from ..up import W\n"
        "from . import *\n"
    )
    _, refs = _refs_by_name(src)
    assert ("import", "User=pkg.models.User") in refs
    assert ("import", "U=pkg.models.User") in refs
    assert ("import", "Thing=.rel.mod.Thing") in refs
    assert ("import", "W=..up.W") in refs
    assert ("import", "*=.") in refs


# --------------------------------------------------------------------- refs


def test_use_site_ref_kinds_and_chain_names():
    src = (
        "def consumer(u: U) -> None:\n"
        "    u.greet(1)\n"
        "    v = u.email\n"
        "    u.email = 2\n"
        "    print(v)\n"
    )
    _, refs = _refs_by_name(src, "pkg/app.py")
    assert ("call", "u.greet") in refs
    assert ("attribute", "u.email") in refs
    assert ("write", "u.email") in refs
    assert ("call", "print") in refs  # builtins emitted; resolver marks external
    assert ("read", "v") not in refs  # local assignments never become deps


def test_keyword_argument_labels_are_not_refs():
    _, refs = _refs_by_name("def f(x: int) -> None: ...\nf(flag=1)\n")
    assert ("read", "flag") not in refs
    assert ("call", "f") in refs


def test_subclass_base_names_emitted_as_reads():
    src = "class Base: ...\nclass Sub(Base):\n    ...\n"
    _, refs = _refs_by_name(src)
    assert ("read", "Base") in refs


def test_params_and_function_locals_suppressed_but_module_names_not():
    src = "GLOB = 1\ndef f(x: int) -> None:\n    local = x + GLOB\n    return None\n"
    _, refs = _refs_by_name(src)
    assert ("read", "x") not in refs  # parameter
    assert ("read", "local") not in refs  # local binding
    assert ("read", "GLOB") in refs  # module-level surface stays resolvable


# ------------------------------------------------------- contract compliance


def test_module_specifier_and_imported_name_per_import_form():
    src = (
        "import os.path\n"
        "import numpy as np\n"
        "from pkg.models import User\n"
        "from pkg.models import User as U\n"
        "from .rel.mod import Thing as T\n"
        "from . import *\n"
    )
    facts = EX.extract_file("pkg/app.py", "main", src)
    by_name = {r.name: r for r in facts.refs if r.kind == "import"}
    assert by_name["os~os.path"].module_specifier == "os.path"
    assert by_name["os~os.path"].imported_name is None
    assert by_name["np~numpy"].module_specifier == "numpy"
    assert by_name["np~numpy"].imported_name is None  # module binding, not export
    assert by_name["User=pkg.models.User"].module_specifier == "pkg.models"
    # unaliased from-import: original name IS the local name -> imported_name null
    assert by_name["User=pkg.models.User"].imported_name is None
    assert by_name["U=pkg.models.User"].module_specifier == "pkg.models"
    assert by_name["U=pkg.models.User"].imported_name == "User"
    assert by_name["T=.rel.mod.Thing"].module_specifier == ".rel.mod"
    assert by_name["T=.rel.mod.Thing"].imported_name == "Thing"
    assert by_name["*=."].module_specifier == "."
    assert by_name["*=."].imported_name is None


def test_non_import_refs_carry_null_module_evidence():
    facts = EX.extract_file("m.py", "main", "def f() -> None:\n    print(1)\n")
    for ref in facts.refs:
        if ref.kind != "import":
            assert ref.module_specifier is None
            assert ref.imported_name is None


def test_symbol_ids_match_frozen_grammar_pattern():
    import re

    pattern = re.compile(r"^[^:]+::[^:]+$")
    src = (
        "class A:\n"
        "    def m(self) -> None:\n"
        "        class Inner:\n"
        "            pass\n"
        "V = 1\n"
    )
    facts = EX.extract_file("deep/pkg/mod.py", "main", src)
    for sym in facts.symbols:
        assert pattern.match(sym.id), sym.id


def test_format_version_stamped_from_ir_version():
    from semlock.ir.version import FORMAT_VERSION

    facts = EX.extract_file("m.py", "main", "X = 1\n")
    assert facts.format_version == FORMAT_VERSION == "0.2.0"


@pytest.mark.parametrize(
    "path,source",
    [
        ("m.py", "def f() -> None: ...\n"),
        ("pkg/__init__.py", "from .mod import Thing\n"),
        (
            "pkg/mod.py",
            "class K:\n    f: int = 0\n    def m(self) -> K:\n        return self\n",
        ),
    ],
)
def test_every_extracted_ref_is_unresolved(path, source):
    facts = EX.extract_file(path, "main", source)
    assert_unresolved(facts)


def test_serialization_is_schema_valid_and_byte_deterministic():
    src = (
        "from collections import OrderedDict\n"
        "__all__ = ['api']\n"
        "class K:\n"
        "    fld: int = 0\n"
        "    @property\n"
        "    def p(self) -> int:\n"
        "        return self.fld\n"
        "def api(k: K, *rest, flag=True) -> 'OrderedDict':\n"
        "    k.fld = 1\n"
        "    return OrderedDict()\n"
    )
    facts = PythonExtractor().extract_file("pkg/a.py", "HEAD", src)
    first = to_json(facts)  # validates against schema/ir.schema.json
    second = to_json(PythonExtractor().extract_file("pkg/a.py", "HEAD", src))
    assert first == second
