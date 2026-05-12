"""Batch-enrich scholar honor tags via LLM with web search.

Reads docs/seed_scholars.json, for each scholar whose `honors` is empty,
queries LLM+search to propose honor tags with evidence, and writes the
augmented data to docs/seed_scholars_enriched.json for human review.

Original honors field is preserved; LLM proposals go into a new
`honors_proposed` field so nothing is overwritten silently.

Usage:
  cd backend
  python -m scripts.enrich_honors                   # enrich all
  python -m scripts.enrich_honors --limit 5         # only first 5 (for testing)
  python -m scripts.enrich_honors --concurrency 3   # default: 3
  python -m scripts.enrich_honors --force           # re-enrich even if already proposed
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import setup_logging  # noqa: E402  (also adds backend/ to sys.path)

import httpx  # noqa: E402

from app.config import LLM_API_BASE, LLM_API_KEY, LLM_BUZZ_MODEL, LLM_FALLBACK_MODEL  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEED_FILE = REPO_ROOT / "docs" / "seed_scholars.json"
OUT_FILE = REPO_ROOT / "docs" / "seed_scholars_enriched.json"


def _parse_json_from_text(text: str) -> dict | None:
    """Extract JSON object from possibly-markdown-wrapped LLM output."""
    s = text.strip()
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


def _build_prompt(name: str, affiliation: str, cn: str | None) -> str:
    alias = f"（中文名：{cn}）" if cn else ""
    return f"""请搜索并列出以下学者在**学术荣誉和人才计划**方面获得过的**可查证**荣誉。

学者：{name}{alias}
单位：{affiliation}

**只列出在权威来源（官方公告、机构官网、学者本人主页、Wikipedia）能直接查到的荣誉**。
**不要猜测**，如果找不到直接证据就空着；**不要把奖项或论文荣誉（Best Paper / Test of Time）当作这里的荣誉**。

关心的荣誉范围：

国际类：Turing Award、ACM Fellow、IEEE Fellow、AAAI Fellow、AAAS Fellow、
        FRS（英国皇家学会）、NAE（美国工程院）、NAS（美国科学院）、
        ACL Fellow、IAPR Fellow、MacArthur Fellow、Royal Society 其他分支

中国类：中国科学院院士、中国工程院院士、
        长江学者特聘/青年长江、
        国家杰出青年科学基金（杰青）、优秀青年科学基金（优青）、海外优青、
        国家万人计划（科技创新领军人才、青年拔尖人才）、
        百千万人才工程、IEEE/ACM 中国区各类 Fellow

请严格输出以下 JSON（不要 markdown 代码块、不要解释文字）：

{{
  "honors": ["荣誉1", "荣誉2"],
  "evidence": [
    {{"honor": "荣誉名", "year": 年份或null, "source": "可访问的证据URL", "note": "简短说明"}}
  ],
  "confidence": "high" 或 "medium" 或 "low"
}}

