"""Seam contracts between extraction (S2), resolution (S3), and everything downstream.

S1 owns this file. Implementations live elsewhere: Extractors are S2's, Resolvers are
S3's. Rules encoded here:

- An Extractor MUST leave every Ref.resolution at its default ('unresolved').
  Only a Resolver may upgrade statuses (INV-2). Enforceable via assert_unresolved().
- A Resolver is REF-WIDE: it receives all FileFacts of one changeset side and returns
  them with resolution filled. It must not drop, reorder-canonicalize away, or rewrite
  any non-resolution field.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from semlock.ir.model import FileFacts


class Extractor(ABC):
    """Parses one file's source into FileFacts for a given ref."""

    language: ClassVar[str]

    @abstractmethod
    def extract_file(self, path: str, ref: str, source: str) -> FileFacts:
        """Extract facts from `source`.

        Contract: every returned Ref.resolution == Resolution() (unresolved);
        format_version stamped from semlock.ir.version; path repo-relative with '/'.
        """
        raise NotImplementedError


class Resolver(ABC):
    """Binds use-sites to definitions across ALL files of one changeset side."""

    language: ClassVar[str]

    @abstractmethod
    def resolve(
        self, files: tuple[FileFacts, ...]
    ) -> tuple[FileFacts, ...]:
        """Return the same number of FileFacts, same order, same paths/refs/spans,
        with Ref.resolution upgraded where evidence allows. Never emits status
        'resolved' without a concrete target_id (model enforces this)."""
        raise NotImplementedError


def assert_unresolved(facts: FileFacts) -> None:
    """Raise AssertionError if any ref in `facts` claims resolution.

    Tests (S1-owned mock-validity suite) run this over every extractor output shape.
    """
    for ref in facts.refs:
        if ref.resolution.status != "unresolved":
            raise AssertionError(
                f"{facts.path}:{ref.span.start_line} ref {ref.name!r} has status "
                f"{ref.resolution.status!r}; extractors must emit unresolved (INV-2)"
            )
