from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            yield value


def append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
            count += 1
    return count


def read_seen_keys(path: Path, key_names: Iterable[str]) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    for record in iter_jsonl(path):
        for key_name in key_names:
            value = record.get(key_name)
            if value:
                seen.add(f"{key_name}:{value}")
    return seen
