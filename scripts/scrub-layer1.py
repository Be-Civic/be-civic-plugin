#!/usr/bin/env python3
"""scrub-layer1.py — Layer-1 scrub for content destined for submission.

Regex pass against a scrub-rules.json file (same shape served at
becivic.be/scrub-rules.json). The LLM contextual pass is the caller's
responsibility; this script does the deterministic regex layer only.

Invocation:
  scrub-layer1.py [--rules PATH] [--text STRING | --stdin]
                  [--field NAME ...] [--output OUT]

If --text is given, that string is scrubbed. With --stdin, reads the
candidate item as JSON on stdin (an observation buffer entry or a
submission payload); applies the regex pass to every string value
recursively. --field NAME may be repeated to constrain to specific
top-level field names (e.g. `--field rationale --field note`).

Output: JSON to stdout with shape
  {
    "status": "clean" | "redacted" | "rejected",
    "redactions": [
      {"category": "direct_identifier", "rule": "belgian_nrn",
       "field": "<path>", "match": "<verbatim>", "start": N, "end": N}
    ],
    "redacted_text": "<original with matches replaced by [REDACTED:cat]>"
  }

Exit codes:
  0   clean        (no matches)
  0   redacted     (only indirect_identifier matches; caller decides)
  2   rejected     (any direct_identifier match — caller MUST NOT submit)
  3   usage / IO error

Rules file: defaults to BUNDLE/data/scrub-rules.json (baseline shipped
with bundle); harness may pass a freshly-fetched copy via --rules.

Runtime: Python 3 stdlib only. No third-party deps. Cross-platform.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


BUNDLE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES = BUNDLE_ROOT / "data" / "scrub-rules.json"

DIRECT_CATEGORY = "direct_identifier"


def compile_rules(rules_data: dict[str, Any]) -> list[dict[str, Any]]:
    compiled: list[dict[str, Any]] = []
    for raw in rules_data.get("rules", []):
        flags = 0
        for f in raw.get("flags", "") or "":
            if f == "i":
                flags |= re.IGNORECASE
            elif f == "m":
                flags |= re.MULTILINE
            elif f == "s":
                flags |= re.DOTALL
        compiled.append({
            "name": raw["name"],
            "category": raw.get("category", "unknown"),
            "pattern": re.compile(raw["pattern"], flags),
        })
    return compiled


def walk_strings(obj: Any, path: str = "", fields: Iterable[str] | None = None) -> Iterable[tuple[str, str]]:
    if isinstance(obj, str):
        yield path, obj
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            child = f"{path}.{k}" if path else k
            if fields and not path and k not in fields:
                continue
            yield from walk_strings(v, child, fields=fields)
        return
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]", fields=fields)


def scrub_text(text: str, rules: list[dict[str, Any]], field: str) -> tuple[list[dict[str, Any]], str]:
    redactions: list[dict[str, Any]] = []
    redacted = text
    spans: list[tuple[int, int, str]] = []
    for rule in rules:
        for m in rule["pattern"].finditer(text):
            redactions.append({
                "category": rule["category"],
                "rule": rule["name"],
                "field": field,
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
            })
            spans.append((m.start(), m.end(), rule["category"]))
    if spans:
        spans.sort(key=lambda s: (s[0], -s[1]))
        merged: list[tuple[int, int, str]] = []
        for s in spans:
            if merged and s[0] < merged[-1][1]:
                continue
            merged.append(s)
        out: list[str] = []
        cursor = 0
        for start, end, category in merged:
            out.append(text[cursor:start])
            out.append(f"[REDACTED:{category}]")
            cursor = end
        out.append(text[cursor:])
        redacted = "".join(out)
    return redactions, redacted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--rules", default=str(DEFAULT_RULES))
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--text")
    src.add_argument("--stdin", action="store_true")
    parser.add_argument("--field", action="append", default=[])
    parser.add_argument("--output", default="-")
    args = parser.parse_args(argv)

    rules_path = Path(args.rules)
    if not rules_path.is_file():
        print(json.dumps({"status": "error", "error": f"rules_not_found: {rules_path}"}), file=sys.stderr)
        return 3

    try:
        rules_data = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": f"rules_parse: {exc}"}), file=sys.stderr)
        return 3

    rules = compile_rules(rules_data)

    all_redactions: list[dict[str, Any]] = []
    redacted_payload: Any

    if args.text is not None:
        reds, redacted = scrub_text(args.text, rules, field="text")
        all_redactions.extend(reds)
        redacted_payload = redacted
    elif args.stdin:
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as exc:
            print(json.dumps({"status": "error", "error": f"stdin_parse: {exc}"}), file=sys.stderr)
            return 3
        redacted_payload = json.loads(json.dumps(payload))
        fields_filter = set(args.field) if args.field else None
        for path, value in walk_strings(payload, fields=fields_filter):
            reds, redacted = scrub_text(value, rules, field=path)
            all_redactions.extend(reds)
            if reds and redacted != value:
                cursor: Any = redacted_payload
                keys = re.findall(r"[^.\[\]]+|\[\d+\]", path)
                for k in keys[:-1]:
                    cursor = cursor[int(k[1:-1])] if k.startswith("[") else cursor[k]
                last = keys[-1]
                if last.startswith("["):
                    cursor[int(last[1:-1])] = redacted
                else:
                    cursor[last] = redacted
    else:
        parser.error("one of --text or --stdin required")

    has_direct = any(r["category"] == DIRECT_CATEGORY for r in all_redactions)
    if has_direct:
        status = "rejected"
        exit_code = 2
    elif all_redactions:
        status = "redacted"
        exit_code = 0
    else:
        status = "clean"
        exit_code = 0

    result: dict[str, Any] = {"status": status, "redactions": all_redactions}
    if args.text is not None:
        result["redacted_text"] = redacted_payload
    elif args.stdin:
        result["redacted_payload"] = redacted_payload

    out_text = json.dumps(result, ensure_ascii=False)
    if args.output == "-":
        print(out_text)
    else:
        Path(args.output).write_text(out_text + "\n", encoding="utf-8")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
