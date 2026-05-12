"""Extract advisor mentions from collected 公众号 article links.

Pipeline (per article):
  1. Fetch HTML at wechat_url (mp.weixin.qq.com)
  2. Strip to body text (div#js_content)
  3. LLM extract structured list: [{advisor_name, school_name, snippet, tags, sentiment}]
  4. Write each as one row in output JSONL (compatible with
     import_advisor_mentions.py)

Reads:  backend/scripts/mentions/luming_links.jsonl (or --in)
Writes: backend/scripts/mentions/luming_mentions.jsonl (or --out)

Usage:
    cd backend
    python scripts/mentions/extract_mentions.py
    # then:
    python scripts/import_advisor_mentions.py scripts/mentions/luming_mentions.jsonl --dedup-by-url
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.config import LLM_API_BASE, LLM_API_KEY, LLM_BUZZ_MODEL  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


EXTRACT_PROMPT = """你正在分析公众号 "{account}" 的一篇文章，目标是提取文章里**提到的每位高校导师/教授**及关于他们的关键信息。这些数据会用于保研学生导师推荐。

### 文章标题
{title}

### 文章正文
{body}

### 任务
列出文章里**明确提到**的每位导师（不是顺带一笔的，而是有实质内容介绍的），输出为 JSON 数组。每个 entry：

- `advisor_name`: 中文姓名（2-4 字纯姓名，不带"老师"/"教授"）
- `school_name`: 学校全名（如"上海交通大学"、"哈尔滨工业大学"）— 必须是教育部正式名称
- `snippet`: 关于该导师的**原文摘抄或紧凑总结**（80-200 字，要让读者一眼判断是否合适）
- `tags`: 字符串数组，从 [招生, 扩招, 不招, push, 放养, 组氛围, 一作友好, 海归, 工业界, 高引用, 顶会, SSP, 量化, 头部互联网, 留学, 博后] 中挑符合的 2-5 个
- `sentiment`: "positive" / "neutral" / "negative"（文章对该导师的整体语气）

### 要求
- 只列**导师（老师/教授级别）**，不列学生
- 如果文章只是泛泛介绍学院/课题组没有点名导师，返回 `[]`
- 同一文章可能列出多位导师 → 多个 entries
- school_name 必须从文章上下文判断；如果文章只说"该组"没说学校，从标题或开头推断；推断不出就跳过该 entry
- 没列出来不要硬编

