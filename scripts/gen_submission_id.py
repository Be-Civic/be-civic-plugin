#!/usr/bin/env python3
"""gen_submission_id.py — client-side submission_id generator.

Usage:
    python3 gen_submission_id.py <issue|validation|feedback|rating>

Prints `<prefix>_<uuidv7>` to stdout, where the prefix is one of
iss_/val_/fbk_/rat_ and the UUID part is a lowercase-hex UUIDv7 that satisfies
the server's validation regex:

    ^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$

UUIDv7 layout (RFC 9562 §5.7), 128 bits:
  - bits  0..47  : unix_ts_ms — 48-bit big-endian Unix timestamp in ms
  - bits 48..51  : ver        — version nibble, set to 0b0111 (7)
  - bits 52..63  : rand_a     — 12 random bits
  - bits 64..65  : var        — variant, set to 0b10
  - bits 66..127 : rand_b     — 62 random bits

Implemented with Python 3 stdlib only (no third-party deps).
"""

from __future__ import annotations

import secrets
import sys
import time

# submission type -> id prefix.
PREFIXES = {
    "issue": "iss",
    "validation": "val",
    "feedback": "fbk",
    "rating": "rat",
}


def uuid7_hex() -> str:
    """Return a UUIDv7 as a canonical lowercase-hex string with hyphens.

    Pure stdlib: 48-bit unix-ms timestamp + cryptographically-random fill,
    version nibble forced to 7 and variant bits forced to 0b10.
    """
    unix_ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # clamp to 48 bits

    # Assemble the full 128-bit integer field by field.
    value = unix_ts_ms << 80  # timestamp occupies the top 48 bits

    # rand_a: 12 bits. ver nibble (top 4 of the next 16) is set separately.
    rand_a = secrets.randbits(12)
    value |= (0x7 << 76)  # version nibble 7 at bits 48..51
    value |= (rand_a << 64)  # 12 bits of rand_a at bits 52..63

    # var: 2 bits = 0b10. rand_b: 62 bits.
    rand_b = secrets.randbits(62)
    value |= (0b10 << 62)  # variant at bits 64..65
    value |= rand_b  # 62 bits of rand_b at bits 66..127

    hex_str = f"{value:032x}"
    return (
        f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-"
        f"{hex_str[16:20]}-{hex_str[20:32]}"
    )


def gen_submission_id(submission_type: str) -> str:
    """Return `<prefix>_<uuidv7>` for the given submission type."""
    try:
        prefix = PREFIXES[submission_type]
    except KeyError:
        valid = "|".join(PREFIXES)
        raise SystemExit(
            f"error: unknown submission type {submission_type!r}; "
            f"expected one of {valid}"
        )
    return f"{prefix}_{uuid7_hex()}"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        valid = "|".join(PREFIXES)
        print(f"usage: gen_submission_id.py <{valid}>", file=sys.stderr)
        return 2
    print(gen_submission_id(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
