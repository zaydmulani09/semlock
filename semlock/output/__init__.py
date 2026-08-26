"""Output writers for SEMLock results (S5): text (default) and JSON.

SARIF lands in a later pass; the CLI contract already reserves `--sarif`.

Determinism (INV-1): every writer emits a fixed key/line order derived from
the canonical Finding sort key, UTF-8, LF newlines, trailing newline. No
timestamps, colors, locale formatting, or machine-specific paths appear in any
artifact.
"""
