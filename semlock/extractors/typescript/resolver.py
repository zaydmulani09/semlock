"""TypeScript resolver (S3): bind use-site refs to canonical member/symbol ids.

Fixed rule: a field/property/method reference resolves to the MEMBER's own
canonical symbol id (``module_path::Owner.member``) -- never a suffixed parent
id (ADR-0008). Member symbols are emitted by the extractor precisely so this
binding is a direct id join.

0.2.0 wiring: import refs carry ``module_specifier`` (+ ``imported_name`` when
aliased/default), so binding is SPECIFIER-DIRECTED: resolve the specifier to a
module of this changeset side, then bind against that module's exports,
following named re-export chains and ``export *`` sources transitively to the
ORIGINAL symbol id (INV-7 chain). Namespace imports (extracted as
``name="<local>.*"`` producer encoding) and barrel star edges bind at MODULE
granularity: ``resolution.target_id`` is the bare ``module_path``, grammar-
distinct by absence of ``::`` (ADR-0008 §3).

Statuses (INV-2 downstream): ``resolved`` iff evidence pins exactly one id;
``ambiguous`` iff >= 2 distinct ids match; ``external`` for node_modules/
builtins and in-repo modules absent from this side; ``unresolved`` otherwise.
UNRESOLVED IS NEVER A MATCH.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import ClassVar

from semlock.extractors.base import Resolver
from semlock.extractors.typescript._paths import (
    is_relative,
    module_path_of,
    strip_extension_and_collapse,
)
from semlock.ir.model import (
    FileFacts,
    Ref,
    Resolution,
    ResolutionStatus,
)

_NAMESPACE_SUFFIX = ".*"
_STAR = "*"
_DEFAULT = "default"
_MAX_CHAIN_DEPTH = 8

_GLOBAL_IDENTIFIERS = frozenset(
    {
        "Promise", "Array", "Map", "Set", "WeakMap", "WeakSet", "Object",
        "Function", "Boolean", "String", "Number", "Date", "RegExp", "Error",
        "JSON", "Math", "console", "window", "document", "globalThis",
        "Symbol",
    }
)


class TypeScriptResolver(Resolver):
    language: ClassVar[str] = "typescript"

    def __init__(self, path_aliases: Mapping[str, str] | None = None) -> None:
        """``path_aliases`` maps tsconfig-style patterns ("@/*") to repo bases
        ("src/*"). When omitted, the single conventional "@/" -> "src/"
        mapping is applied ONLY when the mapped module exists on the side
        (evidence-checked, never guessed)."""
        self._path_aliases: dict[str, str] = dict(path_aliases or {})

    def resolve(self, files: tuple[FileFacts, ...]) -> tuple[FileFacts, ...]:
        index = _SideIndex(files, self._path_aliases)
        resolved: list[FileFacts] = []
        for facts in files:
            resolved.append(self._resolve_file(facts, index))
        return tuple(resolved)

    def _resolve_file(self, facts: FileFacts, index: _SideIndex) -> FileFacts:
        """Two phases per file: imports first (they define the file's local
        identifier table), then every other use-site may consult it -- a call
        of an imported name refers to THAT binding (static scoping)."""
        local_bindings: dict[str, str] = {}
        import_refs: dict[int, Ref] = {}
        for i, ref in enumerate(facts.refs):
            if ref.kind != "import":
                continue
            upgraded = self._bind_import(ref, facts, index)
            import_refs[i] = upgraded
            target = upgraded.resolution.target_id
            if (
                upgraded.resolution.status == "resolved"
                and target is not None
                and "::" in target
                and target is not None
                and not upgraded.name.endswith(_NAMESPACE_SUFFIX)
                and upgraded.name != _STAR
            ):
                local_bindings[upgraded.name] = target
        new_refs: list[Ref] = []
        for i, ref in enumerate(facts.refs):
            if i in import_refs:
                new_refs.append(import_refs[i])
            else:
                new_refs.append(self._bind_use_site(ref, facts, local_bindings, index))
        return FileFacts(
            format_version=facts.format_version,
            path=facts.path,
            language=facts.language,
            ref=facts.ref,
            symbols=facts.symbols,
            refs=tuple(new_refs),
        )

    def _bind_import(
        self,
        ref: Ref,
        facts: FileFacts,
        index: _SideIndex,
    ) -> Ref:
        specifier = ref.module_specifier
        if specifier is None:
            status, target = self._bind_unique(
                index.exported_top_level.get(ref.name, ())
            )
            return _finished(ref, status, target)
        kind, module = index.target_module(specifier, _dir_of(facts.path))
        if kind == "external":
            return _with(ref, Resolution(status="external"))
        if module is None:
            return _with(ref, Resolution(status="unresolved"))
        if ref.name == _STAR or ref.name.endswith(_NAMESPACE_SUFFIX):
            return _finished(ref, "resolved", module)
        if ref.imported_name == _DEFAULT:
            return self._bind_default(ref, module, index)
        # The name requested FROM the target module: the original exported
        # name for aliased imports, otherwise the local name itself.
        wanted = ref.imported_name if ref.imported_name is not None else ref.name
        status, target = self._lookup_export(module, wanted, index)
        return _finished(ref, status, target)

    def _bind_default(
        self, ref: Ref, module: str, index: _SideIndex
    ) -> Ref:
        """ES default exports are literally named "default"; 0.2.0 has no
        default flag on Symbol, so bind only when the module's export surface
        is unambiguous (exactly one exported top-level symbol). Never guess."""
        exported_ids: set[str] = set()
        for ids in index.exports_of(module).values():
            exported_ids.update(ids)
        if len(exported_ids) == 1:
            return _finished(ref, "resolved", next(iter(exported_ids)))
        return _with(ref, Resolution(status="unresolved"))

    def _lookup_export(
        self,
        module: str,
        name: str,
        index: _SideIndex,
        depth: int = 0,
        seen: frozenset[tuple[str, str]] = frozenset(),
    ) -> tuple[ResolutionStatus, str | None]:
        """Direct exports, then named re-export chains, then `export *`
        sources -- always to the ORIGINAL symbol id."""
        key = (module, name)
        if depth > _MAX_CHAIN_DEPTH or key in seen:
            return "unresolved", None
        seen = seen | {key}
        direct = sorted(set(index.exports_of(module).get(name, ())))
        if len(direct) == 1:
            return "resolved", direct[0]
        if len(direct) > 1:
            return "ambiguous", None
        hop = index.reexports_of(module).get(name)
        if hop is not None:
            return self._lookup_export(hop[0], hop[1], index, depth + 1, seen)
        for source in index.stars_of(module):
            status, target = self._lookup_export(
                source, name, index, depth + 1, seen
            )
            if status != "unresolved":
                return status, target
        return "unresolved", None

    # ------------------------------------------------- non-import use sites

    def _bind_use_site(
        self,
        ref: Ref,
        facts: FileFacts,
        local_bindings: dict[str, str],
        index: _SideIndex,
    ) -> Ref:
        if ref.resolution.status != "unresolved":
            return ref
        if ref.kind == "call":
            bound = self._via_local_binding(ref.name, local_bindings)
            if bound is not None:
                return _finished(ref, "resolved", bound)
            if ref.name in _GLOBAL_IDENTIFIERS:
                return _with(ref, Resolution(status="external"))
            candidates: Sequence[str] = tuple(index.top_level.get(ref.name, ()))
            candidates = (
                *candidates,
                *index.exported_top_level.get(ref.name, ()),
                *index.members.get(ref.name, ()),
            )
            status, target = self._bind_unique(candidates)
        elif ref.kind == "read":
            bound = self._via_local_binding(ref.name, local_bindings)
            if bound is not None:
                return _finished(ref, "resolved", bound)
            if ref.name in _GLOBAL_IDENTIFIERS:
                return _with(ref, Resolution(status="external"))
            candidates = tuple(index.top_level.get(ref.name, ()))
            candidates = (*candidates, *index.exported_top_level.get(ref.name, ()))
            status, target = self._bind_unique(candidates)
        elif ref.kind in ("attribute", "write"):
            status, target = self._bind_unique(index.members.get(ref.name, ()))
        else:
            status, target = "unresolved", None
        return _finished(ref, status, target)

    @staticmethod
    def _via_local_binding(
        name: str, local_bindings: dict[str, str]
    ) -> str | None:
        """A call/read whose name matches this file's resolved import binding
        refers to THAT binding (TS static scoping). Module-granular targets
        (namespace imports) carry no member evidence and are skipped."""
        target = local_bindings.get(name)
        if target is None or "::" not in target:
            return None
        return target

    @staticmethod
    def _bind_unique(
        candidate_ids: Sequence[str],
    ) -> tuple[ResolutionStatus, str | None]:
        distinct = sorted(set(candidate_ids))
        if len(distinct) == 1:
            return "resolved", distinct[0]
        if len(distinct) > 1:
            return "ambiguous", None
        return "unresolved", None


def _finished(ref: Ref, status: ResolutionStatus, target: str | None) -> Ref:
    if status == "resolved" and target is not None:
        return _with(ref, Resolution(status="resolved", target_id=target))
    return _with(ref, Resolution(status=status))


def _with(ref: Ref, resolution: Resolution) -> Ref:
    return Ref(
        name=ref.name,
        kind=ref.kind,
        span=ref.span,
        resolution=resolution,
        module_specifier=ref.module_specifier,
        imported_name=ref.imported_name,
    )


class _SideIndex:
    """Module-directed view of one changeset side."""

    def __init__(
        self, files: tuple[FileFacts, ...], path_aliases: dict[str, str]
    ) -> None:
        self.modules: dict[str, FileFacts] = {}
        self._exports: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._reexports: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
        self._stars: dict[str, list[str]] = defaultdict(list)
        self.exported_top_level: dict[str, list[str]] = defaultdict(list)
        self.top_level: dict[str, list[str]] = defaultdict(list)
        self.members: dict[str, list[str]] = defaultdict(list)
        self._path_aliases = path_aliases

        for facts in files:
            mod = module_path_of(facts.path)
            self.modules[mod] = facts
            for symbol in facts.symbols:
                qualified = symbol.id.split("::", 1)[1] if "::" in symbol.id else ""
                if "." in qualified:
                    self.members[symbol.name].append(symbol.id)
                    continue
                self.top_level[symbol.name].append(symbol.id)
                if symbol.exports:
                    self.exported_top_level[symbol.name].append(symbol.id)
                    self._exports[mod][symbol.name].append(symbol.id)

        for facts in files:
            mod = module_path_of(facts.path)
            declared_top_level = {
                s.id.split("::", 1)[1]
                for s in facts.symbols
                if "::" in s.id and "." not in s.id.split("::", 1)[1]
            }
            for ref in facts.refs:
                if ref.kind != "import" or ref.module_specifier is None:
                    continue
                importer_dir = _dir_of(facts.path)
                target = self.target_module(ref.module_specifier, importer_dir)[1]
                if target is None:
                    continue
                if ref.name == _STAR:
                    self._stars[mod].append(target)
                elif (
                    ref.imported_name is not None
                    and ref.imported_name != _DEFAULT
                    # Only declaration-less modules (barrels) re-export;
                    # an aliased import in a consumer file is NOT an export.
                    and ref.name not in declared_top_level
                ):
                    self._reexports[mod][ref.name] = (target, ref.imported_name)

    # ------------------------------------------------------------ accessors

    def exports_of(self, module: str) -> Mapping[str, list[str]]:
        return self._exports.get(module, {})

    def reexports_of(self, module: str) -> Mapping[str, tuple[str, str]]:
        return self._reexports.get(module, {})

    def stars_of(self, module: str) -> list[str]:
        return self._stars.get(module, [])

    def target_module(
        self, specifier: str, importer_dir: str
    ) -> tuple[str, str | None]:
        """("internal", module_path) | ("external", None). Deterministic.

        `importer_dir` is the importing FILE's directory (e.g. "src/client"),
        which is correct for relative resolution even when the importer is an
        index-collapsed module ("src/api/index.ts" -> dir "src/api").
        """
        if is_relative(specifier):
            resolved = strip_extension_and_collapse(
                _join_relative(specifier, importer_dir)
            )
            if resolved in self.modules:
                return "internal", resolved
            return "external", None
        if specifier in self.modules:
            return "internal", specifier
        for candidate in self._alias_candidates(specifier):
            if candidate in self.modules:
                return "internal", candidate
        return "external", None

    def _alias_candidates(self, specifier: str) -> list[str]:
        candidates: list[str] = []
        for pattern, base in self._path_aliases.items():
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                base_dir = base[:-1] if base.endswith("*") else base
                if specifier.startswith(prefix):
                    joined = base_dir + specifier[len(prefix):]
                    candidates.append(strip_extension_and_collapse(joined))
            elif pattern == specifier:
                candidates.append(strip_extension_and_collapse(base))
        if not self._path_aliases and specifier.startswith("@/"):
            candidates.append(
                strip_extension_and_collapse("src/" + specifier[2:])
            )
        return candidates


def _dir_of(path: str) -> str:
    """Directory of a repo-relative FILE path ('src/api/index.ts' -> 'src/api')."""
    head, _, _tail = path.replace("\\", "/").rpartition("/")
    return head


def _join_relative(specifier: str, importer_dir: str) -> str:
    parts = [p for p in importer_dir.split("/") if p]
    segment = specifier
    while segment.startswith("./"):
        segment = segment[2:]
    while True:
        if segment.startswith("../"):
            if parts:
                parts.pop()
            segment = segment[3:]
        elif segment.startswith("./"):
            segment = segment[2:]
        else:
            break
    for piece in segment.split("/"):
        if piece and piece != ".":
            parts.append(piece)
    return "/".join(parts)


def measure_resolution(
    files: tuple[FileFacts, ...],
) -> dict[str, float | dict[str, dict[str, int]]]:
    """Resolution coverage per Constitution §4: fraction of refs with status
    == 'resolved'. External/unresolved/ambiguous reported separately."""
    per_kind: dict[str, dict[str, int]] = defaultdict(
        lambda: {"resolved": 0, "external": 0, "ambiguous": 0, "unresolved": 0}
    )
    for facts in files:
        for ref in facts.refs:
            per_kind[ref.kind][ref.resolution.status] += 1
    total = sum(sum(counts.values()) for counts in per_kind.values())
    resolved_total = sum(counts["resolved"] for counts in per_kind.values())
    coverage = (resolved_total / total) if total else 1.0
    detail = {kind: dict(counts) for kind, counts in sorted(per_kind.items())}
    return {"coverage": coverage, "refs": total, "by_kind": detail}
