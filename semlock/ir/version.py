"""SEMLock IR format version.

FROZEN at 0.2.0 (Day 2 EOD). The single deliberate 0.1.0 -> 0.2.0 revision ratified
the `<module_path>::<qualified_name>` id grammar and added Ref.module_specifier /
Ref.imported_name (S3 issue #3). Post-freeze changes require an ADR + version bump +
S1 arbitration (INV-6). Consumers gate on this value: mismatch means refuse, never
guess.
"""

FORMAT_VERSION = "0.2.0"
