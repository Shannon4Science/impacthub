"""Import advisor mentions (公众号 / 小红书 / etc.) from a JSONL file.

输入文件每行一条 JSON 对象，字段如下（匹配 advisor 用 name + school_name）：

    {
      "advisor_name": "张伟",
      "school_name": "清华大学",
      "source": "wechat",                      // wechat / xiaohongshu / zhihu / forum / other
      "source_account": "鹿鸣观山海",            // 公众号名 / 小红书账号
      "title": "清华 XXX 老师组招生",
      "url": "https://mp.weixin.qq.com/s/...",
      "snippet": "文章摘要或摘抄关键句...",
      "cover_url": "https://...",              // optional
      "likes": 123,
      "reads": 4500,
      "comments": 8,
      "sentiment": "positive",                 // positive / neutral / negative / "" 不知道
      "tags": ["招生", "组氛围"],
      "published_at": "2026-04-15T08:00:00+08:00"
    }

未匹配到 advisor 的行会跳过（多半是同名歧义需要补 school_name，或导师未抓到）。

Usage:
    cd backend && python scripts/import_advisor_mentions.py path/to/mentions.jsonl
    # 仅试跑（不写入），加 --dry-run
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import async_session, init_db
from app.models import AdvisorSchool, Advisor, AdvisorMention


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


async def _find_advisor(db, advisor_id, name, school_name):
    if advisor_id:
        return await db.get(Advisor, advisor_id)
    if not name:
        return None
    stmt = select(Advisor).where(Advisor.name == name)
    if school_name:
        stmt = stmt.join(AdvisorSchool, AdvisorSchool.id == Advisor.school_id).where(
            AdvisorSchool.name == school_name
        )
    rows = (await db.execute(stmt)).scalars().all()
    if len(rows) == 1:
        return rows[0]
    return None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonl", help="Path to JSONL file with mention records")
    parser.add_argument("--dry-run", action="store_true", help="Parse + match but don't write")
    parser.add_argument("--default-source", default="wechat",
                        help="Source to use if record omits it (default: wechat)")
    parser.add_argument("--default-account", default="",
                        help="Source account to use if record omits it (e.g. 鹿鸣观山海)")
    parser.add_argument("--dedup-by-url", action="store_true",
                        help="Skip if a mention with the same URL already exists for that advisor")
    args = parser.parse_args()

    path = Path(args.jsonl)
    if not path.exists():
        log.error("File not found: %s", path)
        sys.exit(1)

    await init_db()

    inserted = 0
    skipped_no_advisor: list[str] = []
    skipped_dup = 0
    parse_errors = 0

    async with async_session() as db:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                parse_errors += 1
                log.warning("line %d: JSON decode error: %s", line_no, e)
                continue

            advisor = await _find_advisor(
                db,
                rec.get("advisor_id"),
                rec.get("advisor_name"),
                rec.get("school_name"),
            )
            if not advisor:
                key = f"{rec.get('advisor_name','?')}@{rec.get('school_name','?')}"
                if len(skipped_no_advisor) < 10:
                    skipped_no_advisor.append(key)
                log.info("line %d: no advisor match for %s", line_no, key)
                continue

            url = (rec.get("url") or "").strip()
            if args.dedup_by_url and url:
                exists = (await db.execute(
                    select(AdvisorMention.id).where(
                        AdvisorMention.advisor_id == advisor.id,
                        AdvisorMention.url == url,
                    )
                )).scalar_one_or_none()
                if exists:
                    skipped_dup += 1
                    continue

            published_at = None
            if rec.get("published_at"):
                try:
                    published_at = datetime.fromisoformat(
                        rec["published_at"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            mention = AdvisorMention(
                advisor_id=advisor.id,
                source=(rec.get("source") or args.default_source)[:30],
                source_account=(rec.get("source_account") or args.default_account)[:120],
                title=rec.get("title", ""),
                url=url[:500],
                snippet=rec.get("snippet", ""),
                cover_url=(rec.get("cover_url") or "")[:500],
                likes=int(rec.get("likes") or 0),
                reads=int(rec.get("reads") or 0),
                comments=int(rec.get("comments") or 0),
                sentiment=(rec.get("sentiment") or "")[:20],
                tags=rec.get("tags") if isinstance(rec.get("tags"), list) else None,
                published_at=published_at,
            )
            if not args.dry_run:
                db.add(mention)
            inserted += 1

        if not args.dry_run:
            await db.commit()

    log.info(
        "Done. inserted=%d  skipped_no_advisor=%d  skipped_dup=%d  parse_errors=%d  dry_run=%s",
        inserted, len(skipped_no_advisor) + (0 if not skipped_no_advisor else 0),
        skipped_dup, parse_errors, args.dry_run,
    )
    if skipped_no_advisor:
        log.info("First few unmatched: %s", skipped_no_advisor[:10])


if __name__ == "__main__":
    asyncio.run(main())
