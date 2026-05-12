"""Merge api_tool output/results.jsonl back into seed_scholars_enriched.json.

Parses each scholar's LLM response (expecting JSON), adds `honors_proposed`
to the scholar record. Original `honors` field is preserved.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # impacthub/
SEED = ROOT / "docs" / "seed_scholars.json"
OUT = ROOT / "docs" / "seed_scholars_enriched.json"
RESULTS = Path(__file__).parent / "output" / "results.jsonl"


def parse_json(text: str) -> dict | None:
    s = text.strip()
    # Strip <think>...</think>
    if "<think>" in s:
        s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL).strip()
    # Strip markdown fences
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        s = s.rsplit("```", 1)[0]
    try:
        return json.loads(s.strip())
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


def main():
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    by_name = {s["name"]: s for s in seed["scholars"]}

    if not RESULTS.exists():
        print(f"No results file at {RESULTS}. Run api_tool first.")
        return

    parsed_ok = 0
    parse_fail = 0
    no_honors = 0
    with_honors = 0
    honor_counter: dict[str, int] = {}

    for line in RESULTS.open(encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        name = rec.get("name")
        resp = rec.get("response", "")
        if name not in by_name:
            continue

        parsed = parse_json(resp)
        if not parsed:
            parse_fail += 1
            by_name[name]["honors_proposed"] = {"error": "parse_failed", "raw": resp[:300]}
            continue

        honors = parsed.get("honors", []) or []
        honors = [str(h) for h in honors][:10]
        confidence = parsed.get("confidence", "medium")
        note = parsed.get("note", "")

        by_name[name]["honors_proposed"] = {
            "honors": honors,
            "confidence": confidence,
            "note": note,
        }
        parsed_ok += 1
        if honors:
            with_honors += 1
            for h in honors:
                honor_counter[h] = honor_counter.get(h, 0) + 1
        else:
            no_honors += 1

    # Write enriched JSON
    seed["scholars"] = list(by_name.values())
    OUT.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Parsed OK: {parsed_ok}")
    print(f"Parse failed: {parse_fail}")
    print(f"With honors: {with_honors}")
    print(f"No honors: {no_honors}")
    print(f"\nTop honor types:")
    for honor, n in sorted(honor_counter.items(), key=lambda x: -x[1]):
        print(f"  {honor}: {n}")
    print(f"\nOutput: {OUT}")


if __name__ == "__main__":
    main()
