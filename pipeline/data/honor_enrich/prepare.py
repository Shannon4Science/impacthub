"""Convert seed_scholars.json -> input.jsonl for api_tool batch processing."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # impacthub/
SEED = ROOT / "docs" / "seed_scholars.json"
OUT = Path(__file__).parent / "input.jsonl"


def main():
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    scholars = seed["scholars"]

    count = 0
    with OUT.open("w", encoding="utf-8") as f:
        for s in scholars:
            # Skip if already has verified honors (keep them, don't overwrite)
            if s.get("honors"):
                continue
            cn = s.get("cn", "")
            record = {
                "scholar_id": s["name"].replace(" ", "_"),  # unique key for api_tool
                "name": s["name"],
                "affiliation": s.get("affiliation", ""),
                "cn": cn,
                "cn_block": f"，中文名：{cn}" if cn else "",
                "direction": s.get("direction", ""),
                "tier": s.get("tier", ""),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    print(f"Wrote {count} scholars to {OUT}")


if __name__ == "__main__":
    main()