### 严格 JSON 输出（只输出 JSON 数组）
[
  {{"advisor_name":"张三","school_name":"上海交通大学","snippet":"...","tags":["招生","组氛围"],"sentiment":"positive"}},
  ...
]
"""


def _parse_json_array(text: str):
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        s = s.rsplit("```", 1)[0].strip()
    try:
        out = json.loads(s)
        if isinstance(out, list):
            return out
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[[\s\S]*\]", s)
    if m:
        try:
            out = json.loads(m.group())
            if isinstance(out, list):
                return out
        except json.JSONDecodeError:
            pass
    return None


def fetch_article_text(client: httpx.Client, url: str) -> tuple[str, str]:
    """Fetch a wechat article and return (title, body_text). Empty on failure."""
    try:
        r = client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
    except httpx.HTTPError as e:
        log.warning("fetch %s failed: %s", url[:60], e)
        return "", ""
    if r.status_code != 200:
        log.warning("fetch %s → %d", url[:60], r.status_code)
        return "", ""
    if "环境异常" in r.text or "请输入验证码" in r.text:
        return "", ""
    soup = BeautifulSoup(r.text, "lxml")
    title_el = soup.select_one("#activity-name") or soup.find("title")
    title = re.sub(r"\s+", " ", title_el.get_text(strip=True)) if title_el else ""
    body_el = soup.select_one("#js_content") or soup.body
    body = re.sub(r"\s+", " ", body_el.get_text(" ", strip=True)) if body_el else ""
    return title, body


async def llm_extract(client: httpx.AsyncClient, title: str, body: str, account: str = "保研公众号") -> list[dict]:
    prompt = EXTRACT_PROMPT.format(title=title, body=body, account=account)
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_BUZZ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 8000,
            },
            timeout=180,
        )
        if resp.status_code != 200:
            log.warning("LLM %d: %s", resp.status_code, resp.text[:200])
            return []
        text = resp.json()["choices"][0]["message"].get("content", "")
        result = _parse_json_array(text)
        return result or []
    except Exception as e:
        log.warning("LLM call failed: %s", e)
        return []


async def _process_one(
    sem: asyncio.Semaphore,
    sync_client: httpx.Client,
    llm_client: httpx.AsyncClient,
    row: dict,
    default_account: str,
    source: str,
    idx: int,
    total: int,
) -> list[dict]:
    """Fetch + extract for one row. Returns list of finished mention records."""
    async with sem:
        wechat_url = row.get("wechat_url") or ""
        fallback_title = row.get("title", "")
        if not wechat_url.startswith("http"):
            log.info("[%4d/%d] skip (no url): %s", idx, total, fallback_title[:50])
            return []
        # fetch is sync (httpx.Client), wrap in to_thread to avoid blocking the loop
        title, body = await asyncio.to_thread(fetch_article_text, sync_client, wechat_url)
        if not body:
            log.info("[%4d/%d] empty body: %s", idx, total, fallback_title[:50])
            return []
        title = title or fallback_title
        row_account = row.get("account") or default_account
        log.info("[%4d/%d] [%s] %s | body=%d", idx, total, row_account, title[:50], len(body))
        mentions = await llm_extract(llm_client, title, body, account=row_account)
        if not mentions:
            return []
        out_recs: list[dict] = []
        for m in mentions:
            if not isinstance(m, dict):
                continue
            name = (m.get("advisor_name") or "").strip()
            school = (m.get("school_name") or "").strip()
            if not name or not school:
                continue
            out_recs.append({
                "advisor_name": name,
                "school_name": school,
                "source": source,
                "source_account": row_account,
                "title": title,
                "url": wechat_url,
                "snippet": m.get("snippet") or "",
                "tags": m.get("tags") if isinstance(m.get("tags"), list) else None,
                "sentiment": m.get("sentiment") or "",
            })
        log.info("[%4d/%d]   → +%d mentions", idx, total, len(out_recs))
        return out_recs


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="inp",
                        default="backend/scripts/mentions/luming_links.jsonl")
    parser.add_argument("--out",
                        default="backend/scripts/mentions/luming_mentions.jsonl")
    parser.add_argument("--account", default="鹿鸣观山海")
    parser.add_argument("--source", default="wechat")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true",
                        help="skip URLs already present in --out (reads existing file first)")
    parser.add_argument("--concurrency", type=int, default=4,
                        help="parallel article fetch+extract workers (default 4)")
    args = parser.parse_args()

    inp = Path(args.inp)
    if not inp.exists():
        log.error("Input file not found: %s", inp)
        sys.exit(1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        json.loads(l) for l in inp.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.startswith("#")
    ]
    if args.limit:
        rows = rows[: args.limit]

    # Resume mode: read existing output, skip URLs already covered, append-mode write
    seen_urls: set[str] = set()
    write_mode = "w"
    if args.resume and out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(ln)
                if rec.get("url"):
                    seen_urls.add(rec["url"])
            except json.JSONDecodeError:
                continue
        log.info("resume: %d URLs already extracted in %s", len(seen_urls), out)
        write_mode = "a"
    rows_to_do = [r for r in rows if r.get("wechat_url") not in seen_urls]
    log.info("Processing %d articles (skipped %d already-extracted, concurrency=%d)",
             len(rows_to_do), len(rows) - len(rows_to_do), args.concurrency)

    sync_client = httpx.Client(headers=HEADERS, follow_redirects=True)
    sem = asyncio.Semaphore(args.concurrency)
    written = 0
    t0 = time.time()
    async with httpx.AsyncClient() as llm_client:
        with out.open(write_mode, encoding="utf-8") as f:
            tasks = [
                _process_one(sem, sync_client, llm_client, row,
                             args.account, args.source, i, len(rows_to_do))
                for i, row in enumerate(rows_to_do, 1)
            ]
            for coro in asyncio.as_completed(tasks):
                recs = await coro
                for rec in recs:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    written += 1
                if recs:
                    f.flush()
    sync_client.close()

    log.info("Done in %.0fs. wrote %d new mention rows → %s", time.time() - t0, written, out)


if __name__ == "__main__":
    asyncio.run(main())
