"""Collect article URLs from one or more 公众号 via 搜狗微信搜索.

Uses sogou's /weixin search endpoint, paginates 1..N, and for each result
resolves the sogou /link?url=... → real mp.weixin.qq.com URL by extracting
the JavaScript-concatenated url from the intermediate page.

Sogou caps practical pagination at ~10 pages and triggers anti-bot quickly,
so per-query yield is typically 30-100 articles before CAPTCHA hits.

Default queries: the 5 一线 保研推荐 accounts. Override with --query.

Output: one JSONL line per article:
    {"title": "...", "account": "鸡哥保研", "sogou_url": "...", "wechat_url": "...", "page": 1}
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

DEFAULT_QUERIES = [
    "鹿鸣观山海",
    "保研论坛",
    "鸡哥保研",
    "保研er",
    "强基保研之家",
]
SOGOU_BASE = "https://weixin.sogou.com"
DELAY = 3.0   # politeness pause between pages


def fetch_page(
    client: httpx.Client, query: str, page: int, publisher_filter: str | None = None
) -> tuple[list[tuple[str, str, str]], bool]:
    """Returns (results, has_more). results = list of (title, sogou_link, publisher).

    If `publisher_filter` is given, only keep results whose .s-p account matches.
    Sogou article-search OR-matches across the query terms, so without filtering
    you get noise from unrelated 公众号. Filter by publisher restores precision.
    """
    url = f"{SOGOU_BASE}/weixin"
    params = {"type": 2, "query": query, "ie": "utf8", "page": page}
    try:
        r = client.get(url, params=params, timeout=15)
    except httpx.HTTPError as e:
        print(f"  page {page}: fetch failed: {e}")
        return [], False
    if r.status_code != 200:
        print(f"  page {page}: HTTP {r.status_code}")
        return [], False
    if "请输入验证码" in r.text or "/antispider" in r.text:
        print(f"  page {page}: CAPTCHA hit")
        return [], False
    soup = BeautifulSoup(r.content, "lxml")
    results: list[tuple[str, str, str]] = []
    for li in soup.select("li[id*=sogou_vr]"):
        title_el = li.select_one("a[uigs^=article_title]")
        if not title_el:
            continue
        title = re.sub(r"\s+", " ", title_el.get_text(strip=True))
        href = title_el.get("href", "").strip()
        if not href:
            continue
        # Publisher account name lives in <div class="s-p">
        sp_el = li.select_one(".s-p")
        publisher = sp_el.get_text(" ", strip=True) if sp_el else ""
        if publisher_filter and publisher_filter not in publisher:
            continue
        results.append((title, urljoin(SOGOU_BASE, href), publisher))
    has_more = bool(soup.select_one("a#sogou_next")) or len(results) >= 10
    return results, has_more


JS_URL_RE = re.compile(r"""url\s*\+=\s*['"]([^'"]+)['"]""")


def resolve_sogou_link(client: httpx.Client, sogou_link: str) -> str:
    """Resolve sogou /link?url=... to the real mp.weixin.qq.com URL."""
    try:
        r = client.get(sogou_link, timeout=15)
    except httpx.HTTPError as e:
        return f"<resolve-failed: {e}>"
    if r.status_code != 200:
        return f"<HTTP {r.status_code}>"
    parts = JS_URL_RE.findall(r.text)
    if not parts:
        # Maybe direct redirect via meta or already at mp.weixin
        if "mp.weixin.qq.com" in str(r.url):
            return str(r.url)
        return ""
    url = "".join(parts)
    return url


def collect_one_account(
    client: httpx.Client, query: str, max_pages: int, no_resolve: bool,
    publisher_filter: str | None = None,
) -> list[dict]:
    """Run sogou search for ONE query. Returns list of records.

    If `publisher_filter` is set, only results whose s-p account contains that
    string are kept (e.g. publisher_filter='鹿鸣观山海' for keyword-narrowed
    queries like '鹿鸣观山海 清华').
    """
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    records: list[dict] = []

    label = f"{query}" + (f" (filter pub={publisher_filter})" if publisher_filter else "")
    print(f"\n=== Collecting: {label} ===")
    empty_pages = 0
    for page in range(1, max_pages + 1):
        results, has_more = fetch_page(client, query, page, publisher_filter=publisher_filter)
        if not results:
            empty_pages += 1
            if empty_pages >= 2:
                print(f"  stopping at page {page} (2 empty pages — likely CAPTCHA / no more matches)")
                break
            time.sleep(DELAY)
            continue
        empty_pages = 0
        print(f"  page {page}: {len(results)} articles (after publisher filter)")
        for title, sogou_link, publisher in results:
            if title in seen_titles:
                continue
            seen_titles.add(title)
            wechat_url = ""
            if not no_resolve:
                time.sleep(DELAY)
                wechat_url = resolve_sogou_link(client, sogou_link)
                if wechat_url and wechat_url.startswith("http") and wechat_url in seen_urls:
                    continue
                if wechat_url:
                    seen_urls.add(wechat_url)
            records.append({
                "title": title,
                # Use the actual publisher (s-p) as account, not the search query
                "account": publisher or query,
                "query": query,
                "sogou_url": sogou_link,
                "wechat_url": wechat_url,
                "page": page,
            })
        if not has_more:
            break
        time.sleep(DELAY)
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", action="append",
                        help="公众号名或关键词（可多次给）。默认跑 5 个一线保研账号")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--out", default="backend/scripts/mentions/wechat_links.jsonl")
    parser.add_argument("--append", action="store_true",
                        help="追加到 --out 文件（按 title 去重），而不是覆盖")
    parser.add_argument("--no-resolve", action="store_true",
                        help="Skip JS-redirect resolution (just store sogou links)")
    parser.add_argument("--publisher",
                        help="只保留 publisher 包含此字符串的结果。当 query 是 "
                             "'鹿鸣观山海 清华' 这种带关键词的搜索时强烈建议用此过滤，"
                             "否则会混入大量同名匹配的无关公众号。")
    args = parser.parse_args()

    queries = args.query or DEFAULT_QUERIES

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing for dedup if --append
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    existing: list[dict] = []
    if args.append and out_path.exists():
        for ln in out_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
                existing.append(rec)
                if rec.get("title"):
                    seen_titles.add(rec["title"])
                if rec.get("wechat_url"):
                    seen_urls.add(rec["wechat_url"])
            except json.JSONDecodeError:
                continue
        print(f"Loaded {len(existing)} existing records (dedup enabled)")

    new_records: list[dict] = []
    t0 = time.time()
    with httpx.Client(headers=HEADERS, follow_redirects=False) as client:
        for q in queries:
            recs = collect_one_account(client, q, args.max_pages, args.no_resolve,
                                       publisher_filter=args.publisher)
            for r in recs:
                if r["title"] in seen_titles:
                    continue
                if r.get("wechat_url") and r["wechat_url"] in seen_urls:
                    continue
                seen_titles.add(r["title"])
                if r.get("wechat_url"):
                    seen_urls.add(r["wechat_url"])
                new_records.append(r)
            time.sleep(DELAY * 2)   # extra pause between queries

    all_records = existing + new_records if args.append else new_records
    with out_path.open("w", encoding="utf-8") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    elapsed = time.time() - t0
    resolved = sum(1 for r in all_records if r.get("wechat_url", "").startswith("http"))
    by_account: dict[str, int] = {}
    for r in all_records:
        acct = r.get("account", "?")
        by_account[acct] = by_account.get(acct, 0) + 1
    print(f"\n=== Done in {elapsed:.0f}s ===")
    print(f"Total in file: {len(all_records)} | new this run: {len(new_records)} | "
          f"resolved: {resolved} → {out_path}")
    for q, n in by_account.items():
        print(f"  {q}: {n}")


if __name__ == "__main__":
    main()