要求：
- confidence = high：多条独立来源或官方公告直接印证
- confidence = medium：只有个人主页/单一来源
- confidence = low：线索弱、需要人工核实
- 每个荣誉必须在 evidence 中有对应条目
- 荣誉名使用 JSON _meta 里的标准词汇（如用「杰青」而非「国家杰出青年」）
- 若查无任何荣誉，返回 {{"honors": [], "evidence": [], "confidence": "high"}}"""


async def _query_llm_with_search(client: httpx.AsyncClient, prompt: str) -> dict | None:
    """Call Responses API with web_search tool. Returns parsed dict or None.

    gpt-5 is a reasoning model that spends many tokens on internal reasoning
    + multi-turn web searches. Allocate a generous token budget (16k) so it
    has room to emit the final JSON message after tool use.
    """
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/responses",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_BUZZ_MODEL,
                "tools": [{"type": "web_search_preview"}],
                "input": prompt,
                "max_output_tokens": 16000,
            },
            timeout=300,
        )
        if resp.status_code != 200:
            logger.warning("Responses API %d: %s", resp.status_code, resp.text[:200])
        else:
            data = resp.json()
            incomplete = data.get("incomplete_details")
            if incomplete:
                logger.warning("Responses API incomplete: %s", incomplete)

            text = ""
            sources: list[dict] = []
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for c in item.get("content", []):
                        if c.get("type") == "output_text":
                            text = c.get("text", "")
                            for ann in c.get("annotations", []):
                                if ann.get("type") == "url_citation":
                                    sources.append({
                                        "title": ann.get("title", ""),
                                        "url": ann.get("url", ""),
                                    })
            if text:
                parsed = _parse_json_from_text(text)
                if parsed:
                    if sources and isinstance(parsed.get("evidence"), list):
                        parsed["_search_sources"] = sources[:10]
                    return parsed
                else:
                    logger.warning("Responses API returned text but JSON parse failed. First 200: %s", text[:200])
    except Exception as e:
        logger.warning("Responses API error: %s", e)

    # Fallback: chat completions (no web search)
    # Note: response_format=json_object is unreliable on some proxies; prompt alone is enough
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_FALLBACK_MODEL,
                "messages": [{"role": "user", "content": prompt + "\n\n再次强调：只输出 JSON，不要任何其他内容。"}],
                "max_completion_tokens": 16000,
            },
            timeout=300,
        )
        if resp.status_code != 200:
            logger.warning("Chat API %d: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        content = data["choices"][0]["message"].get("content", "")
        if not content:
            # Debug: log finish reason when content is empty
            finish = data["choices"][0].get("finish_reason")
            usage = data.get("usage", {})
            logger.warning("Chat API empty content (finish=%s, usage=%s)", finish, usage)
            return None
        return _parse_json_from_text(content)
    except Exception as e:
        logger.warning("Chat API error: %s", e)
        return None


async def enrich_one(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    scholar: dict[str, Any],
) -> dict[str, Any]:
    """Enrich one scholar. Mutates and returns the dict."""
    async with semaphore:
        name = scholar.get("name", "")
        cn = scholar.get("cn")
        aff = scholar.get("affiliation", "")
        display = f"{name}" + (f" ({cn})" if cn else "")
        logger.info("▶ %s — %s", display, aff)

        prompt = _build_prompt(name, aff, cn)
        result = await _query_llm_with_search(client, prompt)

        if not result:
            scholar["honors_proposed"] = {"error": "llm_failed"}
            logger.warning("  ✗ LLM failed")
            return scholar

        honors = result.get("honors", []) or []
        evidence = result.get("evidence", []) or []
        confidence = result.get("confidence", "low")

        scholar["honors_proposed"] = {
            "honors": [str(h) for h in honors][:10],
            "evidence": evidence[:10],
            "confidence": confidence,
        }
        if "_search_sources" in result:
            scholar["honors_proposed"]["_search_sources"] = result["_search_sources"]

        logger.info("  ✓ %d honors (conf=%s): %s", len(honors), confidence, ", ".join(honors) if honors else "(none)")
        return scholar


async def main():
    parser = argparse.ArgumentParser(description="Enrich scholar honor tags via LLM+search.")
    parser.add_argument("--limit", type=int, default=0, help="Only enrich first N scholars (for testing)")
    parser.add_argument("--concurrency", type=int, default=3, help="Parallel requests (default 3)")
    parser.add_argument("--force", action="store_true", help="Re-enrich even if already proposed")
    parser.add_argument("--only-missing", action="store_true", help="Skip scholars who already have verified honors")
    args = parser.parse_args()

    if not LLM_API_KEY:
        logger.error("LLM_API_KEY is empty. Set it in backend/.env")
        return

    # Load seed
    if not SEED_FILE.exists():
        logger.error("Seed file not found: %s", SEED_FILE)
        return
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))

    # Load existing output if any (resume)
    existing: dict[str, dict] = {}
    if OUT_FILE.exists() and not args.force:
        try:
            prev = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            for s in prev.get("scholars", []):
                existing[s.get("name", "")] = s
            logger.info("Loaded %d previously enriched records from %s", len(existing), OUT_FILE)
        except Exception as e:
            logger.warning("Could not load prev output: %s", e)

    scholars = seed.get("scholars", [])
    to_process = []
    kept = []
    for s in scholars:
        name = s.get("name", "")
        # Skip if already has verified honors (unless --force)
        if args.only_missing and s.get("honors"):
            kept.append(s)
            continue
        # Reuse existing enrichment
        prev = existing.get(name)
        if prev and not args.force and "honors_proposed" in prev and "error" not in prev.get("honors_proposed", {}):
            kept.append(prev)
            continue
        to_process.append(s)

    if args.limit > 0:
        to_process = to_process[: args.limit]

    logger.info("Processing %d scholars (skip %d cached, concurrency=%d)", len(to_process), len(kept), args.concurrency)

    # Prepare output skeleton
    out_scholars_by_name: dict[str, dict] = {s["name"]: s for s in kept}

    # Run concurrent
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=200) as client:
        tasks = [enrich_one(client, semaphore, s) for s in to_process]
        results: list[dict] = []
        # Process with incremental save
        for coro in asyncio.as_completed(tasks):
            s = await coro
            out_scholars_by_name[s["name"]] = s
            results.append(s)
            # Incremental save after every result
            out_seed = dict(seed)
            # Preserve original scholar order
            ordered = [out_scholars_by_name.get(orig["name"], orig) for orig in scholars]
            out_seed["scholars"] = ordered
            OUT_FILE.write_text(json.dumps(out_seed, ensure_ascii=False, indent=2), encoding="utf-8")

    # Summary
    summary_high = sum(
        1 for s in out_scholars_by_name.values()
        if s.get("honors_proposed", {}).get("confidence") == "high"
        and s.get("honors_proposed", {}).get("honors")
    )
    summary_none = sum(
        1 for s in out_scholars_by_name.values()
        if s.get("honors_proposed") and not s["honors_proposed"].get("honors")
    )
    summary_err = sum(
        1 for s in out_scholars_by_name.values()
        if "error" in (s.get("honors_proposed") or {})
    )
    logger.info("=" * 60)
    logger.info("Done. high-conf with honors: %d, no honors found: %d, errors: %d", summary_high, summary_none, summary_err)
    logger.info("Output: %s", OUT_FILE)
    logger.info("Review the file, then merge trusted proposals into `honors` field.")


if __name__ == "__main__":
    asyncio.run(main())
