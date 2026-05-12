"""Collect 公众号 article URLs via mp.weixin.qq.com (NOT Sogou).

Uses the official 公众号后台 "超链接 → 查找文章" interface, which exposes:
  1. /cgi-bin/searchbiz?action=search_biz&query=...   → resolve nickname → fakeid
  2. /cgi-bin/appmsg?action=list_ex&fakeid=...&type=9 → paginate full history

Versus Sogou this gets the FULL history (e.g. 鹿鸣观山海 = 238 articles vs Sogou's
~30) with publisher already pinned (no cross-account noise) and clean
mp.weixin.qq.com links (no JS-redirect resolution needed).

Login state lives in `.mp_cookie.json` (gitignored). Re-extract via DevTools when
expired: token ~hours, cookie ~days. Visible signs of expiry: searchbiz returns
{"base_resp":{"ret":-3,...}} or 200012 / freq control errors.

Output: one JSONL line per article, schema-compatible with collect_luming_links.py:
  {"title", "account", "wechat_url", "publish_time", "fakeid", "page"}
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx


SCRIPT_DIR = Path(__file__).resolve().parent
COOKIE_FILE = SCRIPT_DIR / ".mp_cookie.json"
MP_BASE = "https://mp.weixin.qq.com"
DELAY = 2.5            # politeness pause between page calls
SEARCH_DELAY = 4.0     # extra pause between switching accounts
PAGE_SIZE = 20         # mp api caps at 20 per call


def load_cookie() -> dict:
    if not COOKIE_FILE.exists():
        sys.exit(
            f"missing {COOKIE_FILE}. extract via DevTools:\n"
            "  1. login to mp.weixin.qq.com\n"
            "  2. 新建图文 → 超链接 → 查找文章 → 选择其他公众号 → 搜任意名字\n"
            "  3. devtools network → right-click /cgi-bin/searchbiz?... → Copy as cURL\n"
            "  4. paste token + cookie into .mp_cookie.json"
        )
    return json.loads(COOKIE_FILE.read_text(encoding="utf-8"))


def make_client(cfg: dict) -> httpx.Client:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": (
            f"{MP_BASE}/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit"
            f"&isNew=1&type=10&token={cfg['token']}&lang=zh_CN"
        ),
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": cfg["cookie"],
    }
    return httpx.Client(headers=headers, timeout=20)


def search_biz(client: httpx.Client, cfg: dict, query: str) -> dict | None:
    """Resolve a 公众号 nickname → its biz record (fakeid + nickname + alias)."""
    params = {
        "action": "search_biz",
        "begin": 0,
        "count": 5,
        "query": query,
        "fingerprint": cfg.get("fingerprint", ""),
        "token": cfg["token"],
        "lang": "zh_CN",
        "f": "json",
        "ajax": 1,
    }
    r = client.get(f"{MP_BASE}/cgi-bin/searchbiz", params=params)
    if r.status_code != 200:
        print(f"  searchbiz HTTP {r.status_code}")
        return None
    data = r.json()
    ret = data.get("base_resp", {}).get("ret")
    if ret != 0:
        print(f"  searchbiz error: {data.get('base_resp')}")
        return None
    lst = data.get("list", [])
    if not lst:
        print(f"  no biz match for '{query}'")
        return None
    # Prefer exact nickname match if present
    for biz in lst:
        if biz.get("nickname") == query:
            return biz
    return lst[0]


def list_articles_page(
    client: httpx.Client, cfg: dict, fakeid: str, begin: int, count: int = PAGE_SIZE
) -> tuple[list[dict], int]:
    """Returns (articles, total_count). Articles already have title + link + create_time."""
    params = {
        "action": "list_ex",
        "begin": begin,
        "count": count,
        "fakeid": fakeid,
        "type": 9,
        "query": "",
        "token": cfg["token"],
        "lang": "zh_CN",
        "f": "json",
        "ajax": 1,
    }
    r = client.get(f"{MP_BASE}/cgi-bin/appmsg", params=params)
    if r.status_code != 200:
        print(f"  list_ex HTTP {r.status_code}")
        return [], -1
    data = r.json()
    ret = data.get("base_resp", {}).get("ret")
    if ret != 0:
        print(f"  list_ex error: {data.get('base_resp')}")
        return [], -1
    return data.get("app_msg_list", []), int(data.get("app_msg_cnt", 0))


def collect_one_account(
    client: httpx.Client, cfg: dict, query: str, max_articles: int | None,
    start_begin: int = 0,
) -> list[dict]:
    print(f"\n=== {query} ===")
    biz = search_biz(client, cfg, query)
    if not biz:
        return []
    fakeid = biz["fakeid"]
    nickname = biz.get("nickname", query)
    print(f"  fakeid={fakeid} nickname={nickname}" + (f" (resume from begin={start_begin})" if start_begin else ""))
    time.sleep(DELAY)

    records: list[dict] = []
    begin = start_begin
    total = -1
    page = 0
    while True:
        page += 1
        articles, total_now = list_articles_page(client, cfg, fakeid, begin)
        if total_now >= 0:
            total = total_now
        if not articles:
            print(f"  page {page}: empty (begin={begin}) — stop")
            break
        print(f"  page {page}: +{len(articles)} (total={total}, begin={begin})")
        for a in articles:
            records.append({
                "title": a.get("title", ""),
                "account": nickname,
                "wechat_url": a.get("link", ""),
                "publish_time": a.get("create_time"),
                "update_time": a.get("update_time"),
                "fakeid": fakeid,
                "aid": a.get("aid"),
                "appmsgid": a.get("appmsgid"),
                "itemidx": a.get("itemidx"),
                "digest": a.get("digest", ""),
                "cover": a.get("cover", ""),
                "page": page,
            })
            if max_articles and len(records) >= max_articles:
                print(f"  reached --limit {max_articles}, stop")
                return records
        begin += len(articles)
        if total >= 0 and begin >= total:
            print(f"  done: collected {begin}/{total}")
            break
        time.sleep(DELAY)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", required=True,
                        help="公众号 nickname (可多次给). e.g. --query 鹿鸣观山海")
    parser.add_argument("--out", default="backend/scripts/mentions/wechat_links.jsonl")
    parser.add_argument("--append", action="store_true",
                        help="merge into --out (dedup by wechat_url)")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap per account (testing)")
    parser.add_argument("--start-begin", type=int, default=0,
                        help="resume offset (e.g. 1118 to continue 保研论坛 from where freq-control hit)")
    args = parser.parse_args()

    cfg = load_cookie()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

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
                if rec.get("wechat_url"):
                    seen_urls.add(rec["wechat_url"])
            except json.JSONDecodeError:
                continue
        print(f"loaded {len(existing)} existing records (dedup by wechat_url)")

    new_records: list[dict] = []
    t0 = time.time()
    with make_client(cfg) as client:
        for q in args.query:
            recs = collect_one_account(client, cfg, q, args.limit, start_begin=args.start_begin)
            for r in recs:
                url = r.get("wechat_url")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                new_records.append(r)
            time.sleep(SEARCH_DELAY)

    all_records = existing + new_records if args.append else new_records
    with out_path.open("w", encoding="utf-8") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    elapsed = time.time() - t0
    by_account: dict[str, int] = {}
    for r in all_records:
        acc = r.get("account", "?")
        by_account[acc] = by_account.get(acc, 0) + 1
    print(f"\n=== done in {elapsed:.0f}s ===")
    print(f"total in file: {len(all_records)} | new: {len(new_records)} → {out_path}")
    for q, n in sorted(by_account.items(), key=lambda kv: -kv[1]):
        print(f"  {q}: {n}")


if __name__ == "__main__":
    main()
