"""SEMLock IR format version.

PROVISIONAL at 0.1.0 (Day 1). Freezes at 0.2.0 Day 2 EOD after exactly ONE deliberate
revision driven by S2/S3 spike answers (docs/IR_CONTRACT.md §6). Consumers gate on this
value (INV-6): mismatch means refuse, never guess.
"""

FORMAT_VERSION = "0.1.0"
